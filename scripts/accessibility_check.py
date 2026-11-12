"""Real-browser axe-core checks, using a dev-only local npm dependency.

Run npm ci --ignore-scripts, then python scripts/accessibility_check.py.
Automated checks and keyboard acceptance are evidence, not a full WCAG audit.
"""
from __future__ import annotations
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from browser_check import ROOT, start_server, stop_server, login, visit, ready


def run():
    (ROOT/'outputs').mkdir(exist_ok=True)
    axe=ROOT/'node_modules/axe-core/axe.min.js'
    if not axe.exists():
        raise RuntimeError('Run npm ci --ignore-scripts before accessibility checks')
    checks=[]
    with tempfile.TemporaryDirectory(prefix='atlas-a11y-') as folder:
        base, _, process, log=start_server(folder)
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch()
                context=browser.new_context(reduced_motion='reduce')
                context.add_init_script(path=str(axe))
                page=context.new_page()

                def scan(name):
                    result=page.evaluate("""async () => {const r=await axe.run(document,{
                      runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa','best-practice']}
                    });return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,help:v.help,
                      helpUrl:v.helpUrl,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),
                      incomplete:r.incomplete.map(v=>({id:v.id,help:v.help,count:v.nodes.length})),
                      passes:r.passes.length,testEngine:r.testEngine};}""")
                    checks.append({'screen':name,**result})
                    (ROOT/'outputs/a11y-last.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
                    print(name+': '+str(sum(len(v['nodes']) for v in result['violations']))+' violations',flush=True)
                    for violation in result['violations']:
                        for node in violation['nodes'][:2]:
                            print(json.dumps({'rule':violation['id'],**node},ensure_ascii=False),flush=True)

                for width,height in [(1440,1000),(360,800)]:
                    page.set_viewport_size({'width':width,'height':height})
                    page.goto(base,wait_until='networkidle')
                    scan(f'login-{width}')
                    login(page,base,0)
                    for section in ['home','schedule','grades','plan','requests','notifications','profile']:
                        visit(page,base,section)
                        scan(f'{section}-{width}')
                    visit(page,base,'schedule')
                    page.locator('[data-view="day"]').click()
                    page.locator('.day-pick').last.click()
                    scan(f'schedule-empty-{width}')
                    visit(page,base,'plan')
                    page.locator('[data-deadline]').first.check()
                    page.locator('[data-plan-filter="done"]').click()
                    scan(f'plan-done-{width}')
                    page.locator('[data-deadline]').first.uncheck()
                    page.locator('[data-action="search"]:visible').first.click()
                    scan(f'search-{width}')
                    page.locator('.close-btn').click()
                    page.route('**/api/schedule?*',lambda route:route.abort('failed'))
                    page.goto(base+'/app/schedule',wait_until='networkidle')
                    expect(page.locator('.error-state')).to_be_visible()
                    scan(f'error-{width}')
                    page.unroute('**/api/schedule?*')
                    visit(page,base,'certificates')
                    page.locator('[data-request-view="services"]').first.click()
                    page.locator('.certificate-service [data-type="study"]').click()
                    expect(page.locator('#request-form')).to_be_visible()
                    scan(f'new-request-{width}')
                    page.locator('.close-btn').click()
                    result=context.request.post(base+'/api/requests',headers={'X-Requested-With':'ATLAS'},data={'type':'study','comment':'Проверка доступности конкурсного образца'}).json()
                    request_id=result['id']
                    visit(page,base,'profile')
                    page.locator('.danger-button[data-action="logout"]').click()
                    expect(page.locator('#login-form')).to_be_visible()
                    login(page,base,2)
                    page.locator('[data-staff-kind="certificate"]').click()
                    scan(f'staff-{width}')
                    page.locator('.request-row').first.click()
                    expect(page.locator('.detail-summary')).to_be_visible()
                    scan(f'staff-detail-{width}')
                    page.locator('.close-btn').click()
                    for status in ['review','processing','ready']:
                        record=context.request.get(base+f'/api/staff/requests/{request_id}').json()
                        r=context.request.post(base+f'/api/staff/requests/{request_id}/status',headers={'X-Requested-With':'ATLAS'},data={'status':status,'message':'Демонстрационный образец готов. Это конкурсная проверка.','expected_version':record['version']})
                        assert r.ok, r.text()
                    visit(page,base,'profile')
                    page.locator('.danger-button').click()
                    expect(page.locator('#login-form')).to_be_visible()
                    login(page,base,0)
                    visit(page,base,'certificates')
                    page.locator(f'.request-row[data-id="{request_id}"]').click()
                    expect(page.locator('.document-result')).to_be_visible()
                    scan(f'document-ready-{width}')
                    page.locator('.close-btn').click()
                    visit(page,base,'profile')
                    page.locator('.danger-button').click()
                    expect(page.locator('#login-form')).to_be_visible()
                browser.close()
        finally:
            stop_server(process,log)
    count=sum(len(v['nodes']) for c in checks for v in c['violations'])
    report={'verified_at':datetime.now(timezone(timedelta(hours=3))).isoformat(),
            'scope':'Automated axe-core on real local Chromium. Not a full WCAG certification or screen-reader/device audit.',
            'source':'https://github.com/dequelabs/axe-core',
            'screens':checks,'violating_nodes':count,'status':'PASS' if not count else 'FAIL'}
    target=ROOT/'docs/verification/accessibility-report.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Accessibility: {len(checks)} screens, {count} violating nodes',flush=True)
    return 1 if count else 0


if __name__=='__main__':
    raise SystemExit(run())
