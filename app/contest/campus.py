"""Office records and campus services for the synthetic autumn semester."""
from datetime import date, timedelta
from io import BytesIO
from secrets import token_urlsafe

from sqlalchemy import select

from ..absence_certificate_db import (AbsenceCertificate, AbsenceCertificateAudit, AbsenceCertificateFile,
                                       AbsenceCertificateNote, AbsenceCertificateReview)
from ..announcements_db import Announcement, PUBLICATIONS
from ..campus_db import PortfolioItem
from ..certificate_catalog import APPENDIX_4, COMMISSIONER_OPTIONS
from ..certificates import CertificateIssue, ENROLLMENT_LABELS, ENROLLMENT_SEED, seed_certificate_enrollment
from ..db import CAMPUS_TZ, DOC_NAMES, DocumentRequest, RequestEvent, User, password_hasher, request_due_date, request_kind
from ..improvement_db import PersonalDraft
from ..learning_db import (Attendance, Flashcard, FocusSession, PersonalTask, Quiz, QuizAttempt, StudyNote)
from ..medical_storage import certificate_key, encrypt
from ..schedule_calendar import KIND
from ..schedule_occurrences import local_interval
from ..services_db import (CampusEvent, ConsultationBooking, ConsultationSlot, EventRegistration, FinanceEntry,
                           LibraryBook, LibraryLoan, StudentPreference, SupportTicket, TicketMessage)
from ..session_security import as_utc
from ..university_db import DirectAttachment, DirectDialog, DirectMessage, MaterialDelegation, Teacher
from ..workspace_db import ScheduledClass, TableImport, TeacherConsultation
from .seed import HISTORY_THROUGH, autumn, json_data, token


def document(semester, student, office, code, at, purpose, steps, details=None):
    name = DOC_NAMES[code]
    target = '/app/certificates' if request_kind(name) == 'certificate' else '/app/requests'
    row = semester.add(DocumentRequest, student_id=student.id, type=name, comment=purpose, status='submitted',
                       details=json_data(details or {}), created_at=at, updated_at=at,
                       due_at=request_due_date(name, at.astimezone(CAMPUS_TZ).date()))
    semester.db.add(RequestEvent(request_id=row.id, status='submitted', message=purpose, actor_role='student',
                                 actor_name=student.full_name, created_at=at))
    for number, (status, message) in enumerate(steps, 1):
        stamp = at + timedelta(hours=number * 2)
        actor = student if status == 'followup' else office
        if status != 'followup':
            row.status, row.staff_message = status, message
        row.updated_at, row.version = stamp, number + 1
        semester.db.add(RequestEvent(request_id=row.id, status=row.status, message=message, actor_role=actor.role,
                                     actor_name=actor.full_name, created_at=stamp))
        if actor == office:
            semester.notify(student, 'Учебный офис обновил заявку', message, 'request', f'{target}?id={row.id}', stamp,
                            key=f'contest:request:{row.id}:{number}', read=stamp.date() < date(2026, 11, 17), request_id=row.id)
    return row


