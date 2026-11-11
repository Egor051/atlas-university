"""The operations are exercised through the real cabinet and file picker."""
from datetime import date, timedelta
import os
import re

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server
from test_university_browser import enter

pytestmark=pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS')!='1',reason='Opt-in isolated Chromium')


def save(page):
    page.get_by_role('dialog').get_by_role('button',name='Сохранить',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)


def test_teacher_marks_and_attendance_in_browser(frontend_page):
    teacher,base=frontend_page
    teacher.set_viewport_size({'width':360,'height':900})
    enter(teacher,base,3,'/app/teaching')
    teacher.get_by_role('link',name='Алгоритмы и структуры данных').click()
    teacher.get_by_role('link',name='Ведомость',exact=True).click()
    teacher.get_by_role('button',name='Изменить балл').click()
    teacher.get_by_label('Балл от 0 до 100').fill('92')
    teacher.get_by_label('Основание изменения').fill('Проверен демонстрационный граф.')
    save(teacher)
    expect(teacher.locator('.op-row')).to_contain_text('Балл: 92')
    teacher.get_by_role('link',name='Посещаемость',exact=True).click()
    teacher.get_by_role('button',name='Поставить отметку').click()
    teacher.get_by_label('Отметка',exact=True).select_option('present')
    save(teacher)
    expect(teacher.locator('.op-row')).to_contain_text('Присутствовал')
    teacher.get_by_role('link',name='Отчёт и история',exact=True).click()
    expect(teacher.locator('.op-log')).to_contain_text('Михаил Орлов')
    expect(teacher.locator('.op-log')).to_contain_text('→ 92')
    assert teacher.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_teacher_reads_student_submission_and_returns_feedback(frontend_page):
    teacher,base=frontend_page
    teacher.set_viewport_size({'width':390,'height':900})
    enter(teacher,base,3,'/app/teaching')
    teacher.get_by_role('link',name='Алгоритмы и структуры данных').click()
    teacher.get_by_role('link',name='Задания',exact=True).click()
    teacher.get_by_role('button',name='Создать задание').press('Enter')
    title='Учебная проверка связности'
    teacher.get_by_label('Название',exact=True).fill(title)
    teacher.get_by_label('Условия задания').fill('Объясните результат обхода простого графа.')
    save(teacher)
    teacher.get_by_role('link',name=title,exact=True).click()
    expect(teacher.get_by_text('Работы ещё не отправлены')).to_be_visible()
    work_url=teacher.url
    context=teacher.context.browser.new_context(viewport={'width':360,'height':900},locale='ru-RU')
    try:
        student=context.new_page()
        enter(student,base,0,'/app/assignments')
        assignment=student.locator('.assignment-row').filter(has_text=title)
        assignment.get_by_role('button',name='Сдать работу').click()
        form=student.locator('[data-c-form="assignment"]')
        expect(form).to_have_attribute('data-draft-bound','true')
        form.evaluate('form => form._atlasDraft.restore')
        answer='Все вершины графа доступны из вершины А.'
        form.get_by_label('Текст ответа',exact=True).fill(answer)
        assignment_id=assignment.get_attribute('data-campus-record-id')
        form.get_by_role('button',name='Отправить работу').click()
        expect(student.get_by_role('dialog')).to_have_count(0)

        teacher.goto(work_url)
        expect(teacher.get_by_text(answer,exact=True)).to_be_visible()
        teacher.get_by_role('button',name='Дать обратную связь').press('Enter')
        teacher.get_by_label('Балл за работу (необязательно)',exact=True).fill('94')
        reply='Добавьте пример графа из двух компонент.'
        teacher.get_by_label('Комментарий студенту').fill(reply)
        save(teacher)
        expect(teacher.get_by_text(reply,exact=True)).to_be_visible()

        student.goto(base+'/app/notifications')
        notice=student.locator('.notification-full').filter(has_text='Преподаватель проверил работу')
        notice.get_by_role('button',name='Открыть').click()
        expect(student.get_by_role('dialog',name='Сдать работу')).to_be_visible()
        assert student.url.endswith('/app/assignments?id='+assignment_id)
        student.get_by_text('Обратная связь преподавателя',exact=True).click()
        expect(student.get_by_text(reply,exact=True)).to_be_visible()
        expect(student.get_by_text('Михаил Орлов · версия 1 · 94 баллов',exact=True)).to_be_visible()
        assert teacher.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        context.close()


