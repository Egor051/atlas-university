"""Connected union stories and clearly attributed VUC examples."""
from datetime import date, timedelta

from sqlalchemy import select

from ..units_db import (CenterEnrollment, CenterGroup, CenterProgram, CenterSession, UnionMembership,
                        UnitCase, UnitCaseEvent, UnitPublication)
from ..vuc_db import VucApplication, VucApplicationEvent, VucCampaign, VucProgram, program_data
from .seed import autumn


VSU_NOTICE = 'https://mil.vsu.ru/2026/09/11/для-студентов-2-го-курса-вгу-желающим-о/'
URFU_ORDER = ('https://vuc.urfu.ru/fileadmin/user_upload/site_15426/dokumenty_kursantam/dokumenty_na_leitenanta_zapasa/'
              'Prikaz_po_osnovnoi_dejatelnosti_No0731_03_ot_31.08.2026__Ob_organizacii_otbora_grazhdan_dlja_obuchen_v3_.pdf')


def unit_case(semester, unit, student, operator, kind, at, message, steps, *, program=None, publication=None):
    row = semester.add(UnitCase, unit=unit, student_id=student.id, kind=kind, status='submitted',
                       message=message, program=program, publication=publication, created_at=at, updated_at=at)
    semester.db.add(UnitCaseEvent(case_id=row.id, actor_id=student.id, action='submitted', status='submitted',
                                  message=message, created_at=at))
    for index, (status, answer) in enumerate(steps, 1):
        stamp = at + timedelta(hours=3 * index)
        followup = status == 'followup'
        if not followup:
            row.status, row.response = status, answer
        row.version, row.updated_at = index + 1, stamp
        semester.db.add(UnitCaseEvent(case_id=row.id, actor_id=student.id if followup else operator.id,
                                      action='followup' if followup else 'status', status=row.status,
                                      message=answer, created_at=stamp))
    if steps:
        semester.notify(student, 'Подразделение ответило на обращение', row.response, unit, f'/app/{unit}/{row.id}',
                        row.updated_at, key=f'contest:unit:{row.id}', read=row.updated_at.date() < date(2026, 11, 17))
    return row


def seed_union(semester, students, operator):
    alina, mark = students
    event = None
    for kind, stamp, title, body, day, seats in (
        ('structure', autumn(9, 3), 'Представители студенческого профсоюза',
         'Полина Савельева ведёт членство. Команда мероприятий принимает записи и помогает собрать предложения групп.', None, None),
        ('document', autumn(9, 7), 'Порядок оформления членства',
         'Подтвердите своё решение в заявлении. После рассмотрения в кабинете появятся ответ и история.', None, None),
        ('benefit', autumn(10, 8), 'Поддержка расходных материалов для практикумов',
         'К заявлению приложите описание учебной задачи и перечислите расходы по видам. Условия уточняет представитель.', None, None),
        ('event', autumn(10, 12), 'Обмен учебными книгами',
         'Студенты обмениваются практикумами и справочниками. Место встречи — холл корпуса А.', date(2026, 10, 17), 18),
        ('news', autumn(11, 18), 'Собираем предложения для зимних мастерских',
         'На открытой встрече группы обсудят темы практикумов и дни, когда занятия не пересекаются.', None, None),
        ('event', autumn(11, 20), 'Встреча с представителями учебных групп',
         'Обсудим расписание мастерских и помощь новым участникам. Студенческий центр, зал 2.', date(2026, 12, 2), 20),
    ):
        post = semester.add(UnitPublication, unit='union', kind=kind, author_id=operator.id, title=title, body=body,
                            event_day=day, capacity=seats, updated_at=stamp, published=True)
        semester.event(operator, 'union', post.id, 'publication', stamp, after={'title': title, 'published': True})
        if day == date(2026, 12, 2):
            event = post
    for student, stamp in ((alina, autumn(9, 10, '09:00')), (mark, autumn(10, 5, '10:00'))):
        membership = unit_case(semester, 'union', student, operator, 'join', stamp,
                               'Подтверждаю заявление о вступлении в студенческий профсоюз.',
                               [('review', 'Сведения о группе сверены.'), ('accepted', 'Членство оформлено.')])
        semester.db.add(UnionMembership(student_id=student.id, active=True, case_id=membership.id,
                                        updated_at=membership.updated_at))
    unit_case(semester, 'union', alina, operator, 'event', autumn(11, 21, '09:00'), 'Хочу предложить тему мастерской по графам.',
              [('review', 'Проверяем наличие мест.'), ('accepted', 'Участие подтверждено, встреча в зале 2.')], publication=event)
    unit_case(semester, 'union', alina, operator, 'aid', autumn(11, 19, '09:00'),
              'В октябре купила расходные материалы для практикума по проектированию.',
              [('review', 'Уточняем вид расходов.'), ('needs_info', 'Сообщите, к какой работе относятся материалы.'),
               ('followup', 'Материалы нужны для прототипа формы обращения.')])
    unit_case(semester, 'union', mark, operator, 'consult', autumn(11, 17, '10:00'),
              'Где обсудить вопрос об оплате проживания?',
              [('review', 'Уточняем, кто ведёт расчёты.'), ('resolved', 'Вопрос рассмотрит учебный офис через раздел «Заявки».')])
    unit_case(semester, 'union', mark, operator, 'appeal', autumn(11, 21, '11:00'),
              'Предлагаю проводить разборы по проектам после сдачи лабораторных работ.', [])