def seed_documents(semester, students, office):
    alina, mark = students
    seed_certificate_enrollment(semester.db)
    document(semester, alina, office, 'study', autumn(9, 8, '09:10'),
             'Нужна справка об обучении для оформления доступа в городской архив.',
             [('review', 'Сведения об обучении сверены.'), ('ready', 'Справка доступна для скачивания.')],
             {'purpose': 'Доступ в городской архив', 'copies': '1'})
    document(semester, alina, office, 'elective', autumn(10, 6, '09:15'),
             'Хочу записаться на факультатив по доступности интерфейсов.',
             [('review', 'Проверяем совместимость с расписанием.'), ('processing', 'Запрос согласован с кафедрой.'),
              ('ready', 'Место в группе подтверждено. Встречи проходят после основной учебной недели.')])
    document(semester, alina, office, 'practice', autumn(11, 17, '09:30'),
             'Прошу согласовать практику в проектной мастерской института на весенний период.',
             [('review', 'Проверяем сроки и программу мастерской.'), ('processing', 'Направление согласуется на кафедре.')])
    document(semester, alina, office, 'social_support', autumn(11, 20, '10:20'),
             'Прошу рассмотреть компенсацию расходов на обязательные материалы для практикума.',
             [('needs_info', 'Уточните наименование практикума и период приобретения материалов.'),
              ('followup', 'Уточнение студента: материалы для проектного практикума были приобретены в октябре.')])
    document(semester, mark, office, 'transcript', autumn(10, 13, '09:45'),
             'Выписка за прошедший учебный год нужна для учебного проекта.',
             [('review', 'Проверяем учебную карточку.'), ('ready', 'Выписка за завершённый учебный год подготовлена.')],
             {'period': '2025/2026', 'format': 'HTML'})
    issued = document(semester, mark, office, APPENDIX_4, autumn(9, 29, '09:40'),
                      'Подтверждение формы обучения.',
                      [('review', 'Учебная запись и назначение справки проверены.'), ('ready', 'Справка подготовлена по реестру.')],
                      {'commissioner': 'north'})
    enrollment = {key: ENROLLMENT_SEED[key] for key in ENROLLMENT_LABELS if key != 'course'}
    enrollment.update(course=str(mark.course), graduation_date='30.06.2027', commissioner=COMMISSIONER_OPTIONS['north'])
    semester.db.add(CertificateIssue(request_id=issued.id, prepared_by=office.id, prepared_at=issued.updated_at, data=enrollment))
    document(semester, mark, office, 'student_card', autumn(10, 21, '10:10'),
             'Требуется восстановить доступ по студенческому билету.',
             [('review', 'Уточняем характер проблемы.'), ('followup', 'Просьба об отзыве: оригинал найден, замена не нужна.'),
              ('rejected', 'Обращение закрыто по просьбе студента.')])
    document(semester, mark, office, 'retake', autumn(11, 21, '11:30'),
             'Прошу подтвердить время повторного зачёта по управлению проектами.', [],
             {'subject': 'Управление проектами', 'preferred_date': '2026-12-08'})
    document(semester, mark, office, 'tuition', autumn(11, 19, '11:30'),
             'Прошу сверить запись хозяйственного платежа за осенний семестр.',
             [('review', 'Запись передана на сверку в расчётный отдел.')])
    semester.db.add(PersonalDraft(user_id=alina.id, name='request', updated_at=autumn(11, 21),
                                 values_json=json_data({'type': 'mobility', 'comment': 'Уточнить сроки подачи учебного плана.'})))
    semester.db.add(PersonalDraft(user_id=mark.id, name='certificate-order', updated_at=autumn(11, 20),
                                 values_json=json_data({'type': 'scholarship', 'comment': 'Сведения за октябрь и ноябрь.'})))


def seed_publications(semester, cohorts, office):
    everyone = list(semester.db.scalars(select(User).order_by(User.id)))
    posts = [
        (autumn(9, 2), 'all', None, 'archived', 'announcement', 'normal', False, 'Подключение к учебным кабинетам',
         'Расписание на первую неделю и контакты преподавателей опубликованы.',
         'Откройте раздел «Расписание» и проверьте свою учебную группу. Курс и программу можно сверить в профиле.'),
        (autumn(10, 6), 'employees', None, 'published', 'academic', 'normal', False, 'Сверка нагрузок на октябрь',
         'Сверьте назначения и отметки в ведомостях.',
         'Согласованные изменения расписания публикуются диспетчером и видны студентам в календаре.'),
        (autumn(11, 20), 'group', cohorts[0].group, 'published', 'academic', 'important', True,
         'Практикум 25 ноября пройдёт в аудитории А-115',
         'Группа ИТ-24-03. Начало практикума в 10:40, время остаётся прежним.',
         'Для разбора графовых задач выделена аудитория с компьютерами на первом этаже. Откройте занятие в расписании.'),
        (autumn(11, 21), 'students', None, 'draft', 'campus', 'normal', False,
         'Зимняя встреча студенческих кружков', 'Программа встречи согласуется.',
         'Место и время будут добавлены после подтверждения площадки.'),
    ]
    dates = ((9, 14), (11, 19), (9, 23), (11, 12), (10, 13), (10, 27))
    for (title, category, priority, summary, body), day in zip(PUBLICATIONS.values(), dates):
        posts.append((autumn(*day), 'all', None, 'published', category, priority, False, title, summary, body))
    for posted, audience, group, state, category, priority, pinned, title, summary, body in sorted(posts):
        published = state != 'draft'
        archived = autumn(9, 30) if state == 'archived' else posted
        row = semester.add(Announcement, author_id=office.id, group=group, title=title, summary=summary, body=body,
                           audience=audience, status=state, category=category, priority=priority, pinned=pinned,
                           created_at=posted, updated_at=archived, published_at=posted if published else None,
                           version=2 if state == 'archived' else 1)
        semester.event(office, 'announcement', row.id, 'published' if published else 'created', posted,
                       after={'title': title, 'status': 'published' if published else 'draft'})
        if state == 'archived':
            semester.event(office, 'announcement', row.id, 'archived', archived, after={'title': title, 'status': state})
        if published:
            recipients = next(cohort.students for cohort in cohorts if cohort.group == group) if group else everyone
            for user in recipients:
                if (audience == 'employees' and user.role == 'student') or (audience == 'students' and user.role != 'student'):
                    continue
                semester.notify(user, title, summary, 'announcement', f'/app/announcements/{row.id}', posted,
                                key=f'contest:announcement:{row.id}:{user.id}', read=posted.date() < date(2026, 11, 17))


