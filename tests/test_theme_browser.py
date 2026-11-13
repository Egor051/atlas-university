"""The appearance preference applies before login and throughout the cabinet."""
import os

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server
from test_university_browser import enter


pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in isolated real Chromium')
LIGHT = 'rgb(245, 246, 250)'
DARK = 'rgb(21, 20, 32)'


def expect_theme(page, mode, background):
    root = page.locator('html')
    expect(root).to_have_attribute('data-theme', mode)
    expect(root).to_have_css('background-color', background)


def test_theme_settings_live_system_keyboard_and_sign_in(frontend_page):
    page, base = frontend_page
    page.set_viewport_size({'width': 360, 'height': 800})
    page.emulate_media(color_scheme='dark')
    page.goto(base)
    expect(page.locator('#login-form')).to_be_visible()
    expect_theme(page, 'system', DARK)
    enter(page, base, 0, '/app/settings')
    choices = page.get_by_role('group', name='Тема оформления')
    system = choices.get_by_role('radio', name='Системная')
    light = choices.get_by_role('radio', name='Светлая')
    dark = choices.get_by_role('radio', name='Тёмная')
    expect(system).to_be_checked()
    page.get_by_role('checkbox', name='Компактный вид').check()
    system.press('ArrowRight')
    expect(light).to_be_focused()
    expect(light).to_be_checked()
    expect_theme(page, 'light', LIGHT)
    expect(page.get_by_role('checkbox', name='Компактный вид')).to_be_checked()
    assert page.url == base + '/app/settings'
    page.reload()
    expect(light).to_be_checked()
    expect_theme(page, 'light', LIGHT)
    page.emulate_media(color_scheme='light')
    dark.check()
    expect_theme(page, 'dark', DARK)
    page.locator('.avatar-button[data-route="profile"]').click()
    page.locator('.danger-button[data-action="logout"]').click()
    expect(page.locator('#login-form')).to_be_visible()
    expect_theme(page, 'dark', DARK)
    enter(page, base, 2, '/app/settings')
    expect(dark).to_be_checked()
    expect_theme(page, 'dark', DARK)
    system.check()
    expect_theme(page, 'system', LIGHT)
    page.emulate_media(color_scheme='dark')
    expect_theme(page, 'system', DARK)
    page.emulate_media(color_scheme='light')
    expect_theme(page, 'system', LIGHT)
    assert page.url == base + '/app/settings'


def test_theme_precedes_boot_and_recovers_invalid_storage(frontend_page):
    page, base = frontend_page
    page.emulate_media(color_scheme='light')
    page.goto(base)
    expect(page.locator('#login-form')).to_be_visible()
    page.evaluate("localStorage.setItem('atlas.theme', 'dark')")
    boot = []

    def hold_boot(route):
        expect(page.locator('.boot')).to_be_visible()
        expect_theme(page, 'dark', DARK)
        boot.append(page.locator('meta[name=color-scheme]').get_attribute('content'))
        route.continue_()

    page.route('**/api/config', hold_boot, times=1)
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#login-form')).to_be_visible()
    assert boot == ['dark']
    expect_theme(page, 'dark', DARK)
    page.evaluate("localStorage.setItem('atlas.theme', 'invalid')")
    page.reload()
    expect_theme(page, 'system', LIGHT)


def test_certificate_preview_uses_current_theme_and_prints_on_light_paper(frontend_page):
    page, base = frontend_page
    enter(page, base, 0, '/app/certificates')
    page.evaluate("localStorage.setItem('atlas.theme', 'dark')")
    page.reload()
    expect_theme(page, 'dark', DARK)
    page.locator('.request-is-ready').first.click()
    preview = page.locator('[data-document-preview]')
    with page.expect_popup() as opened:
        preview.click()
    document = opened.value
    expect(document.locator('.warning')).to_contain_text('ВСЕ ДАННЫЕ ВЫМЫШЛЕНЫ')
    assert 'theme=dark' in document.url
    expect(document.locator('body')).to_have_css('background-color', DARK)
    document.emulate_media(media='print')
    expect(document.locator('body')).to_have_css('background-color', 'rgb(255, 255, 255)')
    document.close()
