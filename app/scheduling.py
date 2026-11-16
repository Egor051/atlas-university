"""Room and timetable operations. Only approved occurrences enter a timetable."""
from datetime import date, timedelta
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .db import CAMPUS_TZ, User, utc_now
from .main import StrictBody, date_iso, get_db, require_roles, require_same_origin
from .schedule_calendar import Calendar, KIND, LESSON_KINDS, occurrence_kind
from .schedule_occurrences import (campus_instant, check_date, class_data, class_query, legacy_occurrences,
                                  legacy_record, local_interval, occurrence_key, week_bounds)
from .services import begin_idempotent, commit_idempotent
from .services_db import ConsultationBooking, ConsultationSlot
from .session_security import as_utc
from .university_db import Teacher, TeachingAssignment
from .workspace import event_payload, load_payload, load_query, lock_workspace, notify, recorded
from .workspace_db import (AcademicGroup, AcademicSubgroup, Classroom, GroupMember, LegacyClassOverride,
                           OperationEvent, ScheduleChange, ScheduledClass, TeachingLoad)

router = APIRouter(prefix='/api')
view_schedule = require_roles('scheduler', 'staff', 'admin')
dispatcher = require_roles('scheduler')
teacher_only = require_roles('teacher')
write = [Depends(require_same_origin)]
ChangeAction = Literal['create', 'update', 'cancel', 'restore']
EventKind = Literal['lecture', 'seminar', 'practice', 'lab', 'consultation', 'credit', 'exam', 'retake', 'organization', 'other']
CLOCK = r'^(?:[01]\d|2[0-3]):[0-5]\d$'


class SlotBody(StrictBody):
    load_id: int = Field(strict=True, ge=1)
    teacher_id: int = Field(strict=True, ge=1)
    room_id: int = Field(strict=True, ge=1)
    day: date
    start: str = Field(pattern=CLOCK)
    end: str = Field(pattern=CLOCK)
    kind: EventKind
    equipment: str = Field(default='', max_length=160)
    weeks: int = Field(default=1, strict=True, ge=1, le=32)
    interval: int = Field(default=1, strict=True, ge=1, le=4)
    subgroup_id: int | None = Field(default=None, strict=True, ge=1)
    student_id: int | None = Field(default=None, strict=True, ge=1)
    title: str = Field(default='', max_length=180)
    calendar_exception: str = Field(default='', max_length=300)


class LegacySlot(StrictBody):
    day: date
    start: str = Field(pattern=CLOCK)
    end: str = Field(pattern=CLOCK)
    room: str = Field(min_length=1, max_length=80)
    teacher: str = Field(min_length=1, max_length=120)
    calendar_exception: str = Field(default='', max_length=300)


class LegacyReference(StrictBody):
    id: int = Field(strict=True, ge=1)
    day: date


class ChangeBody(StrictBody):
    action: ChangeAction
    event_id: int | None = Field(default=None, strict=True, ge=1)
    event_version: int | None = Field(default=None, strict=True, ge=1)
    slot: SlotBody | LegacySlot | None = None
    legacy: LegacyReference | None = None
    note: str = Field(default='', max_length=300)

    @model_validator(mode='after')
    def valid_shape(self):
        if self.action == 'create':
            if self.event_id is not None or self.event_version is not None or self.legacy or not isinstance(self.slot, SlotBody):
                raise ValueError('Для нового занятия укажите параметры занятия')
        elif (self.event_id is None) == (self.legacy is None) or self.event_version is None:
            raise ValueError('Укажите занятие и его версию')
        elif self.action == 'update':
            valid = isinstance(self.slot, LegacySlot) if self.legacy else isinstance(self.slot, SlotBody) and self.slot.weeks == 1
            if not valid:
                raise ValueError('Перенос применяется к выбранному занятию')
        elif self.slot is not None or (self.action == 'cancel' and len(self.note.strip()) < 3):
            raise ValueError('Укажите причину отмены или восстановите исходные параметры')
        return self


class EditChange(ChangeBody):
    version: int = Field(strict=True, ge=1)


class StepBody(StrictBody):
    step: Literal['submit', 'agree', 'return', 'publish']
    version: int = Field(strict=True, ge=1)
    comment: str = Field(default='', max_length=300)