def seed_conversations(semester, cohorts, students, office):
    alina, mark = students
    for student, contact, at, question, answer, is_read in (
        (alina, cohorts[0].loads[0].assignment.teacher.user, autumn(10, 21, '13:20'),
         'В обходе графа можно отметить корпус сразу после добавления в очередь?',
         'Да. Приложите вывод для карты с циклом и отдельно покажите восстановление маршрута.', True),
        (alina, office, autumn(11, 20, '10:00'),
         'Могу уточнить период расходов в уже открытом обращении?',
         'Откройте историю обращения о поддержке, затем добавьте уточнение к той же записи.', False),
        (mark, cohorts[1].loads[0].assignment.teacher.user, autumn(11, 20, '15:00'),
         'У двух моделей одинаковая точность. Как показать различия в работе?',
         'Сравните число ложных тревог и пропусков. Возьмите данные из замечания к ноябрьской работе.', False),
        (mark, office, autumn(9, 28, '10:20'),
         'Какой вариант справки соответствует приложению № 4?',
         'Выберите отдельную справку об очном обучении. Порядок заполнения указан на карточке услуги.', True),
    ):
        reply = at + timedelta(hours=3)
        dialog = semester.add(DirectDialog, student_id=student.id, contact_id=contact.id, updated_at=reply)
        semester.db.add(DirectMessage(dialog_id=dialog.id, sender_id=student.id, body=question, created_at=at,
                                      read_at=at + timedelta(hours=2)))
        notice = semester.notify(student, 'Ответ в личной переписке', answer, 'direct', f'/app/direct/{dialog.id}',
                                 reply, key=f'contest:direct:{dialog.id}', read=is_read)
        message = semester.add(DirectMessage, dialog_id=dialog.id, sender_id=contact.id, body=answer,
                               created_at=reply, read_at=reply + timedelta(minutes=30) if is_read else None,
                               notification_id=notice.id)
        if contact.role == 'teacher':
            content = f'# Вопрос к практикуму\n\n{question}\n\n## Ответ\n\n{answer}\n'.encode()
            semester.db.add(DirectAttachment(message_id=message.id, name='разбор.md', content=content, size=len(content)))

    for student, topic, stamp, title, question, response, closed in (
        (alina, 'technical', autumn(9, 9, '10:00'), 'Календарь в телефоне показывает другой часовой пояс',
         'После импорта расписания на телефоне встреча началась на час раньше.',
         'Проверьте часовой пояс устройства и повторно импортируйте календарь с московским временем.', True),
        (alina, 'academic', autumn(11, 20, '13:00'), 'Место на консультации по графам',
         'Подскажите, можно ли принести на разбор схему маршрута между корпусами.',
         'Запишитесь на консультацию по алгоритмам. Схему можно приложить к диалогу с преподавателем.', False),
        (mark, 'financial', autumn(11, 18, '10:00'), 'Сверка платежа за проживание',
         'Хочу сверить назначение октябрьской записи в финансовой выписке.',
         'Для сверки откройте заявку об оплате. Номер банковской карты прикладывать не нужно.', False),
        (mark, 'academic', autumn(10, 2, '11:00'), 'Тема выступления на семинаре по данным',
         'Подойдёт ли сравнение простых моделей для секции прикладных проектов?',
         'Подойдёт. Добавьте описание датасета и ограничения интерпретации.', True),
    ):
        reply = stamp + timedelta(hours=4)
        ticket = semester.add(SupportTicket, student_id=student.id, topic=topic, title=title,
                              status='closed' if closed else 'open', created_at=stamp, updated_at=reply)
        for actor, body, sent in ((student, question, stamp), (office, response, reply)):
            semester.db.add(TicketMessage(ticket_id=ticket.id, actor_id=actor.id, actor_role=actor.role,
                                          actor_name=actor.full_name, body=body, created_at=sent))
        semester.notify(student, 'Ответ учебного офиса', title, 'service', f'/app/messages/{ticket.id}', reply,
                        key=f'contest:ticket:{ticket.id}', read=closed)


