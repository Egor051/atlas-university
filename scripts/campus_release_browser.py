"""Capture the changed Campus pages in Chromium locally or over public HTTPS."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from playwright.sync_api import expect, sync_playwright

from improvement_runtime import ROOT, browser_ready, isolated_server


CONCEPT = 'Конкурсный концепт · все данные вымышлены · неофициальный сервис'
WIDTHS = (320, 360, 375, 390, 768, 1280, 1440, 1920)
THEMES = (('light', 'dark'), ('dark', 'light'), ('system', 'light'), ('system', 'dark'))
STUDENT = {
    'home': 'home', 'submissions': 'assignments?subject=' + quote('Алгоритмы и структуры данных'),
    'finance': 'finance', 'grades': 'grades', 'exams': 'exams',
    'notes': 'notes', 'materials': 'materials', 'news': 'announcements',
}
SECOND_STUDENT = {'mark-submissions': 'assignments?subject=' + quote('Инженерия ПО')}


def visit(page, base, route):
    page.goto(f'{base}/app/{route}', wait_until='domcontentloaded')
    browser_ready(page)


def sign_in(page, base, account):
    page.goto(base, wait_until='domcontentloaded')
    page.locator('[data-action="demo-picker"]').click()
    page.locator(f'[data-demo="{account}"]').click()
    browser_ready(page)


def observe(page, label, output, report, width, theme, scheme, *, contrast):
    path = f'{theme}-{scheme}-{width}-{label}.png'
    dimensions = page.evaluate("""() => ({
        viewport: document.documentElement.clientWidth,
        document: document.documentElement.scrollWidth,
        theme: document.documentElement.dataset.theme,
        system_dark: matchMedia('(prefers-color-scheme: dark)').matches,
        scheme: document.querySelector('meta[name=theme-color]').content,
        concept: document.querySelector('.concept-bar')?.innerText.trim(),
        concept_count: document.querySelectorAll('.concept-bar').length
    })""")
    if dimensions['document'] > dimensions['viewport']:
        report['failures'].append({'screen': path, 'overflow': dimensions})
    if dimensions['concept'] != CONCEPT or dimensions['concept_count'] != 1 or dimensions['theme'] != theme:
        report['failures'].append({'screen': path, 'shell': dimensions})
    effective_dark = theme == 'dark' or (theme == 'system' and scheme == 'dark')
    if dimensions['system_dark'] != (scheme == 'dark') or dimensions['scheme'] != (
        '#151420' if effective_dark else '#f5f6fa'
    ):
        report['failures'].append({'screen': path, 'theme_mismatch': dimensions})
    if contrast:
        violations = page.evaluate("""async () => {
            const result = await axe.run({runOnly: ['color-contrast']});
            return result.violations.map(rule => rule.nodes.map(node => ({
                target: node.target, detail: node.failureSummary
            }))).flat();
        }""")
        if violations:
            report['failures'].append({'screen': path, 'contrast': violations})
    page.screenshot(path=output / path, full_page=True, animations='disabled')
    report['screens'].append({'file': path, 'contrast_checked': contrast, **dimensions})


def exercise_home(page, base, *, require_overflow):
    timeline = page.locator('.announcement-timeline')
    expect(timeline).to_be_visible()
    region = timeline.locator('#announcement-timeline-items')
    assert region.evaluate("node => /auto|scroll/.test(getComputedStyle(node).overflowY) && node.tabIndex === 0")
    overflow = region.evaluate("node => node.scrollHeight > node.clientHeight")
    assert overflow or not require_overflow
    if overflow:
        region.hover()
        page.mouse.wheel(0, 100)
        wait_for_scroll(region)
        region.evaluate('node => { node.scrollTop = 0; }')
        region.press('End')
        wait_for_scroll(region)
        region.evaluate('node => { node.scrollTop = 0; }')
    card = timeline.locator('.announcement-event').first
    news = card.locator('details.announcement-expansion')
    news.locator('summary').press('Enter')
    expect(news).to_have_attribute('open', '')
    expect(news.locator('.announcement-excerpt')).to_be_visible()
    link = card.locator('.announcement-title-link')
    expect(link).to_be_visible()
    target = link.get_attribute('href')
    link.press('Enter')
    expect(page).to_have_url(base + target)
    browser_ready(page)


def wait_for_scroll(region):
    assert region.evaluate("""async node => {
        for (let frame = 0; frame < 30 && node.scrollTop === 0; frame++) {
            await new Promise(requestAnimationFrame);
        }
        return node.scrollTop > 0;
    }""")


def verify_touch_scroll(browser, base):
    context = browser.new_context(
        viewport={'width': 375, 'height': 812}, is_mobile=True, has_touch=True, locale='ru-RU',
    )
    try:
        page = context.new_page()
        sign_in(page, base, 0)
        region = page.locator('#announcement-timeline-items')
        region.evaluate("node => node.scrollIntoView({block:'center', behavior:'instant'})")
        box = region.bounding_box()
        assert box and box['height'] >= 180
        x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] - 30
        cdp = context.new_cdp_session(page)
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
        for delta in range(20, 141, 20):
            cdp.send('Input.dispatchTouchEvent', {
                'type': 'touchMove', 'touchPoints': [{'x': x, 'y': y - delta}],
            })
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        wait_for_scroll(region)
        cdp.detach()
    finally:
        context.close()


def exercise_grades(page):
    table = page.locator('table.academic-table')
    expect(table).to_be_visible()
    sort = page.locator('[data-academic-sort]').first
    sort.press('Enter')
    expect(table.locator('th[aria-sort="ascending"], th[aria-sort="descending"]')).to_have_count(1)
    toggle = page.locator('[data-academic-toggle]').first
    toggle.press('Enter')
    expect(page.locator('.academic-details:visible').first).to_be_visible()
    search = page.locator('#academic-search')
    search.fill('zzzz-фильтр-без-результата')
    expect(page.locator('[data-academic-toggle]')).to_have_count(0)
    search.clear()
    expect(page.locator('[data-academic-toggle]').first).to_be_visible()
    discipline = page.locator('#academic-discipline')
    discipline.select_option(index=1)
    expect(page.locator('[data-academic-toggle]')).to_have_count(1)
    discipline.select_option(index=0)
    semester = page.locator('#academic-semester')
    semester.select_option(index=1)
    first = page.locator('[data-academic-toggle]').first
    expect(first).to_be_visible()
    if first.get_attribute('aria-expanded') == 'false':
        first.press('Enter')
    expect(page.locator('.academic-details:visible').first).to_be_visible()


def verify_block_spacing(page, label):
    if label not in ('submissions', 'mark-submissions', 'finance'):
        return
    toolbar = page.locator('.campus-toolbar').first
    expect(toolbar).to_be_visible()
    before = toolbar.evaluate("""node => {
        const previous = node.previousElementSibling;
        return previous && node.getBoundingClientRect().top - previous.getBoundingClientRect().bottom;
    }""")
    assert before is not None and before >= 12, (label, before)


def capture_modal(page, label, output, report, width, theme, scheme, *, contrast):
    controls = {
        'submissions': '.assignment-row [data-c-action="assignment"]',
        'teaching-works': '[data-op-action="new-work"]',
    }
    if label not in controls:
        return
    trigger = page.locator(controls[label]).first
    if not trigger.count():
        return
    trigger.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    observe(page, label + '-modal', output, report, width, theme, scheme, contrast=contrast)
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--public-url')
    parser.add_argument('--expect-build')
    parser.add_argument('--smoke', action='store_true', help='Run only two widths and explicit light/dark themes')
    args = parser.parse_args()
    if args.public_url and urlsplit(args.public_url).scheme != 'https':
        parser.error('--public-url must use HTTPS')
    args.output.mkdir(parents=True, exist_ok=True)
    axe = (ROOT / 'node_modules/axe-core/axe.min.js').read_text(encoding='utf-8')
    report = {'screens': [], 'failures': [], 'origin': args.public_url or 'isolated-local'}
    target = (nullcontext({'base': args.public_url.rstrip('/')})
              if args.public_url else isolated_server())
    try:
        with target as server, sync_playwright() as playwright:
            base = server['base']
            browser = playwright.chromium.launch()
            report['chromium'] = browser.version
            checks = playwright.request.new_context()
            health = checks.get(f'{base}/api/health')
            assert health.ok and health.json()['version'] == '3.7.0'
            report['health'] = health.json()
            if args.expect_build:
                assert report['health']['build'] == args.expect_build
            assert checks.get(f'{base}/api/ready').ok
            checks.dispose()
            widths = (375, 1280) if args.public_url or args.smoke else WIDTHS
            themes = THEMES[:2] if args.public_url or args.smoke else THEMES
            for theme, scheme in themes:
                for account, routes in ((0, STUDENT), (1, SECOND_STUDENT), (3, None)):
                    context = browser.new_context(
                        color_scheme=scheme, locale='ru-RU', timezone_id='Europe/Simferopol',
                        reduced_motion='reduce',
                    )
                    context.add_init_script(axe)
                    context.add_init_script(f"localStorage.setItem('atlas.theme', {json.dumps(theme)})")
                    page = context.new_page()
                    page.on('pageerror', lambda error: report['failures'].append({'javascript': str(error)}))
                    page.on('response', lambda response: report['failures'].append({
                        'path': urlsplit(response.url).path, 'status': response.status
                    }) if response.status >= 500 else None)
                    if account == 0:
                        for width in widths:
                            page.set_viewport_size({'width': width, 'height': 900})
                            page.goto(base, wait_until='domcontentloaded')
                            expect(page.locator('#login-form')).to_be_visible()
                            observe(page, 'login', args.output, report, width, theme, scheme, contrast=False)
                    sign_in(page, base, account)
                    if routes is None:
                        teaching = context.request.get(base + '/api/teaching')
                        assert teaching.ok
                        load = teaching.json()['items'][0]['id']
                        routes = {f'teaching-{tab}': f'teaching/{load}?tab={tab}'
                                  for tab in ('grades', 'attendance', 'works', 'report')}
                    if account == 0:
                        for legacy, canonical in (
                            ('notes', 'learning/notes'), ('planning/notes', 'learning/notes'),
                            ('attendance', 'grades'), ('records/attendance', 'grades'),
                            ('library', 'materials'), ('flashcards', 'materials'),
                            ('quizzes', 'materials'), ('focus', 'tasks'),
                        ):
                            visit(page, base, legacy)
                            expect(page).to_have_url(f'{base}/app/{canonical}')
                    for width in widths:
                        page.set_viewport_size({'width': width, 'height': 900})
                        for label, route in routes.items():
                            try:
                                contrast = not args.public_url and width in (375, 1280) and theme != 'system'
                                visit(page, base, route)
                                verify_block_spacing(page, label)
                                observe(page, label, args.output, report, width, theme, scheme, contrast=contrast)
                                if label == 'home':
                                    exercise_home(page, base, require_overflow=not args.public_url)
                                    observe(page, 'news-detail', args.output, report,
                                            width, theme, scheme, contrast=contrast)
                                if label == 'grades':
                                    exercise_grades(page)
                                    observe(page, 'grades-expanded', args.output, report,
                                            width, theme, scheme, contrast=contrast)
                                capture_modal(page, label, args.output, report,
                                              width, theme, scheme, contrast=contrast)
                            except Exception as error:
                                report['failures'].append({'page': route, 'theme': theme, 'width': width,
                                                           'error': str(error)})
                        print(f'{theme}/{scheme} account={account} width={width}', flush=True)
                    logout = context.request.post(base + '/api/logout', headers={'X-Requested-With': 'ATLAS'})
                    assert logout.ok
                    context.close()
            if not args.public_url:
                verify_touch_scroll(browser, base)
                report['mobile_touch_scroll'] = True
            browser.close()
    except Exception as error:
        report['failures'].append({'run': str(error)})
    report['status'] = 'FAIL' if report['failures'] else 'PASS'
    (args.output / 'geometry.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"{report['status']}: {len(report['screens'])} captures, {len(report['failures'])} findings.")
    return int(report['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