def tokens(value):
    return {part.strip().casefold() for part in value.split(',') if part.strip()}


def room_problems(room, group, kind, equipment, *, capacity=None):
    return [
        message for problem, message in (
            (not room.available, 'Аудитория недоступна'),
            (room.kind != 'online' and room.capacity < (capacity or group.capacity), 'В аудитории недостаточно мест'),
            (group.accessible and not room.accessible, 'Для группы требуется безбарьерный доступ'),
            (kind == 'lab' and room.kind not in {'lab', 'online'}, 'Для лабораторной работы нужна лаборатория'),
            (not tokens(equipment) <= tokens(room.equipment), 'В аудитории нет требуемого оборудования'),
        ) if problem
    ]


def aliases(teacher):
    name = teacher.user.full_name.split()
    return {teacher.user.full_name, f'{name[0][0]}. {name[-1]}'} if name else {''}


def teacher_has_consultation(db, teacher, start, end):
    return db.scalar(select(ConsultationSlot.id).where(ConsultationSlot.teacher.in_(aliases(teacher)),
                     ConsultationSlot.start_at < end, ConsultationSlot.end_at > start).limit(1)) is not None


def matching_room(db, column, code):
    folded = func.casefold(column) if db.get_bind().dialect.name == 'sqlite' else func.lower(column)
    return folded == code.casefold()


def room_consultations(db, code, start, end):
    return select(ConsultationSlot).where(matching_room(db, ConsultationSlot.room, code),
                                         ConsultationSlot.start_at < end, ConsultationSlot.end_at > start)


def legacy_intervals(db, start, end):
    first = start.astimezone(CAMPUS_TZ).date()
    last = end.astimezone(CAMPUS_TZ).date()
    for item in legacy_occurrences(db, first, last):
        day = date.fromisoformat(item['day'])
        if item['status'] == 'active' and campus_instant(day, item['start']) < end and campus_instant(day, item['end']) > start:
            yield item


def teacher_is_busy(db, teacher, start, end):
    if teacher_has_consultation(db, teacher, start, end) or db.scalar(select(ScheduledClass.id).where(
            ScheduledClass.status == 'active', ScheduledClass.teacher_id == teacher.id, ScheduledClass.starts_at < end,
            ScheduledClass.ends_at > start).limit(1)) is not None:
        return True
    names = aliases(teacher)
    return any(row['teacher'] in names for row in legacy_intervals(db, start, end))


def room_is_busy(db, room, start, end):
    if room.kind == 'online':
        return False
    class_overlap = select(ScheduledClass.id).where(
            ScheduledClass.status == 'active', ScheduledClass.room_id == room.id, ScheduledClass.starts_at < end,
            ScheduledClass.ends_at > start)
    if db.scalar(class_overlap.limit(1)) is not None or db.scalar(room_consultations(db, room.code, start, end).limit(1)) is not None:
        return True
    return any(row['room'].casefold() == room.code.casefold() for row in legacy_intervals(db, start, end))


def existing_class(db, change):
    if change.event_id is None:
        return None
    event = db.scalar(class_query().where(ScheduledClass.id == change.event_id))
    if event is None:
        raise HTTPException(404, 'Занятие не найдено')
    check_event_version(change, event.version, event.status)
    if as_utc(event.ends_at) < utc_now():
        raise HTTPException(409, 'Занятие уже завершилось')
    return event


def check_event_version(change, version, status):
    expected = 'cancelled' if change.action == 'restore' else 'active'
    if version != change.event_version or status != expected:
        raise HTTPException(409, 'Версия или состояние занятия уже изменились')


def recipients(db, event):
    if event.get('student_id'):
        return {event['student_id']}
    query = select(GroupMember.student_id).where(GroupMember.group_id == event['group_id'])
    if event.get('subgroup_id'):
        query = query.where(GroupMember.subgroup_id == event['subgroup_id'])
    return set(db.scalars(query))


def intersects(db, first, second):
    if first['group_id'] != second['group_id']:
        return False
    student, other = first.get('student_id'), second.get('student_id')
    subgroup, other_group = first.get('subgroup_id'), second.get('subgroup_id')
    if student and other:
        return student == other
    if student or other:
        section = other_group if student else subgroup
        member = db.get(GroupMember, student or other) if section else None
        return not section or bool(member and member.subgroup_id == section)
    return not subgroup or not other_group or subgroup == other_group


