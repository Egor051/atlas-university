"""Actual browser workflows on the disposable local HTTP application."""
import os
import re

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in isolated real Chromium')
PROFILE = '/app/university/digital/systems/mikhail-orlov'


def enter(page, base, actor, destination='/'):
    page.goto(base + destination)
    page.locator(f'[data-demo="{actor}"]').click()
    expect(page.locator('#page-title')).to_be_visible()


def test_department_teacher_file_and_private_reply(frontend_page, tmp_path):
    student, base = frontend_page
    student.set_viewport_size({'width': 360, 'height': 900})
    enter(student, base, 0, '/app/university')
    student.get_by_role('link', name='Институт цифровых технологий', exact=True).click()
    student.get_by_role('link', name='Кафедра информационных систем', exact=True).click()
    student.get_by_role('link', name='Михаил Орлов', exact=True).click()
    expect(student).to_have_url(base + PROFILE)
    crumbs = student.get_by_role('navigation', name='Путь к разделу')
    expect(crumbs.locator('[aria-current="page"]')).to_have_text('Михаил Орлов')
    expect(crumbs.get_by_role('link', name='Кафедра информационных систем')).to_have_attribute(
        'href', '/app/university/digital/systems')
    expect(student.get_by_role('heading', name='Консультации · МСК')).to_be_visible()
    student.get_by_role('link', name=re.compile('Лекция. Поиск пути')).click()
    expect(student.locator('.school-reader')).to_contain_text('O(V + E)')
    with student.expect_download() as pending:
        student.get_by_role('link', name='Скачать HTML').click()
    lecture = tmp_path / pending.value.suggested_filename
    pending.value.save_as(lecture)
    viewer = student.context.new_page()
    viewer.goto(lecture.as_uri())
    expect(viewer.get_by_role('heading', name='Лекция. Поиск пути в невзвешенном графе')).to_be_visible()
    expect(viewer.get_by_role('heading', name='Обход в ширину')).to_be_visible()
    viewer.close()
    student.go_back()
    expect(student).to_have_url(base + PROFILE)
    student.get_by_role('link', name='Написать преподавателю').click()
    student.get_by_label('Сообщение', exact=True).fill('Как выбрать <b>очередь</b> для графа?')
    student.get_by_role('button', name='Отправить').click()
    expect(student).to_have_url(re.compile('/app/direct/[0-9]+$'))
    url = student.url
    expect(student.locator('.school-conversation')).to_contain_text('Как выбрать <b>очередь</b> для графа?')
    expect(student.locator('.school-conversation p b')).to_have_count(0)
    teacher_context = student.context.browser.new_context(viewport={'width': 1440, 'height': 900})
    other_context = student.context.browser.new_context()
    try:
        teacher = teacher_context.new_page()
        enter(teacher, base, 3)
        expect(teacher).to_have_url(base + '/app/teacher')
        expect(teacher.locator('.topbar [data-route=direct]')).to_have_attribute('aria-label', re.compile('непрочитанных'))
        teacher.locator('.topbar [data-route=direct]').click()
        teacher.get_by_role('link', name='Алина Ветрова').click()
        expect(teacher).to_have_url(url)
        expect(teacher.locator('.school-conversation')).to_contain_text('для графа')
        teacher.get_by_label('Сообщение', exact=True).fill('Для BFS подходит очередь FIFO.')
        teacher.get_by_role('button', name='Отправить').click()
        expect(teacher.locator('.school-conversation')).to_contain_text('очередь FIFO')
        student.goto(base + '/app/notifications')
        notification = student.locator('.notification-full').filter(has_text='Новое личное сообщение').first
        expect(notification).to_contain_text('Михаил Орлов')
        notification.get_by_role('button', name='Открыть').click()
        expect(student).to_have_url(url)
        expect(student.locator('.school-conversation')).to_contain_text('очередь FIFO')
        student.reload()
        expect(student.locator('.school-conversation')).to_contain_text('очередь FIFO')
        assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
        other = other_context.new_page()
        other.goto(url)
        other.locator('[data-demo="1"]').click()
        expect(other.locator('.error-state')).to_contain_text('Диалог не найден')
        expect(other.locator('.school-conversation')).to_have_count(0)
    finally:
        teacher_context.close()
        other_context.close()


def test_publish_edit_delete_from_teacher_cabinet(frontend_page):
    teacher, base = frontend_page
    teacher.set_viewport_size({'width': 390, 'height': 850})
    enter(teacher, base, 3)
    teacher.get_by_role('link', name='Публикации', exact=True).filter(visible=True).last.click()
    expect(teacher.locator('#page-title')).to_have_text('Публикации')
    teacher.get_by_role('button', name='Опубликовать материал').click()
    form = teacher.locator('form[data-school-form=material]')
    form.get_by_label('Название').fill('Практикум для проверки редактора')
    form.get_by_label('Описание').fill('Фиктивный практикум для демонстрации публикации.')
    form.get_by_label('Текст материала').fill('## Пример\nПроверьте доступ к своему учебному материалу.')
    form.get_by_role('button', name='Опубликовать', exact=True).click()
    item = teacher.locator('.compact-row').filter(has_text='Практикум для проверки редактора')
    expect(item).to_be_visible()
    item.get_by_role('button', name=re.compile('Изменить')).click()
    form.get_by_label('Название').fill('Практикум после правки')
    form.get_by_role('button', name='Сохранить изменения').click()
    updated = teacher.locator('.compact-row').filter(has_text='Практикум после правки')
    expect(updated).to_be_visible()
    updated.get_by_role('button', name=re.compile('Удалить')).click()
    teacher.get_by_role('dialog').get_by_role('button', name='Удалить', exact=True).click()
    expect(updated).to_have_count(0)
    assert teacher.evaluate('document.documentElement.scrollWidth <= innerWidth')
