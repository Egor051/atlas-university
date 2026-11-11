"""Room and timetable operations. Only approved occurrences enter a timetable."""
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .db import CAMPUS_TZ, Lesson, LessonChange, User, campus_today, utc_now
from .main import StrictBody, date_iso, get_db, require_roles, require_same_origin
from .services import begin_idempotent, commit_idempotent
from .services_db import ConsultationSlot
from .session_security import as_utc
from .university_db import Teacher, TeachingAssignment
from .workspace import event_payload, load_payload, load_query, lock_workspace, notify, recorded, student_ids
from .workspace_db import AcademicGroup, Classroom, GroupMember, OperationEvent, ScheduleChange, ScheduledClass, TeachingLoad

router = APIRouter(prefix='/api')
view_schedule = require_roles('scheduler', 'staff', 'admin')
dispatcher = require_roles('scheduler')
teacher_only = require_roles('teacher')
write = [Depends(require_same_origin)]
KIND = {'lecture': 'Лекция', 'seminar': 'Семинар', 'practice': 'Практика', 'lab': 'Лабораторная'}
ChangeAction = Literal['create', 'update', 'cancel']


class SlotBody(StrictBody):
    load_id: int = Field(strict=True, ge=1)
    teacher_id: int = Field(strict=True, ge=1)
    room_id: int = Field(strict=True, ge=1)
    day: date
    start: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    kind: Literal['lecture', 'seminar', 'practice', 'lab']
    equipment: str = Field(default='', max_length=160)
    weeks: int = Field(default=1, strict=True, ge=1, le=16)


class ChangeBody(StrictBody):
    action: ChangeAction
    event_id: int | None = Field(default=None, strict=True, ge=1)
    event_version: int | None = Field(default=None, strict=True, ge=1)
    slot: SlotBody | None = None
    note: str = Field(default='', max_length=300)

    @model_validator(mode='after')
    def valid_shape(self):
        if self.action == 'create':
            if self.event_id is not None or self.event_version is not None or self.slot is None:
                raise ValueError('Для нового занятия укажите параметры занятия')
        elif self.event_id is None or self.event_version is None:
            raise ValueError('Укажите занятие и его версию')
        elif self.action == 'update' and (self.slot is None or self.slot.weeks != 1):
            raise ValueError('Перенос применяется к выбранному занятию')
        elif self.action == 'cancel' and (self.slot is not None or len(self.note.strip()) < 3):
            raise ValueError('Укажите причину отмены')
        return self


class EditChange(ChangeBody):
    version: int = Field(strict=True, ge=1)


class StepBody(StrictBody):
    step: Literal['submit', 'agree', 'return', 'publish']
    version: int = Field(strict=True, ge=1)
    comment: str = Field(default='', max_length=300)


def campus_instant(day, clock):
    return datetime.combine(day, time.fromisoformat(clock), CAMPUS_TZ).astimezone(timezone.utc)


def week_bounds(week):
    day = week or campus_today()
    if abs((day-campus_today()).days)>370:
        raise HTTPException(422, 'Выберите неделю в пределах учебного года')
    monday = day-timedelta(days=day.weekday())
    return monday, campus_instant(monday, '00:00'), campus_instant(monday+timedelta(days=7), '00:00')


def tokens(value):
    return {part.strip().casefold() for part in value.split(',') if part.strip()}


def room_problems(room, group, kind, equipment):
    return [
        message for problem, message in (
            (not room.available, 'Аудитория недоступна'),
            (room.capacity < group.capacity, 'В аудитории недостаточно мест для группы'),
            (group.accessible and not room.accessible, 'Для группы требуется безбарьерный доступ'),
            (kind == 'lab' and room.kind != 'lab', 'Для лабораторной работы нужна лаборатория'),
            (not tokens(equipment) <= tokens(room.equipment), 'В аудитории нет требуемого оборудования'),
        ) if problem
    ]


def aliases(teacher):
    name = teacher.user.full_name.split()
    return {teacher.user.full_name, f'{name[0][0]}. {name[-1]}'} if name else {''}


def legacy_day(db, day):
    lessons = db.execute(select(Lesson, GroupMember.group_id).join(GroupMember, GroupMember.student_id == Lesson.student_id)
                         .where(Lesson.weekday == day.weekday())).all()
    changes = {row.lesson_id: row for row in db.scalars(select(LessonChange).where(LessonChange.day == day))}
    for row, group in lessons:
        change = changes.get(row.id)
        start = campus_instant(day, row.start_time)
        end = campus_instant(day, row.end_time)
        if change and change.new_start:
            difference = campus_instant(day, change.new_start)-start
            start, end = start+difference, end+difference
        room = change.new_room if change and change.new_room else row.room
        yield row, group, room, start, end


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
    day = start.astimezone(CAMPUS_TZ).date()
    last = end.astimezone(CAMPUS_TZ).date()
    while day <= last:
        yield from ((row, group, code) for row, group, code, s, e in legacy_day(db, day) if s < end and e > start)
        day += timedelta(days=1)


