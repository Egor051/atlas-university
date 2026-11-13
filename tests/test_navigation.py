"""Navigation, shared branding and refresh on the real local browser."""
import os
import re

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server, wait_for_held_response

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in isolated real Chromium')


@pytest.mark.parametrize('width', [320, 360, 390, 768, 1024, 1280, 1440, 1920])
def test_hierarchy_links_back_forward_reload_and_role_boundaries(frontend_page, width):
    page, base = frontend_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(base + '/app/records/grades')
    page.get_by_role('button',name='Попробовать демо',exact=True).click()
    page.locator('[data-demo="0"]').click()
    expect(page).to_have_url(base + '/app/grades')
    expect(page.locator('#page-title')).to_have_text('Успеваемость')
    crumbs = page.get_by_role('navigation', name='Путь к разделу')
    expect(crumbs.locator('[aria-current=page]')).to_have_text('Успеваемость')
    expect(crumbs.get_by_role('link', name='Кабинет')).to_have_attribute('href', '/app/home')
    siblings = page.get_by_role('navigation', name='Занятия и оценки — разделы')
    assert siblings.evaluate("node => node.nextElementSibling.matches('.concept-bar')")
    expect(page.locator('.concept-bar')).to_have_text('Конкурсный концепт · все данные вымышлены · неофициальный сервис')
    siblings.get_by_role('link', name='Посещаемость').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#page-title')).to_have_text('Посещаемость')
    page.go_back()
    expect(page.locator('#page-title')).to_have_text('Успеваемость')
    page.go_forward()
    expect(page.locator('#page-title')).to_have_text('Посещаемость')
    page.reload()
    expect(page.locator('#page-title')).to_have_text('Посещаемость')
    assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
    expect(page.locator('.nav-stack [data-route=staff]')).to_have_count(0)
    page.goto(base + '/app/office/staff')
    expect(page).to_have_url(base + '/app/home')
    assert page.request.get(base + '/api/staff/requests').status == 403
    page.goto(base + '/app/records')
    expect(page).to_have_url(base + '/app/schedule')
    page.goto(base + '/app/campus')
    expect(page).to_have_url(base + '/app/home')


def test_desktop_sidebar_persists_and_accordion_tracks_route(frontend_page):
    page, base = frontend_page
    page.goto(base + '/app/grades')
    page.get_by_role('button', name='Попробовать демо', exact=True).click()
    page.locator('[data-demo="0"]').click()
    page.wait_for_url('**/app/grades')
    nav = page.get_by_role('navigation', name='Основная навигация')
    records = nav.get_by_role('button', name='Занятия и оценки')
    planning = nav.get_by_role('button', name='Планирование')
    expect(records).to_have_attribute('aria-expanded', 'true')
    planning.click()
    expect(records).to_have_attribute('aria-expanded', 'false')
    expect(planning).to_have_attribute('aria-expanded', 'true')
    expect(nav.locator('[aria-expanded=true]')).to_have_count(1)
    planning.press('Enter')
    expect(nav.locator('[aria-expanded=true]')).to_have_count(0)
    expect(nav.get_by_text('Обзор раздела', exact=True)).to_have_count(0)
    expect(nav.get_by_text('Все разделы', exact=True)).to_have_count(0)
    sidebar = page.locator('.sidebar')
    before = sidebar.bounding_box()['width']
    page.get_by_role('button', name='Свернуть боковое меню').click()
    expect(sidebar).to_have_css('width', '68px')
    assert before > sidebar.bounding_box()['width']
    page.reload()
    expect(sidebar).to_have_css('width', '68px')
    expect(records).to_have_attribute('title', 'Занятия и оценки')
    expect(nav.get_by_role('link', name='Успеваемость')).to_have_attribute('aria-current', 'page')
    page.get_by_role('button', name='Развернуть боковое меню').press('Enter')
    expect(sidebar).to_have_css('width', '240px')


