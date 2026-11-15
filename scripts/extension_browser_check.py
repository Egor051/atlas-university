"""Real local browser acceptance for the ATLAS 3 extension.

Runs only against its own temporary SQLite database and HTTP server. Successful
API responses are never mocked. Playwright Chromium and local axe-core are used;
this is not evidence about public hosting, a physical phone, or access from РФ.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from browser_check import ROOT, start_server, stop_server

SCREENSHOTS = ROOT / 'screenshots'
REPORT = ROOT / 'docs' / 'verification' / 'extension-browser-report.json'
STUDENT_PAGES = ['home', 'schedule', 'grades', 'requests', 'certificates', 'notifications', 'profile',
                 'announcements', 'courses', 'assignments', 'exams', 'materials', 'consultations', 'messages',
                 'events', 'finance', 'contacts', 'knowledge', 'settings']
STAFF_PAGES = ['staff', 'staffdesk', 'staffmessages', 'announcement-admin', 'settings', 'profile']
WIDTHS = [(360, 800), (390, 844), (768, 1024), (1440, 1000)]
TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']


class Acceptance:
    def __init__(self):
        self.checks = []
        self.failures = []
        self.layout_checks = []
        self.captures = []
        self.axe_checks = []
        self.page_errors = []
        self.csp_errors = []
        self.api_errors = []
        self.token = 'atlas-ui-' + uuid.uuid4().hex[:10]
        self.source_start = self.fingerprints()

    @staticmethod
    def fingerprints():
        paths = [*sorted((ROOT / 'static').glob('*')), *sorted((ROOT / 'app').glob('*.py'))]
        return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths if path.is_file()}

    def report(self, final=False):
        violations = sum(len(v['nodes']) for check in self.axe_checks for v in check.get('violations', []))
        current_source = self.fingerprints()
        changed_source = sorted(path for path in set(self.source_start) | set(current_source)
                                if self.source_start.get(path) != current_source.get(path))
        report = {'verified_at': datetime.now(timezone(timedelta(hours=3))).isoformat(),
                  'scope': 'Real local Chromium and temporary isolated SQLite database; no mocked successful responses. Not a physical-device, public-hosting or Russian-connectivity check.',
                  'status': ('FAIL' if self.failures or self.page_errors or self.csp_errors or self.api_errors or violations or changed_source else 'PASS') if final else 'RUNNING',
                  'checks': self.checks, 'failures': self.failures, 'layout_checks': self.layout_checks,
                  'screenshots': self.captures, 'axe_tags': TAGS, 'axe_screens': self.axe_checks,
                  'violating_nodes': violations, 'page_errors': self.page_errors,
                  'csp_errors': self.csp_errors, 'unexpected_api_errors': self.api_errors,
                  'source_sha256': self.source_start, 'source_changed_during_run': changed_source}
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return report

    def monitor(self, page):
        page.on('pageerror', lambda error: self.page_errors.append({'url': page.url, 'error': str(error)}))
        page.on('console', lambda msg: self.csp_errors.append({'url': page.url, 'error': msg.text})
                if msg.type == 'error' and ('Content Security Policy' in msg.text or 'violates' in msg.text) else None)
        page.on('response', lambda response: self.api_errors.append({'url': response.url, 'status': response.status})
                if '/api/' in response.url and response.status >= 400 and not (response.status == 401 and response.url.endswith('/api/me')) else None)

    def ready(self, page):
        page.locator('#page-title').wait_for(timeout=18000)
        expect(page.locator('#page-content')).not_to_have_attribute('aria-busy', 'true', timeout=18000)
        assert page.locator('.error-state').count() == 0, page.locator('#page-content').inner_text()
        expect(page.locator('.concept-bar')).to_contain_text('Конкурсный концепт')
        expect(page.locator('.concept-bar')).to_contain_text('все данные вымышлены')

    def visit(self, page, base, section):
        page.goto(base + '/app/' + section, wait_until='networkidle')
        self.ready(page)
        assert page.url.rstrip('/').endswith('/app/' + section), f'Unexpected route: {page.url}'

    def login(self, page, base, account):
        page.goto(base, wait_until='networkidle')
        page.get_by_role('button',name='Или выбрать демо-аккаунт',exact=True).click()
        page.locator(f'[data-demo="{account}"]').click()
        self.ready(page)

    def capture(self, page, name):
        path = SCREENSHOTS / (name + '.png')
        page.screenshot(path=str(path), full_page=not bool(page.locator('.modal').count()), animations='disabled')
        self.captures.append(path.relative_to(ROOT).as_posix())

    def geometry(self, page, name):
        result = page.evaluate("""() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
          overhanging:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();
            return r.width>0&&r.right>innerWidth+1&&getComputedStyle(e).position!=='fixed'&&
              !e.closest('.login-art,.hero-art');}).slice(0,8).map(e=>e.tagName+'.'+String(e.className))})""")
        self.layout_checks.append({'screen': name, **result})
        assert result['scrollWidth'] <= result['width'], f'Horizontal overflow: {name}: {result}'

    def axe(self, page, name):
        result = page.evaluate("""async tags => {const result=await axe.run(document,{runOnly:{type:'tag',values:tags}});
          return {violations:result.violations.map(v=>({id:v.id,impact:v.impact,help:v.help,helpUrl:v.helpUrl,
            nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),
            incomplete:result.incomplete.map(v=>({id:v.id,help:v.help,count:v.nodes.length})),
            passes:result.passes.length,testEngine:result.testEngine};}""", TAGS)
        self.axe_checks.append({'screen': name, **result})
        if result['violations']:
            print('AXE ' + name + ': ' + json.dumps(result['violations'], ensure_ascii=False), flush=True)
        assert not result['violations'], 'Axe violations: ' + ', '.join(v['id'] for v in result['violations'])

    def case(self, name, page, operation):
        try:
            operation()
            self.checks.append(name)
            print('PASS ' + name, flush=True)
        except Exception as error:
            details = {'check': name, 'error': str(error), 'trace': traceback.format_exc(limit=5)}
            self.failures.append(details)
            print('FAIL ' + name + ': ' + str(error), flush=True)
            try:
                self.capture(page, 'extension-failure-' + str(len(self.failures)))
            except Exception:
                pass
        self.report()

    def submit(self, page, name, path, fill=None):
        form = page.locator(f'form[data-c-form="{name}"]')
        expect(form).to_be_visible()
        if fill:
            for field, value in fill.items():
                control = form.locator(f'[name="{field}"]')
                if control.evaluate('(element) => element.tagName') == 'SELECT':
                    control.select_option(str(value))
                else:
                    control.fill(str(value))
        with page.expect_response(lambda r: r.url.endswith('/api/' + path) and r.request.method == 'POST') as response:
            form.locator('button[type="submit"]').click()
        assert response.value.status in (200, 201), f'{path}: {response.value.status} {response.value.text()}'
        result = response.value.json()
        expect(form).to_have_count(0)
        self.ready(page)
        return result

    def confirm(self, page, name, resource_id, path):
        page.locator(f'[data-c-action="{name}"][data-id="{resource_id}"]').first.click()
        confirm = page.locator(f'.modal [data-c-action="{name}"][data-confirmed]')
        expect(confirm).to_be_visible()
        with page.expect_response(lambda r: r.url.endswith('/api/' + path) and r.request.method == 'POST') as response:
            confirm.click()
        assert response.value.status == 200, response.value.text()
        expect(page.locator('.modal')).to_have_count(0)
        self.ready(page)
        return response.value.json()

    def learning_flows(self, page, base):
        def courses():
            self.visit(page, base, 'courses')
            button = page.locator('[data-c-action="course"]').first
            course_id = int(button.get_attribute('data-id'))
            button.click()
            page.locator('.campus-modules details summary').first.click()
            checkbox = page.locator('[data-c-module]').first
            expect(checkbox).to_be_visible()
            module_id = int(checkbox.get_attribute('data-c-module'))
            expected = not checkbox.is_checked()
            with page.expect_response(lambda r: r.url.endswith(f'/api/learning/courses/{course_id}/modules/{module_id}') and r.request.method == 'POST') as response:
                checkbox.set_checked(expected)
            assert response.value.status == 200, response.value.text()
            expect(checkbox).to_be_enabled()
            page.locator('.close-btn').click()
            page.reload(wait_until='networkidle'); self.ready(page)
            page.locator(f'[data-c-action="course"][data-id="{course_id}"]').click()
            page.locator('.campus-modules details summary').first.click()
            expect(page.locator(f'[data-c-module="{module_id}"]')).to_be_checked(checked=expected)
            self.geometry(page, 'course-modules-modal-390'); self.axe(page, 'course-modules-modal-390')
            self.capture(page, 'extension-390-course-modules-modal')
            page.locator('.close-btn').click()
        self.case('Course module toggles through UI and persists after reload', page, courses)

        def assignments():
            self.visit(page, base, 'assignments')
            button = page.locator('[data-c-action="assignment"]').first
            task_id = int(button.get_attribute('data-id'))
            button.click()
            first = self.submit(page, 'assignment', f'learning/assignments/{task_id}/submit', {'text': self.token + ': учебное решение с проверкой.', 'url': 'https://example.com/study'})
            assert first['submission']['status'] == 'submitted'
            page.locator('[data-c-filter="assignments"][data-value="submitted"]').click()
            page.locator(f'[data-c-action="assignment"][data-id="{task_id}"]').click()
            withdrawn = self.confirm(page, 'withdraw', task_id, f'learning/assignments/{task_id}/withdraw')
            assert withdrawn['submission']['status'] == 'withdrawn'
            page.locator('[data-c-filter="assignments"][data-value="pending"]').click()
            page.locator(f'[data-c-action="assignment"][data-id="{task_id}"]').click()
            expect(page.locator('form[data-c-form="assignment"] [name="text"]')).to_have_value(self.token + ': учебное решение с проверкой.')
            second = self.submit(page, 'assignment', f'learning/assignments/{task_id}/submit', {'text': self.token + ': исправленная версия решения.'})
            assert second['submission']['version'] == withdrawn['submission']['version'] + 1
            assert len(second['attempts']) == 2
            page.locator('[data-c-filter="assignments"][data-value="submitted"]').click()
            page.locator(f'[data-c-action="assignment"][data-id="{task_id}"]').click()
            withdrawn = self.confirm(page, 'withdraw', task_id, f'learning/assignments/{task_id}/withdraw')
            assert withdrawn['submission']['status'] == 'withdrawn'
            page.reload(wait_until='networkidle'); self.ready(page)
            saved = page.context.request.get(base + f'/api/learning/assignments/{task_id}').json()
            assert saved['submission']['status'] == 'withdrawn'
            assert saved['submission']['text'] == self.token + ': исправленная версия решения.'
        self.case('Assignment UI submit, revision, withdrawal and persisted text', page, assignments)

    def run(self):
        SCREENSHOTS.mkdir(exist_ok=True)
        axe = ROOT / 'node_modules' / 'axe-core' / 'axe.min.js'
        if not axe.exists():
            raise RuntimeError('Install the project dev dependency axe-core before running this check')
        if REPORT.exists():
            previous = json.loads(REPORT.read_text(encoding='utf-8'))
            if previous.get('status') in ('PASS', 'FAIL'):
                history = REPORT.parent / 'history'
                history.mkdir(exist_ok=True)
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                (history / f'extension-browser-report-{timestamp}.json').write_text(json.dumps(previous, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='atlas-extension-browser-') as folder:
            base, db_path, process, log = start_server(folder)
            assert db_path.parent == Path(folder), 'Acceptance must use only its temporary database'
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    student = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce')
                    staff_context = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce')
                    for context in (student, staff_context):
                        context.add_init_script(path=str(axe))
                    page, staff = student.new_page(), staff_context.new_page()
                    self.monitor(page); self.monitor(staff)
                    self.login(page, base, 0); self.login(staff, base, 2)
                    self.learning_flows(page, base)
                    visits = 0
                    for width, height in WIDTHS:
                        for tab, role, sections in [(page, 'student', STUDENT_PAGES), (staff, 'staff', STAFF_PAGES)]:
                            tab.set_viewport_size({'width': width, 'height': height})
                            for section in sections:
                                label = (section if role == 'student' or section.startswith('staff') else 'staff-' + section)
                                name = f'extension-{width}-{label}'
                                def examine(tab=tab, section=section, name=name):
                                    self.visit(tab, base, section)
                                    self.geometry(tab, name)
                                    self.capture(tab, name)
                                    self.axe(tab, name)
                                self.case(f'{role} {section} at {width}px: load, concept, geometry, axe, screenshot', tab, examine)
                                visits += 1
                                if visits % 10 == 0:
                                    print(f'PROGRESS {visits}/{len(WIDTHS)*(len(STUDENT_PAGES)+len(STAFF_PAGES))} responsive page visits', flush=True)
                    browser.close()
            finally:
                stop_server(process, log)
        result = self.report(final=True)
        print(f'{result["status"]}: {len(self.checks)} checks, {len(self.layout_checks)} geometry states, {len(self.axe_checks)} axe states, {result["violating_nodes"]} violating nodes, {len(self.failures)} failures', flush=True)
        return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    runner = Acceptance()
    try:
        raise SystemExit(runner.run())
    except Exception as error:
        runner.failures.append({'check':'runner startup or infrastructure','error':str(error),'trace':traceback.format_exc()})
        runner.report(final=True)
        raise
