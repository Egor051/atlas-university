"""Compare real browser geometry before/after the usability pass on an isolated DB.

No successful API responses are mocked. The working atlas.db is never opened.
Run: .venv/Scripts/python.exe scripts/ux_capture.py before|after
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, expect

from browser_check import start_server, stop_server, ready, visit

ROOT = Path(__file__).resolve().parents[1]
STUDENT = ['home', 'schedule', 'grades', 'plan', 'requests', 'notifications', 'profile',
           'campus', 'courses', 'assignments', 'exams', 'attendance', 'calendar', 'tasks',
           'notes', 'flashcards', 'quizzes', 'focus', 'consultations', 'messages', 'library',
           'events', 'finance', 'contacts', 'knowledge', 'portfolio', 'settings']
STAFF = ['staff', 'staffdesk', 'staffmessages', 'profile', 'settings']
WIDTHS = [(360, 800), (390, 844), (768, 1024), (1440, 1000)]


def run(phase):
    destination = ROOT / 'screenshots' / ('ux-' + phase + '-2026-11-08')
    destination.mkdir(parents=True, exist_ok=True)
    report = {'phase': phase, 'created_at': datetime.now(timezone.utc).isoformat(),
              'source_sha256': {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
                                for f in ['static/app.js', 'static/campus.js', 'static/style.css', 'static/campus.css', 'static/usability.css']},
              'scope': 'Real local Chromium, isolated fictional SQLite; no public hosting or physical device check.',
              'geometry': [], 'errors': [], 'accessibility': []}
    axe = (ROOT / 'node_modules/axe-core/axe.min.js').read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='atlas-ux-') as folder:
        base, _, process, log = start_server(folder)
        try:
            with sync_playwright() as automation:
                browser = automation.chromium.launch()
                for account, routes in [(0, STUDENT), (2, STAFF)]:
                    context = browser.new_context(locale='ru-RU', reduced_motion='reduce')
                    context.add_init_script(axe)
                    page = context.new_page()
                    page.on('pageerror', lambda error: report['errors'].append(str(error)))
                    page.goto(base, wait_until='networkidle')
                    if account == 0:
                        for width, height in WIDTHS:
                            page.set_viewport_size({'width': width, 'height': height})
                            page.screenshot(path=str(destination / f'{width}-login.png'), full_page=True)
                    page.get_by_role('button',name='Попробовать демо',exact=True).click()
                    page.locator(f'[data-demo="{account}"]').click()
                    ready(page)
                    for width, height in WIDTHS:
                        page.set_viewport_size({'width': width, 'height': height})
                        for route in routes:
                            visit(page, base, route)
                            data = page.evaluate('''() => ({width:innerWidth, height:innerHeight,
                              scrollWidth:document.documentElement.scrollWidth,
                              scrollHeight:document.documentElement.scrollHeight,
                              contentHeight:Math.round(document.querySelector('#page-content').getBoundingClientRect().height),
                              textSize:getComputedStyle(document.querySelector('.page-subtitle')).fontSize})''')
                            report['geometry'].append({'role': 'staff' if account == 2 else 'student', 'page': route, **data})
                            assert data['scrollWidth'] <= width, f'Overflow at {width} / {route}'
                            expect(page.locator('.concept-bar')).to_contain_text('все данные вымышлены')
                            if phase == 'after':
                                result = page.evaluate('''async () => {const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}});return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),passes:r.passes.length}}''')
                                report['accessibility'].append({'role':account,'width':width,'page':route,**result})
                            name = ('staff-' if account == 2 else '') + route
                            page.screenshot(path=str(destination / f'{width}-{name}.png'), full_page=True, animations='disabled')
                        print(f'{phase}: account {account}, {width}px, {len(routes)} pages', flush=True)
                    context.close()
                browser.close()
        finally:
            stop_server(process, log)
            path = ROOT / 'docs/verification' / f'ux-{phase}-2026-11-08.json'
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['errors']:
        raise AssertionError(report['errors'])
    violations = [x for x in report['accessibility'] if x['violations']]
    if violations:
        raise AssertionError(f'{len(violations)} accessibility states failed; see report')


if __name__ == '__main__':
    phase = sys.argv[1] if len(sys.argv) > 1 else 'after'
    if phase not in {'before', 'after'}:
        raise SystemExit('Expected before or after')
    run(phase)
