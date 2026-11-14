"""Real-browser regression for rendering private notes and portfolios as text."""
import os

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import (frontend_server, frontend_browser, frontend_page,
                                     enter_demo)

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in real browser test')


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
    expect(page).to_have_url(address + '/app/learning/notes')
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


def test_retired_sections_and_notes_routes(frontend_page):
    page, address = frontend_page
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    destinations = {'library': 'materials', 'learning/quizzes': 'materials',
                    'flashcards': 'materials', 'planning/focus': 'tasks',
                    'planning/notes': 'learning/notes'}
    for before, after in destinations.items():
        page.goto(f'{address}/app/{before}')
        expect(page).to_have_url(f'{address}/app/{after}')
    learning = page.get_by_role('navigation', name='Учебные материалы и задания — разделы')
    expect(learning.get_by_text('Конспекты', exact=True)).to_have_attribute('aria-current', 'page')
    expect(page.locator('[data-route=quizzes],[data-route=flashcards],[data-route=focus],[data-route=library]')).to_have_count(0)
    expect(page.locator('.concept-bar')).to_have_text('Конкурсный концепт · все данные вымышлены · неофициальный сервис')
    expect(page.locator('.concept-bar')).to_have_count(1)
    page.keyboard.press('Control+k')
    search = page.get_by_role('textbox', name='Поиск по кабинету', exact=True)
    search.fill('конспекты')
    expect(page.locator('#search-results [data-route=notes]')).to_be_visible()
    search.fill('самопроверка')
    expect(page.locator('#search-results [data-route=quizzes]')).to_have_count(0)
