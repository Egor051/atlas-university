"""Student calendar assembled from the session's own group and registrations."""
from calendar import monthrange
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from .assignment_workflow import effective_due, visible_deadline
from .db import CAMPUS_TZ, Deadline, Grade
from .schedule_calendar import Calendar, KIND, LESSON_KINDS, date_range, occurrence_kind
from .schedule_occurrences import audience, campus_instant, class_data, class_query, legacy_occurrences, local_interval, occurrence_key
from .services_db import CampusEvent, ConsultationBooking, ConsultationSlot, EventRegistration
from .session_security import as_utc
from .units_db import CenterEnrollment, CenterSession
from .workspace_db import (AcademicGroup, AcademicSubgroup, GroupMember, GroupWork,
                           ScheduleCalendarAlert, ScheduleDismissal, ScheduledClass, WorkDelivery)

ScheduleView = Literal['week', 'month']


def view_bounds(target, view):
    if view == 'month':
        start = target.replace(day=1)
        end = target.replace(day=monthrange(target.year, target.month)[1])
        return start-timedelta(days=start.weekday()), end+timedelta(days=6-end.weekday())
    monday = target-timedelta(days=target.weekday())
    return monday, monday+timedelta(days=6)


def change_summary(item, previous, action):
    if action == 'create':
        return 'Добавлено', 'Опубликовано новое событие'
    if action == 'cancel':
        return 'Отменено', 'Занятие не состоится'
    if action == 'restore':
        return 'Восстановлено', 'Занятие состоится'
    if not previous:
        return 'Изменено', 'Обновлены сведения о занятии'
    fields = [(('day',), 'дата'), (('start', 'end'), 'время'), (('room',), 'аудитория или формат'),
              (('teacher',), 'преподаватель'), (('kind',), 'вид занятия'), (('title',), 'название')]
    current = {**item, 'kind': occurrence_kind(item['kind']), 'title': item.get('title') or ''}
    before = {**previous, 'kind': occurrence_kind(previous['kind']), 'title': previous.get('title') or ''}
    names = [name for keys, name in fields if any(current.get(key) != before.get(key) for key in keys)]
    moved = any(current[key] != before[key] for key in ('day', 'start', 'end'))
    if len(names) == 1:
        summary = ('Изменена ' if names[0] in {'дата', 'аудитория или формат'} else
                   'Изменён ' if names[0] in {'преподаватель', 'вид занятия'} else 'Изменено ') + names[0]
    else:
        summary = 'Изменения: ' + ', '.join(names) if names else 'Обновлены сведения о занятии'
    return 'Перенесено' if moved else 'Изменено', summary


def student_item(data, subgroup=None):
    legacy = bool(data.get('legacy_day'))
    before = data.get('previous')
    key = data.get('change_key')
    action = data.get('change_action')
    change = None
    if key:
        label, summary = change_summary(data, before, action)
        previous = None
        if before:
            previous = {field: before.get(field) for field in ('day', 'start', 'end', 'room', 'teacher', 'status')}
            previous['kind'] = KIND[occurrence_kind(before.get('kind', data['kind']))]
            previous['title'] = before.get('title') or before.get('discipline') or data['discipline']
        change = dict(key=key, label=label, summary=summary, previous=previous)
    code = data['kind']
    return dict(
        id=data['id'] if legacy else 1_000_000_000 + data['id'], uid=occurrence_key(data),
        date=data['day'], end_date=data['day'], start=data['start'], end=data['end'],
        title=data.get('title') or data['discipline'], subject=data['discipline'], discipline_id=data.get('discipline_id'),
        kind=KIND[code], type=code,
        is_lesson=code in LESSON_KINDS, room=data['room'], teacher=data['teacher'], group=data['group'],
        subgroup=data.get('subgroup') or (subgroup if legacy else None), individual=data.get('student_id') is not None and not legacy,
        format=data.get('delivery') or ('online' if data['room'].casefold() == 'онлайн' else 'room'),
        color='violet', status=data['status'], version=data['version'], changed=bool(change), change=change, note=data['note'],
        calendar_exception=data.get('calendar_exception') or '',
        original_room=before['room'] if before else None, original_start=before['start'] if before else None,
        original_end=before['end'] if before else None,
    )


def external_item(source, key, start, end, title, room, *, teacher='', status='active', version=1):
    day, starts, ends = local_interval(start, end)
    change = None
    if source == 'vuc' and version > 1:
        label = 'Отменено' if status == 'cancelled' else 'Изменено'
        change = dict(key=f'{source}:{key}:{version}', label=label, summary='Расписание ВУЦ обновлено', previous=None)
    return dict(
        id={'consultation': 2, 'campus': 3, 'vuc': 4}[source]*1_000_000_000+key, uid=f'{source}-{key}',
        date=day, end_date=as_utc(end).astimezone(CAMPUS_TZ).date().isoformat(),
        start=starts, end=ends, title=title, kind=KIND[source], type=source, is_lesson=False, room=room, teacher=teacher,
        color='violet', status=status, version=version, changed=bool(change), change=change, note='',
    )


def registered_items(db, user, start, end):
    consultations = select(ConsultationSlot).join(ConsultationBooking).where(
        ConsultationBooking.student_id == user.id, ConsultationBooking.status == 'active',
        ConsultationSlot.start_at >= start, ConsultationSlot.start_at < end)
    for row in db.scalars(consultations).unique():
        yield external_item('consultation', row.id, row.start_at, row.end_at, row.subject, row.room, teacher=row.teacher)
    events = select(CampusEvent).join(EventRegistration).where(
        EventRegistration.student_id == user.id, EventRegistration.status == 'active',
        CampusEvent.start_at >= start, CampusEvent.start_at < end)
    for row in db.scalars(events).unique():
        yield external_item('campus', row.id, row.start_at, row.end_at, row.title, row.location)
    sessions = select(CenterSession).where(CenterSession.group_id.in_(
        select(CenterEnrollment.group_id).where(CenterEnrollment.student_id == user.id)),
        CenterSession.starts_at >= start, CenterSession.starts_at < end)
    for row in db.scalars(sessions):
        yield external_item('vuc', row.id, row.starts_at, row.ends_at, row.title, row.room,
                            status='cancelled' if row.cancelled else 'active', version=row.version)