def seed_admission(semester, students, operator):
    programs = {row.category: row for row in semester.db.scalars(select(VucProgram).order_by(VucProgram.id))}
    for program in programs.values():
        semester.add(VucCampaign, program=program, academic_year=2026, title='Следующий набор · сроки уточняются',
                     state='published', intake_enabled=True, documents=[], stages={},
                     requirements='Условия конкретного набора будут опубликованы организатором отбора.',
                     procedure='Проверьте карточку программы. Порядок подачи появится после утверждения кампании.',
                     source_title=program.source_title, source_url=program.source_url, verified_on=program.verified_on,
                     program_snapshot=program_data(program))
    sample = semester.add(
        VucCampaign, program=programs['officer_reserve'], academic_year=2026, title='Учебная история отбора · осень 2026',
        state='archived', opens_on=date(2026, 9, 14), closes_on=date(2026, 9, 30), intake_enabled=False,
        documents=['Заявление о прохождении отбора'],
        procedure='Архив синтетической кампании АТЛАС. Интервал взят из объявления ВГУ от 11 сентября 2026 года.',
        requirements='Хронология показывает работу кабинета. Состав документов и условия реального набора проверяются отдельно.',
        stages={}, source_title='ВГУ · пример опубликованного интервала приёма, 11.09.2026',
        source_url=VSU_NOTICE, verified_on=date(2026, 11, 22),
        program_snapshot=program_data(programs['officer_reserve']))
    semester.add(VucCampaign, program=programs['soldier_reserve'], academic_year=2026,
                 title='УрФУ · справочный пример этапов отбора', state='published', intake_enabled=False,
                 documents=[], procedure='Справочная карточка. АТЛАС не ведёт приём по приказу УрФУ.',
                 requirements='Даты приведены для объяснения этапов кампании в опубликованном примере.',
                 stages={'physical': {'starts_on': '2026-11-23', 'ends_on': '2026-11-27'},
                         'formalities': {'ends_on': '2027-01-15'}}, source_title='УрФУ · приказ № 0731/03 от 31.08.2026',
                 source_url=URFU_ORDER, verified_on=date(2026, 11, 22),
                 program_snapshot=program_data(programs['soldier_reserve']))
    full_path = (
        ((9, 16), 'documents_received', 'Принят комплект документов по учебному сценарию.', 'АТЛАС-ОБР-026'),
        ((9, 21), 'preliminary', 'Ожидается отметка о завершении предварительного отбора.', ''),
        ((10, 5), 'admitted', 'Запись о допуске внесена по учебному решению.', 'АТЛАС-ДОП-026'),
        ((10, 19), 'selection_complete', 'Конкурсные мероприятия в учебной истории завершены.', 'АТЛАС-КОНК-026'),
        ((10, 26), 'recommended', 'В учебном журнале внесена рекомендация комиссии.', 'АТЛАС-ПРОТ-026'),
        ((11, 3), 'enrolled', 'Учебный допуск отражён в карточке кандидата.', 'АТЛАС-ПРИК-026'),
    )
    needs_documents = (
        ((9, 18), 'documents_received', 'В учебном журнале зарегистрирован комплект.', 'АТЛАС-ОБР-031'),
        ((9, 22), 'needs_documents', 'Запрошено уточнение сведений об основной программе.', ''),
    )
    for student, start, steps in ((students[0], autumn(9, 15), full_path), (students[1], autumn(9, 17), needs_documents)):
        message = 'Обращение зарегистрировано. Порядок подачи указан в карточке кампании.'
        application = semester.add(VucApplication, student_id=student.id, campaign=sample, status='inquiry',
                                   next_action=message, created_at=start, updated_at=start)
        semester.db.add(VucApplicationEvent(application_id=application.id, actor_id=student.id, status='inquiry',
                                             action='submitted', message=message, created_at=start))
        for number, (day, status, notice, basis) in enumerate(steps, 1):
            at = autumn(*day)
            application.status, application.updated_at, application.next_action = status, at, notice
            application.version = number + 1
            semester.db.add(VucApplicationEvent(application_id=application.id, actor_id=operator.id, status=status,
                                                 action='status', message=notice, basis_ref=basis,
                                                 basis_on=date(2026, *day) if basis else None,
                                                 contract_ref='АТЛАС-ДОГ-026' if status == 'enrolled' else '', created_at=at))
        semester.notify(student, 'Результат рассмотрения ВУЦ', application.next_action, 'vuc',
                        f'/app/vuc/admission/{application.id}', application.updated_at,
                        key=f'contest:vuc-admission:{application.id}', read=True)


