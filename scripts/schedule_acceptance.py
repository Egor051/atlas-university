"""Exercise the real schedule UI and its API on an isolated or public server."""
import argparse
from contextlib import ExitStack, nullcontext
from pathlib import Path
import json

from playwright.sync_api import expect, sync_playwright

from improvement_runtime import browser_login, browser_ready, browser_visit, geometry, isolated_server


HEADERS = {'X-Requested-With': 'ATLAS'}
CALENDAR = '/api/scheduling/calendar'
CHANGES = '/api/scheduling/changes'
LOCAL_WEEK = '2034-10-02'
EXAM_WEEK = '2034-10-09'
PUBLISHED_WEEK = '2026-11-09'


def api(context, path, method='GET', data=None):
    response = context.request.fetch(path, method=method, data=data, headers=HEADERS)
    assert response.ok, f'{method} {path} {response.status}: {response.text()}'
    return response.json()


def publish(dispatcher, office, admin, data):
    row = api(dispatcher, CHANGES, 'POST', data)
    for role, action in [(dispatcher, 'submit'), (office, 'agree'), (admin, 'publish')]:
        row = api(role, f'{CHANGES}/{row["id"]}/step', 'POST', {'step': action, 'version': row['version']})
    return row


def prepare(browser, base, path):
    with ExitStack() as stack:
        actors = []
        for account in (4, 2, 5):
            context = browser.new_context(base_url=base, viewport={'width': 360, 'height': 800}, device_scale_factor=1)
            stack.callback(context.close)
            browser_login(context.new_page(), base, account)
            actors.append(context)
        dispatcher, office, admin = actors
        page = admin.pages[0]
        settings = api(admin, CALENDAR+'?year=2034')
        student = next(member for member in settings['members'] if member['name'] == 'Алина Ветрова')
        exercise = api(admin, CALENDAR+'/subgroups', 'PUT', {
            'group_id': student['group_id'], 'code': 'Подгруппа А', 'capacity': 10,
        })
        api(admin, CALENDAR+'/members', 'PUT', {
            'student_id': student['id'], 'subgroup_id': exercise['id'], 'version': student['version'],
        })
        browser_visit(page, base, 'academic-calendar?year=2034')
        page.get_by_role('button', name='Добавить семестр').click()
        dialog = page.get_by_role('dialog')
        dialog.get_by_label('Календарь для').select_option('g:'+str(student['group_id']))
        for label, value in [('Начало семестра', LOCAL_WEEK), ('Конец семестра', '2034-10-20'),
                             ('Основание или источник дат', 'Учебный график изолированной приёмки')]:
            dialog.get_by_label(label).fill(value)
        periods = [('teaching', LOCAL_WEEK, '2034-10-08'), ('credit', EXAM_WEEK, '2034-10-12'),
                   ('exam', '2034-10-13', '2034-10-20')]
        for i, (kind, begin, end) in enumerate(periods):
            if i:
                dialog.get_by_role('button', name='Добавить период').click()
            part = dialog.locator('[data-calendar-period]').nth(i)
            part.get_by_label('Период', exact=True).select_option(kind)
            part.get_by_label('Начало периода').fill(begin)
            part.get_by_label('Конец периода').fill(end)
        dialog.get_by_role('button', name='Сохранить').click()
        expect(dialog).to_have_count(0)
        expect(page.get_by_text('Экзаменационная сессия', exact=False)).to_be_visible()
        geometry(page)
        page.screenshot(path=path/'local-calendar-360.png', animations='disabled')

        options = api(dispatcher, '/api/scheduling/options')
        load = next(x for x in options['loads'] if x['teacher']=='Михаил Орлов')
        teacher = next(x['id'] for x in options['teachers'] if x['name']==load['teacher'])
        rooms = {x['code']: x['id'] for x in options['rooms']}
        slot = dict(load_id=load['id'], teacher_id=teacher, day=LOCAL_WEEK, kind='lecture',
                    start='11:00', end='12:30', room_id=rooms['А-301'])
        draft = publish(dispatcher, office, admin, {'action':'create', 'slot':slot})
        for day, kind, room, name in [
            ('2034-10-03','practice','Онлайн','Разбор задач по поиску'), ('2034-10-04','lab','Б-208','Графы и маршруты'),
            ('2034-10-05','consultation','Б-115','Консультация по лабораторной работе'),
            ('2034-10-06','organization','В-404','Собрание учебной группы'), (EXAM_WEEK,'credit','В-404','Зачёт по алгоритмам'),
            ('2034-10-13','exam','А-301','Экзамен по алгоритмам'),
        ]:
            fields = dict(slot, day=day, kind=kind, room_id=rooms[room], title=name)
            if kind=='lab':
                fields['subgroup_id'] = exercise['id']
            publish(dispatcher, office, admin, {'action':'create', 'slot':fields})
        update = dict(action='update', event_id=draft['event_id'], event_version=1, note='Изменение аудитории и времени',
                      slot=dict(slot, room_id=rooms['В-404'], start='10:30', end='12:00'))
        publish(dispatcher, office, admin, update)
        page = dispatcher.pages[0]
        browser_visit(page, base, 'timetable-admin?week='+LOCAL_WEEK)
        page.get_by_role('button', name='Подготовить занятие').click()
        expect(page.get_by_label('Вид события')).to_be_visible()
        geometry(page)
        return update