def test_mobile_drawer_and_demo_dialog_restore_focus(frontend_page):
    page, base = frontend_page
    page.set_viewport_size({'width': 320, 'height': 620})
    page.goto(base)
    trigger = page.get_by_role('button', name='Попробовать демо', exact=True)
    expect(page.locator('[data-demo="0"]')).to_be_hidden()
    trigger.click()
    dialog = page.get_by_role('dialog', name='Попробовать демо')
    expect(dialog).to_be_visible()
    expect(dialog.locator('[data-demo]')).to_have_count(11)
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    expect(trigger).to_be_focused()
    trigger.press('Enter')
    dialog.locator('[data-demo="0"]').click()
    menu = page.get_by_role('button', name='Открыть меню')
    menu.click()
    drawer = page.get_by_role('dialog', name='Личный кабинет')
    close = drawer.get_by_role('button', name='Закрыть меню')
    expect(close).to_be_focused()
    page.keyboard.press('Escape')
    expect(menu).to_be_focused()
    expect(menu).to_have_attribute('aria-expanded', 'false')
    menu.click()
    drawer.get_by_role('button', name='Заявки и документы').click()
    drawer.get_by_role('link', name='Справки').click()
    expect(page).to_have_url(base + '/app/certificates')
    expect(menu).to_have_attribute('aria-expanded', 'false')
    assert page.evaluate('document.documentElement.scrollWidth === innerWidth')


@pytest.mark.parametrize('keyboard_mode', ['layout-resize', 'visual-only'])
def test_mobile_login_keeps_password_and_submit_inside_keyboard_view(frontend_browser, frontend_server, keyboard_mode):
    base = frontend_server
    page = frontend_browser.new_page(viewport={'width': 390, 'height': 820}, has_touch=True, is_mobile=True)
    try:
        assert_mobile_login_with_keyboard(page, base, keyboard_mode)
    finally:
        page.context.close()


def assert_mobile_login_with_keyboard(page, base, keyboard_mode):
    page.goto(base)
    login = page.locator('#login-name')
    password = page.locator('#login-password')
    submit = page.get_by_role('button', name='Войти в кабинет')
    expect(login).to_have_attribute('autocomplete', 'username')
    expect(password).to_have_attribute('autocomplete', 'current-password')
    login.fill('alina.demo')
    password.fill('AtlasDemo!2026-A')

    # Browsers either shrink both viewports or leave the layout viewport
    # unchanged and report the keyboard through VisualViewport.
    height = 235
    if keyboard_mode == 'layout-resize':
        page.set_viewport_size({'width': 390, 'height': height})
    else:
        page.evaluate("""height => {
            const viewport = window.visualViewport;
            Object.defineProperty(viewport, 'height', {configurable: true, get: () => height});
            viewport.dispatchEvent(new Event('resize'));
        }""", height)

    expect(page.locator('html')).to_have_attribute('data-atlas-keyboard', '')
    expect(password).to_be_focused()
    expect(password).to_have_value('AtlasDemo!2026-A')
    boxes = page.locator('#login-password, .login-submit')
    for element in boxes.all():
        position = element.evaluate("""node => {
            const {top, bottom} = node.getBoundingClientRect();
            const {height, offsetTop} = visualViewport;
            return {top, bottom, height, offsetTop};
        }""")
        assert position['offsetTop'] <= position['top'] and position['bottom'] <= position['height'] + position['offsetTop'], position
    box = submit.bounding_box()
    # Coordinate click uses the current view rather than Playwright scrolling
    # the submit button into view before the click.
    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    expect(page).to_have_url(base + '/app/home')


def test_schedule_context_survives_bookmark_and_brand_uses_versioned_icon(frontend_page):
    page, base = frontend_page
    page.goto(base)
    icon = page.locator('link[rel=icon]').get_attribute('href')
    build = page.request.get(base + '/api/health').json()['build']
    assert icon == f'/static/favicon.svg?v={build}'
    assert page.request.get(base + icon).headers['content-type'] == 'image/svg+xml'
    assert page.request.get(base + '/static/favicon.svg').headers['cache-control'] == 'no-cache'
    expect(page.locator('.logo-mark').first).to_have_attribute('src', icon)
    page.get_by_role('button',name='Попробовать демо',exact=True).click()
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
    page.get_by_role('button',name='Попробовать демо',exact=True).click()
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
