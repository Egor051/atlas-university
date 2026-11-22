"""Check the semester in a real browser with an independent local database."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
from secrets import token_urlsafe
import socket
import tempfile
from threading import Thread
import time
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
import uvicorn

from scripts.improvement_runtime import browser_login, browser_ready, geometry


CASES = (('2026-11-23T00:00:00+03:00', 360), ('2026-11-25T12:15:00+03:00', 390),
         ('2026-11-28T23:59:00+03:00', 1440))
ROUTES = {
    0: ('home', 'schedule', 'grades', 'exams', 'courses', 'assignments', 'requests', 'certificates',
        'finance', 'knowledge', 'direct', 'messages', 'consultations', 'university', 'contacts',
        'union', 'vuc', 'events', 'profile', 'settings', 'announcements', 'notifications'),
    1: ('home', 'grades', 'exams', 'assignments', 'certificates', 'finance'),
    2: ('staff', 'staffdesk', 'staffmessages', 'announcement-admin', 'timetable-admin', 'schedule-changes',
        'academic-calendar', 'registry', 'tables', 'courses', 'materials-admin', 'direct'),
    3: ('teacher', 'teaching', 'teach-schedule', 'absence-certificates', 'teach-consultations', 'tables',
        'courses', 'materials-admin', 'direct'),
    4: ('timetable-admin', 'schedule-changes', 'academic-calendar', 'registry', 'tables'),
    5: ('registry', 'timetable-admin', 'schedule-changes', 'academic-calendar', 'tables', 'material-delegations'),
    6: ('union-office',),
    7: ('vuc-office',),
}
CAPTURES = {
    (0, 'home'), (0, 'schedule'), (0, 'grades'), (1, 'exams'), (2, 'staff'), (3, 'teaching'),
    (7, 'vuc-office'),
}


@contextmanager
def server(app, listener):
    service = uvicorn.Server(uvicorn.Config(app, log_level='warning', timeout_graceful_shutdown=5))
    worker = Thread(target=service.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not service.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        if not service.started:
            raise RuntimeError('Isolated contest web server failed to start.')
        yield
    finally:
        service.should_exit = True
        worker.join(10)


@contextmanager
def transport(app, listener, base, asgi):
    if not asgi:
        with server(app, listener):
            yield None
        return
    with TestClient(app, base_url=base) as client:
        assets = {}

        def respond(route):
            request = route.request
            target = urlsplit(request.url)
            if request.method == 'GET' and target.path.startswith('/static/') and request.url in assets:
                route.fulfill(**assets[request.url])
                return
            client.cookies.clear()
            response = client.request(request.method, target.path + ('?' + target.query if target.query else ''),
                                      headers=request.all_headers(), content=request.post_data_buffer,
                                      follow_redirects=False)
            headers = {key: value for key, value in response.headers.items()
                       if key not in {'content-encoding', 'content-length', 'transfer-encoding'}}
            answer = dict(status=response.status_code, headers=headers, body=response.content)
            if request.method == 'GET' and target.path.startswith('/static/') and response.status_code == 200:
                assets[request.url] = answer
            route.fulfill(**answer)
        yield respond


def cabinet(browser, base, moment, width, account, routes, screenshots, report, respond):
    browser_context = browser.new_context(viewport={'width': width, 'height': 940}, locale='ru-RU',
                                          timezone_id='Europe/Moscow', reduced_motion='reduce')
    try:
        if respond:
            browser_context.route(base + '/**', respond)
        page = browser_context.new_page()
        page.clock.set_fixed_time(moment)
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        page.on('response', lambda response: report['errors'].append(f'{response.status} {response.url}')
                if response.status >= 500 else None)
        browser_login(page, base, account)
        for route in routes:
            destination = f'{base}/app/{route}'
            page.goto(destination, wait_until='domcontentloaded')
            browser_ready(page)
            assert page.url == destination, (route, page.url)
            result = geometry(page)
            if route == 'grades':
                expect(page.locator('[data-type="points"] table')).to_contain_text('Разбор')
                expect(page.locator('#page-content')).not_to_contain_text('Перенесённый остаток')
            if (account, route) in CAPTURES and (account < 2 or width == 1440):
                name = f'{account}-{route}-{width}.png'
                page.screenshot(path=screenshots / name)
                result['screenshot'] = name
            report['routes'].append({'date': moment.isoformat(), 'account': account, 'route': route, **result})
        if account == 0:
            page.goto(f'{base}/app/grades', wait_until='domcontentloaded')
            browser_ready(page)
            points = page.locator('[data-type="points"]')
            points.get_by_label('Дисциплина', exact=True).select_option(label='Алгоритмы и структуры данных')
            expect(points.locator('table')).to_contain_text('Алгоритмы и структуры данных')
            assert geometry(page)['width'] == width
    finally:
        browser_context.close()


def acceptance(args, report):
    with tempfile.TemporaryDirectory(prefix='atlas-contest-browser-') as temp, socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        base = f'http://127.0.0.1:{listener.getsockname()[1]}'
        os.environ.update(DATABASE_URL='sqlite:///' + (Path(temp) / 'contest.db').as_posix(),
                          APP_ENV='test', DEMO_MODE='true', COOKIE_SECURE='false', PUBLIC_ORIGIN=base,
                          ALLOWED_HOSTS='127.0.0.1', ATLAS_CERTIFICATE_KEY=token_urlsafe(32))
        from app import db
        from app.contest.seed import install
        from app.main import app

        moment = datetime.fromisoformat(CASES[0][0])

        class BrowserClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

        try:
            with patch.object(db, 'datetime', BrowserClock):
                report['dataset'] = install()
                with transport(app, listener, base, args.asgi) as respond, sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, channel=args.channel)
                    try:
                        report['browser'] = browser.version
                        for stamp, width in CASES:
                            moment = datetime.fromisoformat(stamp)
                            for account, routes in ROUTES.items():
                                cabinet(browser, base, moment, width, account, routes, args.screenshots, report, respond)
                    finally:
                        browser.close()
        finally:
            db.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', choices=('chrome', 'msedge'))
    parser.add_argument('--asgi', action='store_true', help='Use the real app through in-process ASGI instead of loopback TCP.')
    parser.add_argument('--screenshots', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'transport': 'ASGI' if args.asgi else 'HTTP', 'routes': [], 'errors': [], 'status': 'FAIL'}
    try:
        acceptance(args, report)
        if report['errors']:
            raise RuntimeError(report['errors'])
        report['status'] = 'PASS'
    except Exception as error:
        report['errors'].append(str(error))
        raise
    finally:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'{report["status"]}: {len(report["routes"])} cabinet pages')


if __name__ == '__main__':
    main()