def seed_services(semester, cohorts, students):
    catalog = (
        ((9, 12), 'Знакомство с проектной мастерской', 'community', 'Корпус А, мастерская 2',
         'Участники выбирают тему осеннего проекта и записываются на разбор в малых группах.'),
        ((10, 17), 'Круглый стол по учебным данным', 'science', 'Библиотека, читальный зал',
         'Студенты показывают выборку наблюдений и объясняют применённую проверку качества.'),
        ((11, 24), 'Разбор научных тезисов', 'science', 'Библиотека, читальный зал',
         'Принесите черновик тезисов и один график для обсуждения со студенческой секцией.'),
        ((11, 28), 'Мастерская резюме и портфолио', 'career', 'Корпус Б, аудитория 210',
         'Участники составят короткий рассказ о своём учебном проекте и обменяются отзывами.'),
        ((12, 3), 'Открытая встреча волонтёрского клуба', 'community', 'Корпус А, зал 2',
         'На встрече распределят задачи для зимних образовательных и культурных мероприятий.'),
        ((12, 5), 'Турнир студенческих групп', 'sport', 'Спортивный зал кампуса',
         'Группы представят команды, игры пройдут по круговой системе.'),
    )
    for index, (day, title, category, location, description) in enumerate(catalog):
        clock = '17:30' if day == (11, 24) else '19:15' if day == (12, 3) else '14:30'
        at = autumn(*day, clock)
        active = [students[index % 2], cohorts[index % 3].students[-1]]
        event = semester.add(CampusEvent, seed_key=f'contest-2026-event-{index}', title=title, category=category,
                             description=description, start_at=at, end_at=at + timedelta(minutes=85), location=location,
                             capacity=20 + index * 3, registered_count=len(active))
        for student in active:
            semester.db.add(EventRegistration(student_id=student.id, event_id=event.id, status='active',
                                              created_at=min(at - timedelta(days=3), autumn(11, 19))))
        if index == 2:
            semester.db.add(EventRegistration(student_id=students[1].id, event_id=event.id, status='cancelled',
                                              created_at=autumn(11, 17)))

    for cohort in cohorts:
        for index, load in enumerate(cohort.loads[:2]):
            teacher = load.assignment.teacher.user
            dates = ((10, 8 + 2 * cohort.index + index), (11, 12 + 2 * cohort.index + index),
                     (11, 24 + cohort.index + index), (12, 1 + cohort.index + index))
            for number, day in enumerate(dates):
                at = autumn(*day, '19:00' if index == 0 else '20:00')
                end = at + timedelta(minutes=45)
                booking_count = int(number != 3)
                slot = semester.add(ConsultationSlot, seed_key=f'contest-2026-consult-{load.id}-{number}',
                                    teacher=teacher.full_name, subject=load.discipline.title, room=cohort.lab.code,
                                    start_at=at, end_at=end, capacity=4, booked_count=booking_count)
                semester.db.add(TeacherConsultation(slot_id=slot.id, load_id=load.id,
                                                     completed_at=end if end <= HISTORY_THROUGH else None))
                if booking_count:
                    student = cohort.students[0 if number == 2 else index]
                    semester.db.add(ConsultationBooking(student_id=student.id, slot_id=slot.id, status='active',
                                                        created_at=min(at - timedelta(days=2), autumn(11, 20))))
                if number == 1:
                    semester.db.add(ConsultationBooking(student_id=cohort.students[-1].id, slot_id=slot.id, status='cancelled',
                                                        created_at=at - timedelta(days=4)))

    seen = set()
    for cohort in cohorts:
        for load in cohort.loads:
            subject = load.discipline.title
            if subject in seen:
                continue
            seen.add(subject)
            current = subject in ('Алгоритмы и структуры данных', 'Анализ данных')
            book = semester.add(LibraryBook, seed_key=f'contest-book-{load.discipline_id}', title=f'{subject}. Практикум',
                                author=load.assignment.teacher.user.full_name, subject=subject,
                                description=load.discipline.description, total=6, available=5 if current else 6)
            reader = cohort.students[0]
            semester.db.add(LibraryLoan(student_id=reader.id, book_id=book.id, borrowed_at=autumn(10, 6),
                                       due_date=date(2026, 10, 20), returned_at=autumn(10, 15), status='returned'))
            if current:
                semester.db.add(LibraryLoan(student_id=reader.id, book_id=book.id, borrowed_at=autumn(11, 17),
                                           due_date=date(2026, 12, 1), status='active'))

    for cohort in cohorts:
        for number, student in enumerate(cohort.students):
            grants = (385_000, 402_000, 402_000) if number < 3 and student != students[1] else (0, 0, 0)
            for month, grant in zip((9, 10, 11), grants):
                if grant:
                    semester.db.add(FinanceEntry(student_id=student.id, date=date(2026, month, 17), direction='credit',
                                                 description='Академическая стипендия', amount_kopecks=grant))
                if student in students or number % 2 == 0:
                    semester.db.add(FinanceEntry(student_id=student.id, date=date(2026, month, 7), direction='debit',
                                                 description='Плата за проживание', amount_kopecks=87_000 + number * 3000))
            if student == students[1]:
                semester.db.add(FinanceEntry(student_id=student.id, date=date(2026, 10, 8), direction='credit',
                                             description='Зачисление оплаты за проживание', amount_kopecks=174_000))
            semester.db.add(StudentPreference(student_id=student.id, weekly_goal=8 if number < 2 else 6,
                                               deadline_reminders=True, compact_mode=number % 3 == 2))