def check_matrix(browser, base, local, folder):
    evidence = []
    for width, height in [(1440,1000), (390,844), (360,800)]:
        for compact in ([False,True] if local else [None]):
            mode = 'compact' if compact else 'regular'
            color = 'dark' if compact else 'light'
            with browser.new_context(base_url=base, viewport={'width':width,'height':height},
                                     color_scheme=color, device_scale_factor=1, has_touch=width<500) as context:
                page = context.new_page()
                browser_login(page, base)
                if local:
                    api(context,'/api/services/preferences','POST',{'compact_mode':compact})
                target = LOCAL_WEEK if local else PUBLISHED_WEEK
                browser_visit(page,base,'schedule?date='+target+'&view=week')
                if local:
                    assert page.locator('body').evaluate("(node) => node.classList.contains('compact-campus')") == compact
                expect(page.locator('.schedule-week .schedule-day')).to_have_count(7)
                expect(page.locator('.schedule-week .schedule-day').last).to_contain_text('Выходной')
                expect(page.locator('.schedule-event')).not_to_have_count(0)
                if local:
                    for label in ('Лекция','Практическое занятие','Лабораторная работа','Консультация',
                                  'Организационное мероприятие'):
                        expect(page.get_by_text(label,exact=True)).to_be_visible()
                    expect(page.get_by_text('ИТ-24-03 · Подгруппа А',exact=True)).to_be_visible()
                geometry(page)
                prefix = 'local' if local else 'public'
                if (width, compact) in ((1440,False),(390,True),(1440,None),(390,None)):
                    page.screenshot(path=folder/f'{prefix}-week-{width}-{mode}.png',animations='disabled')
                page.get_by_role('button',name='Месяц',exact=True).click()
                expect(page.locator('.schedule-month')).to_be_visible()
                assert page.locator('.schedule-month-day').count() % 7 == 0
                geometry(page)
                if (width, compact) in ((1440,False),(390,True)):
                    page.screenshot(path=folder/f'{prefix}-month-{width}-{mode}.png',animations='disabled')
                page.locator(f'.schedule-month-day[data-day="{target}"]').click()
                expect(page.locator('.day-view')).to_be_visible()
                expect(page.locator('.day-pick[aria-pressed=true]')).to_have_attribute('data-day',target)
                geometry(page)
                if local:
                    change = page.locator('.schedule-changed').first
                    expect(change.locator('details')).not_to_have_attribute('open','')
                    change.locator('summary').click()
                    expect(change).to_contain_text('Было')
                    expect(change).to_contain_text('Стало')
                    expect(change).to_contain_text('10:30')
                    if width==390 and compact:
                        change.screenshot(path=folder/'local-change-390-compact.png',animations='disabled')
                evidence.append(dict(width=width,density=mode,views=['week','month','day']))
    return evidence


def check_dismissal(browser, base, update):
    with browser.new_context(base_url=base) as context:
        page = context.new_page()
        browser_login(page,base)
        route = 'schedule?date='+LOCAL_WEEK+'&view=week'
        browser_visit(page,base,route)
        page.get_by_role('button',name='Скрыть уведомление об изменениях').click()
        expect(page.locator('.schedule-banner')).to_have_count(0)
        expect(page.get_by_text('Перенесено',exact=True)).to_be_visible()
        page.reload()
        browser_ready(page)
        expect(page.locator('.schedule-banner')).to_have_count(0)
        api(context,'/api/logout','POST')
        browser_login(page,base)
        browser_visit(page,base,route)
        expect(page.locator('.schedule-banner')).to_have_count(0)
        with ExitStack() as stack:
            staff = []
            for account in (4,2,5):
                actor = stack.enter_context(browser.new_context(base_url=base))
                browser_login(actor.new_page(),base,account)
                staff.append(actor)
            publish(*staff, dict(update,event_version=2,slot=dict(update['slot'],start='10:45',end='12:15')))
        page.reload()
        browser_ready(page)
        change_link = page.get_by_role('link',name='Показать изменение')
        expect(change_link).to_be_visible()
        expect(page.locator('.schedule-banner')).to_contain_text('· 1')
        change_link.click()
        expect(page.locator('.schedule-event.search-match .schedule-event-details[open]')).to_contain_text('Было')
        browser_visit(page,base,'schedule?date='+EXAM_WEEK+'&view=week')
        expect(page.get_by_text('Зачётная неделя',exact=True).first).to_be_visible()
        expect(page.get_by_text('Экзаменационная сессия',exact=True).first).to_be_visible()
        expect(page.locator('.schedule-type-exam h3')).to_have_text('Экзамен по алгоритмам')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Public base URL for read-only checks')
    parser.add_argument('--screenshots', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.screenshots.mkdir(exist_ok=True, parents=True)
    args.report.parent.mkdir(exist_ok=True, parents=True)
    with (nullcontext({'base':args.url}) if args.url else isolated_server()) as server, sync_playwright() as play:
        base, local = server['base'], args.url is None
        browser = play.chromium.launch()
        if local:
            update = prepare(browser,base,args.screenshots)
        matrix = check_matrix(browser,base,local,args.screenshots)
        if local:
            check_dismissal(browser,base,update)
        with browser.new_context(base_url=base) as context:
            health = api(context, '/api/health')
            assert api(context, '/api/ready')['database']=='ready'
        browser.close()
    report = dict(ok=True, public=not local, build=health['build'], view_checks=matrix,
                  dismissal_checked=local, admin_form_checked=local)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