def test_dispatch_dean_admin_publish_and_csv_import(frontend_page):
    dispatch,base=frontend_page
    dispatch.set_viewport_size({'width':390,'height':900})
    enter(dispatch,base,4)
    expect(dispatch).to_have_url(base+'/app/timetable-admin')
    dispatch.get_by_role('button',name='Подготовить занятие').click()
    form=dispatch.get_by_role('dialog')
    form.get_by_label('Группа и дисциплина').select_option(label='ИТ-24-03 · Алгоритмы и структуры данных')
    form.get_by_label('Преподаватель',exact=True).select_option(label='Михаил Орлов')
    form.get_by_label('Аудитория',exact=True).select_option(label='А-301 · 45 мест')
    day=(date.today()+timedelta(days=30)).isoformat()
    form.get_by_label('Дата',exact=True).fill(day)
    form.get_by_label('Начало',exact=True).fill('19:00')
    form.get_by_label('Окончание',exact=True).fill('20:00')
    form.get_by_label('Комментарий',exact=True).fill('Демонстрационный разбор графа')
    save(dispatch)
    expect(dispatch).to_have_url(re.compile(r'/app/schedule-changes/\d+$'))
    path=dispatch.url.removeprefix(base)
    dispatch.get_by_role('button',name='На согласование').click()
    save(dispatch)
    expect(dispatch.locator('.page-subtitle')).to_contain_text('На согласовании')
    context=dispatch.context.browser.new_context()
    try:
        dean=context.new_page()
        enter(dean,base,2,path)
        dean.get_by_role('button',name='Согласовать',exact=True).click()
        save(dean)
        expect(dean.locator('.page-subtitle')).to_contain_text('Согласован')
    finally:
        context.close()
    context=dispatch.context.browser.new_context()
    try:
        admin=context.new_page()
        enter(admin,base,5,path)
        admin.get_by_role('button',name='Утвердить и опубликовать').click()
        save(admin)
        expect(admin.locator('.page-subtitle')).to_contain_text('Опубликован')
    finally:
        context.close()
    student_context=dispatch.context.browser.new_context(viewport={'width':360,'height':900})
    try:
        student=student_context.new_page()
        enter(student,base,0,'/app/schedule?date='+day)
        expect(student.locator('.lesson-row').filter(has_text='Михаил Орлов')).to_contain_text('19:00')
    finally:
        student_context.close()

    dispatch.goto(base+'/app/tables?dataset=rooms')
    expect(dispatch.get_by_label('Файл CSV или XLSX')).to_be_visible()
    source='Здание;Кабинет;Места;Тип\nДемо-корпус;АТ-302;30;lab\n'.encode('utf-8-sig')
    dispatch.get_by_label('Файл CSV или XLSX').set_input_files({'name':'rooms.csv','mimeType':'text/csv','buffer':source})
    dispatch.get_by_label('Корпус *',exact=True).select_option('Здание')
    dispatch.get_by_label('Код *',exact=True).select_option('Кабинет')
    dispatch.get_by_label('Мест *',exact=True).select_option('Места')
    dispatch.get_by_label('Тип *',exact=True).select_option('Тип')
    dispatch.get_by_role('button',name='Проверить сопоставление').click()
    dispatch.get_by_role('button',name='Подтвердить импорт').click()
    expect(dispatch.get_by_role('heading',name='Журнал моих импортов')).to_be_visible()
    dispatch.goto(base+'/app/registry')
    expect(dispatch.get_by_role('link',name='АТ-302',exact=True)).to_be_visible()
    assert dispatch.evaluate('document.documentElement.scrollWidth <= innerWidth')
