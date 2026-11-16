"""Common occurrence data for approved events and the bounded legacy timetable."""
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from .db import CAMPUS_TZ, Lesson, LessonChange, campus_today
from .schedule_calendar import Calendar, KIND, MAX_DATE, MIN_DATE, date_range, occurrence_kind
from .session_security import as_utc
from .university_db import Teacher
from .workspace_db import AcademicGroup, GroupMember, LegacyClassOverride, ScheduledClass, TeachingLoad


def campus_instant(day, clock='00:00'):
    return datetime.combine(day, time.fromisoformat(clock), CAMPUS_TZ).astimezone(timezone.utc)


def check_date(day):
    if not MIN_DATE <= day <= MAX_DATE:
        raise HTTPException(422, 'Дата должна быть в пределах 2000–2099 годов')
    return day


def week_bounds(week):
    day = check_date(week or campus_today())
    monday = day - timedelta(days=day.weekday())
    return monday, campus_instant(monday), campus_instant(monday + timedelta(days=7))


def class_query():
    return select(ScheduledClass).options(joinedload(ScheduledClass.room), joinedload(ScheduledClass.subgroup),
           joinedload(ScheduledClass.teacher).joinedload(Teacher.user),
           joinedload(ScheduledClass.load).joinedload(TeachingLoad.discipline),
           joinedload(ScheduledClass.load).joinedload(TeachingLoad.group))


def local_interval(start, end):
    start, end = (as_utc(value).astimezone(CAMPUS_TZ) for value in (start, end))
    return start.date().isoformat(), start.strftime('%H:%M'), end.strftime('%H:%M')


def class_data(row):
    day, start, end = local_interval(row.starts_at, row.ends_at)
    kind = occurrence_kind(row.kind)
    return dict(
        id=row.id, load_id=row.load_id, group_id=row.group_id, group=row.load.group.code,
        subgroup_id=row.subgroup_id, subgroup=row.subgroup.code if row.subgroup else None,
        student_id=row.student_id, teacher_id=row.teacher_id, teacher=row.teacher.user.full_name,
        room_id=row.room_id, room=row.room.code, delivery='online' if row.room.kind == 'online' else 'room',
        day=day, start=start, end=end, discipline_id=row.load.discipline_id, discipline=row.load.discipline.title, title=row.title,
        kind=kind, kind_label=KIND[kind], equipment=row.equipment, note=row.note, status=row.status,
        version=row.version, series=row.series, calendar_exception=row.calendar_exception,
    )


def lesson_query():
    return (select(Lesson, AcademicGroup, GroupMember.subgroup_id)
            .outerjoin(GroupMember, GroupMember.student_id == Lesson.student_id)
            .outerjoin(AcademicGroup, AcademicGroup.id == GroupMember.group_id))


def legacy_data(lesson, group, subgroup_id, day, change, override):
    kind = occurrence_kind(lesson.kind)
    code = group.code if group else ''
    group_id = group.id if group else None
    data = dict(id=lesson.id, legacy_day=day.isoformat(), day=day.isoformat(), group=code,
                group_id=group_id, subgroup_id=subgroup_id, student_id=lesson.student_id,
                start=lesson.start_time, end=lesson.end_time, room=lesson.room, teacher=lesson.teacher,
                discipline=lesson.title, kind=kind, kind_label=KIND[kind], note='', status='active',
                version=1, calendar_exception='')
    if override:
        return {**data, 'day': override.day.isoformat(), 'start': override.start, 'end': override.end,
                'room': override.room, 'teacher': override.teacher, 'status': override.status, 'note': override.note,
                'version': override.version, 'calendar_exception': override.calendar_exception,
                'previous': override.previous, 'change_action': override.change_action,
                'change_key': f'legacy:{lesson.id}:{day}:{override.version}'}
    if change:
        start = change.new_start or data['start']
        duration = campus_instant(day, data['end']) - campus_instant(day, data['start'])
        end = (datetime.combine(day, time.fromisoformat(start)) + duration).strftime('%H:%M')
        stamp = sha256(repr((start, change.new_room, change.note)).encode()).hexdigest()[:16]
        return {**data, 'start': start, 'end': end, 'room': change.new_room or data['room'], 'note': change.note,
                'previous': data, 'change_action': 'update', 'change_key': f'legacy-import:{change.id}:{stamp}'}
    return data


