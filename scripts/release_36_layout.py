"""Check the redesigned student pages with actual browser layout and Chromium tab zoom."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from improvement_runtime import browser_login, browser_ready, isolated_server


WIDTHS = (320, 360, 390, 768, 1024, 1280, 1440, 1920)
ROUTES = ('home', 'announcements', 'schedule', 'requests', 'certificates', 'notifications', 'direct', 'settings')
WARNING = 'Конкурсный концепт · все данные вымышлены · неофициальный сервис'


def check_width(page, case, rows):
    result = page.evaluate('''() => ({width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth, dpr: devicePixelRatio,
        warnings: [...document.querySelectorAll('.concept-bar')].filter(el=>el.getClientRects().length)
            .map(el=>el.textContent.trim()), title:document.querySelector('#page-title')?.textContent})''')
    rows.append({**case, **result})
    assert result['scrollWidth'] <= result['width'] + 1, {**case, **result}
    assert result['warnings'] == [WARNING], {**case, **result}


def visit(page, base, route):
    page.goto(f'{base}/app/{route}', wait_until='networkidle')
    browser_ready(page)


def check_viewports(browser, engine, base, evidence, screenshots):
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, locale='ru-RU', color_scheme='light')
    page = context.new_page()
    page.on('pageerror', lambda error: evidence['page_errors'].append(str(error)))
    browser_login(page, base)
    for width in WIDTHS:
        page.set_viewport_size({'width': width, 'height': 900})
        for route in ROUTES:
            visit(page, base, route)
            check_width(page, {'engine': engine, 'viewport': width, 'route': route, 'view': 'normal'}, evidence['layout'])
    page.emulate_media(color_scheme='dark', reduced_motion='reduce')
    visit(page, base, 'settings')
    page.get_by_role('checkbox', name='Компактный вид').check()
    with page.expect_response(lambda response: response.request.method == 'POST' and '/api/services/preferences' in response.url) as saved:
        page.get_by_role('button', name='Сохранить настройки').click()
    assert saved.value.ok
    expect(page.locator('#toast')).to_contain_text('Сохранено')
    for width in (320, 390, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        for route in ROUTES:
            visit(page, base, route)
            check_width(page, {'engine': engine, 'viewport': width, 'route': route, 'view': 'compact-dark'}, evidence['layout'])
            if engine == 'chromium' and route in {'certificates', 'notifications', 'direct'} and width in {390, 1440}:
                page.screenshot(path=screenshots / f'{route}-{width}-compact-dark.png', animations='disabled')
    visit(page, base, 'settings')
    setting = page.get_by_role('checkbox', name='Компактный вид')
    expect(setting).to_be_checked()
    setting.uncheck()
    with page.expect_response(lambda response: response.request.method == 'POST' and '/api/services/preferences' in response.url) as saved:
        page.get_by_role('button', name='Сохранить настройки').click()
    assert saved.value.ok
    expect(page.locator('#toast')).to_contain_text('Сохранено')
    context.close()


def check_zoom(playwright, base, evidence):
    with TemporaryDirectory(prefix='atlas-tab-zoom-') as temporary:
        root = Path(temporary)
        extension = root / 'extension'
        extension.mkdir()
        (extension / 'manifest.json').write_text(json.dumps({
            'manifest_version': 3, 'name': 'ATLAS browser zoom check', 'version': '1.0',
            'background': {'service_worker': 'worker.js'}, 'permissions': ['tabs'],
        }), encoding='utf-8')
        (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(() => {});\n', encoding='utf-8')
        context = playwright.chromium.launch_persistent_context(root / 'profile', channel='chromium',
            headless=True, no_viewport=True, args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}',
                                                 '--window-size=1440,950'])
        try:
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            page.on('pageerror', lambda error: evidence['page_errors'].append(str(error)))
            browser_login(page, base)
            cdp = context.new_cdp_session(page)
            window_id = cdp.send('Browser.getWindowForTarget')['windowId']
            for size in (1440, 680):
                cdp.send('Browser.setWindowBounds', {'windowId': window_id, 'bounds': {'width': size, 'height': 950}})
                base_dpr = None
                for factor in (1, 1.25, 1.5, 2):
                    for route in ROUTES:
                        visit(page, base, route)
                        actual = worker.evaluate('''async ({origin, factor}) => {
                            const [tab] = await chrome.tabs.query({url: origin + '/*'});
                            await chrome.tabs.setZoomSettings(tab.id, {mode:'automatic', scope:'per-origin'});
                            await chrome.tabs.setZoom(tab.id, factor);
                            return chrome.tabs.getZoom(tab.id);
                        }''', {'origin': base, 'factor': factor})
                        assert abs(actual - factor) < 0.01, actual
                        if base_dpr is None:
                            base_dpr = page.evaluate('devicePixelRatio')
                        page.wait_for_function('expected => Math.abs(devicePixelRatio - expected) < 0.04',
                                               arg=base_dpr * factor, timeout=5000)
                        check_width(page, {'engine': 'chromium', 'window': size, 'zoom': actual, 'route': route}, evidence['zoom'])
        finally:
            context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--screenshots', required=True, type=Path)
    parser.add_argument('--engines', default='chromium,firefox,webkit')
    parser.add_argument('--only-zoom', action='store_true')
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.screenshots.mkdir(parents=True, exist_ok=True)
    evidence = {'layout': [], 'zoom': [], 'page_errors': [], 'engines': {}, 'status': 'FAIL'}
    try:
        with isolated_server() as server, sync_playwright() as playwright:
            base = server['base']
            if not args.only_zoom:
                for engine in args.engines.split(','):
                    browser = getattr(playwright, engine).launch()
                    try:
                        evidence['engines'][engine] = browser.version
                        check_viewports(browser, engine, base, evidence, args.screenshots)
                    finally:
                        browser.close()
            check_zoom(playwright, base, evidence)
        assert not evidence['page_errors'], evidence['page_errors']
        evidence['status'] = 'PASS'
    finally:
        args.report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({name: len(evidence[name]) for name in ('layout', 'zoom', 'page_errors')}))


if __name__ == '__main__':
    main()