def seed_personal(semester, cohorts):
    for cohort in cohorts:
        for number, student in enumerate(cohort.students):
            load = cohort.loads[number % len(cohort.loads)]
            subject = load.discipline.title
            started = autumn(9, 29, '16:00') + timedelta(days=number)
            heading = f'Конспект · {subject}'
            body = f'## Вопросы к практикуму\n\n{load.discipline.description}\n\nПроверить решение на независимом примере.'
            semester.db.add(StudyNote(student_id=student.id, subject=subject, title=heading, body=body,
                                      created_at=started, updated_at=autumn(11, 12), record_token=token('note', student.id)[:32]))
            semester.db.add(Flashcard(student_id=student.id, subject=subject, front='Как проверить воспроизводимость вывода?',
                                      back='Сохранить входные данные, шаги и ожидаемый результат для контрольного примера.',
                                      due_date=date(2026, 11, 29), reviews=2, known_count=1, interval_days=4,
                                      record_token=token('card', student.id)[:32]))
            questions = [dict(prompt=f'Что проверяет контрольный пример? Дисциплина «{subject}».',
                              options=['Воспроизводимость результата', 'Длину названия работы', 'Количество строк в пояснении'],
                              correct=0, explanation='Тот же набор данных должен приводить к ожидаемому результату.')]
            quiz = semester.add(Quiz, student_id=student.id, subject=subject, title='Проверка решения перед сдачей',
                                description='Проверка хода решения и контрольных данных.', questions_json=json_data(questions))
            answer = int(number % 3 == 2)
            semester.db.add(QuizAttempt(student_id=student.id, quiz_id=quiz.id, answers_json=json_data([answer]),
                                        score=int(answer == 0), total=1, created_at=autumn(10, 9)))
            for index, (title, due, done) in enumerate((
                ('Подготовить контрольные данные', date(2026, 11, 12), True),
                ('Собрать вопросы к консультации', date(2026, 11, 27), False),
                ('Обновить приложения к отчёту', date(2026, 12, 4), False),
            )):
                semester.db.add(PersonalTask(student_id=student.id, title=title, subject=subject, due_date=due,
                                             priority='high' if index == 1 else 'normal', is_done=done,
                                             created_at=autumn(11, 9 + index), record_token=token('task', student.id, index)[:32]))
            for index, (day, minutes) in enumerate(((5, 35), (11, 50), (20, 42))):
                semester.db.add(FocusSession(student_id=student.id, subject=subject, minutes=minutes + number,
                                             created_at=autumn(11, day), record_token=token('focus', student.id, index)[:32]))
            semester.db.add(PortfolioItem(student_id=student.id, title=f'Практикум: {subject.lower()}', kind='project',
                                          description=f'{load.discipline.description} Результат представлен на ноябрьском разборе.',
                                          day=date(2026, 11, 13), updated_at=autumn(11, 16),
                                          record_token=token('portfolio', student.id)[:32]))


