"""Capture both ATLAS themes in a real browser against disposable demo data."""
from __future__ import annotations

import argparse
import base64
from collections import deque
from datetime import date, timedelta
import json
from pathlib import Path
import re
from struct import unpack
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urlencode, urlsplit

from playwright.sync_api import expect, sync_playwright

from improvement_runtime import ROOT, browser_ready, isolated_server


ACCOUNTS = {'student': 0, 'office': 2, 'teacher': 3, 'dispatcher': 4, 'admin': 5, 'union': 6, 'vuc': 7}
VIEWPORTS = {360: 800, 390: 844, 768: 1024, 1440: 960}
ROLE_PAGES = {
    'student': ('home schedule grades plan requests notifications profile certificates courses assignments exams '
                'attendance calendar tasks notes flashcards quizzes focus consultations messages library events finance '
                'contacts knowledge portfolio settings university materials direct union vuc announcements'),
    'office': ('staff staffdesk staffmessages profile settings notifications university materials materials-admin direct '
               'timetable-admin schedule-changes registry tables announcements announcement-admin'),
    'teacher': ('profile settings notifications university materials materials-admin direct teacher teaching teach-schedule '
                'teach-consultations tables announcements'),
    'dispatcher': 'profile settings notifications timetable-admin schedule-changes registry tables announcements',
    'admin': 'profile settings notifications timetable-admin schedule-changes registry tables announcements',
    'union': 'profile settings notifications union-office announcements',
    'vuc': 'profile settings notifications vuc-office announcements',
}
MODAL_ACTIONS = {
    'home': ['[data-action="search"]', '[data-action="new-request"]'],
    'assignments': ['[data-c-action="assignment"]'],
    'tasks': ['[data-c-action="task-new"]', '[data-c-action="task-edit"]', '[data-c-action="task-delete"]'],
    'notes': ['[data-c-action="note-new"]', '[data-c-action="note-edit"]'],
    'flashcards': ['[data-c-action="flashcard-new"]', '[data-c-action="flashcard-open"]'],
    'quizzes': ['[data-c-action="quiz-open"]'],
    'focus': ['[data-c-action="focus-log"]'],
    'messages': ['[data-c-action="ticket-new"]', '[data-c-action="ticket-open"]'],
    'staffmessages': ['[data-c-action="ticket-open"]'],
    'portfolio': ['[data-c-action="portfolio-new"]', '[data-c-action="portfolio-edit"]'],
    'settings': ['[data-c-action="revoke-sessions"]'],
    'staffdesk': ['[data-c-action="staff-slot"]', '[data-c-action="staff-event"]'],
    'staff': ['[data-action="request-details"]'],
    'requests': ['[data-action="new-request"]', '[data-action="request-details"]'],
    'certificates': ['[data-action="new-request"]', '.request-is-ready'],
    'materials-admin': ['[data-school-material="new"]', '[data-school-material="edit"]', '[data-school-material="delete"]'],
    'announcement-admin': ['[data-announcement-action="new"]', '[data-announcement-action="edit"]'],
    'teaching': ['[data-op-action="grade"]', '[data-op-action="attendance"]', '[data-op-action="new-work"]',
                 '[data-op-action="edit-work"]', '[data-op-action="feedback"]'],
    'teach-consultations': ['[data-op-action="consultation"]'],
    'timetable-admin': ['[data-op-action="class-create"]', '[data-op-action="class-update"]', '[data-op-action="class-cancel"]'],
    'schedule-changes': ['[data-op-action="edit-change"]', '[data-op-action^="step-"]'],
    'registry': ['[data-op-action="new-ref"]', '[data-op-action="edit-ref"]'],
    'union': ['[data-unit-action="join"]', '[data-unit-action="aid"]', '[data-unit-action="consult"]',
              '[data-unit-action="appeal"]', '[data-unit-action="event"]'],
    'vuc': ['[data-unit-action="apply"]'],
    'union-office': ['[data-unit-action="new-publication"]', '[data-unit-action="edit-publication"]',
                     '[data-unit-action^="step-"]'],
    'vuc-office': ['[data-unit-action="new-publication"]', '[data-unit-action="edit-program"]',
                   '[data-unit-action="edit-group"]', '[data-unit-action="edit-session"]',
                   '[data-unit-action="edit-result"]', '[data-unit-action^="step-"]'],
}
INTERACTIONS = {
    'home': ['.home-links > summary', '[data-announcement-priority="important"]'],
    'grades': ['.metric-explanation > summary', '.session-card > summary'],
    'schedule': ['[data-view="day"]', '[data-view="week"]'],
    'calendar': ['[data-calendar-view="day"]', '[data-calendar-view="week"]', '.calendar-options > summary'],
    'requests': ['[data-request-view="services"]', '[data-request-filter="rejected"]'],
    'certificates': ['[data-request-view="services"]', '[data-request-filter="rejected"]'],
    'staff': ['[data-staff-kind="certificate"]', '[data-staff-kind="all"]', '[data-staff-filter="overdue"]'],
    'notifications': ['[data-notice-filter="unread"]', '[data-notice-filter="request"]'],
    'settings': ['.theme-choices input:checked'],
    'materials': ['[data-school-slide]'],
    'announcement-admin': ['.announcement-history summary'],
    'exams': ['.text-details > summary'],
    'knowledge': ['.campus-faq summary'],
}
VIEW_QUERY = {'tab', 'dataset', 'scope', 'recipient', 'status'}


