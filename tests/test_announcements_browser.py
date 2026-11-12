"""A real office-to-student publication through the browser and API."""
import os
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1', reason='Opt-in local Chromium')


def login(page, base, login, password):
    page.goto(base)
    form = page.locator('#login-form')
    form.get_by_label('Логин').fill(login)
    form.get_by_label('Пароль').fill(password)
    form.get_by_role('button', name='Войти в кабинет').click()
    expect(page.locator('.shell').or_(page.locator('#login-error:visible'))).to_be_visible()
    assert page.locator('.shell').count() == 1, page.locator('#login-error').inner_text()


def test_announcement_preview_publish_and_home_layout(frontend_page):
    office, base = frontend_page
    errors = []
    office.on('pageerror', lambda error: errors.append(str(error)))
    login(office, base, 'dean.demo', 'AtlasStaff!2026-D')
    office.get_by_role('navigation', name='Работа со студентами — разделы').get_by_role('link', name='Управление объявлениями').click()
    expect(office.get_by_role('heading', name='Управление объявлениями')).to_be_visible()
    office.get_by_role('button', name='Создать объявление').click()
    form = office.get_by_role('dialog', name='Создать объявление')
    title = f'Уточнение сроков {uuid4().hex[:6]}'
    body = 'Первая строка\n' + ('ДлинныйТекст' * 120) + '\n<b>Последняя строка</b>'
    form.get_by_label('Заголовок').fill(title)
    form.get_by_label('Текст объявления').fill(body)
    form.get_by_label('Приоритет').select_option('critical')
    form.get_by_role('button', name='Предпросмотр').click()
    preview = form.get_by_role('region', name='Предпросмотр объявления')
    expect(preview.get_by_role('heading')).to_have_text(title)
    expect(preview.locator('.announcement-body')).to_contain_text('<b>Последняя строка</b>')
    form.get_by_role('button', name='Сохранить черновик').click()
    expect(form).to_have_count(0)
    expect(office.get_by_role('heading', name=title)).to_be_visible()
    office.get_by_role('button', name='Редактировать').click()
    edit = office.get_by_role('dialog', name='Редактировать объявление')
    edit.get_by_label('Статус').select_option('published')
    edit.get_by_role('button', name='Сохранить', exact=True).click()
    expect(edit).to_have_count(0)
    expect(office.locator('.announcement-history')).to_contain_text('Опубликовано')
    office.reload()
    expect(office.get_by_role('heading', name=title)).to_be_visible()

    with office.context.browser.new_context(viewport={'width': 1440, 'height': 1000}) as context:
        student = context.new_page()
        student.on('pageerror', lambda error: errors.append(str(error)))
        login(student, base, 'alina.demo', 'AtlasDemo!2026-A')
        student.goto(base + '/app/home')
        timeline = student.get_by_role('region', name='Объявления')
        item = timeline.get_by_role('link', name=title)
        expect(item).to_be_visible()
        assert timeline.bounding_box()['y'] < 850
        timeline.get_by_role('button', name='Важные').click()
        expect(item).to_have_count(0)
        timeline.get_by_role('button', name='Срочные').click()
        expect(item).to_be_visible()
        for width in [320, 360, 390, 768, 1024, 1280, 1440, 1920]:
            student.set_viewport_size({'width': width, 'height': 1000})
            assert student.evaluate('document.documentElement.scrollWidth') <= width
            assert student.locator('.announcement-track').evaluate('node => node.scrollWidth <= node.clientWidth')
        deadlines = student.get_by_role('heading', name='Ближайшие сроки').locator('xpath=ancestor::section[1]')
        notices = student.get_by_role('heading', name='Уведомления').locator('xpath=ancestor::section[1]')
        gap = notices.bounding_box()['y'] - (deadlines.bounding_box()['y'] + deadlines.bounding_box()['height'])
        assert 0 <= gap <= 20
        item.click()
        expect(student.get_by_role('heading', name=title)).to_be_visible()
        expect(student.locator('.announcement-detail .announcement-body')).to_contain_text('<b>Последняя строка</b>')
        student.get_by_role('link', name='К объявлениям').click()
        student.get_by_label('Поиск', exact=True).fill(title)
        student.get_by_role('button', name='Применить').click()
        expect(student.locator('.announcement-list .announcement-list-item')).to_have_count(1)
        student.locator('#side-nav a[data-route="notifications"]').click()
        notice = student.locator('.notification-full').filter(has_text=title)
        notice.get_by_role('button', name='Открыть', exact=True).click()
        expect(student.get_by_role('heading', name=title)).to_be_visible()
        expect(student.locator('.announcement-detail')).to_be_visible()
    assert errors == []