def collision_reasons(db, start, end, target, teacher_names, room, event_id=None, legacy_key=None, queued=()):
    teacher_id = target.get('teacher_id')
    physical_room = room is not None and room.casefold() != 'онлайн'
    scope = (ScheduledClass.status == 'active', ScheduledClass.starts_at < end, ScheduledClass.ends_at > start)
    query = class_query().where(*scope)
    if event_id is not None:
        query = query.where(ScheduledClass.id != event_id)
    occupied = [class_data(row) for row in db.scalars(query)]
    occupied.extend(row for row in queued if row['starts_at'] < end and row['ends_at'] > start)
    occupied.extend(row for row in legacy_intervals(db, start, end) if occurrence_key(row) != legacy_key)
    group_busy = any(intersects(db, target, row) for row in occupied)
    teacher_busy = any((teacher_id is not None and row.get('teacher_id') == teacher_id) or row['teacher'] in teacher_names
                       for row in occupied)
    room_busy = physical_room and any(row['room'].casefold() == room.casefold() for row in occupied)
    consultation = select(ConsultationSlot.id).where(ConsultationSlot.start_at < end, ConsultationSlot.end_at > start)
    teacher_busy |= db.scalar(consultation.where(ConsultationSlot.teacher.in_(teacher_names)).limit(1)) is not None
    if physical_room:
        room_busy |= db.scalar(consultation.where(matching_room(db, ConsultationSlot.room, room)).limit(1)) is not None
    if not group_busy:
        booked = consultation.join(ConsultationBooking).where(
            ConsultationBooking.status == 'active', ConsultationBooking.student_id.in_(recipients(db, target)))
        group_busy = db.scalar(booked.limit(1)) is not None
    return [message for flag, message in (
        (group_busy, 'у участников уже есть занятие или запись на консультацию'),
        (teacher_busy, 'преподаватель занят'), (room_busy, 'аудитория занята'),
    ) if flag]


def time_interval(day, start, end):
    check_date(day)
    start_at, end_at = campus_instant(day, start), campus_instant(day, end)
    if start_at <= utc_now() or not timedelta(minutes=15) <= end_at-start_at <= timedelta(hours=6):
        raise HTTPException(422, 'Укажите будущее время и продолжительность от 15 минут до 6 часов')
    return start_at, end_at


def validate_legacy(db, change):
    ref = change.legacy
    previous, override = legacy_record(db, ref.id, check_date(ref.day))
    if previous is None:
        raise HTTPException(404, 'Занятие не найдено')
    check_event_version(change, previous['version'], previous['status'])
    old_day = date.fromisoformat(previous['day'])
    if campus_instant(old_day, previous['end']) <= utc_now():
        raise HTTPException(409, 'Занятие уже завершилось')
    fields = {name: previous[name] for name in ('start', 'end', 'teacher', 'room', 'calendar_exception')}
    if change.slot:
        fields.update(change.slot.model_dump(exclude={'day'}))
    day = change.slot.day if change.slot else old_day
    if change.action != 'cancel':
        fields = {name: value.strip() for name, value in fields.items()}
        if not fields['room'] or not fields['teacher']:
            raise HTTPException(422, 'Укажите преподавателя и аудиторию или формат')
        if fields['calendar_exception'] and len(fields['calendar_exception']) < 3:
            raise HTTPException(422, 'Укажите основание исключения из календаря')
        member = db.get(GroupMember, previous['student_id'])
        group = db.get(AcademicGroup, member.group_id) if member else None
        rule = Calendar(db, day, day).day(day, group)
        if rule.code != 'teaching' and not fields['calendar_exception']:
            raise HTTPException(422, 'На эту дату учебные занятия не предусмотрены календарём')
        start, end = time_interval(day, fields['start'], fields['end'])
        names = {fields['teacher']}
        for teacher in db.scalars(select(Teacher).options(joinedload(Teacher.user))):
            if fields['teacher'] in aliases(teacher):
                names.update(aliases(teacher))
        conflicts = collision_reasons(db, start, end, previous, names, fields['room'], legacy_key=occurrence_key(previous))
        if conflicts:
            raise HTTPException(409, ', '.join(conflicts))
    return previous, override, dict(**fields, day=day, previous_day=old_day, status='cancelled' if change.action == 'cancel' else 'active',
                                    note=change.note.strip(), version=previous['version'] + 1, change_action=change.action,
                                    previous={key: value for key, value in previous.items()
                                              if key not in {'previous', 'change_action', 'change_key'}})