def visit(page, base, path):
    page.goto(base + path, wait_until='domcontentloaded')
    browser_ready(page)
    assert page.url == base + path, (path, page.url)


def login(page, base, account):
    page.goto(base, wait_until='domcontentloaded')
    page.locator('[data-action="demo-picker"]').click()
    page.locator(f'[data-demo="{account}"]').click()
    browser_ready(page)


def first_visible(page, selector):
    return page.locator(f'{selector}:visible').first


def seed_examples(pages, base):
    """Use the interface to give otherwise empty views some fictional content."""
    student = pages['student']
    visit(student, base, '/app/direct')
    first_visible(student, 'a[href*="?recipient="]').click()
    student.get_by_label('Сообщение', exact=True).fill('Здравствуйте! Когда откроется запись на консультацию?')
    student.locator('.school-compose button[type=submit]').click()
    expect(student).to_have_url(re.compile(r'/app/direct/\d+$'))
    for page_name, action in [('union', 'join'), ('vuc', 'apply')]:
        visit(student, base, '/app/' + page_name)
        first_visible(student, f'[data-unit-action="{action}"]').click()
        dialog = student.get_by_role('dialog')
        for checkbox in dialog.get_by_role('checkbox').all():
            checkbox.check()
        dialog.get_by_role('button', name='Отправить', exact=True).click()
        expect(student).to_have_url(re.compile(r'/app/' + page_name + r'/\d+$'))
    dispatcher = pages['dispatcher']
    visit(dispatcher, base, '/app/timetable-admin')
    first_visible(dispatcher, '[data-op-action="class-create"]').click()
    dialog = dispatcher.get_by_role('dialog')
    dialog.get_by_label('Группа и дисциплина').select_option(label='ИТ-24-03 · Алгоритмы и структуры данных')
    dialog.get_by_label('Преподаватель', exact=True).select_option(label='Михаил Орлов')
    dialog.get_by_label('Аудитория', exact=True).select_option(label='А-301 · 45 мест')
    dialog.get_by_label('Дата', exact=True).fill((date.today() + timedelta(days=30)).isoformat())
    dialog.get_by_label('Начало', exact=True).fill('19:00')
    dialog.get_by_label('Окончание', exact=True).fill('20:00')
    dialog.get_by_role('button', name='Сохранить', exact=True).click()
    expect(dispatcher).to_have_url(re.compile(r'/app/schedule-changes/\d+$'))


def linked_views(page):
    for href in page.locator('#app a[href^="/app/"]').evaluate_all('links => links.map(a => a.getAttribute("href"))'):
        url = urlsplit(href)
        query = parse_qsl(url.query)
        if all(key in VIEW_QUERY for key, _ in query):
            yield url.path + ('?' + urlencode(query) if query else '')
    current = urlsplit(page.url)
    if current.path == '/app/tables':
        fields = page.locator('[name="dataset"] option').evaluate_all('options => options.map(o => o.value)')
        for dataset in fields:
            yield '/app/tables?dataset=' + dataset
        query = dict(parse_qsl(current.query))
        if page.locator('select[name="scope"]').count() and 'scope' not in query:
            scope = page.locator('select[name="scope"] option[value]:not([value=""])').first
            if scope.count():
                yield current.path + '?' + urlencode({**query, 'scope': scope.get_attribute('value')})


