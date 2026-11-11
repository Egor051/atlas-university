"""Navigation, shared branding and refresh on the real local browser."""
import os
import re

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server, wait_for_held_response

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in isolated real Chromium')


@pytest.mark.parametrize('width', [360, 390, 768, 1440])
def test_hierarchy_links_back_forward_reload_and_role_boundaries(frontend_page, width):
    page, base = frontend_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(base + '/app/records/grades')
    page.locator('[data-demo="0"]').click()
    expect(page).to_have_url(base + '/app/grades')
    expect(page.locator('#page-title')).to_have_text('Успеваемость')
    crumbs = page.get_by_role('navigation', name='Путь к разделу')
    expect(crumbs.locator('[aria-current=page]')).to_have_text('Успеваемость')
    expect(crumbs.get_by_role('link', name='Кабинет')).to_have_attribute('href', '/app/home')
    siblings = page.get_by_role('navigation', name='Учебный учёт — разделы')
    siblings.get_by_role('link', name='Посещаемость').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#page-title')).to_have_text('Посещаемость')
    crumbs.get_by_role('link', name='Учебный учёт').click()
    expect(page.locator('#page-title')).to_have_text('Учебный учёт')
    expect(page.locator('#page-content a[data-route=quizzes]')).to_have_count(0)
    page.go_back()
    expect(page.locator('#page-title')).to_have_text('Посещаемость')
    page.go_back()
    expect(page.locator('#page-title')).to_have_text('Успеваемость')
    page.go_forward()
    page.reload()
    expect(page.locator('#page-title')).to_have_text('Посещаемость')
    assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
    expect(page.locator('.nav-stack [data-route=staff]')).to_have_count(0)
    page.goto(base + '/app/office/staff')
    expect(page).to_have_url(base + '/app/home')
    assert page.request.get(base + '/api/staff/requests').status == 403


def test_schedule_context_survives_bookmark_and_brand_uses_versioned_icon(frontend_page):
    page, base = frontend_page
    page.goto(base)
    icon = page.locator('link[rel=icon]').get_attribute('href')
    build = page.request.get(base + '/api/health').json()['build']
    assert icon == f'/static/favicon.svg?v={build}'
    assert page.request.get(base + icon).headers['content-type'] == 'image/svg+xml'
    assert page.request.get(base + '/static/favicon.svg').headers['cache-control'] == 'no-cache'
    expect(page.locator('.logo-mark').first).to_have_attribute('src', icon)
    page.locator('[data-demo="0"]').click()
    action = page.locator('.next-class [data-route=schedule]')
    day = action.get_attribute('data-date')
    action.click()
    expect(page).to_have_url(re.compile(r'/app/schedule\?.*date=' + day))
    page.reload()
    expect(page.locator('#page-title')).to_have_text('Расписание')
    expect(page.locator(f'[data-day="{day}"]')).to_have_attribute('aria-pressed', 'true')


def test_single_keyboard_refresh_disables_repeat_until_response(frontend_page):
    page, base = frontend_page
    page.goto(base + '/app/staff')
    page.locator('[data-demo="2"]').click()
    expect(page.locator('#page-title')).to_have_text('Учебный офис')
    button = page.get_by_role('button', name='Обновить данные раздела')
    expect(button).to_have_count(1)
    expect(page.get_by_role('button', name='Обновить очередь')).to_have_count(0)
    held = []

    def delay(route):
        held.append((route, route.fetch()))

    page.route(re.compile(r'.*/api/staff/requests\?'), delay)
    button.focus()
    page.keyboard.press('Enter')
    wait_for_held_response(page, held)
    expect(button).to_be_disabled()
    expect(button).to_have_attribute('aria-busy', 'true')
    button.evaluate('node => node.click()')
    assert len(held) == 1
    route, response = held[0]
    route.fulfill(response=response)
    expect(button).to_be_enabled()
    expect(button).to_be_focused()
