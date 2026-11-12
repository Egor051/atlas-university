"""Real local HTTP acceptance, isolated fictional DB, screenshots at four widths.

Run: python scripts/browser_check.py. Requires installed Playwright Chromium.
No API fixtures or synthetic successful responses are used. One fault check aborts
a real request; empty states are produced by deleting fictional test fixtures.
The user's atlas.db is never opened by this runner.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS = ROOT / 'screenshots'
REPORT = ROOT / 'docs' / 'verification' / 'browser-report.json'
checks: list[str] = []
captures: list[str] = []
errors: list[str] = []
csp_errors: list[str] = []
layout_checks: list[dict] = []


def passed(name):
    checks.append(name)
    print(f'PASS {name}', flush=True)


def start_server(folder):
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    db_path = Path(folder) / 'browser.sqlite3'
    env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + db_path.as_posix(),
           'APP_ENV': 'test', 'DEMO_MODE': 'true', 'COOKIE_SECURE': 'false',
           'PUBLIC_ORIGIN': base, 'ALLOWED_HOSTS': '127.0.0.1,localhost'}
    log = open(Path(folder) / 'server.log', 'w', encoding='utf-8')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                                '--host', '127.0.0.1', '--port', str(port),
                                '--log-level', 'warning'], cwd=ROOT, env=env,
                               stdout=log, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(100):
        if process.poll() is not None:
            log.flush()
            raise RuntimeError((Path(folder) / 'server.log').read_text(encoding='utf-8'))
        try:
            with urlopen(base + '/api/ready', timeout=.5) as r:
                if r.status == 200:
                    return base, db_path, process, log
        except Exception:
            time.sleep(.15)
    process.terminate()
    raise RuntimeError('Temporary API did not become ready')


def monitor(page):
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda msg: csp_errors.append(msg.text) if msg.type == 'error' and
            ('Content Security Policy' in msg.text or 'violates' in msg.text) else None)


def stop_server(process, log):
    if os.name == 'nt' and process.poll() is None:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    log.close()


def ready(page):
    page.locator('#page-title').wait_for(timeout=18000)
    expect(page.locator('#page-content')).not_to_have_attribute('aria-busy', 'true')
    assert page.locator('.error-state').count() == 0, page.locator('#page-content').inner_text()


def visit(page, base, section):
    page.goto(base + '/app/' + section, wait_until='networkidle')
    ready(page)


def screenshot(page, name):
    path = SCREENSHOTS / (name + '.png')
    page.screenshot(path=str(path), full_page=not bool(page.locator('.modal').count()), animations='disabled')
    captures.append(path.relative_to(ROOT).as_posix())


def layout(page, name):
    result = page.evaluate("""() => ({width: innerWidth,scrollWidth:document.documentElement.scrollWidth,
       bad:[...document.querySelectorAll('body *')].filter(e=>{
          const r=e.getBoundingClientRect();return r.width>0 && r.right>innerWidth+1 &&
          getComputedStyle(e).position!=='fixed' && !e.closest('.login-art,.hero-art');
       }).slice(0,5).map(e=>e.tagName+'.'+e.className)})""")
    layout_checks.append({'screen': name, **result})
    assert result['scrollWidth'] <= result['width'], f'Horizontal overflow {name}: {result}'


def login(page, base, account):
    page.goto(base, wait_until='networkidle')
    page.get_by_role('button',name='Попробовать демо',exact=True).click()
    page.locator(f'[data-demo="{account}"]').click()
    ready(page)


def run():
    SCREENSHOTS.mkdir(exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='atlas-browser-') as folder:
        base, db_path, process, log = start_server(folder)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                a = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                b = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
                office = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                page = a.new_page()
                mark = b.new_page()
                staff = office.new_page()
                for tab in (page, mark, staff):
                    monitor(tab)
                page.goto(base, wait_until='networkidle')
                screenshot(page, 'desktop-login')
                layout(page, 'login-1440')
                for width, height in [(768, 1024), (390, 844), (360, 800)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    layout(page, f'login-{width}')
                    if width == 390:
                        screenshot(page, 'mobile-login')
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.locator('#login-name').fill('alina.demo')
                page.locator('#login-password').fill('AtlasDemo!2026-A')
                page.locator('#login-password').press('Enter')
                ready(page)
                passed('Login through the real form and authenticated dashboard')

                for width, height, prefix in [(1440,1000,'desktop'),(768,1024,'tablet'),
                                               (390,844,'mobile'),(360,800,'minimum')]:
                    page.set_viewport_size({'width':width,'height':height})
                    for section in ['home','schedule','grades','plan','requests','notifications','profile']:
                        visit(page, base, section)
                        name='dashboard' if section=='home' else section
                        layout(page, f'{section}-{width}')
                        screenshot(page, f'{prefix}-{name}')
                        if width==390 and section=='home':
                            page.screenshot(path=str(SCREENSHOTS/'mobile-dashboard-viewport.png'),animations='disabled')
                            captures.append('screenshots/mobile-dashboard-viewport.png')
                passed('All seven student sections at 360/390/768/1440: no horizontal scroll')

                visit(page, base, 'schedule')
                page.locator('[data-view="day"]').click()
                expect(page.locator('[data-view="day"]')).to_be_focused()
                expect(page.locator('.day-pick')).to_have_count(7)
                page.locator('.day-pick').last.click()
                expect(page.locator('.day-pick').last).to_be_focused()
                expect(page.locator('.day-view')).to_contain_text('В этот день занятий нет')
                screenshot(page, 'mobile-schedule-day')
                with page.expect_download() as download:
                    page.locator('a[href*="/schedule/export"]').click()
                calendar = Path(download.value.path()).read_text(encoding='utf-8')
                assert 'BEGIN:VCALENDAR' in calendar and 'Europe/Moscow' in calendar
                assert 'Инженерия ПО' not in calendar
                passed('Day/week navigation, keyboard focus, real private ICS download')

                visit(page, base, 'plan')
                task = a.request.get(base+'/api/deadlines').json()[0]
                checkbox = page.locator(f'[data-deadline="{task["id"]}"]')
                checkbox.check()
                expect(checkbox).to_have_count(0)
                page.reload(wait_until='networkidle')
                ready(page)
                saved = next(x for x in a.request.get(base+'/api/deadlines').json() if x['id']==task['id'])
                assert saved['is_done']
                page.locator('[data-plan-filter="done"]').click()
                expect(page.locator('[data-plan-filter="done"]')).to_be_focused()
                expect(page.locator(f'[data-deadline="{task["id"]}"]')).to_be_checked()
                screenshot(page, 'mobile-plan-done')
                page.locator(f'[data-deadline="{task["id"]}"]').uncheck()
                passed('Task completion persists after reload; undo works')

                visit(page, base, 'certificates')
                page.locator('[data-request-view="services"]').first.click()
                page.locator('.certificate-service [data-type="study"]').click()
                expect(page.locator('.skip-link')).to_have_attribute('inert','')
                comment='Для демонстрации: справка по месту требования. Все данные вымышлены.'
                page.locator('#doc-comment').fill(comment)
                layout(page,'request-form-360')
                screenshot(page,'mobile-request-form')
                page.keyboard.press('Escape')
                expect(page.locator('.certificate-service [data-type="study"]')).to_be_focused()
                page.locator('.certificate-service [data-type="study"]').click()
                expect(page.locator('#doc-comment')).to_have_value(comment)
                submit=page.locator('#request-form button[type="submit"]')
                submit.focus()
                page.keyboard.press('Tab')
                expect(page.locator('.modal .close-btn')).to_be_focused()
                with page.expect_response(lambda r:r.url==base+'/api/requests' and r.request.method=='POST') as response:
                    submit.click()
                assert response.value.status == 201
                request_id=response.value.json()['id']
                expect(page.locator('.detail-summary')).to_contain_text('Справка об обучении')
                screenshot(page,'mobile-request-timeline')
                layout(page,'request-timeline-360')
                passed('Request form, session draft, focus trap, Escape return, saved request history')

                login(mark,base,1)
                assert b.request.get(base+f'/api/requests/{request_id}').status==404
                assert b.request.get(base+f'/api/requests/{request_id}/document').status==404
                mine=b.request.get(base+'/api/requests').json()
                assert all(x['id']!=request_id for x in mine)
                assert 'Марк' in mark.locator('#page-title').inner_text()
                passed('Second student has a separate profile, grades, requests and cannot open first student result')

                login(staff,base,2)
                staff.locator('[data-staff-kind="certificate"]').click()
                staff.locator('#staff-search').fill(str(request_id))
                staff.locator(f'.request-row[data-id="{request_id}"]').wait_for()
                staff.locator(f'.request-row[data-id="{request_id}"]').click()
                expect(staff.locator('#staff-form')).to_be_visible()
                for status, message in [('review','Обращение принято. Проверяем сведения в демонстрационной базе.'),
                                        ('processing','Подготавливаем конкурсный образец справки.'),
                                        ('ready','Образец справки подготовлен. Скачайте его в личном кабинете. Документ демонстрационный.')]:
                    staff.locator('#staff-status').select_option(status)
                    staff.locator('#staff-message').fill(message)
                    version=int(staff.locator('#staff-form').get_attribute('data-version'))
                    staff.locator('#staff-form button[type="submit"]').click()
                    if status!='ready':
                        expect(staff.locator('#staff-form')).to_have_attribute('data-version',str(version+1))
                    else:
                        expect(staff.locator('#staff-form')).to_have_count(0)
                        expect(staff.locator('.staff-answer')).to_contain_text('Образец справки подготовлен')
                screenshot(staff,'desktop-staff-result')
                for width, height, prefix in [(1440,1000,'desktop'),(768,1024,'tablet'),(390,844,'mobile'),(360,800,'minimum')]:
                    staff.locator('.close-btn').click() if staff.locator('.modal').count() else None
                    staff.set_viewport_size({'width':width,'height':height})
                    visit(staff,base,'staff')
                    layout(staff,f'staff-{width}')
                    screenshot(staff,f'{prefix}-staff')
                passed('Staff searches requests, follows allowed transitions and sends a real response/notification')

                page.locator('.close-btn').click()
                visit(page,base,'certificates')
                page.locator('[data-request-filter="ready"]').click()
                page.locator(f'.request-row[data-id="{request_id}"]').click()
                expect(page.locator('.staff-answer')).to_contain_text('Образец справки подготовлен')
                expect(page.locator('.request-history>li')).to_have_count(4)
                with page.expect_download() as download:
                    page.locator('a[href*="/document"][download]').click()
                document=Path(download.value.path()).read_text(encoding='utf-8')
                assert 'Алина Ветрова' in document and 'Марк Северин' not in document
                assert 'конкурс' in document.lower() and 'вымышлен' in document.lower()
                assert '<script' not in document.lower()
                screenshot(page,'mobile-document-ready')
                passed('Student sees all four history events and downloads their fictional completed document')

                page.locator('.close-btn').click()
                visit(page,base,'notifications')
                event=next(n for n in a.request.get(base+'/api/notifications').json() if n.get('request_id')==request_id)
                page.locator(f'[data-action="open-notice"][data-id="{event["id"]}"]').click()
                expect(page.locator('.modal')).to_contain_text(f'Заявка № {request_id}')
                page.locator('.close-btn').click()
                visit(page,base,'notifications')
                page.locator('[data-notice-filter="unread"]').click()
                first_unread=page.locator('[data-action="read-notification"]').first
                first_unread.wait_for()
                read_id=first_unread.get_attribute('data-id')
                first_unread.click()
                expect(page.locator(f'[data-action="open-notice"][data-id="{read_id}"]')).to_have_count(0)
                with page.expect_response(lambda r:r.url==base+'/api/notifications/read-all' and r.request.method=='POST') as read_all:
                    page.locator('[data-action="read-all"]').click()
                assert read_all.value.status == 200, read_all.value.text()
                expect(page.get_by_text('Все уведомления прочитаны.',exact=True)).to_be_visible()
                expect(page.locator('[data-action="read-all"]')).to_be_disabled()
                assert a.request.get(base+'/api/notifications?paginated=true').json()['unread_count']==0
                passed('Notification links to exact request; individual read refreshes unread filter; read-all clears count')

                page.route('**/api/schedule?*',lambda route:route.abort('failed'))
                page.goto(base+'/app/schedule',wait_until='networkidle')
                expect(page.locator('.error-state')).to_be_visible()
                layout(page,'error-state-360')
                screenshot(page,'mobile-error-state')
                page.unroute('**/api/schedule?*')
                page.locator('.error-state [data-action="retry"]').click()
                ready(page)
                passed('Real request failure shows a recoverable error and Retry succeeds')

                mark_id=b.request.get(base+'/api/me').json()['id']
                with sqlite3.connect(db_path) as conn:
                    conn.execute('DELETE FROM deadlines WHERE student_id=?',(mark_id,))
                    conn.execute('DELETE FROM grades WHERE student_id=?',(mark_id,))
                    conn.execute('DELETE FROM notifications WHERE student_id=?',(mark_id,))
                conn.close()
                visit(mark,base,'grades')
                expect(mark.locator('#page-content')).to_contain_text('Оценки ещё не опубликованы')
                screenshot(mark,'mobile-empty-grades')
                visit(mark,base,'plan')
                expect(mark.locator('.empty-state')).to_be_visible()
                layout(mark,'empty-plan-390')
                screenshot(mark,'mobile-empty-plan')
                visit(mark,base,'notifications')
                expect(mark.locator('.empty-state')).to_be_visible()
                screenshot(mark,'mobile-empty-notifications')
                passed('Genuine empty database states render meaningful grades, plan and notification messages')

                visit(page,base,'profile')
                page.locator('.danger-button[data-action="logout"]').click()
                expect(page.locator('#login-form')).to_be_visible()
                assert a.request.get(base+'/api/me').status==401
                passed('Logout invalidates the server session')
                assert not errors, errors
                assert not csp_errors, csp_errors
                passed('No uncaught browser JavaScript errors and no CSP violations')
                browser.close()
        finally:
            stop_server(process, log)
    report={'verified_at':datetime.now(timezone(timedelta(hours=3))).isoformat(),
            'scope':'Real local HTTP + Chromium + isolated fictional SQLite; not a public-site or physical-device test',
            'api_mocks':False,'fault_injection':'one request aborted; empty fictional fixtures deleted in temporary database',
            'checks':checks,'layout_checks':layout_checks,'screenshots':captures,
            'javascript_errors':errors,'csp_errors':csp_errors,'status':'PASS'}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Browser acceptance PASS: {len(checks)} scenarios, {len(layout_checks)} layout checks, {len(captures)} screenshots',flush=True)


if __name__=='__main__':
    run()
