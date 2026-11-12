"""Cold-load and interaction lab measurements on real local HTTP.

Chromium mobile profile: 390x844, 150ms added network latency, 1.6Mbit/s down,
750kbit/s up, CPU throttling x4, disabled browser cache. These are laboratory
emulations, not a physical phone, real users, public hosting or field INP.
"""
from __future__ import annotations
import argparse
from contextlib import nullcontext
from pathlib import Path
import json
import math
import platform
import time
import traceback
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright,expect
from improvement_runtime import DEFAULT_REPORTS,isolated_server,browser_ready,report_start,save_report

OBSERVER='''(() => {
  const metrics=window.__atlasLab={lcp:null,cls:0,events:[]};
  try {new PerformanceObserver(list=>{for(const e of list.getEntries())metrics.lcp=e.startTime;}).observe({type:'largest-contentful-paint',buffered:true});} catch {}
  try {new PerformanceObserver(list=>{for(const e of list.getEntries())if(!e.hadRecentInput)metrics.cls+=e.value;}).observe({type:'layout-shift',buffered:true});} catch {}
  try {new PerformanceObserver(list=>{for(const e of list.getEntries())metrics.events.push({name:e.name,duration:e.duration,interactionId:e.interactionId});}).observe({type:'event',durationThreshold:16,buffered:true});} catch {}
})();'''


