"""Occurrence-based attendance shared by the register and journal writers."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import case, or_, select
from sqlalchemy.orm import joinedload

from .absence_certificate_db import AbsenceCertificateReview
from .db import CAMPUS_TZ, campus_today, utc_now
from .learning_db import Attendance
from .schedule_calendar import Calendar, LESSON_KINDS, matches
from .schedule_occurrences import (audience, campus_instant, class_query, legacy_record,
                                   managed_occurrence, occurrence_key, student_occurrences)
from .schedule_views import student_item
from .university_db import Discipline, Teacher, TeachingAssignment
from .workspace_db import AcademicGroup, AcademicSubgroup, GroupMember, ScheduledClass, TeachingLoad


def current_term(db, day, group):
    calendar = Calendar(db, day, day)
    term = calendar.term(day, group)
    if term:
        return dict(id=term.id, starts_on=term.starts_on, ends_on=term.ends_on,
                    label=f'{term.academic_year}/{term.academic_year + 1} · {term.number}-й семестр')
    window = next((rule for rule in calendar.rules if rule.kind == 'legacy' and matches(rule, group)), None)
    if window:
        return dict(id=None, starts_on=window.starts_on, ends_on=window.ends_on, label='Опубликованный период расписания')
    return None


def legacy_teachers(db, group_id):
    from .scheduling import aliases

    result = defaultdict(set)
    stmt = (select(Discipline.title, Teacher).join(TeachingAssignment, TeachingAssignment.teacher_id == Teacher.id)
            .join(Discipline, Discipline.id == TeachingAssignment.discipline_id)
            .join(TeachingLoad, TeachingLoad.discipline_id == Discipline.id)
            .where(TeachingLoad.group_id == group_id).options(joinedload(Teacher.user)))
    for discipline, teacher in db.execute(stmt):
        if teacher.user.role == 'teacher':
            for name in aliases(teacher):
                result[(discipline, name)].add(teacher.user_id)
    return {key: next(iter(ids)) for key, ids in result.items() if len(ids) == 1}


def review_teacher(db, row):
    if not row.get('legacy_day'):
        return row['_teacher_user_id']
    return legacy_teachers(db, row['group_id']).get((row['discipline'], row['teacher']))


def occurrence_window(db, student_id, first, last):
    member = db.get(GroupMember, student_id)
    calendar = Calendar(db, first, last)
    rows = [row for row in student_occurrences(db, student_id, member, first, last, calendar)
            if row['kind'] in LESSON_KINDS]
    return member, calendar, rows


def occurrence_for_review(db, student_id, key):
    if key.startswith('event-'):
        member = db.get(GroupMember, student_id)
        stmt = class_query().where(ScheduledClass.id == int(key.removeprefix('event-')))
        meeting = db.scalar(audience(stmt, member, student_id))
        row = managed_occurrence(meeting) if meeting else None
    else:
        _, lesson_id, original = key.split('-', 2)
        row, _ = legacy_record(db, int(lesson_id), date.fromisoformat(original))
        if row and row['student_id'] != student_id:
            return None
    return row if row and row['kind'] in LESSON_KINDS else None


def completed(row, now):
    end = row.get('_ends_at') or campus_instant(date.fromisoformat(row['day']), row['end'])
    return end <= now


def marks_for_occurrences(db, student_id, rows):
    if not rows:
        return {}
    class_ids = [row['id'] for row in rows if not row.get('legacy_day')]
    lesson_ids = [row['id'] for row in rows if row.get('legacy_day')]
    days = [date.fromisoformat(row['day']) for row in rows]
    old_keys = Counter((row['discipline'], day) for row, day in zip(rows, days))
    old_marks, by_key = {}, {}
    stmt = select(Attendance).where(Attendance.student_id == student_id, or_(
        Attendance.class_id.in_(class_ids), Attendance.legacy_lesson_id.in_(lesson_ids),
        Attendance.class_id.is_(None) & Attendance.legacy_lesson_id.is_(None) & Attendance.day.in_(set(days)),
    )).order_by(Attendance.id)
    for mark in db.scalars(stmt):
        if mark.class_id is not None:
            by_key[f'event-{mark.class_id}'] = mark
        elif mark.legacy_lesson_id is not None:
            by_key[f'lesson-{mark.legacy_lesson_id}-{mark.legacy_original_day}'] = mark
        else:
            old_marks.setdefault((mark.subject, mark.day), mark)
    for row, day in zip(rows, days):
        key = (row['discipline'], day)
        if old_keys[key] == 1 and key in old_marks:
            by_key.setdefault(occurrence_key(row), old_marks[key])
    return by_key


def bind_mark(mark, row):
    if row.get('legacy_day'):
        mark.legacy_lesson_id = row['id']
        mark.legacy_original_day = date.fromisoformat(row['legacy_day'])
    else:
        mark.class_id = row['id']


def recorded_status():
    accepted = select(AbsenceCertificateReview.id).where(AbsenceCertificateReview.attendance_id == Attendance.id,
                                                        AbsenceCertificateReview.status == 'accepted').exists()
    return case(((Attendance.status == 'absent') & accepted, 'excused'), else_=Attendance.status)


def cleared_marks(db, ids):
    return set(db.scalars(select(AbsenceCertificateReview.attendance_id).where(
        AbsenceCertificateReview.attendance_id.in_(ids), AbsenceCertificateReview.status == 'accepted'))) if ids else set()


def journal_occurrence(db, load, teacher_id, student_id, day, class_id):
    _, _, rows = occurrence_window(db, student_id, day, day)
    if class_id is None:
        # The dated journal can record a legacy lesson when the date identifies it.
        # Managed records use the explicit class picker.
        candidates = [row for row in rows if row['discipline'] == load.discipline.title]
        matching = [row for row in candidates if row.get('legacy_day') and row['group_id'] == load.group_id]
        if len(candidates) != 1 or len(matching) != 1:
            raise HTTPException(422, 'Выберите конкретное занятие из расписания')
    else:
        matching = [row for row in rows if not row.get('legacy_day') and row['id'] == class_id
                    and row['load_id'] == load.id]
    if not matching or matching[0]['status'] != 'active' or review_teacher(db, matching[0]) != teacher_id:
        raise HTTPException(404, 'Занятие не найдено в этом журнале')
    row = matching[0]
    if campus_instant(day, row['start']) > utc_now():
        raise HTTPException(422, 'Занятие ещё не началось')
    return row, marks_for_occurrences(db, student_id, rows).get(occurrence_key(row))


def term_rows(db, student_id, now):
    today = now.astimezone(CAMPUS_TZ).date()
    member = db.get(GroupMember, student_id)
    group = db.get(AcademicGroup, member.group_id) if member else None
    term = current_term(db, today, group)
    if term is None:
        return None, []
    _, calendar, rows = occurrence_window(db, student_id, term['starts_on'], min(today, term['ends_on']))
    marks = marks_for_occurrences(db, student_id, rows)
    legacy_reviewers = legacy_teachers(db, group.id) if group and any(row.get('legacy_day') for row in rows) else {}
    subgroup = db.get(AcademicSubgroup, member.subgroup_id) if member and member.subgroup_id else None
    records = []
    for row in rows:
        if term['id'] is not None:
            actual_term = calendar.term(date.fromisoformat(row['day']), group)
            if not actual_term or actual_term.id != term['id']:
                continue
        if row['status'] != 'cancelled' and not completed(row, now):
            continue
        key = occurrence_key(row)
        value = student_item(row, subgroup.code if subgroup else None)
        reviewer = row.get('_teacher_user_id') or legacy_reviewers.get((row['discipline'], row['teacher']))
        records.append((row, value, marks.get(key), reviewer))
    records.sort(key=lambda record: (record[1]['date'], record[1]['start'], record[1]['uid']), reverse=True)
    return term, records


def validate_journal_day(day):
    today = campus_today()
    if not today - timedelta(days=370) <= day <= today:
        raise HTTPException(422, 'Отметка посещаемости относится к прошедшему учебному дню')