def seed_units(semester, students, accounts):
    operator = accounts['vuc.demo']
    seed_union(semester, students, accounts['union.demo'])
    seed_admission(semester, students, operator)
    for kind, stamp, title, body in (
        ('structure', autumn(9, 3), 'Учебный офис военного центра', 'По вопросам программ и кампаний используйте консультацию.'),
        ('document', autumn(11, 12), 'Как читать этапы кампании',
         'Сроки и основание опубликованного этапа приведены в карточке. Для учебного архива записи подписаны отдельно.'),
        ('news', autumn(11, 20), 'Обновлены справочные материалы о приёме',
         'Условия программы и даты конкретного набора можно сверить на вкладке «Приём».'),
        ('material', autumn(11, 18), 'Памятка об учебном календаре центра',
         'Участникам доступно расписание своей учебной группы. Переносы и отмены отображаются в календаре.'),
    ):
        semester.add(UnitPublication, unit='vuc', kind=kind, title=title, body=body, author_id=operator.id, updated_at=stamp)
    unit_case(semester, 'vuc', students[1], operator, 'consult', autumn(11, 20, '10:00'),
              'Где проверить, опубликованы ли сроки следующего набора?',
              [('review', 'Проверяем публикации.'), ('resolved', 'Следите за карточкой кампании. Точные даты пока не опубликованы.')])

    archive = semester.add(CenterProgram, title='Учебная группа центра · архив 2026',
                           description='Организационные встречи учебной группы в синтетической истории АТЛАС.',
                           requirements='Архив учебной группы. Сведения о наборе доступны отдельно.',
                           opens=date(2026, 9, 14), closes=date(2026, 9, 30), published=False)
    group = semester.add(CenterGroup, program=archive, code='ВУЦ-26-01', capacity=16)
    case = unit_case(semester, 'vuc', students[0], operator, 'apply', autumn(11, 4, '09:00'),
                     'Архивная запись о распределении в учебную группу.',
                     [('review', 'Комплект принят на рассмотрение.'), ('selection', 'Подготовлена запись учебного распределения.'),
                      ('accepted', 'Подтверждено участие в учебной истории.')], program=archive)
    semester.db.add(CenterEnrollment(student_id=students[0].id, program=archive, group=group, case_id=case.id,
                                     outcome='pending', comment='Встречи учебной группы продолжаются.'))
    for month, day, title, cancelled in (
        (11, 7, 'Организационная встреча группы', False),
        (11, 14, 'Сверка учебного календаря', False),
        (11, 21, 'Встреча по организации консультаций', True),
        (11, 28, 'Обсуждение календаря на декабрь', False),
        (12, 5, 'Организационная встреча перед аттестацией', False),
    ):
        start = autumn(month, day, '12:00')
        semester.db.add(CenterSession(group=group, title=title, room='Учебный офис ВУЦ', starts_at=start,
                                      ends_at=start + timedelta(minutes=50), cancelled=cancelled))
