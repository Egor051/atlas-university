"""Fictional academic groups and separate operations accounts."""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .db import CAMPUS_TZ, Deadline, Grade, User, campus_today, password_hasher, utc_now
from .university_db import Teacher, TeachingAssignment
from .workspace_db import AcademicGroup, Classroom, GroupMember, GroupWork, ScheduledClass, TeachingLoad, WorkDelivery


def seed_account(db, login, password, full_name, initials, title, role):
    actor = db.scalar(select(User).where(User.login == login))
    if actor is None:
        actor = User(login=login, password_hash=password_hasher.hash(password), full_name=full_name,
                     initials=initials, faculty='Администрация АТЛАС', program=title, course=0,
                     group_name=title, student_number='', role=role, accent='blue')
        db.add(actor)
        db.flush()
    return actor


def seed_workspace(db):
    seed_account(db, 'schedule.demo', 'AtlasRooms!2026-S', 'София Берестова', 'СБ', 'Диспетчер расписания', 'scheduler')
    seed_account(db, 'registry.demo', 'AtlasRegistry!2026-R', 'Роман Ильин', 'РИ', 'Администратор АТЛАС', 'admin')
    if db.scalar(select(AcademicGroup.id).limit(1)) is not None:
        return
    rooms = [
        Classroom(building='Учебный корпус А', code='А-301', kind='lecture', capacity=45, accessible=True, equipment='проектор, доска'),
        Classroom(building='Учебный корпус Б', code='Б-208', kind='lab', capacity=32, accessible=True, equipment='компьютеры, проектор'),
        Classroom(building='Учебный корпус В', code='В-412', kind='seminar', capacity=32, accessible=False, equipment='доска'),
        Classroom(building='Учебный корпус В', code='В-404', kind='seminar', capacity=36, accessible=True, equipment='проектор, доска'),
        Classroom(building='Учебный корпус Б', code='Б-115', kind='seminar', capacity=24, accessible=True, equipment='доска'),
    ]
    db.add_all(rooms)
    db.flush()
    assignments = db.scalars(select(TeachingAssignment).options(joinedload(TeachingAssignment.discipline),
                                                                 joinedload(TeachingAssignment.teacher))
                             .order_by(TeachingAssignment.id)).all()
    algorithms = next((a for a in assignments if a.discipline.title == 'Алгоритмы и структуры данных'), None)
    substitute = db.scalar(select(Teacher).where(Teacher.slug == 'elena-ryabinina'))
    if algorithms and substitute and not any(a.discipline_id == algorithms.discipline_id and a.teacher_id == substitute.id for a in assignments):
        db.add(TeachingAssignment(discipline_id=algorithms.discipline_id, teacher_id=substitute.id))
    students = db.scalars(select(User).where(User.login.in_(['alina.demo', 'mark.demo']), User.role == 'student')
                         .order_by(User.id)).all()
    for student in students:
        group = AcademicGroup(code=student.group_name, program=student.program, capacity=24, accessible=True)
        db.add(group)
        db.flush()
        db.add(GroupMember(group_id=group.id, student_id=student.id))
        subjects = set(db.scalars(select(Grade.subject).where(Grade.student_id == student.id)))
        for assignment in assignments:
            subject = assignment.discipline.title
            if subject not in subjects:
                continue
            load = TeachingLoad(group_id=group.id, assignment_id=assignment.id, discipline_id=assignment.discipline_id)
            db.add(load)
            db.flush()
            if subject != 'Алгоритмы и структуры данных':
                continue
            # One managed occurrence is ready for the dispatcher to move or cancel.
            day = campus_today() + timedelta(days=(4-campus_today().weekday()) % 7 + 7)
            start = datetime.combine(day, time(16, 35), CAMPUS_TZ).astimezone(timezone.utc)
            db.add(ScheduledClass(load_id=load.id, group_id=group.id, teacher_id=assignment.teacher_id,
                                  room_id=rooms[0].id, starts_at=start, ends_at=start+timedelta(minutes=60),
                                  kind='seminar', equipment='проектор', note='Разбор решений по графам',
                                  series='demo-orlov-seminar', status='active'))
            deadline = db.scalar(select(Deadline).where(Deadline.student_id == student.id, Deadline.subject == subject)
                                 .order_by(Deadline.due_date, Deadline.id).limit(1))
            if deadline:
                work = GroupWork(load_id=load.id, title=deadline.title, due=deadline.due_date, author_id=assignment.teacher.user_id,
                                 instructions='Постройте небольшой граф, реализуйте обход в ширину и приложите разбор трёх тестов.',
                                 created_at=utc_now())
                db.add(work)
                db.flush()
                db.add(WorkDelivery(work_id=work.id, deadline_id=deadline.id))
