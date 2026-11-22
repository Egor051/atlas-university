"""The operations are exercised through the real cabinet and file picker."""
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
import os
import re
from secrets import token_urlsafe
from uuid import uuid4

import pytest
from PIL import Image
from playwright.sync_api import expect
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.academic_points import award_points
from app.db import CAMPUS_TZ, User, campus_today
from app.schedule_occurrences import campus_instant
from app.university_db import Discipline, Teacher, TeachingAssignment
from app.workspace_db import AcademicTerm, Classroom, GroupMember, ScheduledClass, TeachingLoad
from test_frontend_contracts import frontend_browser, frontend_page, isolated_frontend_server
from test_university_browser import enter

pytestmark=pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS')!='1',reason='Opt-in isolated Chromium')


@pytest.fixture(scope='module')
def frontend_server():
    with isolated_frontend_server({'ATLAS_CERTIFICATE_KEY':token_urlsafe(32)}) as (base,database):
        engine = create_engine('sqlite:///' + database.as_posix())
        with Session(engine) as db, db.begin():
            student = db.scalar(select(User.id).where(User.login=='alina.demo'))
            member = db.get(GroupMember,student)
            teacher,load = db.execute(select(Teacher.id,TeachingLoad.id).select_from(TeachingLoad)
                .join(TeachingAssignment,TeachingAssignment.id==TeachingLoad.assignment_id)
                .join(Teacher).join(User).join(Discipline,Discipline.id==TeachingLoad.discipline_id)
                .where(User.login=='orlov.demo',TeachingLoad.group_id==member.group_id)).one()
            substitute = db.scalar(select(Teacher.id).join(User).where(User.login=='ryabinina.demo'))
            room = db.scalar(select(Classroom.id).where(Classroom.code=='А-301'))
            today = campus_today()
            first, last = today-timedelta(days=40),today+timedelta(days=30)
            db.add(AcademicTerm(academic_year=today.year,number=2,group_id=member.group_id,starts_on=first,
                ends_on=last,weekdays='0123456',periods=[{'kind':'teaching','start':str(first),'end':str(last)}],
                source='Изолированный браузерный тест'))
            teaching_load = db.get(TeachingLoad, load)
            for year, days, points in [(today.year,60,4),(today.year-1,160,9)]:
                first = today-timedelta(days=days)
                last = first+timedelta(days=15)
                db.add(AcademicTerm(academic_year=year,number=1,group_id=member.group_id,starts_on=first,
                    ends_on=last,weekdays='0123456',periods=[],source='Изолированный браузерный тест'))
                award = award_points(db,student_id=student,discipline_id=teaching_load.discipline_id,points=points,
                    actor_id=teaching_load.assignment.teacher.user_id,source_kind='teacher',source_id=f'{load}:test-{year}',
                    title=f'Практикум {year}',kind='practice')
                award.created_at=campus_instant(first)
            for offset, title, kind, actual_teacher in [(3,'Учебная лекция для журнала','lecture',teacher),
                    (8,'Лабораторная работа для справки','lab',teacher),
                    (22,'Практическое занятие для справки','practice',teacher),
                    (1,'Практика с заменой преподавателя','practice',substitute)]:
                start = datetime.combine(today-timedelta(days=offset),time(7),CAMPUS_TZ).astimezone(timezone.utc)
                db.add(ScheduledClass(load_id=load,group_id=member.group_id,teacher_id=actual_teacher,room_id=room,
                    starts_at=start,ends_at=start+timedelta(hours=1),kind=kind,title=title,note=title,series=uuid4().hex))
        engine.dispose()
        yield base


def save(page):
    page.get_by_role('dialog').get_by_role('button',name='Сохранить',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)


