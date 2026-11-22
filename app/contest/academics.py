"""Timetables, academic records, publications and work from the same semester."""
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from sqlalchemy import select

from ..academic_points import AssignmentPointCorrection, apply_point_delta, award_points
from ..assignment_db import SubmissionAttachment, SubmissionAttempt, WorkFeedbackFile, WorkSourceFile
from ..assignment_workflow import deliver_work, sync_due_date
from ..db import CAMPUS_TZ, Grade, User, password_hasher
from ..learning_db import AssignmentSubmission, Attendance, Course, CourseModule, LearningSeed
from ..schedule_calendar import Calendar, date_range
from ..schedule_occurrences import campus_instant, class_data
from ..session_security import as_utc
from ..university_db import Department, DirectContact, Discipline, Teacher, TeachingAssignment, TeachingMaterial
from ..university_seed import MATERIALS
from ..workspace_db import (AcademicDayRule, AcademicGroup, AcademicSubgroup, AcademicTerm, Classroom,
                            GroupMember, GroupWork, ScheduleChange, ScheduledClass, TeachingLoad,
                            WorkDelivery, WorkFeedback, WorkMaterial)
from .seed import HISTORY_THROUGH, START, autumn, json_data, token


TEACHING_END = date(2026, 12, 11)
TERM_END = date(2027, 1, 24)
LECTURE_TIMES = ('09:00', '12:20', '15:40')
PRACTICE_DAYS = (2, 3, 4, 0)
PRACTICE_TIMES = ('10:40', '14:00', '17:20')
COLORS = ('violet', 'teal', 'blue', 'orange')
WORK_DATES = (
    ((9, 8), (9, 17), 'homework', 10),
    ((9, 22), (10, 2), 'lab', 14),
    ((10, 6), (10, 16), 'test', 14),
    ((10, 20), (10, 30), 'practice', 14),
    ((11, 3), (11, 13), 'project', 16),
    ((11, 17), (11, 27), 'individual', 10),
    ((11, 20), (12, 3), 'project', 10),
    ((11, 25), (12, 8), 'independent', 8),
)

TOPICS = {
    'orlov': ('Оценка операций с массивом', 'Очередь и стек на потоке команд', 'Граничные случаи бинарного поиска',
              'Обход графа и восстановление пути', 'Граф переходов между корпусами', 'Кратчайшие пути при весах рёбер',
              'Время поиска по большой карте', 'Сравнение списка и матрицы смежности'),
    'ryabinina': ('Ключи в журнале выдачи', 'Запросы по читателям и экземплярам', 'Проверка ограничений и связей',
                  'Транзакции при выдаче книги', 'Схема хранения учебных работ', 'План запроса каталога',
                  'Отчёт по возвратам экземпляров', 'Проверка аномалий обновления'),
    'lastochkina': ('Карта пути к услугам', 'Обзор навигации учебного кабинета', 'Проверка сценариев с клавиатуры',
                    'Прототип формы обращения', 'Проверка прототипа на узком экране', 'Сценарий повторной отправки',
                    'Навигация по карточке дисциплины', 'Проверка состояний загрузки и ошибки'),
    'zorin': ('Пропуски в наборе наблюдений', 'Сравнение распределений', 'Границы точности классификации',
              'Разбиение на обучение и проверку', 'Прогноз нагрузки учебного офиса', 'Разбор ошибок модели',
              'Сравнение двух правил классификации', 'Оценка качества при дисбалансе классов'),
    'romanova': ('Правило произведения', 'Оценка условной вероятности', 'Выбор распределения для наблюдений',
                 'График накопленных частот', 'Доверительный интервал для доли', 'Проверка независимости событий',
                 'Расчёт вероятности по неполной выборке', 'Чувствительность результатов к размеру выборки'),
    'belov': ('Топология сети корпуса', 'Адресные диапазоны для кабинетов', 'Модель маршрутизации лаборатории',
              'Сегментация учебной сети', 'Резервирование пути между корпусами', 'Измерение задержки в сети',
              'Обоснование схемы адресации', 'Сравнение вариантов резервирования'),
    'vesnina': ('Границы проекта практикума', 'Зависимости работ и ресурсов', 'Оценка сроков по сетевому графику',
                'Распределение ролей команды', 'Реестр рисков проекта', 'Разбор изменения требований',
                'Ретроспектива осеннего проекта', 'Уточнение критериев приёмки'),
}