def capture(page, path, state, run, *, full_page=True, expected_error=False):
    width = page.evaluate('document.documentElement.clientWidth')
    scroll_width = page.evaluate('document.documentElement.scrollWidth')
    role = run['role']
    screen = run['screen']
    name = re.sub(r'[^a-zA-Z0-9_-]+', '-', path.removeprefix('/app/').strip('/')).strip('-') or 'login'
    slug = name + ('--' + state if state != 'page' else '')
    relative = Path(run['theme'], str(screen), role, slug + '.png')
    destination = run['out'] / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if screen == 'zoom-200':
        # Capture the whole native zoom viewport rather than Playwright's CSS clip.
        target = {
            'page': '.login-form-wrap' if role == 'auth' else '#page-title',
            'theme-choices-input-checked': '.theme-choices',
            'password-visible': '.password-wrap',
            'document-preview': 'h1',
        }.get(state)
        anchor = page.locator(target).first if target else None
        if anchor and anchor.count():
            anchor.evaluate('el => el.scrollIntoView({block: "center", behavior: "instant"})')
        cdp = page.context.new_cdp_session(page)
        try:
            shot = cdp.send('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
            png = base64.b64decode(shot['data'])
            destination.write_bytes(png)
        finally:
            cdp.detach()
        assert unpack('>I', png[16:20])[0] >= width * page.evaluate('devicePixelRatio')
    else:
        png = page.screenshot(path=destination, full_page=full_page, animations='disabled', scale='css')
    result = {'role': role, 'theme': run['theme'], 'screen': screen, 'path': path, 'state': state,
              'width': width, 'scroll_width': scroll_width, 'file': relative.as_posix(),
              'pixels': list(unpack('>II', png[16:24]))}
    run['report']['captures'].append(result)
    if scroll_width > width + 1:
        run['report']['overflow'].append(result)
    if run['axe'] and screen in (360, 1440) and not expected_error:
        run['report']['contrast_scans'] += 1
        checks = page.evaluate('''async () => {
            const result = await axe.run({runOnly: ['color-contrast']});
            const findings = rule => rule.nodes.map(node => ({target: node.target, summary: node.failureSummary}));
            return {violations: result.violations.flatMap(findings), incomplete: result.incomplete.flatMap(findings)};
        }''')
        findings = checks['violations']
        if findings:
            run['report']['contrast'].append({'file': relative.as_posix(), 'findings': findings})
        if checks['incomplete']:
            run['report']['contrast_manual'].append({'file': relative.as_posix(), 'findings': checks['incomplete']})


def capture_states(page, base, path, run, seen):
    view = urlsplit(path).path.split('/')[2]
    for selector in MODAL_ACTIONS.get(view, []) + INTERACTIONS.get(view, []):
        control = first_visible(page, selector)
        kind = (view, selector)
        if kind in seen or not control.count() or not control.is_enabled():
            continue
        seen.add(kind)
        state = re.sub(r'[^a-z0-9]+', '-', selector).strip('-')
        try:
            if selector == '.theme-choices input:checked':
                control.press('ArrowRight')
                page.keyboard.press('ArrowLeft')
                expect(control).to_be_focused()
                assert control.evaluate('radio => radio.matches(":focus-visible")')
            else:
                control.click(timeout=3500)
            if selector in MODAL_ACTIONS.get(view, []):
                expect(page.locator('.modal')).to_be_visible(timeout=5000)
            if selector == '[data-c-action="quiz-open"]':
                expect(page.locator('.campus-quiz')).to_be_visible()
            if selector == '[data-c-action="flashcard-open"]':
                page.locator('.modal [data-c-action="flashcard-reveal"]').click()
                expect(page.locator('.campus-flashcard-back')).to_be_visible()
            if selector == '[data-announcement-action="new"]':
                form = page.locator('.modal form')
                form.locator('[name=title]').fill('Расписание открытых консультаций')
                form.locator('[name=body]').fill('Вымышленное объявление для проверки оформления.')
                form.locator('[data-announcement-action="preview"]').click()
                expect(form.locator('[data-announcement-preview]')).to_be_visible()
                form.locator('[data-announcement-preview]').scroll_into_view_if_needed()
            if selector.startswith(('[data-staff-', '[data-notice-filter', '[data-request-filter')):
                expect(page.locator(selector)).to_have_attribute('aria-pressed', 'true')
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            capture(page, path, state, run, full_page=selector not in MODAL_ACTIONS.get(view, []))
        except Exception as exc:
            run['report']['errors'].append({'path': path, 'state': state, 'screen': run['screen'], 'error': str(exc)})
        finally:
            visit(page, base, path)


def watch(page, report, role):
    page.on('pageerror', lambda error: report['console_errors'].append({'role': role, 'message': str(error)}))
    def console(message):
        if message.type == 'error' and not (
            message.text.startswith('Failed to load resource: the server responded with a status of ')
            and (message.text.endswith('401 (Unauthorized)') or message.text.endswith('503 (Service Unavailable)'))
        ):
            report['console_errors'].append({'role': role, 'message': message.text})
    page.on('console', console)


def capture_auth(page, base, run):
    page.goto(base, wait_until='domcontentloaded')
    expect(page.locator('#login-form')).to_be_visible()
    capture(page, '/', 'page', run)
    page.locator('[data-action="password"]').click()
    capture(page, '/', 'password-visible', run)
    page.locator('[data-action="demo-picker"]').click()
    expect(page.locator('#demo-dialog')).to_be_visible()
    capture(page, '/', 'demo-picker', run, full_page=False)
    page.keyboard.press('Escape')
    page.locator('#login-name').fill('theme-audit.demo')
    page.locator('#login-password').fill('Вымышленный пароль')
    page.locator('#login-form button[type="submit"]').click()
    expect(page.locator('#login-error')).to_be_visible()
    capture(page, '/', 'invalid-login', run, full_page=False)


def capture_role(page, base, run):
    role = run['role']
    first = urlsplit(page.url).path
    queue = deque([first, *('/app/' + name for name in ROLE_PAGES[role].split())])
    seen_paths, seen_states = set(), set()
    if role == 'student':
        queue.extend(['/app/announcements?status=archived', '/app/requests', '/app/certificates'])
    while queue:
        path = queue.popleft()
        if path in seen_paths:
            continue
        seen_paths.add(path)
        try:
            visit(page, base, path)
            queue.extend(view for view in linked_views(page) if view not in seen_paths)
            capture(page, path, 'page', run)
            if run['screen'] in (360, 1440, 'zoom-200'):
                capture_states(page, base, path, run, seen_states)
        except Exception as exc:
            run['report']['errors'].append({'path': path, 'role': role, 'screen': run['screen'], 'error': str(exc)})
    if role == 'student':
        capture_document(page, base, run)
    if role == 'student' and run['screen'] in (360, 1440, 'zoom-200'):
        visit(page, base, '/app/settings')
        if run['screen'] in (360, 'zoom-200'):
            page.locator('[data-action="drawer-open"]').click()
            expect(page.locator('.shell')).to_have_class(re.compile('drawer-open'))
            capture(page, '/app/settings', 'mobile-menu', run, full_page=False)
            page.keyboard.press('Escape')
        if run['screen'] == 1440:
            page.locator('[data-action="sidebar-toggle"]').click()
            capture(page, '/app/settings', 'collapsed-sidebar', run, full_page=False)
            page.locator('[data-action="sidebar-toggle"]').click()
        page.keyboard.press('Control+k')
        expect(page.locator('.modal')).to_be_visible()
        capture(page, '/app/settings', 'keyboard-focus-search', run, full_page=False)
        page.keyboard.press('Escape')
        def failed_page(route):
            capture(page, '/app/settings', 'loading-and-disabled', run, full_page=False)
            route.fulfill(status=503, json={'detail': 'Сервис временно недоступен.'})
        page.route('**/api/services/preferences', failed_page, times=1)
        page.locator('#refresh-current').click()
        expect(page.locator('.error-state')).to_be_visible()
        capture(page, '/app/settings', 'error', run, expected_error=True)
        visit(page, base, '/app/announcements?q=zz-atlas-empty')
        capture(page, '/app/announcements?q=zz-atlas-empty', 'empty-search', run)
        page.locator('.sidebar [data-action="logout"]').evaluate('button => button.click()')
        expect(page.locator('.toast-message')).to_have_text('Вы вышли из кабинета.')
        capture(page, '/', 'logout-toast', run, full_page=False)


def capture_document(page, base, run):
    visit(page, base, '/app/certificates')
    first_visible(page, '.request-is-ready').click()
    link = page.get_by_role('dialog').get_by_role('link', name='Открыть', exact=True)
    with page.expect_popup() as preview:
        link.click()
    document = preview.value
    try:
        expect(document.locator('.warning')).to_contain_text('Не имеет юридической силы')
        watch(document, run['report'], run['role'])
        capture(document, '/app/certificates', 'document-preview', run, expected_error=True)
    finally:
        document.close()


def new_report():
    return {'contrast_scans': 0, **{name: [] for name in
            ('captures', 'overflow', 'contrast', 'contrast_manual', 'console_errors', 'errors')}}


def audit(args, base, browser, report, screen):
    run = {'out': args.out, 'theme': args.theme, 'screen': screen, 'report': report, 'axe': args.axe}
    contexts = {role: browser.new_context(viewport={'width': screen, 'height': VIEWPORTS[screen]},
                                         locale='ru-RU', color_scheme=args.theme, reduced_motion='reduce')
                for role in args.roles}
    try:
        if args.axe:
            for actor in contexts.values():
                actor.add_init_script(path=ROOT / 'node_modules' / 'axe-core' / 'axe.min.js')
        pages = {role: actor.new_page() for role, actor in contexts.items()}
        for role, page in pages.items():
            watch(page, report, role)
            if role == 'student':
                capture_auth(page, base, {**run, 'role': 'auth'})
            login(page, base, ACCOUNTS[role])
        if set(ACCOUNTS).issubset(pages):
            seed_examples(pages, base)
        for role, page in pages.items():
            page.goto(base, wait_until='domcontentloaded')
            browser_ready(page)
            count = len(report['captures'])
            capture_role(page, base, {**run, 'role': role})
            print(f"{args.theme} {screen} {role}: {len(report['captures']) - count}", flush=True)
    finally:
        for actor in contexts.values():
            actor.close()


def audit_zoom(args, base, automation, report):
    # The browser extension uses native tab zoom, including reflow and font scaling.
    with TemporaryDirectory(prefix='atlas-theme-zoom-') as temp:
        root = Path(temp)
        extension = root / 'extension'
        extension.mkdir()
        (extension / 'manifest.json').write_text(json.dumps({
            'manifest_version': 3, 'name': 'ATLAS theme audit zoom', 'version': '1.0',
            'background': {'service_worker': 'worker.js'}, 'permissions': ['tabs'],
        }), encoding='utf-8')
        (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(() => {});', encoding='utf-8')
        context = automation.chromium.launch_persistent_context(
            root / 'profile', channel='chromium', headless=True, no_viewport=True, locale='ru-RU',
            color_scheme=args.theme, reduced_motion='reduce',
            args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}', '--window-size=1440,960'],
        )
        run = {'out': args.out, 'theme': args.theme, 'screen': 'zoom-200', 'report': report, 'axe': False}
        try:
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            watch(page, report, 'zoom')
            if set(ACCOUNTS).issubset(args.roles):
                fixture_browser = automation.chromium.launch()
                fixtures = {role: fixture_browser.new_page() for role in args.roles}
                try:
                    for role, fixture in fixtures.items():
                        login(fixture, base, ACCOUNTS[role])
                    seed_examples(fixtures, base)
                finally:
                    fixture_browser.close()
            page.goto(base)
            dpr = page.evaluate('devicePixelRatio')
            factor = worker.evaluate('''async origin => {
                const [tab] = await chrome.tabs.query({url: origin + '/*'});
                await chrome.tabs.setZoom(tab.id, 2);
                return chrome.tabs.getZoom(tab.id);
            }''', base)
            assert factor == 2, factor
            page.wait_for_function('expected => Math.abs(devicePixelRatio - expected) < .04', arg=2 * dpr)
            report['zoom'] = {'factor': factor, 'dpr': page.evaluate('devicePixelRatio')}
            capture_auth(page, base, {**run, 'role': 'auth'})
            page.keyboard.press('Escape')
            for role in args.roles:
                login(page, base, ACCOUNTS[role])
                count = len(report['captures'])
                capture_role(page, base, {**run, 'role': role})
                print(f"{args.theme} zoom-200 {role}: {len(report['captures']) - count}", flush=True)
                context.clear_cookies()
        finally:
            context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--theme', choices=['light', 'dark'], required=True)
    size = parser.add_mutually_exclusive_group(required=True)
    size.add_argument('--screen', type=int, choices=VIEWPORTS)
    size.add_argument('--zoom', action='store_true')
    parser.add_argument('--axe', action='store_true')
    parser.add_argument('--roles', nargs='+', choices=ACCOUNTS, default=list(ACCOUNTS))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = new_report()
    try:
        with isolated_server(root=args.root) as server, sync_playwright() as automation:
            config = automation.request.new_context(base_url=server['base'])
            try:
                report['build'] = config.get('/api/config').json()['build']
            finally:
                config.dispose()
            if args.zoom:
                audit_zoom(args, server['base'], automation, report)
            else:
                browser = automation.chromium.launch()
                report['browser'] = browser.version
                audit(args, server['base'], browser, report, args.screen)
    finally:
        screen = 'zoom-200' if args.zoom else args.screen
        target = args.out / f'{args.theme}-{screen}.json'
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({key: len(value) for key, value in report.items() if isinstance(value, list)}, flush=True)
    return 1 if report['errors'] or report['console_errors'] or report['overflow'] or report['contrast'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