def validate_change(db, change, queued=()):
    if change.legacy:
        return validate_legacy(db, change)
    event = existing_class(db, change)
    if change.action == 'cancel':
        return event, []
    body = change.slot
    if body is None:
        data = class_data(event)
        body = SlotBody(**{name: data[name] for name in SlotBody.model_fields if name in data})
    load = db.scalar(load_query().where(TeachingLoad.id == body.load_id))
    teacher = db.scalar(select(Teacher).options(joinedload(Teacher.user)).where(Teacher.id == body.teacher_id))
    room = db.get(Classroom, body.room_id)
    if load is None or teacher is None or room is None:
        raise HTTPException(404, 'Назначение, преподаватель или аудитория не найдены')
    if event and (body.load_id, body.subgroup_id, body.student_id) != (event.load_id, event.subgroup_id, event.student_id):
        raise HTTPException(422, 'Учебное назначение и участники сохраняются при переносе')
    if body.subgroup_id and body.student_id:
        raise HTTPException(422, 'Выберите подгруппу или одного студента')
    subgroup = db.get(AcademicSubgroup, body.subgroup_id) if body.subgroup_id else None
    if body.subgroup_id and (subgroup is None or subgroup.group_id != load.group_id):
        raise HTTPException(404, 'Подгруппа не найдена в этой группе')
    if body.student_id:
        member = db.get(GroupMember, body.student_id)
        if member is None or member.group_id != load.group_id:
            raise HTTPException(404, 'Студент не найден в этой группе')
    if db.scalar(select(TeachingAssignment.id).where(TeachingAssignment.teacher_id == teacher.id,
                 TeachingAssignment.discipline_id == load.discipline_id)) is None:
        raise HTTPException(422, 'У преподавателя нет назначения на эту дисциплину')
    kind = occurrence_kind(body.kind)
    if kind in {'organization', 'other'} and not body.title.strip():
        raise HTTPException(422, 'Укажите название мероприятия')
    capacity = subgroup.capacity if subgroup else 1 if body.student_id else load.group.capacity
    problems = room_problems(room, load.group, kind, body.equipment, capacity=capacity)
    if problems:
        raise HTTPException(422, '. '.join(problems))
    exception = body.calendar_exception.strip()
    if exception and (body.weeks != 1 or len(exception) < 3):
        raise HTTPException(422, 'Исключение с основанием применяется к одному занятию')
    if body.weeks > 1 and kind not in LESSON_KINDS:
        raise HTTPException(422, 'Для специального мероприятия укажите одну дату')
    first = check_date(body.day)
    last = check_date(body.day + timedelta(weeks=(body.weeks-1)*body.interval))
    calendar = Calendar(db, first, last)
    term = calendar.term(first, load.group)
    if body.weeks > 1 and term is None:
        raise HTTPException(422, 'Для серии сначала опубликуйте семестр')
    target = dict(group_id=load.group_id, subgroup_id=body.subgroup_id, student_id=body.student_id,
                  teacher_id=teacher.id, room_id=room.id)
    intervals = []
    for week in range(body.weeks):
        day = first + timedelta(weeks=week*body.interval)
        state = calendar.day(day, load.group)
        if body.weeks > 1 and state.term != term:
            raise HTTPException(422, 'Повторения должны попадать в один семестр')
        if kind in LESSON_KINDS and state.code != 'teaching' and not exception:
            if body.weeks > 1:
                continue
            raise HTTPException(422, f'{day:%d.%m.%Y} — {state.payload()["label"]}. Выберите учебный день или укажите основание исключения.')
        start, end = time_interval(day, body.start, body.end)
        conflicts = collision_reasons(db, start, end, target, aliases(teacher), room.code if room.kind != 'online' else None,
                                      event_id=event.id if event else None, queued=queued)
        if conflicts:
            raise HTTPException(409, f'{day.strftime("%d.%m.%Y")} — ' + ', '.join(conflicts))
        intervals.append(dict(**target, load_id=load.id, starts_at=start, ends_at=end, kind=kind,
                              equipment=body.equipment, note=change.note.strip(), title=body.title.strip(),
                              calendar_exception=exception, room=room.code, teacher=teacher.user.full_name))
    if not intervals:
        raise HTTPException(422, 'В заданном интервале нет учебных дней для серии')
    return event, intervals


