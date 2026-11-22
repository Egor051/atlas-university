"""The new units are exercised through real accounts, forms and downloads."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
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



def screenshot(page, name):
    destination = os.environ.get('ATLAS_VUC_SCREENSHOTS')
    if destination:
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        expect(page.locator('#toast .toast-message')).to_have_count(0, timeout=6500)
        page.evaluate('() => { document.activeElement?.blur(); window.scrollTo(0, 0); }')
        page.screenshot(path=directory / (name + '.jpg'), type='jpeg', quality=74, full_page=True, animations='disabled')


def fits_viewport(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.evaluate("""() => {
        const modal = document.querySelector('.modal');
        return !modal || modal.scrollWidth <= modal.clientWidth + 1;
    }""")


def test_vuc_campaign_publication_inquiry_and_archive(frontend_page):
    student, base = frontend_page
    today = datetime.now(timezone(timedelta(hours=3))).date()
    upcoming = (today + timedelta(days=1)).isoformat()
    later = (today + timedelta(days=8)).isoformat()
    earlier = (today - timedelta(days=1)).isoformat()
    title = 'Кампания для изолированной приёмки'
    student.set_viewport_size({'width': 360, 'height': 900})
    enter(student, base, 0, '/app/vuc')
    expect(student.get_by_text('Подтверждённых кампаний пока нет')).to_be_visible()
    expect(student.get_by_role('heading', name='Подготовка офицеров запаса')).to_be_visible()
    student.get_by_text('Условия программы', exact=True).first.focus()
    student.keyboard.press('Enter')
    expect(student.get_by_text('НИУ МГСУ: очный специалитет', exact=False)).to_be_visible()
    fits_viewport(student)
    screenshot(student, 'catalog-360')

    with cabinet(student, base, 7, '/app/vuc-office') as worker:
        worker.get_by_role('button', name='Добавить кампанию').click()
        editor = worker.get_by_role('dialog')
        expect(editor.get_by_label('Начало приёма документов')).to_have_value('')
        editor.get_by_label('Программа', exact=True).select_option(label='Подготовка офицеров запаса')
        editor.get_by_label('Первый год учебного года').fill(str(today.year))
        editor.get_by_label('Название кампании').fill(title)
        editor.get_by_label('Состояние кампании').select_option('published')
        editor.get_by_label('Начало приёма документов').fill(upcoming)
        editor.get_by_label('Последний день приёма').fill(later)
        editor.get_by_label('Документы, по одному на строку').fill('Заявление по форме кампании\nСправка об обучении')
        editor.get_by_label('Как и куда подать документы').fill('Передайте комплект в учебный офис по инструкции кампании.')
        editor.get_by_text('Сроки отдельных этапов', exact=True).click()
        editor.get_by_label('Окончание · Медицинское освидетельствование', exact=True).fill(later)
        editor.get_by_label('Название документа или страницы').fill('Источник для изолированной проверки')
        editor.get_by_label('Ссылка на официальный источник').fill('https://vucmsu.ru/mem.html')
        editor.get_by_label('Дата проверки источника').fill(today.isoformat())
        fits_viewport(worker)
        submit(worker, 'Сохранить')
        expect(worker.get_by_text('Приём ещё не открыт')).to_be_visible()
        student.reload()
        expect(student.get_by_text('Приём ещё не открыт')).to_be_visible()
        expect(student.get_by_role('button', name='Создать обращение')).to_have_count(0)

        worker.get_by_role('button', name='Изменить кампанию').click()
        worker.get_by_label('Начало приёма документов').fill(earlier)
        submit(worker, 'Сохранить')
        expect(worker.get_by_text('Приём документов открыт')).to_be_visible()
        screenshot(worker, 'office-campaign-390')

        student.set_viewport_size({'width': 390, 'height': 900})
        student.reload()
        expect(student.get_by_text('Приём документов открыт')).to_be_visible()
        student.get_by_text('Условия, документы и этапы', exact=True).click()
        expect(student.get_by_text('Справка об обучении', exact=True)).to_be_visible()
        expect(student.locator('.vuc-campaign').get_by_text('Профессиональный психологический отбор', exact=True)).to_be_visible()
        expect(student.get_by_text('Не опубликованы', exact=True)).to_be_visible()
        fits_viewport(student)
        screenshot(student, 'campaign-390')
        student.set_viewport_size({'width': 1440, 'height': 1000})
        fits_viewport(student)
        screenshot(student, 'campaign-1440')
        student.get_by_role('button', name='Создать обращение').click()
        dialog = student.get_by_role('dialog')
        assert dialog.locator('input[type="file"]').count() == 0
        dialog.get_by_role('checkbox').check()
        submit(student, 'Отправить обращение')
        expect(student).to_have_url(re.compile(r'/app/vuc/admission/\d+$'))
        student_path = student.url.removeprefix(base)
        expect(student.locator('.page-subtitle')).to_contain_text('Обращение создано')

        office_path = student_path.replace('/vuc/', '/vuc-office/')
        open_notice(worker, base, 'Новое обращение по приёму в ВУЦ', office_path)
        worker.get_by_role('button', name='Зарегистрировать полученные документы').click()
        worker.get_by_label('Сообщение кандидату и следующие действия').fill('Комплект получен. Ожидайте направление.')
        worker.get_by_label('Регистрационный номер принятого комплекта').fill('Номер изолированной проверки')
        worker.get_by_label('Дата документа').fill(today.isoformat())
        submit(worker, 'Сохранить')
        expect(worker.locator('.page-subtitle')).to_contain_text('Документы зарегистрированы')
        open_notice(student, base, 'Документы зарегистрированы', student_path)
        expect(student.locator('.op-log')).to_contain_text('Ожидайте направление.')
        worker.get_by_role('link', name='К кандидатам').click()
        expect(worker.get_by_role('article').get_by_text('Документы зарегистрированы', exact=True)).to_be_visible()

        worker.goto(base + '/app/vuc-office?tab=content')
        worker.get_by_role('button', name='Добавить публикацию').click()
        worker.get_by_label('Раздел публикации').select_option('news')
        worker.get_by_label('Заголовок').fill('Ответы на вопросы по кампании')
        worker.get_by_label('Текст', exact=True).fill('Приём уточнений через учебный офис.')
        submit(worker, 'Сохранить')
        student.goto(base + '/app/vuc?tab=content')
        expect(student.get_by_role('heading', name='Ответы на вопросы по кампании')).to_be_visible()

        worker.goto(base + '/app/vuc-office')
        worker.get_by_role('button', name='Изменить кампанию').click()
        worker.get_by_label('Последний день приёма').fill(earlier)
        submit(worker, 'Сохранить')
        expect(worker.get_by_text('Приём документов завершён')).to_be_visible()
        worker.get_by_role('button', name='Изменить кампанию').click()
        worker.get_by_label('Состояние кампании').select_option('archived')
        submit(worker, 'Сохранить')
        worker.get_by_role('link', name='Архив кампаний').click()
        expect(worker.get_by_role('heading', name=title)).to_be_visible()
        expect(worker.get_by_role('button', name='Изменить кампанию')).to_have_count(0)
    student.set_viewport_size({'width': 360, 'height': 900})
    student.goto(base + '/app/vuc?tab=archive')
    expect(student.get_by_role('heading', name=title)).to_be_visible()
    expect(student.get_by_role('button', name='Создать обращение')).to_have_count(0)
    student.get_by_role('link', name='Открыть моё обращение').click()
    expect(student).to_have_url(base + student_path)
    fits_viewport(student)