def deadline_markers(db, user, first, last):
    rows = db.execute(select(Deadline, WorkDelivery, GroupWork)
                      .outerjoin(WorkDelivery, WorkDelivery.deadline_id == Deadline.id)
                      .outerjoin(GroupWork, GroupWork.id == WorkDelivery.work_id).where(
                          Deadline.student_id == user.id, Deadline.due_date.between(first, last), visible_deadline()))
    for row, delivery, work in rows:
        has_time = bool((delivery and (delivery.extended_until or delivery.individual_due_at or delivery.revision_due_at))
                        or (work and work.due_at))
        clock = effective_due(row, delivery, work).astimezone(CAMPUS_TZ).strftime('%H:%M') if has_time else None
        yield str(row.due_date), dict(id=row.id, type='deadline', kind=KIND['deadline'], title=row.title,
                                      subject=row.subject, time=clock, done=row.is_done)


def student_days(db, user, first, last, *, markers=True):
    member = db.get(GroupMember, user.id)
    group = db.get(AcademicGroup, member.group_id) if member else None
    subgroup = db.get(AcademicSubgroup, member.subgroup_id) if member and member.subgroup_id else None
    calendar = Calendar(db, first, last)
    days = {str(day): dict(date=str(day), items=[], markers=[], moves=[], calendar_changes=[], reason=calendar.day(day, group).payload())
            for day in date_range(first, last)}
    start, end = campus_instant(first), campus_instant(last+timedelta(days=1))
    managed = class_query().where(or_(
        (ScheduledClass.starts_at >= start) & (ScheduledClass.starts_at < end),
        ScheduledClass.previous_day.between(first, last) if markers else False,
    ))
    dated = []
    for row in db.scalars(audience(managed, member, user.id)):
        item = class_data(row)
        action = row.change_action or ('cancel' if row.status == 'cancelled' else 'update' if row.version > 1 else '')
        if action:
            item.update(previous=row.previous, move_day=str(row.previous_day) if row.previous_day else None,
                        change_action=action, change_key=f'class:{row.id}:{row.version}')
        dated.append(item)
    dated.extend(legacy_occurrences(db, first, last, student_id=user.id, calendar=calendar, include_moved=markers))
    assessments = set()
    for data in dated:
        item = student_item(data, subgroup.code if subgroup else None)
        previous = item['change']['previous'] if item['change'] else None
        if item['date'] in days:
            days[item['date']]['items'].append(item)
        origins = {data.get('move_day'), data.get('legacy_day'), previous['day'] if previous else None}
        origins.discard(item['date'])
        if markers and item['change']:
            for origin in origins.intersection(days):
                days[origin]['moves'].append(dict(
                    id=item['id'], uid=item['uid'], date=item['date'], title=item['title'], change=item['change'],
                    status=item['status'],
                ))
        if item['type'] in {'exam', 'credit'}:
            assessments.add((item['date'], item['subject'], item['type']))
            assessments.update((origin, item['subject'], item['type']) for origin in origins if origin)
    for item in registered_items(db, user, start, end):
        days[item['date']]['items'].append(item)
    if markers:
        if group:
            alerts = db.scalars(select(ScheduleCalendarAlert).where(
                ScheduleCalendarAlert.group_id == group.id, ScheduleCalendarAlert.starts_on <= last,
                ScheduleCalendarAlert.ends_on >= first).order_by(ScheduleCalendarAlert.id.desc()))
            for alert in alerts:
                shown = next((day for day in alert.days if day in days), None)
                if shown:
                    days[shown]['calendar_changes'].append(dict(key=f'calendar:{alert.id}', id=None, date=shown,
                                                               title='Учебный календарь обновлён', uid=None))
        for day, item in deadline_markers(db, user, first, last):
            days[day]['markers'].append(item)
        for row in db.scalars(select(Grade).where(Grade.student_id == user.id, Grade.exam_date.between(first, last))):
            code = 'credit' if row.kind == 'credit' or row.exam_kind == 'Зачёт' else 'exam'
            if (str(row.exam_date), row.subject, code) not in assessments:
                days[str(row.exam_date)]['markers'].append(dict(id=row.id, type=code, kind=KIND[code],
                                                                title=row.subject, time=None))
    for day in days.values():
        day['items'].sort(key=lambda item: (item['start'], item['uid']))
        day['markers'].sort(key=lambda item: (item['time'] or '', item['type'], item['id']))
    return list(days.values())


def change_entries(days):
    entries = {}
    for day in days:
        for entry in day['calendar_changes']:
            entries.setdefault(entry['key'], entry)
        for item in day['items'] + day['moves']:
            if item['change']:
                key = item['change']['key']
                entries.setdefault(key, dict(key=key, id=item['id'], date=item['date'], title=item['title'], uid=item['uid']))
    return list(entries.values())


def unseen_changes(db, student_id, days):
    entries = change_entries(days)
    if not entries:
        return []
    dismissed = set(db.scalars(select(ScheduleDismissal.change_key).where(
        ScheduleDismissal.student_id == student_id, ScheduleDismissal.change_key.in_([row['key'] for row in entries]))))
    return [row for row in entries if row['key'] not in dismissed]