def test_teacher_marks_and_attendance_in_browser(frontend_page):
    teacher,base=frontend_page
    teacher.set_viewport_size({'width':360,'height':900})
    enter(teacher,base,3,'/app/teaching')
    teacher.get_by_role('link',name='Алгоритмы и структуры данных').click()
    teacher.get_by_role('link',name='Ведомость',exact=True).click()
    before=teacher.locator('.op-row').inner_text()
    total=int(re.search(r'Накопленные баллы: (\d+)',before).group(1))+3
    teacher.get_by_role('button',name='Начислить баллы').click()
    teacher.get_by_label('Сколько баллов добавить').fill('3')
    teacher.get_by_label('Максимум за работу (необязательно)').fill('5')
    teacher.get_by_label('Вид деятельности').select_option('project')
    teacher.get_by_label('Название работы или занятия (необязательно)').fill('Учебный проект')
    teacher.get_by_label('Основание начисления').fill('Проверен граф.')
    save(teacher)
    expect(teacher.locator('.op-row')).to_contain_text(f'Накопленные баллы: {total}')
    teacher.get_by_role('button',name='История баллов').click()
    expect(teacher.get_by_role('dialog')).to_contain_text('Проверен граф.')
    teacher.get_by_role('button',name='Скорректировать начисление').first.click()
    teacher.get_by_label('Исправленные баллы').fill('2')
    teacher.get_by_label('Причина корректировки').fill('Уточнение по критерию.')
    save(teacher)
    expect(teacher.locator('.op-row')).to_contain_text(f'Накопленные баллы: {total-1}')
    teacher.get_by_role('link',name='Посещаемость',exact=True).click()
    session = teacher.get_by_label('Занятие',exact=True)
    target = session.locator('option').filter(has_text='Учебная лекция для журнала').get_attribute('value')
    session.select_option(target)
    teacher.get_by_role('button',name='Открыть',exact=True).click()
    teacher.get_by_role('button',name='Поставить отметку').click()
    teacher.get_by_label('Отметка',exact=True).select_option('present')
    save(teacher)
    expect(teacher.locator('.op-row')).to_contain_text('Присутствовал')
    teacher.get_by_role('link',name='Отчёт и история',exact=True).click()
    expect(teacher.locator('.op-log')).to_contain_text('Михаил Орлов')
    expect(teacher.locator('.op-log')).to_contain_text(f'→ {total}')
    expect(teacher.locator('.op-log')).to_contain_text('Уточнение по критерию.')
    assert teacher.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width',[360,390,1440])
def test_student_combined_table_and_session(frontend_page,width):
    page, base = frontend_page
    page.set_viewport_size({'width':width,'height':880})
    enter(page, base, 0, '/app/records/attendance')
    expect(page).to_have_url(base + '/app/grades')
    title = page.get_by_role('heading', name='Успеваемость и посещаемость', exact=True)
    expect(title).to_be_visible()
    summary = page.get_by_role('table',name='Семестровая успеваемость')
    expect(summary).to_be_visible()
    assert page.get_by_role('table').count()==3
    assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
    points_panel = page.locator('[data-type="points"]')
    points = points_panel.get_by_role('table')
    page.get_by_label('Учебный год').select_option(label='Без семестра')
    points_panel.get_by_label('Дисциплина',exact=True).select_option(label='Алгоритмы и структуры данных')
    expect(points).to_contain_text('Перенесённый остаток')
    sort = points.get_by_role('button',name='Баллы',exact=True)
    sort.press('Enter')
    expect(sort.locator('..')).to_have_attribute('aria-sort','ascending')
    sort.press('Enter')
    expect(sort.locator('..')).to_have_attribute('aria-sort','descending')
    page.get_by_role('link',name='К посещаемости').click()
    expect(page.get_by_role('heading',name='Посещаемость занятий')).to_be_focused()
    attendance = page.locator('[data-type="attendance"]')
    attendance.get_by_label('Вид занятия',exact=True).select_option('lab')
    expect(attendance.get_by_role('table')).to_contain_text('Лабораторная работа для справки')
    expect(attendance.get_by_role('table')).to_contain_text('Статус не выставлен')
    attendance.get_by_label('Группировка').select_option('kind')
    expect(attendance.locator('.academic-group').first).to_contain_text('Проведено')
    page.goto(base+'/app/exams')
    expect(page.locator('[data-assessment-status]').first).to_be_visible()
    expect(page.get_by_text('В плане', exact=True)).to_have_count(0)
    expect(page.get_by_text('Нужно внимание', exact=True)).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth === innerWidth')