INSTRUCTIONS = (
    'Опишите исходные допущения и решите задачу на небольшом примере. Поясните, какие данные влияют на результат.',
    'Приложите результат практикума и вывод двух проверок. Одной из проверок должен быть граничный случай.',
    'Дайте ход решения и обоснуйте выбор метода. Укажите, как проверить ответ на независимом наборе данных.',
    'Покажите промежуточные результаты и разберите непредвиденный случай. Объясните одно ограничение подхода.',
    'Представьте законченный результат с критериями проверки. Отметьте ограничения и порядок воспроизведения.',
    'Используйте материал занятия. Сравните два подхода, объясните расхождения и приложите итоговую таблицу.',
    'Подготовьте отчёт по рабочему сценарию и приложите данные для проверки. Укажите решение, которое выбрали.',
    'Самостоятельно сформулируйте контрольный пример и проведите проверку. Кратко запишите вывод.',
)


@dataclass
class Cohort:
    group: AcademicGroup
    students: list
    loads: list
    lab: Classroom
    lecture: Classroom
    subgroups: list
    index: int


def coursework_accounts(semester):
    db = semester.db
    assignments = {row.teacher.user.login.split('.')[0]: row
                   for row in db.scalars(select(TeachingAssignment).order_by(TeachingAssignment.id))}
    for code, name, initials, dept, subject, description in (
        ('romanova', 'Тамара Романова', 'ТР', 'analytics', 'Теория вероятностей',
         'Случайные события, распределения и проверка статистических выводов.'),
        ('belov', 'Андрей Белов', 'АБ', 'systems', 'Компьютерные сети',
         'Топологии, адресация и проектирование учебной сети.'),
        ('vesnina', 'Вера Веснина', 'ВВ', 'design', 'Управление проектами',
         'Границы проекта, планирование работ, риски и приёмка.'),
    ):
        department = db.scalar(select(Department).where(Department.slug == dept))
        user = semester.add(User, login=f'{code}.contest', password_hash=password_hasher.hash(token_urlsafe(32)),
                            full_name=name, initials=initials, faculty=department.faculty.name,
                            program=department.name, role='teacher', group_name='Преподаватель', course=0,
                            student_number='', accent='teal')
        teacher = semester.add(Teacher, department=department, user=user, slug=f'contest-{code}',
                               position='Преподаватель', academic=description)
        subject = semester.add(Discipline, department=department, title=subject, description=description)
        assignments[code] = semester.add(TeachingAssignment, teacher=teacher, discipline=subject)
        db.add(DirectContact(user_id=user.id, label=teacher.position))
    return assignments


def create_cohorts(semester, public_students, assignments):
    profiles = (
        (public_students[0], 'ИТ-24-03', 2024, ('orlov', 'ryabinina', 'lastochkina', 'romanova'),
         ('Влад Леднев', 'Софья Корнева', 'Глеб Долинин', 'Дарья Сомова', 'Ника Селезнёва')),
        (public_students[1], 'ПИ-23-02', 2023, ('zorin', 'belov', 'vesnina', 'ryabinina'),
         ('Яна Мелихова', 'Максим Бережной', 'Зоя Артемьева', 'Пётр Серов')),
        (None, 'ИТ-25-01', 2025, ('orlov', 'ryabinina', 'lastochkina', 'vesnina'),
         ('Ева Яровая', 'Антон Щукин', 'Мила Гречина', 'Олег Тихонов')),
    )
    result = []
    for index, (anchor, code, admission, keys, names) in enumerate(profiles):
        example = anchor or public_students[0]
        group = semester.add(AcademicGroup, code=code, program=example.program, capacity=18, accessible=True)
        subgroups = [semester.add(AcademicSubgroup, group_id=group.id, code=f'{code}-{label}', capacity=9)
                     for label in ('А', 'Б')]
        students = [anchor] if anchor else []
        if anchor:
            anchor.course = 2026 - admission + 1
        for number, name in enumerate(names, 1):
            students.append(semester.add(
                User, login=f'campus26.{index + 1}.{number}', password_hash=password_hasher.hash(token_urlsafe(32)),
                full_name=name, initials=''.join(part[0] for part in name.split()), faculty=example.faculty,
                program=example.program, course=2026 - admission + 1, group_name=code, role='student',
                student_number=f'AT-{admission}-{(index + 2) * 100 + number}', accent=COLORS[index]))
        for number, student in enumerate(students):
            semester.db.add(GroupMember(group_id=group.id, student_id=student.id, subgroup_id=subgroups[number % 2].id))
            semester.db.add(LearningSeed(student_id=student.id, version='autumn-2026'))
        loads = [semester.add(TeachingLoad, group=group, assignment=assignments[key],
                              discipline=assignments[key].discipline) for key in keys]
        lecture = semester.add(Classroom, building=f'Учебный корпус {index + 1}', code=('А-301', 'Б-306', 'В-412')[index],
                               kind='lecture', capacity=36, equipment='Проектор, доска', accessible=True)
        lab = semester.add(Classroom, building=f'Учебный корпус {index + 1}', code=('А-217', 'Б-208', 'В-404')[index],
                           kind='lab', capacity=22, equipment='Компьютеры, проектор', accessible=True)
        result.append(Cohort(group, students, loads, lab, lecture, subgroups, index))
    return result