def seed_absence(semester, students):
    key = certificate_key()
    if key:
        from PIL import Image, ImageDraw

        image = Image.new('RGB', (900, 550), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((54, 80), 'ATLAS CAMPUS / SYNTHETIC CONTEST SAMPLE', fill='black', font_size=24)
        draw.text((54, 135), 'Attendance evidence for the fictional autumn 2026 semester.', fill='black', font_size=18)
        document = BytesIO()
        image.save(document, format='PDF', creationDate=HISTORY_THROUGH.utctimetuple(),
                   modDate=HISTORY_THROUGH.utctimetuple())
        content = document.getvalue()
    for index, student in enumerate(students):
        rows = semester.db.execute(select(Attendance, ScheduledClass, Teacher).join(
            ScheduledClass, ScheduledClass.id == Attendance.class_id).join(
            Teacher, Teacher.id == ScheduledClass.teacher_id).where(
            Attendance.student_id == student.id, Attendance.status == 'absent',
            ScheduledClass.ends_at < autumn(11, 19)).order_by(ScheduledClass.ends_at.desc()).limit(2)).all()
        for number, (mark, lesson, teacher) in enumerate(rows):
            at = as_utc(lesson.ends_at) + timedelta(days=1)
            status = 'accepted' if number == 0 and index == 0 else 'pending' if key and number == 0 else 'rejected'
            reviewed = at + timedelta(hours=2) if status != 'pending' else None
            certificate = semester.add(AbsenceCertificate, student_id=student.id, created_at=at,
                                       expires_at=at + timedelta(days=90))
            _, start, end = local_interval(lesson.starts_at, lesson.ends_at)
            review = semester.add(AbsenceCertificateReview, certificate_id=certificate.id, attendance_id=mark.id,
                                  occurrence=f'event-{lesson.id}', day=mark.day, start=start, end=end,
                                  discipline=mark.subject, kind_label=KIND[lesson.kind], status=status,
                                  notified_teacher_id=teacher.user_id, reviewed_by=teacher.user_id if reviewed else None,
                                  reviewed_at=reviewed)
            semester.db.add(AbsenceCertificateAudit(certificate_id=certificate.id, actor_id=student.id,
                                                    action='submit', created_at=at))
            if reviewed:
                semester.db.add(AbsenceCertificateAudit(certificate_id=certificate.id, review_id=review.id,
                                                        actor_id=teacher.user_id, action=status, created_at=reviewed))
            if key:
                reason = 'Синтетическое подтверждение пропуска для проверки учебного сценария.'
                semester.db.add(AbsenceCertificateFile(certificate_id=certificate.id,
                                                        ciphertext=encrypt(key, certificate.id, 'file', content)))
                semester.db.add(AbsenceCertificateNote(certificate_id=certificate.id, entry=0,
                                                        ciphertext=encrypt(key, certificate.id, 0, reason.encode())))


def seed_registry(semester, cohorts):
    registry = semester.db.scalar(select(User).where(User.login == 'registry.demo'))
    imported_at = autumn(9, 1, '08:00')
    receipt = semester.add(TableImport, actor_id=registry.id, dataset='groups', scope=0, created_at=imported_at,
                           fingerprint=token('groups', *(cohort.group.code for cohort in cohorts)), count=len(cohorts))
    semester.event(registry, 'imports', receipt.id, 'imported', imported_at,
                   after={'dataset': 'groups', 'count': receipt.count, 'fingerprint': receipt.fingerprint})
    for cohort in cohorts:
        semester.event(registry, 'groups', cohort.group.id, 'created', imported_at,
                       after={'code': cohort.group.code, 'capacity': cohort.group.capacity})
    load = cohorts[0].loads[0]
    department = load.discipline.department
    for role, login, name, title, scope in (
        ('coordinator', 'course-office.contest', 'Лев Ветров', 'Координатор дисциплины', {'discipline_id': load.discipline_id}),
        ('department', 'department-office.contest', 'Анна Дубова', 'Кафедра информационных систем',
         {'department_id': department.id}),
    ):
        user = semester.add(User, login=login, password_hash=password_hasher.hash(token_urlsafe(32)), full_name=name,
                            initials=''.join(part[0] for part in name.split()), faculty=department.faculty.name,
                            program=department.name, course=0, group_name=title, student_number='', role=role, accent='blue')
        semester.db.add(MaterialDelegation(user_id=user.id, **scope))


def seed_campus(semester, cohorts, students, office):
    seed_documents(semester, students, office)
    seed_publications(semester, cohorts, office)
    seed_conversations(semester, cohorts, students, office)
    seed_services(semester, cohorts, students)
    seed_personal(semester, cohorts)
    seed_absence(semester, students)
    seed_registry(semester, cohorts)