def teacher_is_busy(db, teacher, start, end):
    if teacher_has_consultation(db, teacher, start, end) or db.scalar(select(ScheduledClass.id).where(
            ScheduledClass.status == 'active', ScheduledClass.teacher_id == teacher.id, ScheduledClass.starts_at < end,
            ScheduledClass.ends_at > start).limit(1)) is not None:
        return True
    names = aliases(teacher)
    return any(row.teacher in names for row, _, _ in legacy_intervals(db, start, end))


def room_is_busy(db, room, start, end):
    class_overlap = select(ScheduledClass.id).where(
            ScheduledClass.status == 'active', ScheduledClass.room_id == room.id, ScheduledClass.starts_at < end,
            ScheduledClass.ends_at > start)
    if db.scalar(class_overlap.limit(1)) is not None or db.scalar(room_consultations(db, room.code, start, end).limit(1)) is not None:
        return True
    return any(code.casefold() == room.code.casefold() for _, _, code in legacy_intervals(db, start, end))


def class_query():
    return select(ScheduledClass).options(joinedload(ScheduledClass.room),
           joinedload(ScheduledClass.teacher).joinedload(Teacher.user),
           joinedload(ScheduledClass.load).joinedload(TeachingLoad.discipline),
           joinedload(ScheduledClass.load).joinedload(TeachingLoad.group))


def class_data(row):
    start, end = (as_utc(v).astimezone(CAMPUS_TZ) for v in (row.starts_at, row.ends_at))
    return dict(id=row.id, load_id=row.load_id, group_id=row.group_id, group=row.load.group.code, teacher_id=row.teacher_id,
                teacher=row.teacher.user.full_name, room_id=row.room_id, room=row.room.code, day=start.date().isoformat(),
                start=start.strftime('%H:%M'), end=end.strftime('%H:%M'), discipline=row.load.discipline.title,
                kind=row.kind, kind_label=KIND[row.kind], equipment=row.equipment, note=row.note,
                status=row.status, version=row.version, series=row.series)


def student_classes(db, user, start_day):
    start, end = campus_instant(start_day,'00:00'), campus_instant(start_day+timedelta(days=7),'00:00')
    group = select(GroupMember.group_id).where(GroupMember.student_id == user.id).scalar_subquery()
    rows = db.scalars(class_query().where(ScheduledClass.group_id == group, ScheduledClass.status == 'active',
                     ScheduledClass.starts_at >= start, ScheduledClass.starts_at < end))
    for row in rows:
        data = class_data(row)
        yield dict(id=1000000000+row.id, date=data['day'], start=data['start'], end=data['end'], title=data['discipline'],
                   kind=data['kind_label'], room=data['room'], teacher=data['teacher'], color='violet',
                   changed=row.version>1, note=row.note, original_room=None, original_start=None, original_end=None)


def existing_class(db, change):
    if change.event_id is None:
        return None
    event = db.scalar(class_query().where(ScheduledClass.id == change.event_id))
    if event is None:
        raise HTTPException(404, 'Занятие не найдено')
    if event.version != change.event_version or event.status != 'active':
        raise HTTPException(409, 'Занятие уже изменилось или отменено')
    if as_utc(event.ends_at) < utc_now():
        raise HTTPException(409, 'Занятие уже завершилось')
    return event


def collision_reasons(db, day, start, end, group, teacher, room, event, queued):
    scope = (ScheduledClass.status == 'active', ScheduledClass.starts_at < end, ScheduledClass.ends_at > start,
             or_(ScheduledClass.group_id == group.id, ScheduledClass.teacher_id == teacher.id, ScheduledClass.room_id == room.id))
    query = select(ScheduledClass.group_id, ScheduledClass.teacher_id, ScheduledClass.room_id).where(*scope)
    if event:
        query = query.where(ScheduledClass.id != event.id)
    occupied = list(db.execute(query))
    occupied.extend((row['group_id'], row['teacher_id'], row['room_id']) for row in queued
                    if row['starts_at'] < end and row['ends_at'] > start)
    flags = [any(value[i] == needle for value in occupied) for i, needle in enumerate((group.id, teacher.id, room.id))]
    teacher_names = aliases(teacher)
    for lesson, group_id, code, s, e in legacy_day(db, day):
        if s < end and e > start:
            flags[0] |= group_id == group.id
            flags[1] |= lesson.teacher in teacher_names
            flags[2] |= code.casefold() == room.code.casefold()
    flags[1] |= teacher_has_consultation(db, teacher, start, end)
    flags[2] |= db.scalar(room_consultations(db, room.code, start, end).limit(1)) is not None
    return [message for flag, message in zip(flags, ('у группы уже есть занятие', 'преподаватель занят', 'аудитория занята')) if flag]