def change_data(row):
    return dict(id=row.id, version=row.version, state=row.state, action=row.action, author_id=row.author_id,
                event_id=row.event_id, change=json.loads(row.payload), updated_at=date_iso(row.updated_at))


def create_draft(db, user, body, *, checked=False):
    if not checked:
        validate_change(db, body)
    row = ScheduleChange(author_id=user.id, state='draft', action=body.action, event_id=body.event_id,
                         payload=body.model_dump_json(), created_at=utc_now(), updated_at=utc_now())
    db.add(row)
    db.flush()
    recorded(db, user, 'schedule', row.id, 'created', after=change_data(row))
    return row


def require_change(db, change_id):
    row = db.get(ScheduleChange, change_id)
    if row is None:
        raise HTTPException(404, 'Проект изменения не найден')
    return row


def publish_change(db, row, body):
    if body.legacy:
        before, override, fields = validate_legacy(db, body)
        if override is None:
            override = LegacyClassOverride(lesson_id=body.legacy.id, original_day=body.legacy.day, **fields)
            db.add(override)
        else:
            for key, value in fields.items():
                setattr(override, key, value)
        db.flush()
        data, _ = legacy_record(db, body.legacy.id, body.legacy.day)
        affected_teachers = {teacher.user_id for teacher in db.scalars(select(Teacher).options(joinedload(Teacher.user)))
                             if aliases(teacher).intersection({data['teacher'], before['teacher']})}
        notify_publication(db, body.action, [data], affected_teachers)
        return {'previous': fields['previous'], 'published': [data]}
    previous, intervals = validate_change(db, body)
    before = class_data(previous) if previous else None
    old_teacher = previous.teacher.user_id if previous else None
    intervals = [{key: value for key, value in fields.items() if key not in {'room', 'teacher'}}
                 for fields in intervals]
    if body.action == 'cancel':
        previous.status, previous.note = 'cancelled', body.note.strip()
    elif previous:
        for key, value in intervals[0].items():
            setattr(previous, key, value)
        previous.status = 'active'
    if previous:
        previous.version += 1
        old_day = date.fromisoformat(before['day'])
        if previous.previous_day is None or old_day != as_utc(previous.starts_at).astimezone(CAMPUS_TZ).date():
            previous.previous_day = old_day
        previous.previous = before
        previous.change_action = body.action
        changed = [previous]
    else:
        series = uuid4().hex
        changed = [ScheduledClass(**fields, series=series, status='active', change_action='create') for fields in intervals]
        db.add_all(changed)
    db.flush()
    if previous:
        db.expire(previous, ['teacher', 'room'])
    first = changed[0]
    row.event_id = first.id
    data = [class_data(event) for event in changed]
    notify_publication(db, body.action, data, {first.teacher.user_id, old_teacher}-{None})
    return {'previous': before, 'published': data}


def notify_publication(db, action, events, teachers):
    from .absence_certificates import notify_reassigned_reviews

    title = {'create': 'Опубликовано занятие', 'update': 'Расписание изменилось',
             'cancel': 'Занятие отменено', 'restore': 'Занятие восстановлено'}[action]
    data = events[0]
    message = f"{data.get('title') or data['discipline']} · {data['day']} · {data['start']} МСК"
    if len(events) > 1:
        message += f' · занятий в серии: {len(events)}'
    item_id = data['id'] if data.get('legacy_day') else 1_000_000_000 + data['id']
    for student in recipients(db, data):
        notify(db, student, title, message, f"/app/schedule?date={data['day']}&id={item_id}", student=True, category='schedule')
    for teacher in teachers:
        notify(db, teacher, title, message, f"/app/teach-schedule?week={data['day']}", category='schedule')
    if action in {'update', 'restore'}:
        notify_reassigned_reviews(db, events)


