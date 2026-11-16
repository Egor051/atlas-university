"""Create and remove a self-contained, fictional academic acceptance fixture."""
import json
import re
import secrets
import sys
from datetime import timedelta

from sqlalchemy import delete, select

from app.absence_certificate_db import AbsenceCertificate
from app.academic_points import ManualPointCorrection, PointAward
from app.db import Grade, Notification, SessionLocal, User, campus_today, password_hasher
from app.learning_db import Attendance
from app.schedule_occurrences import campus_instant
from app.services_db import ServiceIdempotency
from app.university_db import Department, Discipline, Teacher, TeachingAssignment
from app.workspace_db import (AcademicGroup, AcademicSubgroup, AcademicTerm, Classroom, GroupMember,
                              OperationEvent, ScheduledClass, TeachingLoad)


def create_fixture(db, token):
    today = campus_today()
    first, last = today - timedelta(days=65), today + timedelta(days=25)
    label = f'QA-6-{token}'
    group = AcademicGroup(code=label, program='Изолированная проверка', capacity=10)
    room = Classroom(building='Тестовый корпус', code=label, kind='lab', capacity=10)
    db.add_all([group, room])
    db.flush()
    subgroups = [AcademicSubgroup(group_id=group.id, code=code, capacity=5) for code in ('Подгруппа 1', 'Подгруппа 2')]
    db.add_all(subgroups)
    db.add(AcademicTerm(group_id=group.id, academic_year=first.year, number=1, starts_on=first, ends_on=last,
                        weekdays='0123456', periods=[dict(kind='teaching', start=str(first), end=str(last))],
                        source='Изолированная проверка этапа 6'))
    actors = {}
    department_id = db.scalar(select(Department.id).order_by(Department.id).limit(1))
    for index, (name, role) in enumerate((('Студент Проверочный', 'student'), ('Студент Контрольный', 'student'),
                                            ('Преподаватель Проверочный', 'teacher'), ('Преподаватель Замещающий', 'teacher'))):
        login, password = f'qa6.{token}.{index}', 'Qa6!' + secrets.token_urlsafe(24)
        actor = User(login=login, password_hash=password_hasher.hash(password), full_name=name, initials='ТП',
                     faculty='Проверка', program=group.program, course=2 if index < 2 else 0, group_name=label,
                     student_number=f'{label}-{index}', role=role, accent='blue')
        db.add(actor)
        db.flush()
        if role == 'student':
            db.add(GroupMember(student_id=actor.id, group_id=group.id, subgroup_id=subgroups[index].id))
            teacher_id = None
        else:
            teacher = Teacher(department_id=department_id, user_id=actor.id, slug=f'qa6-{token}-{index}',
                              position='Учебная проверка', academic='')
            db.add(teacher)
            db.flush()
            teacher_id = teacher.id
        actors[str(index)] = dict(id=actor.id, login=login, password=password, teacher_id=teacher_id)

    loads = []
    subjects = [f'{label} Распределённые системы', f'{label} Основы проектирования']
    for index, title in enumerate(subjects):
        subject = Discipline(department_id=department_id, title=title, description='Изолированная проверка этапа 6')
        db.add(subject)
        db.flush()
        assignment = TeachingAssignment(discipline_id=subject.id, teacher_id=actors[str(index+2)]['teacher_id'])
        db.add(assignment)
        db.flush()
        load = TeachingLoad(group_id=group.id, discipline_id=subject.id, assignment_id=assignment.id)
        db.add(load)
        db.flush()
        loads.append(load)

    def meeting(key, days, kind, *, load=loads[0], state='active', subgroup=None, personal=None, previous=None):
        day = today + timedelta(days=days)
        start = campus_instant(day, '10:00')
        teacher_id = load.assignment.teacher_id
        previous_day = today + timedelta(days=previous) if previous is not None else None
        row = ScheduledClass(load_id=load.id, group_id=group.id, teacher_id=teacher_id, room_id=room.id,
                             subgroup_id=subgroup.id if subgroup else None, student_id=personal, starts_at=start,
                             ends_at=start + timedelta(hours=1), title=key, kind=kind, series=token, status=state,
                             previous_day=previous_day, version=2 if previous_day else 1,
                             change_action='update' if previous_day else 'cancel' if state == 'cancelled' else 'create',
                             previous=dict(day=str(previous_day), start='10:00', end='11:00', room=label, kind=kind,
                                           status='active', teacher=load.assignment.teacher.user.full_name) if previous_day else None)
        db.add(row)
        db.flush()
        return dict(id=row.id, uid=f'event-{row.id}', day=str(day), previous=str(previous_day) if previous_day else None)

    records = {
        'lecture': meeting('Лекция для приёмки', -42, 'lecture'),
        'lab': meeting('Первая лабораторная для приёмки', -29, 'lab', subgroup=subgroups[0]),
        'moved': meeting('Перенесённая лабораторная для приёмки', -9, 'lab', subgroup=subgroups[0], previous=-14),
        'practice': meeting('Практическое занятие для приёмки', -4, 'practice', load=loads[1]),
        'missing': meeting('Лекция без отметки', -3, 'lecture', load=loads[1]),
        'cancelled': meeting('Отменённая лекция для приёмки', -2, 'lecture', load=loads[1], state='cancelled'),
        'extra': meeting('Дополнительное занятие для приёмки', -1, 'practice', personal=actors['0']['id']),
        'future': meeting('Будущее занятие для приёмки', 3, 'lecture', load=loads[1]),
        'previous': meeting('Занятие вне семестра', -68, 'lecture'),
    }
    return dict(token=token, group=group.code, actors=actors, records=records, subjects=subjects, loads=[load.id for load in loads])


