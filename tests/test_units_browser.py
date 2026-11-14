"""The new units are exercised through real accounts, forms and downloads."""
from contextlib import contextmanager
import os
import re

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server
from test_university_browser import enter

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1', reason='Opt-in local Chromium')


@contextmanager
def cabinet(page, base, actor, destination):
    context = page.context.browser.new_context(viewport={'width': 390, 'height': 900}, locale='ru-RU')
    try:
        other = context.new_page()
        enter(other, base, actor, destination)
        yield other
    finally:
        context.close()


def submit(page, label):
    dialog = page.get_by_role('dialog')
    dialog.get_by_role('button', name=label, exact=True).click()
    expect(dialog).to_have_count(0)


def step(page, label, status, *, message='', group=''):
    page.get_by_role('button', name=label, exact=True).click()
    dialog = page.get_by_role('dialog')
    if message:
        dialog.get_by_label('Ответ студенту', exact=True).fill(message)
    if group:
        dialog.get_by_label('Учебная группа', exact=True).select_option(label=group)
    submit(page, label)
    expect(page.locator('.page-subtitle')).to_contain_text(status)


def open_notice(page, base, text, target):
    page.goto(base + '/app/notifications')
    page.locator('.notification-full').filter(has_text=text).first.get_by_role('button', name='Открыть').click()
    expect(page).to_have_url(base + target)


def test_union_form_queue_clarification_decision_and_publication(frontend_page, tmp_path):
    student, base = frontend_page
    student.set_viewport_size({'width': 360, 'height': 900})
    enter(student, base, 0, '/app/union')
    student.get_by_role('button', name='Вступить в профсоюз').click()
    student.get_by_role('checkbox', name='Подтверждаю отправку').check()
    submit(student, 'Отправить')
    expect(student).to_have_url(re.compile(r'/app/union/\d+$'))
    student_path = student.url.removeprefix(base)
    case_id = student_path.rsplit('/', 1)[1]
    office_path = '/app/union-office/' + case_id
    with cabinet(student, base, 6, '/app/union-office') as representative:
        representative.get_by_role('link', name='Вступление в профсоюз №' + case_id).click()
        expect(representative).to_have_url(base + office_path)
        step(representative, 'Взять на проверку', 'Проверяется')
        step(representative, 'Запросить уточнение', 'Нужно уточнение', message='Подтвердите учебное вступление.')
        open_notice(student, base, 'Нужно уточнение', student_path)
        student.get_by_role('button', name='Добавить уточнение').click()
        student.get_by_label('Уточнение', exact=True).fill('Подтверждаю учебное вступление.')
        submit(student, 'Отправить')
        expect(student.locator('.op-log')).to_contain_text('Подтверждаю учебное вступление.')
        representative.reload()
        expect(representative.locator('.op-log')).to_contain_text('Уточнение студента')
        step(representative, 'Взять на проверку', 'Проверяется')
        step(representative, 'Одобрить', 'Одобрено', message='Демонстрационное членство оформлено.')

        representative.goto(base + '/app/union-office?tab=content')
        representative.get_by_role('button', name='Добавить публикацию').click()
        representative.get_by_label('Раздел публикации').select_option('news')
        representative.get_by_label('Заголовок').fill('Пример рабочего объявления')
        representative.get_by_label('Текст', exact=True).fill('Вымышленное сообщение о консультациях представителей.')
        submit(representative, 'Сохранить')
        expect(representative.get_by_role('heading', name='Пример рабочего объявления')).to_be_visible()
    open_notice(student, base, 'Вступление в профсоюз · Одобрено', student_path)
    with student.expect_download() as pending:
        student.get_by_role('link', name='Скачать решение').click()
    file = tmp_path / pending.value.suggested_filename
    pending.value.save_as(file)
    assert 'Демонстрационное членство оформлено.' in file.read_text(encoding='utf-8')
    student.goto(base + '/app/union')
    expect(student.get_by_text('Членство действует', exact=True)).to_be_visible()
    student.get_by_role('link', name='Публикации', exact=True).click()
    expect(student.get_by_role('heading', name='Пример рабочего объявления')).to_be_visible()
    assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
    with cabinet(student, base, 1, '/app/union') as other:
        assert other.request.get(base + '/api/units/union/cases/' + case_id + '/file').status == 404


def test_vuc_application_selection_and_group_result(frontend_page):
    student, base = frontend_page
    student.set_viewport_size({'width': 390, 'height': 900})
    enter(student, base, 0, '/app/vuc')
    student.locator('.op-row').filter(has_text='Организация учебного процесса').get_by_role('button', name='Подать заявление').click()
    dialog = student.get_by_role('dialog')
    assert dialog.locator('input[type="file"]').count() == 0
    dialog.get_by_role('checkbox', name='Заявление').check()
    dialog.get_by_role('checkbox', name='Подтверждение статуса студента').check()
    dialog.get_by_role('checkbox', name='Подтверждаю отправку').check()
    submit(student, 'Отправить')
    expect(student).to_have_url(re.compile(r'/app/vuc/\d+$'))
    student_path = student.url.removeprefix(base)
    office_path = student_path.replace('/vuc/', '/vuc-office/')
    with cabinet(student, base, 7, '/app/notifications') as worker:
        worker.locator('.notification-full').filter(has_text='Заявление в ВУЦ').get_by_role('button', name='Открыть').click()
        expect(worker).to_have_url(base + office_path)
        step(worker, 'Взять на проверку', 'Проверяется')
        step(worker, 'Передать на решение', 'Рассмотрение решения')
        step(worker, 'Одобрить', 'Одобрено', message='Учебная группа назначена.', group='АТ-ВУЦ-01')
        open_notice(student, base, 'Заявление в ВУЦ · Одобрено', student_path)
        student.goto(base + '/app/vuc?tab=learning')
        expect(student.get_by_role('heading', name='Вводная встреча и учебный календарь')).to_be_visible()
        expect(student.get_by_text('Ожидает результата', exact=True)).to_be_visible()

        worker.goto(base + '/app/vuc-office?tab=learning')
        worker.get_by_role('button', name='Оформить результат').click()
        worker.get_by_label('Результат', exact=True).select_option('passed')
        worker.get_by_label('Комментарий студенту').fill('Демонстрационное занятие зачтено.')
        submit(worker, 'Сохранить')
        expect(worker.get_by_text('Демонстрационное занятие зачтено.')).to_be_visible()
    open_notice(student, base, 'Результат ВУЦ обновлён', '/app/vuc?tab=learning')
    expect(student.get_by_text('Зачтено', exact=True)).to_be_visible()
    expect(student.get_by_text('Демонстрационное занятие зачтено.')).to_be_visible()
    assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