@router.get('/scheduling')
def timetable(week: date | None = None, user=Depends(view_schedule), db: Session = Depends(get_db)):
    monday, start, end = week_bounds(week)
    rows = db.scalars(class_query().where(ScheduledClass.starts_at >= start, ScheduledClass.starts_at < end)
                     .order_by(ScheduledClass.starts_at, ScheduledClass.id)).all()
    items = [class_data(row) for row in rows] + list(legacy_occurrences(db, monday, monday+timedelta(days=6)))
    for item in items:
        item['key'] = occurrence_key(item)
    return {'week': monday.isoformat(), 'items': sorted(items, key=lambda row: (row['day'], row['start'], row['group']))}


@router.get('/teaching/schedule')
def own_timetable(week: date | None = None, user=Depends(teacher_only), db: Session = Depends(get_db)):
    monday, start, end = week_bounds(week)
    teacher = db.scalar(select(Teacher).options(joinedload(Teacher.user)).where(Teacher.user_id == user.id))
    if not teacher:
        return {'week': monday.isoformat(), 'items': []}
    rows = db.scalars(class_query().where(ScheduledClass.teacher_id == teacher.id, ScheduledClass.status == 'active',
                                        ScheduledClass.starts_at >= start, ScheduledClass.starts_at < end)).all()
    items = [class_data(row) for row in rows]
    names = aliases(teacher)
    items.extend(row for row in legacy_occurrences(db, monday, monday+timedelta(days=6))
                 if row['teacher'] in names and row['status'] == 'active')
    return {'week': monday.isoformat(), 'items': sorted(items, key=lambda row:(row['day'], row['start'], row['group']))}


@router.get('/scheduling/options')
def options(user=Depends(view_schedule), db: Session = Depends(get_db)):
    loads = db.scalars(load_query().order_by(TeachingLoad.id)).all()
    teachers = db.execute(select(Teacher.id, User.full_name, TeachingAssignment.discipline_id)
                          .join(User, User.id == Teacher.user_id).join(TeachingAssignment, TeachingAssignment.teacher_id == Teacher.id)
                          .order_by(User.full_name)).all()
    return {'loads': [{**load_payload(row), 'discipline_id': row.discipline_id} for row in loads],
            'teachers': [dict(id=key, name=name, discipline_id=discipline) for key, name, discipline in teachers],
            'rooms': [dict(id=row.id, code=row.code, building=row.building, available=row.available,
                           capacity=row.capacity, kind=row.kind) for row in db.scalars(select(Classroom).order_by(Classroom.code))],
            'subgroups': [dict(id=row.id, group_id=row.group_id, code=row.code) for row in
                          db.scalars(select(AcademicSubgroup).order_by(AcademicSubgroup.code))],
            'students': [dict(id=key, group_id=group_id, name=name) for key, group_id, name in
                         db.execute(select(User.id, GroupMember.group_id, User.full_name).join(GroupMember)
                                    .where(User.role == 'student').order_by(User.full_name))] if user.role == 'scheduler' else []}


@router.get('/scheduling/rooms/{room_id}')
def room_calendar(room_id: int, week: date | None = None, user=Depends(view_schedule), db: Session = Depends(get_db)):
    room = db.get(Classroom, room_id)
    if room is None:
        raise HTTPException(404, 'Аудитория не найдена')
    monday, start, end = week_bounds(week)
    rows = db.scalars(class_query().where(ScheduledClass.room_id == room.id, ScheduledClass.status == 'active',
                                         ScheduledClass.starts_at >= start, ScheduledClass.starts_at < end)).all()
    items = [class_data(row) for row in rows]
    items.extend(row for row in legacy_occurrences(db, monday, monday+timedelta(days=6))
                 if row['room'].casefold() == room.code.casefold() and row['status'] == 'active')
    for slot in db.scalars(room_consultations(db, room.code, start, end)):
        day, s, e = local_interval(slot.start_at, slot.end_at)
        items.append(dict(day=day, start=s, end=e,
                          discipline=slot.subject, room=room.code, teacher=slot.teacher, kind_label='Консультация', status='active'))
    return dict(title=room.code, week=monday.isoformat(), items=sorted(items,key=lambda row:(row['day'],row['start'])))


