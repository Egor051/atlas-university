"""Check local navigation and capture actual browser screenshots on an isolated DB."""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

from improvement_crossbrowser import STAFF, STUDENT
from improvement_runtime import ROOT, browser_login, browser_ready, geometry, isolated_server, report_start, save_report

WIDTHS = [(360, 800), (390, 844), (768, 1024), (1440, 1000)]
SECTIONS = ['records', 'learning', 'planning', 'administration', 'communications', 'university', 'campus-life', 'account']
NEW_STUDENT = ['materials', 'materials/1', 'direct', 'university/digital', 'university/digital/systems',
               'university/digital/systems/mikhail-orlov']
SHOTS = {'grades', 'campus', 'staff', 'learning', 'materials', 'materials/1', 'university/digital/systems/mikhail-orlov',
         'direct', 'teacher'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['before', 'navigation', 'complete'])
    parser.add_argument('--engines', default='chromium')
    parser.add_argument('--screenshots', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    report = report_start('Local real browser engines, disposable fictional SQLite, viewport emulation')
    report.update(phase=args.phase, geometry=[], screenshots=[], engines=[], accessibility=[])
    axe = (ROOT / 'node_modules' / 'axe-core' / 'axe.min.js').read_text(encoding='utf-8')
    routes = [STUDENT[:], STAFF[:]]
    if args.phase != 'before':
        routes[0] += SECTIONS
        routes[1] += ['office', 'account']
    if args.phase == 'complete':
        routes[0] += NEW_STUDENT
        routes[1] += ['direct', 'materials', 'materials-admin', 'communications', 'university']
        routes.append(['teacher', 'direct', 'materials', 'materials-admin', 'university', 'learning', 'communications', 'account', 'profile', 'settings'])
    try:
        with isolated_server() as server, sync_playwright() as automation:
            base = server['base']
            for engine in args.engines.split(','):
                browser = getattr(automation, engine).launch()
                report['engines'].append({'name': engine, 'version': browser.version})
                for index, pages in enumerate(routes):
                    actor = ('student', 'staff', 'teacher')[index]
                    context = browser.new_context(locale='ru-RU', reduced_motion='reduce')
                    context.add_init_script(axe)
                    page = context.new_page()
                    page.on('pageerror', lambda error: report['failures'].append(str(error)))
                    browser_login(page, base, (0, 2, 3)[index])
                    for width, height in WIDTHS:
                        page.set_viewport_size({'width': width, 'height': height})
                        for route in pages:
                            url = base + '/app/' + route
                            page.goto(url, wait_until='domcontentloaded')
                            browser_ready(page)
                            assert page.url == url, (actor, url, page.url)
                            report['geometry'].append(dict(engine=engine, actor=actor, route=route, **geometry(page)))
                            if engine == 'chromium' and route in SHOTS and (index == 0 or route in {'staff', 'teacher'}):
                                name = f'{args.phase}-{actor}-{width}-{route.replace("/", "-")}.png'
                                page.screenshot(path=str(args.screenshots / name), full_page=True, animations='disabled')
                                report['screenshots'].append(name)
                                if args.phase != 'before':
                                    violations = page.evaluate('''async () => (await axe.run(document, {
                                        runOnly: {type:'tag', values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}
                                      })).violations.map(v => ({id:v.id, targets:v.nodes.map(n=>n.target)}))''')
                                    report['accessibility'].append(dict(width=width, route=route, violations=violations))
                                    if violations:
                                        report['failures'].append(dict(width=width, route=route, violations=violations))
                        print(f'{engine} {actor} {width}px: {len(pages)} routes', flush=True)
                    context.close()
                browser.close()
    except Exception as error:
        report['failures'].append(str(error))
    report = save_report(args.report, report)
    print(f"{report['status']}: {len(report['geometry'])} layouts, {len(report['failures'])} failures", flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
