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


def create_note(page, address, title, body='Fictional note for isolated search regression.'):
    response = page.request.post(address + '/api/learning/notes', headers=HEADERS,
                                 data={'title': title, 'subject': 'Security exercise', 'body': body})
    assert response.status == 201, response.text()
    return response.json()


def open_search(page):
    # Use the visible keyboard entry point, independent of sidebar grouping.
    page.keyboard.press('Control+k')
    expect(page.locator('#search-input')).to_be_focused()


def hold_note_search(page, marker, note_id):
    held = []

    def delay_actual_search(route):
        if marker not in route.request.url or held:
            route.continue_()
            return
        actual = route.fetch()
        assert actual.status == 200
        assert any(row['id'] == note_id and row['category'] == 'Конспект'
                   for row in actual.json()['items'])
        held.append((route, actual))

    page.route('**/api/campus/search?*', delay_actual_search)
    return held


def test_delayed_personal_search_never_enters_another_students_dialog(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    marker = 'PrivateSearch' + uuid.uuid4().hex
    title = marker + ' — fictional Alina note'
    note = create_note(page, address, title)
    held = hold_note_search(page, marker, note['id'])
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
    expect(page.locator('#search-personal')).not_to_contain_text(title)
    expect(page.locator('#page-title')).to_contain_text('Марк')
    assert page.request.get(address + '/api/me').json()['full_name'] == 'Марк Северин'


@pytest.mark.parametrize('reopen', [False, True], ids=['changed-query', 'reopened-dialog'])
def test_abandoned_search_cannot_replace_current_query_results(frontend_page, reopen):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    abandoned = 'AbandonedSearch' + uuid.uuid4().hex
    current = 'CurrentSearch' + uuid.uuid4().hex
    old_note = create_note(page, address, abandoned)
    create_note(page, address, current)
    held = hold_note_search(page, abandoned, old_note['id'])
    open_search(page)
    page.locator('#search-input').fill(abandoned)
    wait_for_held_response(page, held)
    if reopen:
        page.locator('.modal .close-btn').click()
        open_search(page)
    page.locator('#search-input').fill(current)
    expect(page.locator('#search-personal .search-result b')).to_have_text(current)
    route, actual = held[0]
    route.fulfill(response=actual)
    finish_browser_tasks(page)
    expect(page.locator('#search-input')).to_have_value(current)
    expect(page.locator('#search-personal .search-result b')).to_have_text(current)
    expect(page.locator('#search-personal')).not_to_contain_text(abandoned)


def test_note_markup_in_personal_search_remains_literal_text(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    marker = 'MarkupSearch' + uuid.uuid4().hex
    title = marker + ' <svg id="search-injected-title" onload="window.__searchExecuted=1">text</svg>'
    body = '</small><img id="search-injected-body" src=x onerror="window.__searchExecuted=2"> & "quoted"'
    create_note(page, address, title, body)
    open_search(page)
    page.locator('#search-input').fill(marker)
    result = page.locator('#search-personal .search-result')
    expect(result).to_have_count(1)
    expect(result.locator('b')).to_have_text(title)
    expect(result.locator('small')).to_have_text('Конспект · ' + body)
    expect(page.locator('#search-injected-title,#search-injected-body')).to_have_count(0)
    assert page.evaluate('() => window.__searchExecuted === undefined') is True
    # A precise result opens this note, preserving markup as text in fields.
    result.click()
    editor = page.locator('.modal form[data-c-form="note"]')
    expect(editor).to_be_visible()
    expect(editor.locator('[name="title"]')).to_have_value(title)
    expect(editor.locator('[name="body"]')).to_have_value(body)
    expect(page.locator('#search-injected-title,#search-injected-body')).to_have_count(0)


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


def test_selected_note_result_cannot_replace_new_dialog_after_list_load(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    marker = 'PreciseDelayedNote' + uuid.uuid4().hex
    note = create_note(page, address, marker)
    held = hold_first_list(page, '**/api/learning/notes')
    open_search(page)
    page.locator('#search-input').fill(marker)
    result = page.locator(f'#search-personal [data-search-target="notes"][data-search-id="{note["id"]}"]')
    expect(result).to_be_visible()
    result.click()
    wait_for_held_response(page, held)
    # Selecting the result has closed the first search and begun loading notes.
    # A new search started by the user must keep ownership of the modal.
    open_search(page)
    route, actual = held[0]
    route.fulfill(response=actual)
    page.wait_for_load_state('networkidle')
    finish_browser_tasks(page)
    expect(page.locator('#search-input')).to_be_visible()
    expect(page.locator('.modal form[data-c-form="note"]')).to_have_count(0)


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