def seed_materials(semester, assignments):
    result = {}
    for index, (key, kind, title, description, body) in enumerate(MATERIALS):
        assignment = assignments[key]
        content = body.encode('utf-8') if index % 2 == 0 else None
        posted = autumn(9 + index // 3, 4 + index % 3 * 7, '14:00')
        row = semester.add(TeachingMaterial, assignment=assignment, publisher_id=assignment.teacher.user_id,
                           kind=kind, title=title, description=description, body=body, access='campus',
                           file_name='конспект.md' if content else None, file_size=len(content) if content else None,
                           file_digest=sha256(content).hexdigest() if content else None, file_content=content,
                           created_at=posted, updated_at=posted)
        result.setdefault(key, []).append(row)
    for key, assignment in assignments.items():
        if key in result:
            continue
        topics = TOPICS[key]
        heading = f'Практикум. {topics[0]}'
        at = autumn(9, 3)
        row = semester.add(TeachingMaterial, assignment=assignment, publisher_id=assignment.teacher.user_id,
                           kind='practice', title=heading, description=assignment.discipline.description,
                           body=f'## Подготовка\n\n{INSTRUCTIONS[0]}\n\n## Разбор\n\n{INSTRUCTIONS[1]}',
                           access='campus', created_at=at, updated_at=at)
        result[key] = [row]
    return result


def meeting(semester, cohort, load, day, clock, room, kind, title):
    start = campus_instant(day, clock)
    return semester.add(ScheduledClass, load=load, group_id=cohort.group.id, teacher=load.assignment.teacher,
                        room=room, starts_at=start, ends_at=start + timedelta(minutes=90), kind=kind,
                        title=title, equipment='Проектор', series=token(load.id, kind, clock)[:24])


def mark_attendance(semester, cohort, load, lesson, number):
    if as_utc(lesson.ends_at) > HISTORY_THROUGH or lesson.status != 'active':
        return
    day = as_utc(lesson.starts_at).astimezone(CAMPUS_TZ).date()
    for index, student in enumerate(cohort.students):
        key = (number * 3 + index * 7 + load.discipline_id) % 23
        weak = student.login == 'mark.demo' or index > 2
        if key == 3:
            continue
        status = 'absent' if key < (6 if weak else 2) else 'excused' if key == 19 else 'late' if key == 20 else 'present'
        semester.db.add(Attendance(student_id=student.id, class_id=lesson.id, day=day,
                                   subject=load.discipline.title, status=status,
                                   note='Подключился после начала' if status == 'late' else ''))


def publish_changes(semester, cohort, load, lessons, accounts):
    if cohort.index != 0 or load != cohort.loads[0]:
        return
    db = semester.db
    scheduler, office, registry = (accounts[login] for login in ('schedule.demo', 'dean.demo', 'registry.demo'))
    for day, action, note, state in (
        (date(2026, 11, 18), 'cancel', 'Практикум объединён с разбором 25 ноября.', 'published'),
        (date(2026, 11, 25), 'update', 'Для разбора выделена аудитория с компьютерами на первом этаже.', 'published'),
        (date(2026, 12, 2), 'update', 'Нужна аудитория для работы с общим экраном.', 'submitted'),
    ):
        lesson = next(row for row in lessons if as_utc(row.starts_at).astimezone(CAMPUS_TZ).date() == day)
        previous = class_data(lesson)
        room = db.scalar(select(Classroom).where(Classroom.code == 'А-115'))
        slot = {key: previous[key] for key in ('load_id', 'teacher_id', 'day', 'start', 'end', 'kind', 'title',
                                                'subgroup_id', 'student_id', 'equipment', 'calendar_exception')}
        slot['room_id'] = room.id
        at = autumn(11, 16 if action == 'cancel' else 20, '14:30')
        payload = dict(action=action, event_id=lesson.id, event_version=lesson.version, note=note,
                       slot=slot if action == 'update' else None)
        change = semester.add(ScheduleChange, author_id=scheduler.id, state=state, action=action, event_id=lesson.id,
                              payload=json_data(payload), version=4 if state == 'published' else 2,
                              created_at=at - timedelta(hours=2), updated_at=at)
        semester.event(scheduler, 'schedule', change.id, 'created', at - timedelta(hours=2), after=payload)
        submitted = at - timedelta(hours=1) if state == 'published' else at
        semester.event(scheduler, 'schedule', change.id, 'submit', submitted, after={'state': 'submitted'})
        if state != 'published':
            semester.notify(office, 'Изменение расписания ожидает решения', note, 'schedule',
                            f'/app/schedule-changes/{change.id}', submitted, key=f'contest:schedule-review:{change.id}')
            continue
        semester.event(office, 'schedule', change.id, 'agree', at - timedelta(minutes=20), after={'state': 'agreed'})
        lesson.previous = previous
        lesson.previous_day = day
        lesson.change_action = action
        lesson.version = 2
        lesson.note = note
        if action == 'cancel':
            lesson.status = 'cancelled'
        else:
            lesson.room = room
        db.flush()
        semester.event(registry, 'schedule', change.id, 'publish', at,
                       before=previous, after={'published': [class_data(lesson)]})
        for student in cohort.students:
            semester.notify(student, 'Изменение в расписании', note, 'schedule', f'/app/schedule?date={day}',
                            at, key=f'contest:schedule:{change.id}:{student.id}', read=action == 'cancel')


def seed_timetable(semester, cohort, load, index, key, calendar, accounts):
    lecture_day, lecture_time = index, LECTURE_TIMES[cohort.index]
    practice_day, practice_time = PRACTICE_DAYS[index], PRACTICE_TIMES[cohort.index]
    lessons = []
    for day in date_range(START, TEACHING_END):
        if day.weekday() not in (lecture_day, practice_day) or calendar.day(day, cohort.group).code != 'teaching':
            continue
        lecture = day.weekday() == lecture_day
        clock, room = (lecture_time, cohort.lecture) if lecture else (practice_time, cohort.lab)
        week = (day - START).days // 7
        topic = TOPICS[key][min(week // 2, len(TOPICS[key]) - 1)]
        lessons.append(meeting(semester, cohort, load, day, clock, room, 'lecture' if lecture else 'lab', topic))
    publish_changes(semester, cohort, load, lessons, accounts)
    for number, lesson in enumerate(lessons):
        mark_attendance(semester, cohort, load, lesson, number)
    return lessons


def awarded(semester, student, load, activity, points, maximum, kind, title, at, *, review=None, work=None):
    grade = semester.db.scalar(select(Grade).where(Grade.student_id == student.id, Grade.subject == load.discipline.title))
    actor = load.assignment.teacher.user
    award = award_points(semester.db, student_id=student.id, discipline_id=load.discipline_id,
                         points=points, source_kind='assignment' if work else 'teacher',
                         source_id=work.id if work else f'{load.id}:{grade.version}', actor_id=actor.id,
                         class_id=activity.id, title=title, kind=kind, max_points=maximum,
                         review_id=review.id if review else None, reason=title)
    award.created_at = at
    semester.event(actor, 'teaching', load.id, 'grade', at,
                   after=dict(student_id=student.id, score=grade.current, points=points,
                              class_id=activity.id, title=title, review_id=review.id if review else None))
    return grade


def work_response(semester, load, work, activity, deliveries, owner, at, due, maximum, kind, mode,
                  *, points=None, revise_at=None, correct=False, file=False):
    teacher = load.assignment.teacher.user
    deadline = deliveries[0]
    text = f'Проверил ход решения по теме «{work.title}». Привёл исходные условия и результат контрольного примера.'
    draft = mode == 'in_progress'
    submission = semester.add(AssignmentSubmission, student_id=owner.id, deadline_id=deadline.id,
                              text='' if draft else text, status=mode if draft else 'submitted', url='',
                              submitted_at=at, updated_at=at, attempt_version=0 if draft else 1)
    if draft:
        return
    attempt = semester.add(SubmissionAttempt, submission_id=submission.id, actor_id=owner.id, version=1, number=1,
                           text=text, url='', submitted_at=at, late=at > due)
    semester.event(owner, 'assignments', deadline.id, 'submitted', at,
                   after=dict(attempt_id=attempt.id, version=1, late=attempt.late))
    if file:
        content = f'# {work.title}\n\n{text}\n'.encode()
        semester.db.add(SubmissionAttachment(attempt_id=attempt.id, name='решение.md', content=content, size=len(content)))
    if mode == 'withdrawn':
        submission.status, submission.version, submission.updated_at = mode, 2, at + timedelta(hours=1)
        semester.event(owner, 'assignments', deadline.id, 'withdrawn', submission.updated_at, after={'version': 2})
        return
    if mode == 'submitted':
        return
    reviewed = at + timedelta(hours=4)
    if revise_at:
        remarks = 'Покажите проверку на граничных данных и поясните расхождение с первым результатом.'
        semester.add(WorkFeedback, submission_id=submission.id, author_id=teacher.id, submitted_version=1,
                     action='revise', comment='Добавьте контрольный пример.', remarks=remarks, created_at=reviewed,
                     extended_until=revise_at)
        for recipient in deliveries:
            delivery = semester.db.get(WorkDelivery, recipient.id)
            delivery.revision_due_at = revise_at
            sync_due_date(recipient, delivery, work)
        work.version += 1
        submission.status, submission.version, submission.updated_at = 'revision_required', 2, reviewed
        if mode == 'revision_required':
            semester.notify(owner, 'Работа возвращена на доработку', work.title, 'academic',
                            f'/app/assignments?id={deadline.id}', reviewed, key=f'contest:revision:{submission.id}')
            return
        at = reviewed + timedelta(days=2)
        text = 'Добавил граничный пример и повторил проверку. Исправленная версия включает оба результата.'
        attempt = semester.add(SubmissionAttempt, submission_id=submission.id, actor_id=owner.id, version=3, number=2,
                               text=text, url='', submitted_at=at, late=at > revise_at)
        submission.text, submission.submitted_at, submission.attempt_version = text, at, 3
        submission.version, reviewed = 3, at + timedelta(days=1)
    action = 'review' if mode == 'in_review' else 'accept'
    comment = ('Проверяю исходные допущения и приложенные выводы.' if points is None else
               'Ход решения проверен. Выводы согласуются с контрольным примером.')
    entry = semester.add(WorkFeedback, submission_id=submission.id, author_id=teacher.id,
                         submitted_version=attempt.version, action=action, score=points,
                         comment=comment, created_at=reviewed)
    submission.status, submission.version, submission.updated_at = mode, submission.version + 1, reviewed
    if mode == 'completed':
        completed = reviewed + timedelta(hours=1)
        semester.add(WorkFeedback, submission_id=submission.id, author_id=teacher.id, submitted_version=attempt.version,
                     action='complete', comment='Работа закрыта после разбора.', created_at=completed)
        submission.version += 1
        submission.updated_at = completed
    if file:
        content = comment.encode()
        semester.db.add(WorkFeedbackFile(feedback_id=entry.id, name='разбор.txt', content=content, size=len(content)))
    if points is None:
        return
    for recipient in deliveries:
        student = semester.db.get(User, recipient.student_id)
        grade = awarded(semester, student, load, activity, points, maximum, kind, work.title, reviewed,
                        review=entry, work=work)
        if correct:
            updated = reviewed + timedelta(days=1)
            reason = 'После сверки критерия учтена дополнительная проверка.'
            replacement = semester.add(WorkFeedback, submission_id=submission.id, author_id=teacher.id,
                                       submitted_version=attempt.version, action='correct_score', comment=reason,
                                       created_at=updated, score=points + 1, previous_score=points)
            apply_point_delta(grade, 1)
            semester.db.add(AssignmentPointCorrection(
                student_id=student.id, work_id=work.id, grade_id=grade.id, feedback_id=replacement.id,
                class_id=activity.id, actor_id=teacher.id, previous_points=points, corrected_points=points + 1,
                reason=reason, created_at=updated))
            submission.version, submission.updated_at = submission.version + 1, updated


def seed_works(semester, cohort, load, lessons, key, topics, materials):
    teacher = load.assignment.teacher.user
    for index, (opening, deadline_day, kind, maximum) in enumerate(WORK_DATES):
        opened, due = autumn(*opening, '09:00'), autumn(*deadline_day, '20:00')
        activity = next(row for row in reversed(lessons) if row.status == 'active' and as_utc(row.ends_at) <= opened)
        state = 'published' if opened <= HISTORY_THROUGH else 'scheduled'
        available = [row for row in materials if as_utc(row.created_at) <= min(opened, HISTORY_THROUGH)]
        team = index == 3 and cohort.index == 0 and key == 'lastochkina'
        subgroup = index == 7 and cohort.index == 0 and key == 'ryabinina'
        if team:
            kind = 'group'
        policy = dict(kind=kind, max_points=maximum, class_id=activity.id, methods=['text', 'files'],
                      formats=['md', 'txt'], max_attempts=3, allow_late=index != 6,
                      criteria='Воспроизводимость, контрольные примеры и обоснование вывода.',
                      description=f'Практическое применение темы «{topics[index].lower()}».',
                      team_lead_id=cohort.students[0].id if team else None,
                      subgroup_id=cohort.subgroups[0].id if subgroup else None)
        work = semester.add(GroupWork, load_id=load.id, author_id=teacher.id, title=topics[index],
                            instructions=INSTRUCTIONS[index], created_at=min(opened - timedelta(days=2), HISTORY_THROUGH),
                            due=due.astimezone(CAMPUS_TZ).date(), due_at=due, publish_at=opened, state=state,
                            policy_json=json_data(policy))
        semester.event(teacher, 'teaching', load.id, 'work_created', work.created_at,
                       after=dict(id=work.id, title=work.title, state=state))
        if available:
            semester.db.add(WorkMaterial(work_id=work.id, material_id=available[-1].id))
        if index in (1, 6):
            source = f'тема,что проверить\n{work.title},граничные условия\n'.encode()
            semester.db.add(WorkSourceFile(work_id=work.id, name='исходные-данные.csv', content=source, size=len(source)))
        members = cohort.students[::2] if subgroup else cohort.students
        deliveries = [deliver_work(semester.db, load, work, student.id, notify_student=False) for student in members]
        if state == 'scheduled':
            continue
        for number, (student, deadline) in enumerate(zip(members, deliveries)):
            weak = student.login == 'mark.demo' or number > 2
            if index >= 5:
                if index == 5:
                    mode = ('in_review', 'revision_required', 'submitted', 'in_progress', 'withdrawn', 'not_started')[
                        (number + cohort.loads.index(load)) % 6]
                    if student.login == 'mark.demo':
                        mode = 'revision_required' if key == 'zorin' else mode
                        delivery = semester.db.get(WorkDelivery, deadline.id)
                        delivery.individual_due_at = autumn(12, 1, '20:00')
                        sync_due_date(deadline, delivery, work)
                    if mode != 'not_started':
                        work_response(semester, load, work, activity, [deadline], student, autumn(11, 19, '10:00'), due,
                                      maximum, kind, mode, revise_at=autumn(12, 2, '20:00') if mode == 'revision_required' else None)
                semester.notify(student, 'Опубликовано учебное задание', work.title, 'academic',
                                f'/app/assignments?id={deadline.id}', opened,
                                key=f'work-publish:{work.id}:{deadline.id}', read=index == 5)
                continue
            if team and number:
                continue
            if index in (0, 2) and (not weak or index == 0):
                attendance = semester.db.scalar(select(Attendance.status).where(
                    Attendance.student_id == student.id, Attendance.class_id == activity.id))
                if attendance in ('present', 'late'):
                    awarded(semester, student, load, activity, 2 if number < 2 else 1, 2, 'practice',
                            f'Разбор: {activity.title}', opened)
            if weak and not team and (index + number + load.discipline_id) % 5 in (0, 1):
                continue
            revised = index == 2 and (number + load.discipline_id) % 3 == 0
            late = index == 1 and weak
            at = due + timedelta(hours=12) if late else opened + timedelta(days=3 + number % 3, hours=2)
            score = max(1, maximum - ((number + load.discipline_id + index) % 4) - (3 if weak else 0))
            correct = index == 1 and number == 0 and cohort.index == 0 and key == 'orlov' and score < maximum
            work_response(semester, load, work, activity, deliveries if team else [deadline], student, at, due,
                          maximum, kind, 'completed' if index == 0 else 'accepted', points=score,
                          revise_at=due + timedelta(days=3) if revised else None, correct=correct, file=index == 1)

    semester.add(GroupWork, load_id=load.id, author_id=teacher.id, title=f'Итоговый разбор: {topics[-1].lower()}',
                 instructions=INSTRUCTIONS[-1], created_at=autumn(11, 21), due=date(2026, 12, 11), state='draft')


def seed_academics(semester, public_students, accounts):
    assignments = coursework_accounts(semester)
    materials = seed_materials(semester, assignments)
    cohorts = create_cohorts(semester, public_students, assignments)
    semester.add(Classroom, building='Учебный корпус 1', code='А-115', kind='lab', capacity=24,
                 equipment='Компьютеры, проектор', accessible=True)
    periods = [dict(kind=kind, start=str(first), end=str(last)) for kind, first, last in (
        ('teaching', START, TEACHING_END), ('credit', date(2026, 12, 14), date(2026, 12, 19)),
        ('exam', date(2026, 12, 21), date(2026, 12, 30)), ('break', date(2027, 1, 1), TERM_END),
    )]
    calendar_source = 'Учебный календарь АТЛАС на осенний семестр 2026/2027'
    semester.add(AcademicTerm, academic_year=2026, number=1, starts_on=START, ends_on=TERM_END,
                 weekdays='01234', periods=periods, source=calendar_source)
    make_up = date(2026, 11, 28)
    semester.add(AcademicDayRule, group_id=cohorts[0].group.id, starts_on=make_up, ends_on=make_up,
                 kind='working', label='Дополнительный практикум перед зачётом', source=calendar_source)
    calendar = Calendar(semester.db, START, TERM_END)
    for cohort in cohorts:
        for index, load in enumerate(cohort.loads):
            key = load.assignment.teacher.user.login.split('.')[0]
            topics = TOPICS[key]
            lessons = seed_timetable(semester, cohort, load, index, key, calendar, accounts)
            if cohort.index == 0 and index == 0:
                meeting(semester, cohort, load, make_up, '10:00', cohort.lab, 'lab', 'Разбор графов перед контролем')
            kind = 'exam' if index < 2 else 'credit'
            early = cohort.index < 2 and index == 2
            soon = cohort.index == 0 and index == 3
            if early or soon:
                assessment_day, clock = date(2026, 11, 20 if early else 26), '19:00'
            else:
                assessment_day, clock = date(2026, 12, (21 if kind == 'exam' else 14) + index), LECTURE_TIMES[cohort.index]
            meeting(semester, cohort, load, assessment_day, clock,
                    cohort.lecture, kind, 'Итоговая аттестация по дисциплине')
            for number, student in enumerate(cohort.students):
                retake = early and student.login == 'mark.demo'
                blocked = index == 1 and student.login == 'mark.demo'
                if retake:
                    repeat = meeting(semester, cohort, load, date(2026, 12, 8), '19:00', cohort.lecture, 'retake', 'Повторный зачёт')
                    repeat.student_id = student.id
                grade = semester.add(Grade, student_id=student.id, subject=load.discipline.title, kind=kind,
                                     current=0, teacher=load.assignment.teacher.user.full_name, max_grade=100,
                                     exam_kind='Экзамен' if kind == 'exam' else 'Зачёт', color=COLORS[index],
                                     exam_date=date(2026, 12, 8) if retake else assessment_day,
                                     assessment='Пересдача назначена' if retake else 'Зачтено' if early else
                                     'Не допущен' if blocked else 'Допуск')
                course = semester.add(Course, student_id=student.id, grade_id=grade.id, discipline_id=load.discipline_id,
                                      subject=grade.subject, teacher=grade.teacher, color=grade.color, credits=3 + index % 2,
                                      description=load.discipline.description)
                semester.db.add_all(CourseModule(course_id=course.id, position=position, title=topic,
                                                 content=INSTRUCTIONS[position], is_done=position < (3 if number < 2 else 1))
                                    for position, topic in enumerate(topics[:4]))
            seed_works(semester, cohort, load, lessons, key, topics, materials[key])
    return cohorts