@router.get('/scheduling/changes')
def list_changes(offset: int = Query(0, ge=0, le=2147483647), user=Depends(view_schedule), db: Session = Depends(get_db)):
    rows = db.execute(select(ScheduleChange, User.full_name).join(User, User.id == ScheduleChange.author_id)
                      .order_by(ScheduleChange.id.desc()).offset(offset).limit(31)).all()
    return {'items': [{**change_data(row), 'author': author} for row, author in rows[:30]], 'offset': offset, 'more':len(rows)>30}


@router.get('/scheduling/changes/{change_id}')
def change_detail(change_id: int, user=Depends(view_schedule), db: Session = Depends(get_db)):
    row = require_change(db, change_id)
    history = db.execute(select(OperationEvent, User.full_name).join(User, User.id == OperationEvent.actor_id)
                         .where(OperationEvent.area == 'schedule', OperationEvent.object_id == row.id)
                         .order_by(OperationEvent.id.desc()).limit(50))
    return {**change_data(row), 'history': [event_payload(event, name, date_iso) for event, name in history]}


@router.post('/scheduling/changes', status_code=201, dependencies=write)
def add_change(body: ChangeBody, request: Request, response: Response, user=Depends(dispatcher), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    receipt, prior = begin_idempotent(db, request, response, user, 'schedule-draft', body.model_dump())
    if prior is not None:
        return prior
    return commit_idempotent(db, receipt, change_data(create_draft(db, user, body)))


@router.put('/scheduling/changes/{change_id}', dependencies=write)
def edit_change(change_id: int, body: EditChange, user=Depends(dispatcher), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    row = require_change(db, change_id)
    if row.author_id != user.id:
        raise HTTPException(404, 'Проект изменения не найден')
    if row.version != body.version or row.state not in {'draft','returned'}:
        raise HTTPException(409, 'Проект уже изменился')
    updated = ChangeBody(**body.model_dump(exclude={'version'}))
    validate_change(db, updated)
    before = change_data(row)
    row.action, row.event_id, row.payload = updated.action, updated.event_id, updated.model_dump_json()
    row.version, row.updated_at, row.state = row.version+1, utc_now(), 'draft'
    recorded(db, user, 'schedule', row.id, 'edited', before, change_data(row))
    db.commit()
    return change_data(row)


@router.post('/scheduling/changes/{change_id}/step', dependencies=write)
def change_step(change_id: int, body: StepBody, user=Depends(view_schedule), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    row = require_change(db, change_id)
    rules = {
        'submit': {'scheduler': (('draft','returned'), 'submitted')},
        'agree': {'staff': (('submitted',), 'agreed')},
        'return': {'staff': (('submitted',), 'returned'), 'admin': (('agreed',), 'returned')},
        'publish': {'admin': (('agreed',), 'published')},
    }
    rule = rules[body.step].get(user.role)
    if not rule or (body.step == 'submit' and row.author_id != user.id):
        raise HTTPException(403, 'Этот этап выполняет другая роль')
    if body.version != row.version or row.state not in rule[0]:
        raise HTTPException(409, 'Проект изменился или переход недоступен')
    if body.step == 'return' and len(body.comment.strip())<3:
        raise HTTPException(422, 'Укажите причину возврата')
    before = change_data(row)
    change = ChangeBody.model_validate_json(row.payload)
    effects = None
    if body.step == 'publish':
        effects = publish_change(db, row, change)
    elif body.step in {'submit','agree'}:
        validate_change(db, change)
    row.state, row.version, row.updated_at = rule[1], row.version+1, utc_now()
    recorded(db, user, 'schedule', row.id, body.step, before, {**change_data(row), 'comment': body.comment, 'effects': effects})
    recipients = {'submit': 'staff', 'agree': 'admin'}.get(body.step)
    if recipients:
        for uid in db.scalars(select(User.id).where(User.role == recipients)):
            notify(db, uid, 'Изменение расписания ожидает решения', f'Проект №{row.id}', f'/app/schedule-changes/{row.id}', category='schedule')
    if body.step in {'return','publish'}:
        notify(db, row.author_id, 'Проект возвращён' if body.step == 'return' else 'Расписание опубликовано',
               body.comment or f'Проект №{row.id}', f'/app/schedule-changes/{row.id}')
    db.commit()
    return change_data(row)
