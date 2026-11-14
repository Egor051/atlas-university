"""Exercise revision, attachments and accumulation through the real cabinet."""
import os

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server
from test_university_browser import enter

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1', reason='Opt-in isolated Chromium')


def save(page):
    page.get_by_role('dialog').get_by_role('button', name='Сохранить', exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)


def test_assignment_revision_and_final_credit_in_browser(frontend_page):
    teacher, base = frontend_page
    teacher.set_viewport_size({'width': 375, 'height': 900})
    enter(teacher, base, 3, '/app/teaching')
    subject = 'Алгоритмы и структуры данных'
    teacher.get_by_role('link', name=subject).click()
    teacher.get_by_role('link', name='Задания', exact=True).click()
    teacher.get_by_role('button', name='Создать задание').press('Enter')
    title = 'Обход графа и крайние случаи'
    teacher.get_by_label('Название', exact=True).fill(title)
    teacher.get_by_label('Условия задания').fill('Приложите решение и результат выполнения на двух входах.')
    teacher.get_by_text('Способы сдачи и попытки', exact=True).click()
    teacher.get_by_role('checkbox', name='Файлы', exact=True).check()
    save(teacher)
    teacher.get_by_role('link', name=title, exact=True).click()
    expect(teacher.get_by_role('heading', name=title)).to_be_visible()
    work_url = teacher.url

    student_context = teacher.context.browser.new_context(viewport={'width': 320, 'height': 900}, locale='ru-RU',
                                                          color_scheme='dark', accept_downloads=True)
    try:
        student = student_context.new_page()
        enter(student, base, 0, '/app/assignments')
        row = student.locator('.assignment-row').filter(has_text=title)
        assignment_url = base + '/app/assignments?id=' + row.get_attribute('data-campus-record-id')
        row.get_by_role('button', name='Сдать работу').click()
        form = student.locator('form[data-c-form="assignment"]')
        expect(form).to_be_visible()
        form.evaluate('form => form._atlasDraft.restore')
        form.get_by_label('Текст ответа', exact=True).fill('Первая версия показывает обход связного графа.')
        form.get_by_label('Файлы работы').set_input_files(
            {'name': 'граф.txt', 'mimeType': 'text/plain', 'buffer': b'Graph result ' * 3000})
        assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
        form.get_by_role('button', name='Отправить работу', exact=True).click()
        expect(student.get_by_role('dialog')).to_have_count(0)

        teacher.goto(work_url)
        expect(teacher.get_by_text('Первая версия показывает обход связного графа.', exact=True)).to_be_visible()
        expect(teacher.get_by_role('link', name='граф.txt')).to_be_visible()
        teacher.get_by_role('button', name='Взять на проверку').click()
        save(teacher)
        teacher.get_by_role('button', name='Вернуть на доработку').click()
        teacher.get_by_label('Замечания к работе').fill('Добавьте несвязный граф и опишите результат.')
        save(teacher)

        student.goto(assignment_url)
        expect(student.get_by_role('dialog').get_by_text('Нужно исправить: Добавьте несвязный граф и опишите результат.',
                                                        exact=True)).to_be_visible()
        form.evaluate('form => form._atlasDraft.restore')
        form.get_by_label('Текст ответа', exact=True).fill('Новая версия включает разбор двух несвязных компонент.')
        form.get_by_role('button', name='Отправить новую версию').click()
        expect(student.get_by_role('dialog')).to_have_count(0)

        def score():
            grades = student.request.get(base + '/api/grades').json()['items']
            return next(row['score'] for row in grades if row['subject'] == subject)

        original = score()
        teacher.goto(work_url)
        expect(teacher.get_by_text('Новая версия включает разбор двух несвязных компонент.', exact=True)).to_be_visible()
        teacher.get_by_text('История версий', exact=True).click()
        teacher.get_by_text('Попытка 1', exact=False).click()
        expect(teacher.get_by_text('Первая версия показывает обход связного графа.', exact=True)).to_be_visible()
        teacher.get_by_role('button', name='Принять работу').click()
        teacher.get_by_label('Балл за работу (необязательно)', exact=True).fill('7')
        teacher.get_by_label('Комментарий студенту').fill('Результат проверен, обе компоненты разобраны.')
        save(teacher)
        assert score() == original + 7

        student.goto(assignment_url)
        expect(student.get_by_role('dialog').locator('.campus-pill').filter(has_text='Принято')).to_be_visible()
        student.get_by_text('Обратная связь преподавателя', exact=True).click()
        expect(student.get_by_text('Результат проверен, обе компоненты разобраны.', exact=True)).to_be_visible()
        student.get_by_text('История версий', exact=True).click()
        student.get_by_text('Попытка 1', exact=False).click()
        with student.expect_download() as file:
            student.get_by_role('link', name='граф.txt').click()
        assert file.value.suggested_filename == 'граф.txt'
        assert teacher.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        student_context.close()
