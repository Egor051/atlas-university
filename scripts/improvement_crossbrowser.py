"""Real Firefox/WebKit browser workflows with isolated fictional HTTP data.

This is browser-engine coverage and viewport emulation. It does not establish
that a physical Android/iPhone or native Safari installation was tested.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import traceback

from playwright.sync_api import sync_playwright,expect
from improvement_runtime import ROOT,DEFAULT_REPORTS,isolated_server,browser_ready,browser_login,browser_visit,geometry,report_start,save_report

STUDENT=['home','schedule','grades','plan','requests','certificates','notifications','profile','announcements','courses','assignments','exams',
         'calendar','tasks','learning/notes','materials','consultations','messages','events','finance','contacts','knowledge','portfolio','settings']
STAFF=['staff','staffdesk','staffmessages','announcement-admin','profile','settings']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engines',default='firefox,webkit')
    parser.add_argument('--report',type=Path,default=DEFAULT_REPORTS/'crossbrowser.json')
    args=parser.parse_args();engines=args.engines.split(',');assert set(engines)<=set(['chromium','firefox','webkit'])
    report=report_start('Real Firefox/WebKit engines, isolated fictional database and real HTTP. Screen widths emulate layout; no physical-device/native-Safari claim.')
    report['engines']=[];report['geometry']=[];report['browser_errors']=[]
    shots=ROOT/'screenshots'/'improvements-2026-11-08';shots.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as p:
            for engine in engines:
                with isolated_server() as server:
                    browser=getattr(p,engine).launch(headless=True)
                    report['engines'].append({'name':engine,'version':browser.version})
                    contexts=[browser.new_context(viewport={'width':360,'height':800},reduced_motion='reduce',locale='ru-RU') for _ in range(3)]
                    pages=[c.new_page() for c in contexts]
                    for page in pages:page.on('pageerror',lambda error:report['browser_errors'].append(str(error)))
                    a,b,staff=pages
                    for index,page in enumerate(pages):browser_login(page,server['base'],index)
                    for width,height in [(360,800),(390,844),(1440,1000)]:
                        for page,routes,role in [(a,STUDENT,'student'),(staff,STAFF,'staff')]:
                            page.set_viewport_size({'width':width,'height':height})
                            for route in routes:
                                browser_visit(page,server['base'],route)
                                report['geometry'].append({'engine':engine,'role':role,'route':route,**geometry(page)})
                            print(f'{engine}: {role}, {width}px, {len(routes)} routes',flush=True)
                        browser_visit(a,server['base'],'home')
                        a.screenshot(path=str(shots/f'{engine}-{width}-home.png'),full_page=True,animations='disabled')
                    a.set_viewport_size({'width':360,'height':800})
                    browser_visit(a,server['base'],'certificates')
                    a.locator('[data-request-view="services"]').first.click()
                    a.locator('.certificate-service [data-type="study"]').click()
                    a.locator('#doc-comment').fill('Вымышленная заявка из настоящего браузерного сценария приёмки.')
                    # New per-service fields can be required; exercise visible labels with safe synthetic content.
                    for node in a.locator('#request-form input[required], #request-form textarea[required]').all():
                        if node.input_value():continue
                        kind=node.get_attribute('type') or 'text'
                        node.fill('2026-11-20' if kind=='date' else 'Для демонстрационного учебного примера')
                    for node in a.locator('#request-form select[required]').all():
                        if not node.input_value():
                            options=node.locator('option').evaluate_all('(nodes)=>nodes.filter(n=>n.value&&!n.disabled).map(n=>n.value)')
                            if options:node.select_option(options[0])
                    with a.expect_response(lambda r:r.url==server['base']+'/api/requests' and r.request.method=='POST') as response:
                        a.locator('#request-form button[type="submit"]').click()
                    assert response.value.status==201,response.value.text()
                    request_id=response.value.json()['id']
                    expect(a.locator('.detail-summary')).to_be_visible()
                    assert b.request.get(server['base']+f'/api/requests/{request_id}').status==404
                    browser_visit(staff,server['base'],'staff')
                    staff.locator('[data-staff-kind="certificate"]').click()
                    staff.locator('#staff-search').fill(str(request_id))
                    staff.locator(f'.request-row[data-id="{request_id}"]').wait_for()
                    staff.locator(f'.request-row[data-id="{request_id}"]').click()
                    for status in ['review','processing','ready']:
                        staff.locator('#staff-status').select_option(status)
                        staff.locator('#staff-message').fill('Вымышленный ответ учебного офиса в браузерном сценарии.')
                        version=int(staff.locator('#staff-form').get_attribute('data-version'))
                        staff.locator('#staff-form button[type="submit"]').click()
                        if status!='ready':expect(staff.locator('#staff-form')).to_have_attribute('data-version',str(version+1))
                        else:expect(staff.locator('#staff-form')).to_have_count(0)
                    if a.locator('.modal').count():a.locator('.modal .close-btn').click()
                    browser_visit(a,server['base'],'certificates')
                    a.locator('[data-request-filter="ready"]').click()
                    a.locator(f'.request-row[data-id="{request_id}"]').click()
                    expect(a.locator('.staff-answer')).to_contain_text('Вымышленный ответ')
                    download_link=a.locator(f'a[href="/api/requests/{request_id}/document"]')
                    with a.expect_download() as download:download_link.click()
                    doc=Path(download.value.path()).read_text(encoding='utf-8')
                    assert 'Не имеет юридической силы' in doc
                    report['checks'].append({'engine':engine,'workflow':'student UI submit → other student denied → staff UI review/processing/ready → student UI opens answer and downloads actual document','request_id':request_id})
                    for context in contexts:context.close()
                    browser.close()
        if report['browser_errors']:report['failures'].append('Browser page errors observed')
    except Exception:report['failures'].append(traceback.format_exc())
    finally:save_report(args.report,report)
    print(json.dumps({'status':report['status'],'engines':report['engines'],'geometry_checks':len(report['geometry']),'failures':report['failures']},ensure_ascii=False))
    return 1 if report['status']=='FAIL' else 0

if __name__=='__main__':raise SystemExit(main())