def test_semester_switch_and_live_award_keep_details(frontend_page):
    student,base = frontend_page
    student.set_viewport_size({'width':360,'height':900})
    student.clock.install()
    enter(student,base,0,'/app/grades')
    summary = student.get_by_role('table',name='Семестровая успеваемость')
    subject = summary.get_by_role('button',name='Алгоритмы и структуры данных')
    earned = subject.locator('xpath=ancestor::tr').locator('.academic-earned')
    history = student.get_by_role('table',name='История начислений')
    year = campus_today().year
    student.get_by_label('Семестр',exact=True).select_option(f'{year}-1')
    expect(earned).to_have_text('4')
    expect(history).to_contain_text(f'Практикум {year}')
    student.get_by_label('Учебный год').select_option(str(year-1))
    expect(earned).to_have_text('9')
    expect(history).to_contain_text(f'Практикум {year-1}')
    student.get_by_label('Учебный год').select_option(str(year))
    expect(student.get_by_label('Семестр',exact=True)).to_have_value(f'{year}-2')
    before = int(earned.inner_text())
    subject.press('Enter')
    expect(subject).to_have_attribute('aria-expanded','true')

    with student.context.browser.new_context() as teacher_context:
        teacher = teacher_context.new_page()
        enter(teacher,base,3,'/app/teaching')
        load = teacher.request.get(base+'/api/teaching').json()['items'][0]
        roster = f"{base}/api/teaching/{load['id']}"
        student_id = student.request.get(base+'/api/me').json()['id']
        grade = next(person['grade'] for person in teacher.request.get(roster).json()['students'] if person['id']==student_id)
        reply = teacher.request.post(roster+'/points',headers={'Origin':base,'X-Requested-With':'ATLAS'},
            data={'student_id':student_id,'points':5,'version':grade['version'],'kind':'project',
                  'title':'Курсовой макет','reason':'Учтён результат проекта'})
        assert reply.status==201, reply.text()

    student.clock.fast_forward(21000)
    expect(earned).to_have_text(str(before+5))
    expect(subject).to_have_attribute('aria-expanded','true')
    expect(subject).to_be_focused()
    details = student.locator('#'+subject.get_attribute('aria-controls'))
    expect(details.get_by_role('heading',name='Динамика начислений')).to_be_visible()
    details.get_by_role('link',name='К истории дисциплины').click()
    expect(student.get_by_role('heading',name='История начислений')).to_be_focused()
    expect(history).to_contain_text('Курсовой макет')
    assert student.evaluate('document.documentElement.scrollWidth === innerWidth')