def pct(values,p=.75):
    values=sorted(v for v in values if v is not None)
    return round(values[max(0,math.ceil(len(values)*p)-1)],2) if values else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',type=int,default=5)
    parser.add_argument('--report',type=Path,default=DEFAULT_REPORTS/'performance.json')
    parser.add_argument('--url',help='Optional already deployed HTTPS origin; starts no local server and does not change domain records.')
    args=parser.parse_args();assert 3<=args.runs<=5
    if args.url:
        parts=urlsplit(args.url)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.path not in {'','/'} or parts.query or parts.fragment:
            parser.error('--url must be an HTTPS origin without credentials, path or query')
        args.url=args.url.rstrip('/')
    report=report_start(('Chromium laboratory measurement on actual public HTTPS.' if args.url else 'Chromium laboratory measurement on real isolated local HTTP.')+' Synthetic interactions and emulated network/CPU; no field INP, real user or physical-device claim.')
    report['origin']=args.url or 'isolated local server'
    report['environment']={'os':platform.platform(),'python':platform.python_version(),'browser':'Playwright Chromium'}
    report['profiles']={'desktop':{'viewport':'1440x1000','cpu_slowdown':1,'network':'unthrottled public WAN' if args.url else 'unthrottled loopback'},
                        'mobile_lab':{'viewport':'390x844','cpu_slowdown':4,'latency_ms':150,'download_bits_per_second':1600000,'upload_bits_per_second':750000,'cache_disabled':True}}
    report['budgets']={'cold_login_lcp_p75_ms':2500,'cls_p75':.1,'authenticated_home_ready_p75_ms':4000,
                       'action_completion_p75_ms':1500,'lab_event_timing_reference_ms':200}
    report['samples']=[];report['resource_manifest']=[]
    try:
        with (nullcontext({'base':args.url}) if args.url else isolated_server()) as server,sync_playwright() as p:
            browser=p.chromium.launch()
            report['environment']['browser_version']=browser.version
            for profile in ['desktop','mobile_lab']:
                for run in range(args.runs):
                    context=browser.new_context(viewport={'width':390 if profile=='mobile_lab' else 1440,'height':844 if profile=='mobile_lab' else 1000},reduced_motion='reduce')
                    page=context.new_page();page.add_init_script(OBSERVER)
                    cdp=context.new_cdp_session(page)
                    cdp.send('Network.enable');cdp.send('Network.setCacheDisabled',{'cacheDisabled':True})
                    if profile=='mobile_lab':
                        cdp.send('Network.emulateNetworkConditions',{'offline':False,'latency':150,'downloadThroughput':1600000/8,'uploadThroughput':750000/8,'connectionType':'cellular4g'})
                        cdp.send('Emulation.setCPUThrottlingRate',{'rate':4})
                    started=time.perf_counter();page.goto(server['base'],wait_until='networkidle')
                    expect(page.get_by_role('button',name='Попробовать демо',exact=True)).to_be_visible()
                    cold_ms=(time.perf_counter()-started)*1000
                    cold=page.evaluate('''() => ({...window.__atlasLab,resources:performance.getEntriesByType('resource').map(r=>({name:new URL(r.name).pathname,transferSize:r.transferSize,encodedBodySize:r.encodedBodySize,duration:r.duration}))})''')
                    # Repeated cold contexts would exercise login rate protection; one server per profile
                    # uses two distinct accounts and at most five attempts per account.
                    account=(run+(1 if profile=='mobile_lab' else 0))%2
                    start=time.perf_counter();page.get_by_role('button',name='Попробовать демо',exact=True).click();page.locator(f'[data-demo="{account}"]').click();browser_ready(page)
                    auth_ms=(time.perf_counter()-start)*1000
                    actions=[]
                    for target in ['grades','schedule','requests']:
                        start=time.perf_counter()
                        link_selector=f'[data-route="{target}"]'
                        visible_link=page.locator(link_selector).filter(visible=True).first
                        if not visible_link.is_visible():
                            group=page.locator('.sidebar .nav-group').filter(has=page.locator(link_selector))
                            group.locator('summary').click()
                        visible_link.click()
                        browser_ready(page)
                        # Wait for route render, not merely the previous page's ready state.
                        expect(page).to_have_url(server['base']+'/app/'+target)
                        expect(page.locator('#page-content')).not_to_have_attribute('aria-busy','true')
                        actions.append({'target':target,'completion_ms':round((time.perf_counter()-start)*1000,2)})
                    live=page.evaluate('window.__atlasLab')
                    events=[e['duration'] for e in live['events'] if e.get('interactionId')]
                    sample={'profile':profile,'run':run+1,'cold_login_ready_ms':round(cold_ms,2),'cold_login_lcp_ms':cold['lcp'],
                            'cls':live['cls'],'authenticated_home_ready_ms':round(auth_ms,2),'actions':actions,
                            'lab_event_timing_max_ms':max(events) if events else None,'lab_event_timing_event_count':len(events),
                            'first_load_transfer_bytes':sum(r['transferSize'] for r in cold['resources'])}
                    report['samples'].append(sample)
                    if run==0:report['resource_manifest'].append({'profile':profile,'resources':cold['resources']})
                    print(f'performance {profile} {run+1}/{args.runs}: LCP {cold["lcp"]}ms, login {round(auth_ms)}ms',flush=True)
                    context.close()
            browser.close()
        report['summary']=[]
        for profile in report['profiles']:
            rows=[r for r in report['samples'] if r['profile']==profile]
            summary={'profile':profile,'cold_login_lcp_p75_ms':pct([r['cold_login_lcp_ms'] for r in rows]),
                     'cold_login_ready_p75_ms':pct([r['cold_login_ready_ms'] for r in rows]),'cls_p75':pct([r['cls'] for r in rows]),
                     'authenticated_home_ready_p75_ms':pct([r['authenticated_home_ready_ms'] for r in rows]),
                     'action_completion_p75_ms':pct([a['completion_ms'] for r in rows for a in r['actions']]),
                     'lab_event_timing_max_p75_ms':pct([r['lab_event_timing_max_ms'] for r in rows]),
                     'max_first_load_transfer_bytes':max(r['first_load_transfer_bytes'] for r in rows)}
            report['summary'].append(summary)
            for key in ['cold_login_lcp_p75_ms','cls_p75','authenticated_home_ready_p75_ms','action_completion_p75_ms']:
                if summary[key] is None or summary[key]>report['budgets'][key]:
                    report['failures'].append(f'{profile}: {key}={summary[key]} exceeds {report["budgets"][key]}')
        report['checks']=['fresh browser contexts','browser cache disabled','declared CPU/network profile','real API responses','cold login LCP and document CLS','measured action completion','EventTiming reported only as lab evidence']
        report['limitations']=['Five observations per profile by default, not a representative user population.',
            'LCP describes the cold login document; authenticated-home readiness is measured separately.',
            'EventTiming on synthetic interactions is not a field INP value.',
            'A few public WAN samples are not a server capacity guarantee or Russian connectivity proof.' if args.url else 'Local loopback backend does not represent public WAN/server capacity.']
    except Exception:report['failures'].append(traceback.format_exc())
    finally:save_report(args.report,report)
    print(json.dumps({'status':report['status'],'summary':report.get('summary'),'failures':report['failures']},ensure_ascii=False))
    return 1 if report['status']=='FAIL' else 0

if __name__=='__main__':raise SystemExit(main())
