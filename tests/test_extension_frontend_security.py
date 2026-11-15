"""Browser coverage for retired student routes and retained teaching materials."""
import os
from datetime import date, timedelta
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import enter_demo, frontend_browser, frontend_page, frontend_server

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in real browser test')
HEADERS = {'X-Requested-With': 'ATLAS'}


def test_saved_records_survive_retired_routes_and_stay_out_of_search(frontend_page):
    page, base = frontend_page
    page.goto(base)
    enter_demo(page, 0, 'Алина')
    marker = 'RetiredRecord' + uuid4().hex
    for endpoint, route, destination, values in [
        ('learning/tasks', 'tasks', 'assignments', {'due_date': (date.today() + timedelta(days=7)).isoformat()}),
        ('learning/notes', 'learning/notes', 'courses', {'body': 'Вымышленная заметка до изменения навигации.'}),
        ('campus/portfolio', 'portfolio', 'profile', {'kind': 'project', 'day': '2026-11-07'}),
    ]:
        url = f'{base}/api/{endpoint}'
        created = page.request.post(url, headers=HEADERS, data={'title': marker, **values})
        assert created.status == 201, created.text()
        record = created.json()
        page.goto(f'{base}/app/{route}?id={record["id"]}')
        expect(page).to_have_url(f'{base}/app/{destination}')
        expect(page.get_by_role('dialog')).to_have_count(0)
        assert record in page.request.get(url).json()['items']
    page.keyboard.press('Control+k')
    page.locator('#search-input').fill(marker)
    expect(page.locator('#search-personal')).to_contain_text('В ваших данных совпадений нет.')


def test_legacy_routes_and_materials_belong_to_current_navigation(frontend_page):
    page, base = frontend_page
    page.goto(base + '/app/planning/tasks')
    page.get_by_role('button', name='Или выбрать демо-аккаунт', exact=True).click()
    page.locator('[data-demo="0"]').click()
    expect(page).to_have_url(base + '/app/assignments')
    expect(page.locator('#page-title')).to_have_text('Сдача работ')
    destinations = {
        'planning': 'assignments', 'plan': 'assignments', 'planning/focus': 'assignments',
        'calendar': 'schedule', 'planning/calendar': 'schedule',
        'notes': 'courses', 'planning/notes': 'courses', 'account/portfolio': 'profile',
        'library': 'courses', 'learning/quizzes': 'courses',
        'flashcards': 'courses', 'learning/materials': 'courses',
    }
    for before, after in destinations.items():
        page.goto(f'{base}/app/{before}')
        expect(page).to_have_url(f'{base}/app/{after}')
        expect(page.locator('.error-state')).to_have_count(0)
    breadcrumbs = page.get_by_role('navigation', name='Путь к разделу')
    expect(page.locator('#page-title')).to_have_text('Мои дисциплины')
    learning = page.get_by_role('navigation', name='Учебные материалы и задания — разделы')
    expect(learning.get_by_text('Мои дисциплины', exact=True)).to_have_attribute('aria-current', 'page')
    expect(learning.get_by_role('link')).to_have_text(['Сдача работ'])
    page.locator('.discipline-catalog').get_by_role('link', name='Алгоритмы и структуры данных', exact=True).click()
    expect(page.locator('#page-title')).to_have_text('Алгоритмы и структуры данных')
    material = page.locator('.material-row h2 a').first
    title = material.inner_text()
    address = material.get_attribute('href')
    material.click()
    expect(page.locator('#page-title')).to_have_text(title)
    expect(page).to_have_url(base + address)
    page.goto(base + '/app/materials/' + address.rsplit('/', 1)[1])
    expect(page).to_have_url(base + address)
    expect(breadcrumbs.get_by_role('link', name='Алгоритмы и структуры данных')).to_be_visible()
    expect(breadcrumbs.get_by_role('link', name='Мои дисциплины')).to_be_visible()
    expect(page.get_by_role('link', name='Скачать HTML')).to_be_visible()
    nav = page.locator('#side-nav')
    expect(nav.locator('[data-route="courses"]')).to_have_attribute('aria-current', 'location')
    expect(nav.locator('[data-route=materials],[data-route=notes],[data-route=portfolio],[data-nav-group=planning]')).to_have_count(0)
    expect(page.locator('.concept-bar')).to_have_text('Конкурсный концепт · все данные вымышлены · неофициальный сервис')
    expect(page.locator('.concept-bar')).to_have_count(1)
    page.keyboard.press('Control+k')
    search = page.get_by_role('textbox', name='Поиск по кабинету', exact=True)
    search.fill('учебные материалы')
    expect(page.locator('#search-results [data-route=courses]')).to_be_visible()
    expect(page.locator('#search-results [data-route=materials]')).to_have_count(0)