def legacy_occurrences(db, first, last, *, student_id=None, calendar=None, include_moved=False):
    scope = lesson_query()
    if student_id is not None:
        scope = scope.where(Lesson.student_id == student_id)
    lessons = {row[0].id: row for row in db.execute(scope)}
    if not lessons:
        return
    calendar = calendar or Calendar(db, first, last)
    overrides = list(db.scalars(select(LegacyClassOverride).where(
        LegacyClassOverride.lesson_id.in_(lessons),
        or_(LegacyClassOverride.original_day.between(first, last), LegacyClassOverride.day.between(first, last),
            LegacyClassOverride.previous_day.between(first, last) if include_moved else False))))
    overridden = {(row.lesson_id, row.original_day) for row in overrides}
    dated = {(row.lesson_id, row.day): row for row in db.scalars(select(LessonChange).where(
        LessonChange.lesson_id.in_(lessons), LessonChange.day.between(first, last)).order_by(LessonChange.id))
        if lessons[row.lesson_id][0].student_id == row.student_id}
    for day in date_range(first, last):
        for lesson, group, subgroup_id in lessons.values():
            key = (lesson.id, day)
            if lesson.weekday == day.weekday() and key not in overridden and calendar.day(day, group).legacy:
                yield legacy_data(lesson, group, subgroup_id, day, dated.get(key), None)
    for row in overrides:
        if first <= row.day <= last or (include_moved and (
                first <= row.previous_day <= last or first <= row.original_day <= last)):
            yield legacy_data(*lessons[row.lesson_id], row.original_day, None, row)


def legacy_record(db, lesson_id, day):
    lesson = db.execute(lesson_query().where(Lesson.id == lesson_id)).first()
    if lesson is None:
        return None, None
    override = db.scalar(select(LegacyClassOverride).where(
        LegacyClassOverride.lesson_id == lesson_id, LegacyClassOverride.original_day == day))
    if override:
        return legacy_data(*lesson, day, None, override), override
    template, group, _ = lesson
    if template.weekday != day.weekday() or not Calendar(db, day, day).day(day, group).legacy:
        return None, None
    change = db.scalar(select(LessonChange).where(LessonChange.lesson_id == lesson_id,
                       LessonChange.student_id == template.student_id, LessonChange.day == day)
                       .order_by(LessonChange.id.desc()).limit(1))
    return legacy_data(*lesson, day, change, None), None


def occurrence_key(item):
    if item.get('legacy_day'):
        return f"lesson-{item['id']}-{item['legacy_day']}"
    return f"event-{item['id']}"


def managed_occurrence(row):
    item = class_data(row)
    item.update(_teacher_user_id=row.teacher.user_id, _ends_at=as_utc(row.ends_at))
    action = row.change_action or ('cancel' if row.status == 'cancelled' else 'update' if row.version > 1 else '')
    if action:
        item.update(previous=row.previous, move_day=str(row.previous_day) if row.previous_day else None,
                    change_action=action, change_key=f'class:{row.id}:{row.version}')
    return item


def student_occurrences(db, student_id, member, first, last, calendar, *, include_moved=False):
    start, end = campus_instant(first), campus_instant(last + timedelta(days=1))
    managed = class_query().where(or_(
        (ScheduledClass.starts_at >= start) & (ScheduledClass.starts_at < end),
        ScheduledClass.previous_day.between(first, last) if include_moved else False,
    ))
    for row in db.scalars(audience(managed, member, student_id)):
        yield managed_occurrence(row)
    yield from legacy_occurrences(db, first, last, student_id=student_id, calendar=calendar, include_moved=include_moved)


def audience(query, member, user_id):
    if member is None:
        return query.where(ScheduledClass.student_id == user_id)
    in_group = (ScheduledClass.group_id == member.group_id) & ScheduledClass.student_id.is_(None)
    in_subgroup = or_(ScheduledClass.subgroup_id.is_(None), ScheduledClass.subgroup_id == member.subgroup_id)
    return query.where(or_(ScheduledClass.student_id == user_id, in_group & in_subgroup))