def validate_change(db, change, queued=()):
    event = existing_class(db, change)
    if change.action == 'cancel':
        return event, []
    body = change.slot
    load = db.scalar(load_query().where(TeachingLoad.id == body.load_id))
    teacher = db.scalar(select(Teacher).options(joinedload(Teacher.user)).where(Teacher.id == body.teacher_id))
    room = db.get(Classroom, body.room_id)
    if load is None or teacher is None or room is None:
        raise HTTPException(404, 'Назначение, преподаватель или аудитория не найдены')
    if db.scalar(select(TeachingAssignment.id).where(TeachingAssignment.teacher_id == teacher.id,
                 TeachingAssignment.discipline_id == load.discipline_id)) is None:
        raise HTTPException(422, 'У преподавателя нет назначения на эту дисциплину')
    problems = room_problems(room, load.group, body.kind, body.equipment)
    if problems:
        raise HTTPException(422, '. '.join(problems))
    intervals = []
    for week in range(body.weeks):
        day = body.day+timedelta(weeks=week)
        if not campus_today() <= day <= campus_today()+timedelta(days=370):
            raise HTTPException(422, 'Занятие должно попадать в будущий учебный период')
        start, end = campus_instant(day, body.start), campus_instant(day, body.end)
        if start <= utc_now() or not timedelta(minutes=15) <= end-start <= timedelta(hours=6):
            raise HTTPException(422, 'Укажите будущее время и продолжительность от 15 минут до 6 часов')
        conflicts = collision_reasons(db, day, start, end, load.group, teacher, room, event, queued)
        if conflicts:
            raise HTTPException(409, f'{day.strftime("%d.%m.%Y")} — ' + ', '.join(conflicts))
        intervals.append(dict(load_id=load.id, group_id=load.group_id, teacher_id=teacher.id, room_id=room.id,
                              starts_at=start, ends_at=end, kind=body.kind, equipment=body.equipment, note=change.note))
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
    previous, intervals = validate_change(db, body)
    before = class_data(previous) if previous else None
    old_group = previous.group_id if previous else None
    old_teacher = previous.teacher.user_id if previous else None
    changed = []
    if body.action == 'cancel':
        previous.status, previous.note, previous.version = 'cancelled', body.note, previous.version+1
        changed.append(previous)
    elif previous:
        for key, value in intervals[0].items():
            setattr(previous, key, value)
        previous.version += 1
        # Re-resolve relationships after foreign keys changed.
        db.flush()
        db.expire(previous, ['teacher', 'room', 'load'])
        changed.append(previous)
    else:
        series = uuid4().hex
        changed = [ScheduledClass(**fields, series=series, status='active') for fields in intervals]
        db.add_all(changed)
    db.flush()
    first = changed[0]
    row.event_id = first.id
    title = {'create': 'Опубликовано занятие', 'update': 'Расписание изменилось', 'cancel': 'Занятие отменено'}[body.action]
    data = class_data(first)
    groups = {first.group_id, old_group}-{None}
    students = {student for group_id in groups for student in student_ids(db, group_id)}
    message = f"{data['discipline']} · {data['day']} · {data['start']} МСК"
    if len(changed)>1:
        message += f' · занятий в серии: {len(changed)}'
    for student in students:
        notify(db, student, title, message, f"/app/schedule?date={data['day']}", student=True, category='schedule')
    for teacher in {first.teacher.user_id, old_teacher}-{None}:
        notify(db, teacher, title, message, f"/app/teach-schedule?week={data['day']}")
    return {'previous': before, 'published': [class_data(event) for event in changed]}


@router.get('/scheduling')
def timetable(week: date | None = None, user=Depends(view_schedule), db: Session = Depends(get_db)):
    monday, start, end = week_bounds(week)
    rows = db.scalars(class_query().where(ScheduledClass.starts_at >= start, ScheduledClass.starts_at < end)
                     .order_by(ScheduledClass.starts_at, ScheduledClass.id)).all()
    return {'week': monday.isoformat(), 'items': [class_data(row) for row in rows]}


