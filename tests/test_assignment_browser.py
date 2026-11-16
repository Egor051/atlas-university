"""Exercise revision, attachments and accumulation through the real cabinet."""
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

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
    teacher.get_by_role('link', name='Сдача работ', exact=True).click()
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
        expect(student.get_by_role('dialog').get_by_text('Добавьте несвязный граф и опишите результат.', exact=True)).to_be_visible()
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
        expect(student.get_by_role('dialog').locator('.campus-pill').filter(has_text='Оценено')).to_be_visible()
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


@pytest.mark.parametrize('committed_before_loss', [False, True])
def test_file_only_draft_and_safe_retry_after_network_loss(frontend_page, committed_before_loss):
    student, base = frontend_page
    student.set_viewport_size({'width': 360, 'height': 900})
    enter(student, base, 0, '/app/assignments')
    with student.context.browser.new_context() as context:
        teacher = context.new_page()
        enter(teacher, base, 3, '/app/teaching')
        load = teacher.request.get(base + '/api/teaching').json()['items'][0]
        identity = student.request.get(base + '/api/me').json()['id']
        title = 'Файловая работа ' + uuid4().hex[:6]
        created = teacher.request.post(base + f'/api/teaching/{load["id"]}/works', headers={'X-Requested-With': 'ATLAS'},
            data={'title': title, 'instructions': 'Отправьте два файла с результатами проверки.',
                  'due_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), 'recipient_ids': [identity],
                  'methods': ['files'], 'required_methods': ['files'], 'formats': ['txt'], 'min_files': 2, 'max_files': 2})
        assert created.status == 201, created.text()
    student.reload()
    row = student.locator('.assignment-row').filter(has_text=title)
    expect(row).to_be_visible()
    deadline_id = row.get_attribute('data-campus-record-id')
    page_url = base + f'/app/assignments?id={deadline_id}'
    api_url = base + f'/api/learning/assignments/{deadline_id}'
    student.goto(page_url)
    form = student.locator('form[data-c-form="assignment"]')
    expect(form).to_be_visible()
    expect(form.get_by_label('Текст ответа', exact=True)).to_have_count(0)
    button = form.get_by_role('button', name='Отправить работу', exact=True)
    error = form.locator('[data-c-error]')
    button.click()
    expect(error).to_be_visible()
    upload = form.get_by_label('Файлы работы')
    upload.set_input_files({'name': 'чертёж.exe', 'mimeType': 'application/octet-stream', 'buffer': b'plain test bytes'})
    expect(error).to_contain_text('формат')
    upload.set_input_files([
        {'name': 'решение.txt', 'mimeType': 'text/plain', 'buffer': b'edge case'},
        {'name': 'проверка.txt', 'mimeType': 'text/plain', 'buffer': b'valid result'},
    ])
    expect(form.locator('[data-work-draft]')).to_contain_text('Черновик сохранён')
    student.reload()
    expect(form.locator('[data-work-draft]')).to_contain_text('Восстановлен черновик')
    expect(form.locator('[data-work-files] li')).to_have_count(2)
    keys = []

    def drop_first(route):
        keys.append(route.request.headers.get('idempotency-key'))
        if len(keys) > 1:
            route.continue_()
            return
        if committed_before_loss:
            assert route.fetch().status == 200
        route.abort('failed')

    student.route(api_url + '/submit', drop_first)
    button.evaluate('(button) => { button.click(); button.click(); }')
    retry = form.get_by_role('button', name='Повторить отправку', exact=True)
    expect(retry).to_be_enabled()
    assert len(keys) == 1 and keys[0]
    expect(error).to_be_visible()
    expect(form.locator('[data-work-files] li')).to_have_count(2)
    if not committed_before_loss:
        assert student.request.get(api_url).json()['attempts'] == []
        student.reload()
        expect(form.locator('[data-work-draft]')).to_contain_text('Восстановлен черновик')
        expect(form.locator('[data-work-files] li')).to_have_count(2)
        button.click()
    else:
        retry.click()
    expect(student.get_by_role('dialog')).to_have_count(0)
    assert keys == [keys[0], keys[0]]
    attempts = student.request.get(api_url).json()['attempts']
    assert len(attempts) == 1 and len(attempts[0]['files']) == 2
    student.reload()
    expect(student.get_by_role('dialog')).to_contain_text('Сдано')
    expect(form).to_have_count(0)
