"""Local visual and accessibility evidence for the role-specific workspaces."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from improvement_runtime import ROOT, browser_login, browser_ready, geometry, isolated_server, report_start, save_report

WIDTHS = (360, 390, 768, 1440)
WORKSPACES = [
    (0, 'student', ['home','schedule','grades','assignments','notifications']),
    (3, 'teacher', ['teacher','teaching','teaching/1?tab=grades','teaching/1?tab=attendance','teaching/1?tab=works',
                    'teaching/1?tab=report','teach-schedule','teach-consultations','tables?dataset=grades','notifications']),
    (2, 'dean', ['staff','staffdesk','schedule-changes','timetable-admin','registry']),
    (4, 'dispatcher', ['timetable-admin','schedule-changes','registry','registry/1','tables?dataset=rooms']),
    (5, 'admin', ['registry','registry?tab=students','registry?tab=loads','timetable-admin','schedule-changes','tables']),
]
CAPTURES = {'teacher','teaching/1?tab=grades','timetable-admin','schedule-changes','registry','tables?dataset=rooms',
            'union','vuc','union-office','vuc-office','vuc?tab=learning'}


def call(client, method, path, payload=None):
    response = client.request(method, '/api/'+path, json=payload)
    response.raise_for_status()
    return response.json()


def unit_examples(base):
    """Create visible sample decisions in the disposable database via the public workflow."""
    options = dict(base_url=base, headers={'X-Requested-With':'ATLAS'}, trust_env=False)
    with httpx.Client(**options) as student:
        call(student,'POST','login',{'login':'alina.demo','password':'AtlasDemo!2026-A'})
        overview = call(student,'GET','units/vuc')
        program_id = overview['programs'][0]['id']
        join = call(student,'POST','units/union/cases',{'kind':'join','confirmed':True})
        apply = call(student,'POST','units/vuc/cases',{'kind':'apply','confirmed':True,'program_id':program_id,
                                                      'checklist':list(overview['checklist'])})
    with httpx.Client(**options) as union, httpx.Client(**options) as center:
        call(union,'POST','login',{'login':'union.demo','password':'AtlasUnion!2026-U'})
        call(center,'POST','login',{'login':'vuc.demo','password':'AtlasCenter!2026-V'})
        for client, row, statuses in [(union, join, ('review','accepted')), (center, apply, ('review','selection','accepted'))]:
            for status in statuses:
                body = {'status':status,'version':row['version']}
                if status=='accepted':
                    body['message'] = 'Демонстрационное заявление рассмотрено.'
                    if row['unit']=='vuc':
                        groups = call(center,'GET','units/vuc/learning')['groups']
                        body['group_id'] = next(group['id'] for group in groups if group['program_id']==program_id)
                row = call(client,'POST',f"units/{row['unit']}/cases/{row['id']}/step",body)
    return join['id'], apply['id']


def academic_examples(base):
    """Create a submitted and reviewed assignment, a dialogue, and a schedule project."""
    options = dict(base_url=base,headers={'X-Requested-With':'ATLAS'},trust_env=False)
    today = datetime.now(timezone(timedelta(hours=3))).date()
    with httpx.Client(**options) as student, httpx.Client(**options) as teacher, httpx.Client(**options) as scheduler:
        call(student,'POST','login',{'login':'alina.demo','password':'AtlasDemo!2026-A'})
        call(teacher,'POST','login',{'login':'orlov.demo','password':'AtlasTeach!2026-M'})
        call(scheduler,'POST','login',{'login':'schedule.demo','password':'AtlasRooms!2026-S'})
        load = call(teacher,'GET','teaching')['items'][0]['id']
        title = 'Обход связного графа'
        works = f'teaching/{load}/works'
        work = call(teacher,'POST',works,{'title':title,'instructions':'Разберите посещение вершин в порядке обхода.',
                                          'due':(today+timedelta(days=7)).isoformat()})
        assignment = next(row for row in call(student,'GET','learning/assignments')['items'] if row['title']==title)
        submission = call(student,'POST',f"learning/assignments/{assignment['id']}/submit",
                          {'text':'В учебном графе все вершины достижимы из первой.'})['submission']
        work_path = f"{works}/{work['id']}"
        comment = 'Добавьте пример с изолированной вершиной.'
        call(teacher,'POST',f"{work_path}/feedback/{submission['id']}",
             {'submitted_version':submission['version'],'score':94,'comment':comment})
        recipient = call(student,'GET','direct/recipients?q=Орлов')['items'][0]['id']
        sent = call(student,'POST','direct/dialogs',{'recipient_id':recipient,'message':'Как проверить связность графа?'})
        conversation = f"direct/{sent['dialog_id']}"
        reply = 'Попробуйте обход из одной вершины и проверьте, все ли вершины посещены.'
        call(teacher,'POST',f"direct/dialogs/{sent['dialog_id']}/messages",{'message':reply})
        choices = call(scheduler,'GET','scheduling/options')
        teacher_id = next(row['id'] for row in choices['teachers'] if row['name']=='Михаил Орлов')
        room = next(row['id'] for row in choices['rooms'] if row['code']=='А-301')
        project = call(scheduler,'POST','scheduling/changes',{'action':'create','note':'Разбор обхода графов',
            'slot':{'load_id':load,'teacher_id':teacher_id,'room_id':room,'day':(today+timedelta(days=35)).isoformat(),
                    'start':'20:00','end':'21:00','kind':'seminar'}})
        call(scheduler,'POST',f"scheduling/changes/{project['id']}/step",{'step':'submit','version':project['version']})
    return {work_path:comment,conversation:reply,f"schedule-changes/{project['id']}":'Новое занятие · На согласовании'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['academic','units','acceptance'])
    parser.add_argument('--engines',default='chromium')
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--screenshots',type=Path,required=True)
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True,exist_ok=True)
    report = report_start('Local real browsers, fictional disposable database, viewport emulation')
    report.update(phase=args.phase,geometry=[],accessibility=[],engines=[],screenshots=[])
    actors = [(idx,name,routes[:]) for idx,name,routes in WORKSPACES]
    if args.phase!='academic':
        actors[0][2].extend(['union','union?tab=content','union?tab=cases',
                            'vuc','vuc?tab=learning','vuc?tab=content','vuc?tab=cases'])
        actors.extend([(6,'union', ['union-office','union-office?tab=content','union-office?tab=report','notifications']),
                       (7,'vuc', ['vuc-office','vuc-office?tab=content','vuc-office?tab=learning','vuc-office?tab=report','notifications'])])
    axe = (ROOT/'node_modules/axe-core/axe.min.js').read_text(encoding='utf-8')
    try:
        with isolated_server() as server, sync_playwright() as browsers:
            captures = set(CAPTURES)
            expected = {}
            if args.phase!='academic':
                join, apply = unit_examples(server['base'])
                actors[0][2].extend([f'union/{join}',f'vuc/{apply}'])
                actors[-2][2].append(f'union-office/{join}')
                actors[-1][2].append(f'vuc-office/{apply}')
                captures.update([f'union/{join}', f'vuc-office/{apply}'])
            if args.phase=='acceptance':
                expected = academic_examples(server['base'])
                work, conversation, project = expected
                actors[0][2].append(conversation)
                actors[1][2].extend([work,conversation])
                for index in (2,3,4):
                    actors[index][2].append(project)
                actors.append((1,'second-student',['home','schedule','grades','requests','direct','union?tab=cases','vuc?tab=learning']))
                captures.update(expected)
            for engine in args.engines.split(','):
                browser = getattr(browsers,engine).launch(headless=True)
                report['engines'].append(dict(name=engine,version=browser.version))
                for index,actor,routes in actors:
                    context=browser.new_context(locale='ru-RU',reduced_motion='reduce')
                    if engine=='chromium':
                        context.add_init_script(axe)
                    page=context.new_page()
                    page.on('pageerror',lambda error:report['failures'].append(str(error)))
                    page.on('response',lambda response:report['failures'].append(
                        dict(status=response.status,path=response.url.split('/api/',1)[-1])) if response.status>=500 else None)
                    browser_login(page,server['base'],index)
                    for width in WIDTHS:
                        page.set_viewport_size({'width':width,'height':900})
                        for route in routes:
                            url=server['base']+'/app/'+route
                            page.goto(url,wait_until='networkidle')
                            browser_ready(page)
                            assert page.url==url,(actor,url,page.url)
                            if route in expected:
                                target = page.locator('[data-messenger-messages]') if route.startswith('direct/') else page
                                target.get_by_text(expected[route],exact=True).first.wait_for()
                            try:
                                report['geometry'].append(dict(engine=engine,actor=actor,route=route,**geometry(page)))
                            except AssertionError as error:
                                report['failures'].append(dict(engine=engine,actor=actor,route=route,width=width,error=str(error)))
                            if engine=='chromium' and route in captures:
                                name=f"{args.phase}-{actor}-{width}-{route.translate(str.maketrans('/?=','---'))}.png"
                                page.screenshot(path=str(args.screenshots/name),full_page=True,animations='disabled')
                                report['screenshots'].append(name)
                                violations=page.evaluate('''async () => (await axe.run(document,{
                                    runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}
                                })).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))''')
                                item=dict(actor=actor,route=route,width=width,violations=violations)
                                report['accessibility'].append(item)
                                if violations:
                                    report['failures'].append(item)
                    print(f'{engine} {actor}: {len(routes)*len(WIDTHS)} layouts',flush=True)
                    context.close()
                browser.close()
    except Exception as error:
        report['failures'].append(str(error))
    report=save_report(args.report,report)
    print(f"{report['status']}: {len(report['geometry'])} layouts, {len(report['failures'])} failures")
    return int(report['status']!='PASS')


if __name__=='__main__':
    raise SystemExit(main())