@router.get('/teaching/schedule')
def own_timetable(week: date | None = None, user=Depends(teacher_only), db: Session = Depends(get_db)):
    monday, start, end = week_bounds(week)
    teacher = db.scalar(select(Teacher).options(joinedload(Teacher.user)).where(Teacher.user_id == user.id))
    if not teacher:
        return {'week': monday.isoformat(), 'items': []}
    rows = db.scalars(class_query().where(ScheduledClass.teacher_id == teacher.id, ScheduledClass.status == 'active',
                                        ScheduledClass.starts_at >= start, ScheduledClass.starts_at < end)).all()
    items = [class_data(row) for row in rows]
    groups = dict(db.execute(select(AcademicGroup.id, AcademicGroup.code).join(TeachingLoad)
                            .join(TeachingAssignment).where(TeachingAssignment.teacher_id == teacher.id)).all())
    names = aliases(teacher)
    for i in range(7):
        day = monday+timedelta(days=i)
        seen = set()
        for lesson, group, room, s, e in legacy_day(db, day):
            identity = (group, lesson.title, s)
            if group in groups and lesson.teacher in names and identity not in seen:
                seen.add(identity)
                items.append(dict(group=groups[group], discipline=lesson.title, day=day.isoformat(),
                                  start=s.astimezone(CAMPUS_TZ).strftime('%H:%M'), end=e.astimezone(CAMPUS_TZ).strftime('%H:%M'),
                                  room=room, kind_label=lesson.kind, status='active', teacher=user.full_name))
    return {'week': monday.isoformat(), 'items': sorted(items, key=lambda row:(row['day'], row['start'], row['group']))}


@router.get('/scheduling/options')
def options(user=Depends(view_schedule), db: Session = Depends(get_db)):
    loads = db.scalars(load_query().order_by(TeachingLoad.id)).all()
    teachers = db.execute(select(Teacher.id, User.full_name, TeachingAssignment.discipline_id)
                          .join(User, User.id == Teacher.user_id).join(TeachingAssignment, TeachingAssignment.teacher_id == Teacher.id)
                          .order_by(User.full_name)).all()
    return {'loads': [{**load_payload(row), 'discipline_id': row.discipline_id} for row in loads],
            'teachers': [dict(id=key, name=name, discipline_id=discipline) for key, name, discipline in teachers],
            'rooms': [dict(id=row.id, code=row.code, building=row.building, available=row.available, capacity=row.capacity)
                      for row in db.scalars(select(Classroom).order_by(Classroom.code))]}


@router.get('/scheduling/rooms/{room_id}')
def room_calendar(room_id: int, week: date | None = None, user=Depends(view_schedule), db: Session = Depends(get_db)):
    room = db.get(Classroom, room_id)
    if room is None:
        raise HTTPException(404, 'Аудитория не найдена')
    monday, start, end = week_bounds(week)
    rows = db.scalars(class_query().where(ScheduledClass.room_id == room.id, ScheduledClass.status == 'active',
                                         ScheduledClass.starts_at >= start, ScheduledClass.starts_at < end)).all()
    items = [class_data(row) for row in rows]
    for offset in range(7):
        day = monday+timedelta(days=offset)
        seen = set()
        for lesson, group, code, s, e in legacy_day(db, day):
            key = (group, lesson.title, s)
            if code.casefold() == room.code.casefold() and key not in seen:
                seen.add(key)
                items.append(dict(day=day.isoformat(), start=s.astimezone(CAMPUS_TZ).strftime('%H:%M'),
                                  end=e.astimezone(CAMPUS_TZ).strftime('%H:%M'), discipline=lesson.title,
                                  room=room.code, teacher=lesson.teacher, kind_label=lesson.kind, status='active'))
    for slot in db.scalars(room_consultations(db, room.code, start, end)):
        s, e = as_utc(slot.start_at).astimezone(CAMPUS_TZ), as_utc(slot.end_at).astimezone(CAMPUS_TZ)
        items.append(dict(day=s.date().isoformat(), start=s.strftime('%H:%M'), end=e.strftime('%H:%M'),
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
            notify(db, uid, 'Изменение расписания ожидает решения', f'Проект №{row.id}', f'/app/schedule-changes/{row.id}')
    if body.step in {'return','publish'}:
        notify(db, row.author_id, 'Проект возвращён' if body.step == 'return' else 'Расписание опубликовано',
               body.comment or f'Проект №{row.id}', f'/app/schedule-changes/{row.id}')
    db.commit()
    return change_data(row)