def cleanup_fixture(db, token):
    label = f'QA-6-{token}'
    actors = list(db.scalars(select(User.id).where(User.login.in_([f'qa6.{token}.{index}' for index in range(4)]))))
    group_id = db.scalar(select(AcademicGroup.id).where(AcademicGroup.code == label))
    if not actors or group_id is None:
        return 0
    subject_ids = list(db.scalars(select(TeachingLoad.discipline_id).where(TeachingLoad.group_id == group_id)))
    for model, scope in (
        (AbsenceCertificate, AbsenceCertificate.student_id.in_(actors)),
        (Attendance, Attendance.student_id.in_(actors)),
        (ManualPointCorrection, ManualPointCorrection.award_id.in_(
            select(PointAward.id).where(PointAward.student_id.in_(actors)))),
        (PointAward, PointAward.student_id.in_(actors)),
        (Grade, Grade.student_id.in_(actors)),
        (OperationEvent, OperationEvent.actor_id.in_(actors)),
        (Notification, Notification.student_id.in_(actors)),
        (ServiceIdempotency, ServiceIdempotency.user_id.in_(actors)),
        (ScheduledClass, ScheduledClass.group_id == group_id),
        (GroupMember, GroupMember.group_id == group_id),
        (AcademicSubgroup, AcademicSubgroup.group_id == group_id),
        (AcademicTerm, AcademicTerm.group_id == group_id),
        (TeachingLoad, TeachingLoad.group_id == group_id),
        (TeachingAssignment, TeachingAssignment.discipline_id.in_(subject_ids)),
        (Discipline, Discipline.id.in_(subject_ids)),
        (Teacher, Teacher.user_id.in_(actors)),
        (Classroom, Classroom.code == label),
        (AcademicGroup, AcademicGroup.id == group_id),
        (User, User.id.in_(actors)),
    ):
        db.execute(delete(model).where(scope))
    return len(actors)


if __name__ == '__main__':
    command, token = sys.argv[1:]
    if not re.fullmatch(r'[0-9a-f]{12}', token) or command not in ('create', 'cleanup'):
        raise SystemExit('Expected create/cleanup and a random 12-digit hex fixture token')
    with SessionLocal.begin() as session:
        result = create_fixture(session, token) if command == 'create' else {'removed_actors': cleanup_fixture(session, token)}
    print(json.dumps(result, ensure_ascii=True))
