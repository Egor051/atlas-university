"""Real-browser regressions for cross-account async extension responses.

Only an actual API response is delayed; successful responses are not fabricated.
The imported fixtures launch an isolated local server and temporary database.
"""
import os

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import (frontend_server, frontend_browser, frontend_page,
                                     enter_demo, finish_browser_tasks,
                                     wait_for_held_response)

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in real browser test')


def open_quizzes(page):
    target = page.locator('.nav-stack [data-route="quizzes"]')
    if not target.is_visible():
        target.locator('xpath=ancestor::details[contains(@class,"nav-group")]').locator('summary').click()
    target.click()
    expect(page.locator('#page-title')).to_have_text('Самопроверка')


def test_old_quiz_result_does_not_reopen_after_another_student_logs_in(frontend_page):
    page, address = frontend_page
    held = []

    def delay_actual_refresh(route):
        actual = route.fetch()
        assert actual.status == 200
        held.append((route, actual))

    page.goto(address)
    enter_demo(page, 0, 'Алина')
    open_quizzes(page)
    page.locator('[data-c-action="quiz-open"]').first.click()
    form = page.locator('[data-c-form="quiz"]')
    expect(form).to_be_visible()
    for question in form.locator('fieldset').all():
        question.locator('input[type="radio"]').first.check()
    page.route('**/api/learning/quizzes', delay_actual_refresh)
    form.locator('button[type="submit"]').click()
    wait_for_held_response(page, held)
    # The POST has committed and the refresh is pending, so navigation is free.
    page.locator('.topbar [data-route="profile"]').click()
    expect(page.locator('#page-title')).to_have_text('Мой профиль')
    page.locator('.danger-button[data-action="logout"]').click()
    expect(page.locator('#login-form')).to_be_visible()
    enter_demo(page, 1, 'Марк')
    route, actual = held[0]
    route.fulfill(response=actual)
    finish_browser_tasks(page)
    expect(page.locator('#page-title')).to_contain_text('Марк')
    expect(page.locator('.campus-quiz-results')).to_have_count(0)
    expect(page.locator('.modal')).to_have_count(0)


def test_abandoned_quiz_load_cannot_replace_active_quiz_answer_labels(frontend_page):
    page, address = frontend_page
    held = []

    def delay_abandoned_detail(route):
        actual = route.fetch()
        assert actual.status == 200
        held.append((route, actual))

    page.goto(address)
    enter_demo(page, 0, 'Алина')
    open_quizzes(page)
    buttons = page.locator('[data-c-action="quiz-open"]')
    expect(buttons).to_have_count(2)
    abandoned_id = buttons.first.get_attribute('data-id')
    page.route(f'**/api/learning/quizzes/{abandoned_id}', delay_abandoned_detail)
    buttons.first.click()
    wait_for_held_response(page, held)
    page.locator('.modal .close-btn').click()
    buttons.nth(1).click()
    form = page.locator('[data-c-form="quiz"]')
    expect(form).to_be_visible()
    selected_text = form.locator('fieldset').first.locator('label').first.inner_text().strip()
    for question in form.locator('fieldset').all():
        question.locator('input[type="radio"]').first.check()
    route, actual = held[0]
    route.fulfill(response=actual)
    finish_browser_tasks(page)
    form.locator('button[type="submit"]').click()
    feedback = page.locator('.campus-quiz-results article').first
    expect(feedback).to_be_visible()
    expect(feedback.locator('p').first).to_have_text('Ваш ответ: ' + selected_text)


def test_personal_text_and_link_markup_remain_text_in_cards_and_editors(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    title = '<b id="injected-title">Fictional note</b>'
    body = '</textarea><img id="injected-body" src=x onerror="alert(1)">'
    note = page.request.post(address + '/api/learning/notes', headers={'X-Requested-With': 'ATLAS'},
                             data={'title': title, 'subject': 'Security exercise', 'body': body})
    assert note.status == 201, note.text()
    note_id = note.json()['id']
    page.goto(address + '/app/notes')
    card = page.locator('.compact-row').filter(has=page.locator(f'[data-c-action="note-edit"][data-id="{note_id}"]'))
    expect(card.locator('h2')).to_have_text(title)
    expect(card.locator('.note-preview')).to_have_text(body)
    expect(page.locator('#injected-title,#injected-body')).to_have_count(0)
    card.locator('[data-c-action="note-edit"]').click()
    expect(page.locator('[name="title"]')).to_have_value(title)
    expect(page.locator('[name="body"]')).to_have_value(body)
    expect(page.locator('#injected-title,#injected-body')).to_have_count(0)
    page.locator('.modal .close-btn').click()
    project_title = '<svg id="injected-project" onload="alert(2)">Project</svg>'
    project = page.request.post(address + '/api/campus/portfolio', headers={'X-Requested-With': 'ATLAS'},
                                data={'title': project_title, 'kind': 'project', 'description': body,
                                      'url': 'https://example.invalid/?q="quoted"', 'day': '2026-11-07'})
    assert project.status == 201, project.text()
    page.goto(address + '/app/portfolio')
    tile = page.locator('.campus-tile').filter(has=page.locator(f'[data-c-action="portfolio-edit"][data-id="{project.json()["id"]}"]'))
    expect(tile.locator('h2')).to_have_text(project_title)
    expect(tile.locator('.user-text')).to_have_text(body)
    expect(page.locator('#injected-project,#injected-body')).to_have_count(0)
    external = tile.locator('a[target="_blank"]')
    expect(external).to_have_count(1)
    assert external.get_attribute('href').startswith('https://example.invalid/')
    assert set(external.get_attribute('rel').split()) >= {'noopener', 'noreferrer'}
