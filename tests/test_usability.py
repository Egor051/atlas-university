"""Real user journeys for the compact interface, on an isolated fictional API."""
from __future__ import annotations

import os
import uuid

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server, enter_demo

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in real Chromium checks')


def visit(page, base, section):
    page.goto(base + '/app/' + section, wait_until='networkidle')
    expect(page.locator('#page-content')).not_to_have_attribute('aria-busy', 'true')
    expect(page.locator('.error-state')).to_have_count(0)


def enter(page, base):
    page.goto(base)
    enter_demo(page, 0, 'Алина')


@pytest.mark.parametrize('width', [360, 390])
def test_mobile_core_is_one_tap_and_other_sections_are_grouped(frontend_page, width):
    page, base = frontend_page
    page.set_viewport_size({'width': width, 'height': 800})
    enter(page, base)
    navigation = page.locator('.bottom-nav')
    for label in ['Главная', 'Расписание', 'Оценки', 'Заявки']:
        expect(navigation.get_by_role('button', name=label, exact=True)).to_be_visible()
    navigation.get_by_role('button', name='Оценки', exact=True).click()
    expect(page.locator('#page-title')).to_have_text('Успеваемость и посещаемость')
    menu = navigation.get_by_role('button', name='Открыть меню', exact=True)
    menu.click()
    expect(page.locator('.nav-group.is-open')).to_have_count(1)
    page.locator('[data-nav-group="learning"] .nav-group-toggle').click()
    page.locator('.nav-stack [data-route="notes"]').click()
    expect(page.locator('#page-title')).to_have_text('Конспекты')
    expect(menu).to_have_attribute('aria-expanded', 'false')
    page.keyboard.press('Control+k')
    page.locator('#search-input').fill('оценки')
    expect(page.locator('#search-results [data-route="grades"]')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_certificate_history_precedes_searchable_certificate_catalog(frontend_page):
    page, base = frontend_page
    page.set_viewport_size({'width': 360, 'height': 800})
    enter(page, base)
    visit(page, base, 'certificates')
    expect(page.locator('.request-row').first).to_be_visible()
    expect(page.locator('.certificate-service')).to_have_count(0)
    assert page.locator('.request-row').first.bounding_box()['y'] < 650
    page.locator('[data-request-view="services"]').click()
    page.locator('#service-search').fill('стипендии')
    service = page.locator('.certificate-service [data-type="scholarship"]')
    expect(service).to_be_visible()
    service.click()
    expect(page.locator('#doc-type')).to_have_value('scholarship')
    expect(page.locator('#selected-service')).to_contain_text('Учебный офис')


def test_dirty_form_survives_escape_and_network_failure_then_saves(frontend_page):
    page, base = frontend_page
    enter(page, base)
    visit(page, base, 'notes')
    page.locator('.page-actions [data-c-action="note-new"]').click()
    form = page.locator('form[data-c-form="note"]')
    marker = 'UX note ' + uuid.uuid4().hex
    form.locator('[name="title"]').fill(marker)
    form.locator('[name="body"]').fill('Содержимое конспекта сохраняется после ошибки сети.')
    page.keyboard.press('Escape')
    expect(page.locator('.unsaved-warning')).to_be_visible()
    page.locator('[data-action="continue-edit"]').click()
    expect(form.locator('[name="title"]')).to_have_value(marker)
    page.route('**/api/learning/notes', lambda route: route.abort('failed')
               if route.request.method == 'POST' else route.continue_())
    form.locator('[type="submit"]').click()
    expect(form.locator('[data-c-error]')).to_be_visible()
    expect(form.locator('[name="body"]')).to_have_value('Содержимое конспекта сохраняется после ошибки сети.')
    page.unroute('**/api/learning/notes')
    with page.expect_response(lambda r: r.url.endswith('/api/learning/notes') and r.request.method == 'POST') as response:
        form.locator('[type="submit"]').click()
    assert response.value.status == 201
    expect(page.locator('.modal')).to_have_count(0)
    expect(page.locator('.compact-row h2', has_text=marker)).to_be_visible()


def test_search_opens_request_and_marks_exact_grade_and_deadline(frontend_page):
    page, base = frontend_page
    enter(page, base)
    marker = 'ExactResult' + uuid.uuid4().hex
    result = page.request.post(base + '/api/requests', headers={'X-Requested-With': 'ATLAS'},
                               data={'type': 'study', 'comment': marker})
    assert result.status == 201
    request_id = result.json()['id']
    visit(page, base, 'certificates')
    page.locator('[data-request-view="services"][aria-pressed]').click()
    page.keyboard.press('Control+k')
    page.locator('#search-input').fill(marker)
    page.locator(f'[data-search-target="certificates"][data-search-id="{request_id}"]').click()
    expect(page.get_by_role('dialog')).to_have_attribute('aria-label', f'Заявка № {request_id}')
    expect(page.locator('.detail-block .user-text', has_text=marker)).to_be_visible()
    page.locator('.close-btn').click()
    for endpoint, target in [('grades', 'grades'), ('deadlines', 'plan')]:
        data = page.request.get(base + '/api/' + endpoint).json()
        row = (data['items'] if isinstance(data, dict) else data)[0]
        query = row.get('subject') if target == 'grades' else row['title']
        page.keyboard.press('Control+k')
        page.locator('#search-input').fill(query)
        page.locator(f'[data-search-target="{target}"][data-search-id="{row["id"]}"]').click()
        expect(page.locator('.search-match')).to_be_focused()
        expect(page.locator('.search-match')).to_contain_text(query)


def test_course_disclosure_keyboard_and_live_module_status(frontend_page):
    page, base = frontend_page
    enter(page, base)
    visit(page, base, 'courses')
    page.locator('[data-c-action="course"]').first.click()
    summaries = page.locator('.campus-modules details summary')
    expect(page.locator('.campus-modules details[open]')).to_have_count(0)
    summaries.last.focus()
    page.keyboard.press('Tab')
    expect(page.locator('.close-btn')).to_be_focused()
    summaries.first.click()
    checkbox = page.locator('[data-c-module]').first
    desired = not checkbox.is_checked()
    with page.expect_response(lambda r: '/modules/' in r.url and r.request.method == 'POST') as response:
        checkbox.set_checked(desired)
    assert response.value.status == 200
    expect(summaries.first).to_contain_text('Изучено' if desired else 'К изучению')


def test_schedule_day_count_and_money_readability(frontend_page):
    page, base = frontend_page
    page.set_viewport_size({'width': 360, 'height': 800})
    enter(page, base)
    visit(page, base, 'schedule')
    expect(page.locator('[data-view="day"]')).to_have_attribute('aria-pressed', 'true')
    page.locator('.day-pick').last.click()
    expect(page.locator('.schedule-info')).to_contain_text('0 занятий')
    expect(page.locator('.day-view')).to_contain_text('В этот день занятий нет')
    visit(page, base, 'finance')
    for amount in page.locator('.finance-summary b').all():
        assert amount.bounding_box()['height'] < 35, 'Currency must remain on one line'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