def test_substitute_teacher_marks_actual_class_from_schedule(frontend_page):
    teacher,base = frontend_page
    teacher.set_viewport_size({'width':390,'height':900})
    previous = campus_today()-timedelta(days=1)
    enter(teacher,base,8,'/app/teach-schedule?week='+str(previous))
    session = teacher.locator('.op-row').filter(has_text='Практика с заменой преподавателя')
    session.get_by_role('button',name='Журнал посещаемости').click()
    journal = teacher.get_by_role('dialog',name='Журнал посещаемости')
    journal.get_by_role('button',name='Поставить отметку').click()
    teacher.get_by_label('Отметка',exact=True).select_option('absent')
    teacher.get_by_role('dialog',name='Посещаемость',exact=True).get_by_role('button',name='Сохранить').click()
    expect(journal).to_contain_text('Отсутствовал')
    assert teacher.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_absence_certificate_multiselect_review_and_decisions(frontend_page):
    student, base = frontend_page
    teacher_context = student.context.browser.new_context(viewport={'width':390,'height':900},locale='ru-RU')
    try:
        teacher = teacher_context.new_page()
        enter(teacher,base,3,'/app/teaching')
        load = teacher.request.get(base+'/api/teaching').json()['items'][0]
        journal = f"{base}/api/teaching/{load['id']}"
        sessions = teacher.request.get(journal).json()['sessions']
        for session in (row for row in sessions if row['topic'].endswith('для справки')):
            person = teacher.request.get(journal,params={'class_id':session['id']}).json()['students'][0]
            reply = teacher.request.put(journal+'/attendance',headers={'Origin':base,'X-Requested-With':'ATLAS'},
                data={'class_id':session['id'],'day':session['day'],'student_id':person['id'],
                      'status':'absent','version':person['attendance']['version']})
            assert reply.ok,reply.text()

        student.set_viewport_size({'width':360,'height':880})
        enter(student,base,0,'/app/grades?kind=attendance')
        table = student.get_by_role('table',name='Посещаемость занятий')
        lab = table.get_by_role('row').filter(has_text='Лабораторная работа для справки')
        practice = table.get_by_role('row').filter(has_text='Практическое занятие для справки')
        lab.get_by_role('button',name='Отправить справку').click()
        upload = student.get_by_role('dialog',name='Отправить справку')
        upload.get_by_role('checkbox',name=re.compile('Практическое занятие · Михаил Орлов')).check()
        document = BytesIO()
        Image.new('RGB',(32,32),'white').save(document,'PNG')
        upload.get_by_label('Справка',exact=True).set_input_files({'name':'test.png','mimeType':'image/png','buffer':document.getvalue()})
        upload.get_by_label('Пояснение (необязательно)').fill('Вымышленный документ для приёмки.')
        upload.get_by_role('button',name='Отправить справку').click()
        expect(upload).to_have_count(0)
        expect(lab).to_contain_text('На рассмотрении')
        expect(practice).to_contain_text('На рассмотрении')

        teacher.goto(base+'/app/notifications')
        notice = teacher.locator('.notification-full').filter(has_text='справк').first
        notice.get_by_role('button',name='Открыть').click()
        expect(teacher.get_by_role('heading',name='Справки о пропусках',exact=True)).to_be_visible()
        case = teacher.get_by_role('table').get_by_role('row').filter(has_text='Вымышленный документ')
        case.get_by_role('button',name='Рассмотреть справку').click()
        decision = teacher.get_by_role('dialog',name='Рассмотреть справку')
        with teacher.expect_download() as downloaded:
            decision.get_by_role('button',name='Скачать справку').click()
        assert downloaded.value.path().read_bytes().startswith(b'%PDF-')
        decision.get_by_role('checkbox',name=re.compile('Практическое занятие')).uncheck()
        decision.get_by_label('Решение',exact=True).select_option('accepted')
        decision.get_by_role('button',name='Сохранить решение').click()
        expect(case).to_contain_text('Принята')
        case.get_by_role('button',name='Рассмотреть справку').click()
        decision.get_by_label('Решение',exact=True).select_option('rejected')
        decision.get_by_label('Причина отклонения (необязательно)').fill('Документ относится только к первой дате.')
        decision.get_by_role('button',name='Сохранить решение').click()
        expect(case).to_contain_text('Отклонена')

        student.reload()
        expect(lab).to_contain_text('Уважительный пропуск')
        expect(practice).to_contain_text('Отсутствовал')
        practice.get_by_role('button',name='Решение по справке').click()
        result = student.get_by_role('dialog',name='Решение по справке')
        expect(result).to_contain_text('Документ относится только к первой дате.')
        for page in (student,teacher):
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        teacher_context.close()


def test_teacher_reads_student_submission_and_returns_feedback(frontend_page):
    teacher,base=frontend_page
    teacher.set_viewport_size({'width':390,'height':900})
    enter(teacher,base,3,'/app/teaching')
    teacher.get_by_role('link',name='Алгоритмы и структуры данных').click()
    teacher.get_by_role('link',name='Сдача работ',exact=True).click()
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
        expect(form).to_be_visible()
        answer='Все вершины графа доступны из вершины А.'
        form.get_by_label('Текст ответа',exact=True).fill(answer)
        assignment_id=assignment.get_attribute('data-campus-record-id')
        form.get_by_role('button',name='Отправить работу').click()
        expect(student.get_by_role('dialog')).to_have_count(0)

        teacher.goto(work_url)
        expect(teacher.get_by_text(answer,exact=True)).to_be_visible()
        teacher.get_by_role('button',name='Дать обратную связь').press('Enter')
        reply='Добавьте пример графа из двух компонент.'
        teacher.get_by_label('Комментарий студенту').fill(reply)
        save(teacher)
        expect(teacher.get_by_text(reply,exact=True)).to_be_visible()

        student.goto(base+'/app/notifications')
        notice=student.locator('.notification-full').filter(has_text='Преподаватель проверил работу')
        notice.get_by_role('button',name='Открыть').click()
        expect(student.get_by_role('dialog',name=title)).to_be_visible()
        assert student.url.endswith('/app/assignments?id='+assignment_id)
        student.get_by_text('Обратная связь преподавателя',exact=True).click()
        expect(student.get_by_text(reply,exact=True)).to_be_visible()
        expect(student.get_by_text('Комментарий · Михаил Орлов · версия 1',exact=True)).to_be_visible()
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
    form.get_by_label('Основание для занятия вне учебного периода').fill('Разовое занятие изолированной приёмки')
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
        expect(student.locator('.schedule-event').filter(has_text='Михаил Орлов')).to_contain_text('19:00')
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
