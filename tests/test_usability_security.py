"""Real-browser security regressions for the shared personal search dialog.

The fixture runs a real local HTTP API with a temporary SQLite database.
Only genuine successful search responses are delayed; none are fabricated.
"""
from __future__ import annotations

import os
import uuid

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import (frontend_server, frontend_browser, frontend_page,
                                     enter_demo, leave_demo, finish_browser_tasks,
                                     wait_for_held_response)

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in real browser test')
HEADERS = {'X-Requested-With': 'ATLAS'}


def create_request(page, address, comment):
    response = page.request.post(address + '/api/requests', headers=HEADERS,
                                 data={'type': 'study', 'comment': comment})
    assert response.status == 201, response.text()
    return response.json()


def open_search(page):
    # Use the visible keyboard entry point, independent of sidebar grouping.
    page.keyboard.press('Control+k')
    expect(page.locator('#search-input')).to_be_focused()


def hold_request_search(page, marker, request_id):
    held = []

    def delay_actual_search(route):
        if marker not in route.request.url or held:
            route.continue_()
            return
        actual = route.fetch()
        assert actual.status == 200
        assert any(row['id'] == request_id and row['target'] == 'certificates'
                   for row in actual.json()['items'])
        held.append((route, actual))

    page.route('**/api/campus/search?*', delay_actual_search)
    return held


def test_delayed_personal_search_never_enters_another_students_dialog(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    marker = 'PrivateSearch' + uuid.uuid4().hex
    comment = marker + ' — вымышленный комментарий Алины'
    request = create_request(page, address, comment)
    held = hold_request_search(page, marker, request['id'])
    open_search(page)
    page.locator('#search-input').fill(marker)
    wait_for_held_response(page, held)
    page.locator('.modal .close-btn').click()
    leave_demo(page)
    enter_demo(page, 1, 'Марк')
    # The second account performs a genuine search for the same private marker.
    open_search(page)
    page.locator('#search-input').fill(marker)
    expect(page.locator('#search-personal')).to_contain_text('В ваших данных совпадений нет.')
    assert page.request.get(address + '/api/campus/search', params={'q': marker}).json()['items'] == []
    route, actual = held[0]
    route.fulfill(response=actual)
    finish_browser_tasks(page)
    expect(page.locator('#search-personal .search-result')).to_have_count(0)
    expect(page.locator('#search-personal')).not_to_contain_text(comment)
    expect(page.locator('#page-title')).to_contain_text('Марк')
    assert page.request.get(address + '/api/me').json()['full_name'] == 'Марк Северин'


@pytest.mark.parametrize('reopen', [False, True], ids=['changed-query', 'reopened-dialog'])
def test_abandoned_search_cannot_replace_current_query_results(frontend_page, reopen):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    abandoned = 'AbandonedSearch' + uuid.uuid4().hex
    current = 'CurrentSearch' + uuid.uuid4().hex
    old_request = create_request(page, address, abandoned)
    create_request(page, address, current)
    held = hold_request_search(page, abandoned, old_request['id'])
    open_search(page)
    page.locator('#search-input').fill(abandoned)
    wait_for_held_response(page, held)
    if reopen:
        page.locator('.modal .close-btn').click()
        open_search(page)
    page.locator('#search-input').fill(current)
    expect(page.locator('#search-personal .search-result small')).to_contain_text(current)
    route, actual = held[0]
    route.fulfill(response=actual)
    finish_browser_tasks(page)
    expect(page.locator('#search-input')).to_have_value(current)
    expect(page.locator('#search-personal .search-result small')).to_contain_text(current)
    expect(page.locator('#search-personal')).not_to_contain_text(abandoned)


def test_request_markup_in_personal_search_remains_literal_text(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    marker = 'MarkupSearch' + uuid.uuid4().hex
    comment = marker + ' <img id="search-injected-body" src=x onerror="window.__searchExecuted=1"> & "quoted"'
    request = create_request(page, address, comment)
    open_search(page)
    page.locator('#search-input').fill(marker)
    result = page.locator(f'[data-search-target="certificates"][data-search-id="{request["id"]}"]')
    expect(result.locator('small')).to_have_text('Справка · ' + comment)
    expect(page.locator('#search-injected-body')).to_have_count(0)
    result.click()
    detail = page.get_by_role('dialog')
    expect(detail.locator('.detail-block .user-text', has_text=marker)).to_have_text(comment)
    expect(page.locator('#search-injected-body')).to_have_count(0)
    assert page.evaluate('() => window.__searchExecuted === undefined') is True


def hold_first_list(page, pattern):
    held = []

    def delay_actual_list(route):
        if held:
            route.continue_()
            return
        actual = route.fetch()
        assert actual.status == 200
        held.append((route, actual))

    page.route(pattern, delay_actual_list)
    return held


def test_selected_assignment_result_cannot_replace_new_dialog_after_list_load(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    work = page.request.get(address + '/api/learning/assignments').json()['items'][0]
    held = hold_first_list(page, '**/api/learning/assignments?*')
    open_search(page)
    page.locator('#search-input').fill(work['title'])
    result = page.locator(f'#search-personal [data-search-target="assignments"][data-search-id="{work["id"]}"]')
    expect(result).to_be_visible()
    result.click()
    wait_for_held_response(page, held)
    # Selecting the result has closed the first search and begun loading assignments.
    # A new search started by the user must keep ownership of the modal.
    open_search(page)
    route, actual = held[0]
    route.fulfill(response=actual)
    page.wait_for_load_state('networkidle')
    finish_browser_tasks(page)
    expect(page.locator('#search-input')).to_be_visible()
    expect(page.get_by_role('dialog', name='Сдать работу')).to_have_count(0)


def test_request_notification_cannot_replace_new_dialog_after_list_load(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    request = page.request.post(address + '/api/requests', headers=HEADERS,
                                data={'type': 'study', 'comment': 'Fictional notification race ' + uuid.uuid4().hex})
    assert request.status == 201, request.text()
    request_id = request.json()['id']
    notifications = page.request.get(address + '/api/notifications').json()
    notice = next(row for row in notifications if row['request_id'] == request_id)
    page.goto(address + '/app/notifications')
    expect(page.locator('#page-title')).to_have_text('Уведомления')
    held = hold_first_list(page, '**/api/requests?*')
    page.locator(f'[data-action="open-notice"][data-id="{notice["id"]}"]').click()
    wait_for_held_response(page, held)
    open_search(page)
    route, actual = held[0]
    route.fulfill(response=actual)
    page.wait_for_load_state('networkidle')
    finish_browser_tasks(page)
    expect(page.locator('#search-input')).to_be_visible()
    expect(page.locator('.detail-summary')).to_have_count(0)
