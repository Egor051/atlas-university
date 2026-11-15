"""The administrator maintains published terms and group calendar exceptions."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .db import CAMPUS_TZ, Lesson, User, campus_today, utc_now
from .main import StrictBody, get_db, require_roles, require_same_origin
from .schedule_calendar import Calendar, LESSON_KINDS, MAX_DATE, MIN_DATE, date_range
from .schedule_occurrences import campus_instant
from .session_security import as_utc
from .workspace import lock_workspace, notify, recorded, student_ids
from .workspace_db import (AcademicDayRule, AcademicGroup, AcademicSubgroup, GroupMember,
                           LegacyClassOverride, AcademicTerm, ScheduleCalendarAlert, ScheduledClass)

router = APIRouter(prefix='/api/scheduling/calendar')
view = require_roles('admin', 'scheduler', 'staff')
admin = require_roles('admin')
write = [Depends(require_same_origin)]


class Versioned(StrictBody):
    id: int | None = Field(default=None, strict=True, ge=1)
    version: int = Field(default=0, strict=True, ge=0)


class Scope(Versioned):
    group_id: int | None = Field(default=None, strict=True, ge=1)
    program: str = Field(default='', max_length=180)
    starts_on: date
    ends_on: date
    source: str = Field(min_length=3, max_length=300)

    @model_validator(mode='after')
    def valid_range(self):
        self.program, self.source = self.program.strip(), self.source.strip()
        if self.program and self.group_id is not None:
            raise ValueError('Выберите программу или группу')
        if not MIN_DATE <= self.starts_on <= self.ends_on <= MAX_DATE or (self.ends_on-self.starts_on).days > 366:
            raise ValueError('Укажите период до одного года в пределах 2000–2099 годов')
        if len(self.source) < 3:
            raise ValueError('Укажите основание или источник дат')
        return self


class TermPeriod(StrictBody):
    kind: Literal['teaching', 'credit', 'exam', 'break']
    start: date
    end: date


class TermBody(Scope):
    academic_year: int = Field(strict=True, ge=2000, le=2098)
    number: int = Field(strict=True, ge=1, le=4)
    weekdays: str = Field(pattern='^[0-6]{1,7}$')
    periods: list[TermPeriod] = Field(min_length=1, max_length=32)
    legacy: bool = Field(default=False, strict=True)

    @model_validator(mode='after')
    def valid_periods(self):
        self.weekdays = ''.join(sorted(set(self.weekdays)))
        if not self.academic_year <= self.starts_on.year <= self.ends_on.year <= self.academic_year+1:
            raise ValueError('Даты семестра должны попадать в указанный учебный год')
        self.periods.sort(key=lambda part: part.start)
        end = None
        for part in self.periods:
            if not self.starts_on <= part.start <= part.end <= self.ends_on or (end is not None and part.start <= end):
                raise ValueError('Периоды должны находиться внутри семестра и не пересекаться')
            end = part.end
        return self


class RuleBody(Scope):
    kind: Literal['holiday', 'off', 'working', 'summer', 'break']
    label: str = Field(default='', max_length=130)


class SubgroupBody(Versioned):
    group_id: int = Field(strict=True, ge=1)
    code: str = Field(min_length=1, max_length=60)
    capacity: int = Field(strict=True, ge=1, le=200)


class MembershipBody(StrictBody):
    student_id: int = Field(strict=True, ge=1)
    subgroup_id: int | None = Field(ge=1, strict=True)
    version: int = Field(strict=True, ge=1)


def calendar_data(row):
    data = dict(id=row.id, group_id=row.group_id, program=row.program, starts_on=str(row.starts_on), ends_on=str(row.ends_on),
                source=row.source, version=row.version)
    if isinstance(row, AcademicTerm):
        return dict(**data, academic_year=row.academic_year, number=row.number, weekdays=row.weekdays,
                    periods=row.periods, legacy=row.legacy)
    return dict(**data, kind=row.kind, label=row.label)


def subgroup_data(row):
    return dict(id=row.id, group_id=row.group_id, code=row.code, capacity=row.capacity, version=row.version)


@router.get('')
def calendar_index(year: int = Query(ge=2000, le=2099), user=Depends(view), db: Session = Depends(get_db)):
    first, last = date(year, 1, 1), date(year+1, 12, 31)
    terms = db.scalars(select(AcademicTerm).where(AcademicTerm.academic_year == year)
                       .order_by(AcademicTerm.starts_on, AcademicTerm.id))
    rules = db.scalars(select(AcademicDayRule).where(AcademicDayRule.starts_on <= last, AcademicDayRule.ends_on >= first)
                       .order_by(AcademicDayRule.starts_on, AcademicDayRule.id))
    members = []
    if user.role == 'admin':
        members = [dict(id=uid, name=name, group_id=group_id, subgroup_id=subgroup_id, version=version)
                   for uid, name, group_id, subgroup_id, version in db.execute(
                       select(User.id, User.full_name, GroupMember.group_id, GroupMember.subgroup_id, GroupMember.version)
                       .join(GroupMember, GroupMember.student_id == User.id).where(User.role == 'student').order_by(User.full_name))]
    return dict(
        year=year, terms=[calendar_data(row) for row in terms], rules=[calendar_data(row) for row in rules],
        groups=[dict(id=group.id, code=group.code, program=group.program, capacity=group.capacity)
                for group in db.scalars(select(AcademicGroup).order_by(AcademicGroup.code))],
        subgroups=[subgroup_data(row) for row in db.scalars(select(AcademicSubgroup).order_by(AcademicSubgroup.code))],
        members=members,
    )


def versioned_row(db, model, key, version):
    row = db.get(model, key) if key is not None else None
    if key is not None and row is None:
        raise HTTPException(404, 'Запись не найдена')
    if version != (row.version if row else 0):
        raise HTTPException(409, 'Запись уже изменилась')
    return row


def check_scope(db, group_id, program):
    groups = select(AcademicGroup)
    if group_id is not None:
        groups = groups.where(AcademicGroup.id == group_id)
    elif program:
        groups = groups.where(AcademicGroup.program == program)
    rows = db.scalars(groups).all()
    if (group_id is not None or program) and not rows:
        raise HTTPException(404, 'Группа или учебная программа не найдена')
    return rows


def check_overlap(db, model, body):
    scope = (model.group_id == body.group_id, model.program == body.program)
    query = select(model.id).where(*scope)
    if body.id:
        query = query.where(model.id != body.id)
    overlap = (model.starts_on <= body.ends_on) & (model.ends_on >= body.starts_on)
    if model is AcademicTerm:
        duplicate = (model.academic_year == body.academic_year) & (model.number == body.number)
        query = query.where(or_(overlap, duplicate))
    else:
        comparable = {'holiday': ('holiday',), 'summer': ('summer', 'break'), 'break': ('summer', 'break'),
                      'off': ('off', 'working'), 'working': ('off', 'working')}
        query = query.where(overlap, model.kind.in_(comparable[body.kind]))
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(409, 'Даты или номер пересекаются с существующей записью этой области')


def check_publications(db, group, dates, before, after):
    removed = {day for day in dates if before[day][0] == 'teaching' and after[day][0] != 'teaching'}
    if not removed:
        return
    end = campus_instant(max(removed)+date.resolution)
    classes = db.scalars(select(ScheduledClass).where(
        ScheduledClass.group_id == group.id, ScheduledClass.kind.in_(LESSON_KINDS),
        ScheduledClass.status == 'active', ScheduledClass.calendar_exception == '',
        ScheduledClass.ends_at > utc_now(), ScheduledClass.starts_at < end))
    conflicts = {as_utc(row.starts_at).astimezone(CAMPUS_TZ).date() for row in classes} & removed
    overrides = db.scalars(select(LegacyClassOverride.day).join(Lesson, Lesson.id == LegacyClassOverride.lesson_id)
                           .join(GroupMember, GroupMember.student_id == Lesson.student_id)
                           .where(GroupMember.group_id == group.id, LegacyClassOverride.day.in_(removed),
                                  LegacyClassOverride.status == 'active', LegacyClassOverride.calendar_exception == ''))
    conflicts.update(overrides)
    if conflicts:
        raise HTTPException(409, f'Сначала перенесите или отмените опубликованные занятия группы {group.code} '
                                 f'на {min(conflicts):%d.%m.%Y}.')


def day_states(calendar, dates, group):
    return {day: (value.code, value.detail, value.legacy)
            for day in dates for value in (calendar.day(day, group),)}


def write_calendar(db, user, model, body=None, *, key=None, version=0):
    lock_workspace(db, user.id)
    row = versioned_row(db, model, body.id if body else key, body.version if body else version)
    if isinstance(row, AcademicDayRule) and row.kind == 'legacy':
        raise HTTPException(409, 'Демонстрационный период заменяется настройками семестра')
    scope = body or row
    if row and (row.group_id, row.program) != (scope.group_id, scope.program):
        raise HTTPException(422, 'Создайте отдельную запись для другой группы или программы')
    groups = check_scope(db, scope.group_id, scope.program)
    if body:
        check_overlap(db, model, body)
    today = campus_today()
    dates = sorted({day for span in (scope, row) if span
                    for day in date_range(max(today, span.starts_on), span.ends_on)})
    first, last = (dates[0], dates[-1]) if dates else (today, today)
    calendar = Calendar(db, first, last)
    before = {group.id: day_states(calendar, dates, group) for group in groups}
    old = calendar_data(row) if row else None
    if body:
        fields = body.model_dump(exclude={'id', 'version'})
        if model is AcademicTerm:
            fields['periods'] = [part.model_dump(mode='json') for part in body.periods]
        if row:
            for field, value in fields.items():
                setattr(row, field, value)
            row.version += 1
        else:
            row = model(**fields)
            db.add(row)
    else:
        db.delete(row)
    db.flush()
    calendar = Calendar(db, first, last)
    for group in groups:
        after = day_states(calendar, dates, group)
        check_publications(db, group, dates, before[group.id], after)
        changed = [day for day in dates if before[group.id][day] != after[day]]
        if changed:
            db.add(ScheduleCalendarAlert(group_id=group.id, starts_on=changed[0], ends_on=changed[-1],
                                         days=list(map(str, changed))))
            for uid in student_ids(db, group.id):
                notify(db, uid, 'Учебный календарь обновлён',
                       f'{group.code} · {changed[0]:%d.%m.%Y} — {changed[-1]:%d.%m.%Y}',
                       f'/app/schedule?date={changed[0]}', category='schedule')
    result = calendar_data(row) if body else {'ok': True}
    area = 'academic-term' if model is AcademicTerm else 'academic-day-rule'
    recorded(db, user, area, row.id, 'saved' if body else 'deleted', old, result)
    db.commit()
    return result


@router.put('/terms', dependencies=write)
def save_term(body: TermBody, user=Depends(admin), db: Session = Depends(get_db)):
    return write_calendar(db, user, AcademicTerm, body)


@router.put('/rules', dependencies=write)
def save_rule(body: RuleBody, user=Depends(admin), db: Session = Depends(get_db)):
    return write_calendar(db, user, AcademicDayRule, body)


@router.delete('/{collection}/{key}', dependencies=write)
def delete_rule(collection: Literal['terms', 'rules'], key: int, version: int = Query(ge=1),
                user=Depends(admin), db: Session = Depends(get_db)):
    return write_calendar(db, user, AcademicTerm if collection == 'terms' else AcademicDayRule,
                          key=key, version=version)


@router.put('/subgroups', dependencies=write)
def save_subgroup(body: SubgroupBody, user=Depends(admin), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    row = versioned_row(db, AcademicSubgroup, body.id, body.version)
    group = check_scope(db, body.group_id, '')[0]
    code = body.code.strip()
    if not code or body.capacity > group.capacity or (row and row.group_id != group.id):
        raise HTTPException(422, 'Укажите название и вместимость подгруппы в пределах её группы')
    others = db.scalars(select(AcademicSubgroup).where(AcademicSubgroup.group_id == group.id))
    if any(other.id != body.id and other.code.casefold() == code.casefold() for other in others):
        raise HTTPException(409, 'В группе уже есть такая подгруппа')
    before = subgroup_data(row) if row else None
    if row:
        from .scheduling import room_problems
        count = db.scalar(select(func.count()).select_from(GroupMember).where(GroupMember.subgroup_id == row.id))
        if count > body.capacity:
            raise HTTPException(409, 'Мест меньше, чем участников подгруппы')
        for event in db.scalars(select(ScheduledClass).where(
                ScheduledClass.subgroup_id == row.id, ScheduledClass.status == 'active', ScheduledClass.ends_at > utc_now())):
            if room_problems(event.room, group, event.kind, event.equipment, capacity=body.capacity):
                raise HTTPException(409, 'Для опубликованного занятия понадобится другая аудитория')
        row.code, row.capacity, row.version = code, body.capacity, row.version+1
    else:
        row = AcademicSubgroup(group_id=group.id, code=code, capacity=body.capacity)
        db.add(row)
    db.flush()
    result = subgroup_data(row)
    recorded(db, user, 'academic-subgroup', row.id, 'saved', before, result)
    db.commit()
    return result


@router.put('/members', dependencies=write)
def assign_subgroup(body: MembershipBody, user=Depends(admin), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    row = versioned_row(db, GroupMember, body.student_id, body.version)
    subgroup = db.get(AcademicSubgroup, body.subgroup_id) if body.subgroup_id else None
    if body.subgroup_id and (subgroup is None or subgroup.group_id != row.group_id):
        raise HTTPException(404, 'Подгруппа не найдена в группе студента')
    if body.subgroup_id != row.subgroup_id:
        if subgroup:
            members = db.scalar(select(func.count()).select_from(GroupMember).where(GroupMember.subgroup_id == subgroup.id))
            if members >= subgroup.capacity:
                raise HTTPException(409, 'В подгруппе нет мест')
            validate_member_schedule(db, row, subgroup)
        before = row.subgroup_id
        row.subgroup_id, row.version = body.subgroup_id, row.version+1
        recorded(db, user, 'academic-membership', row.student_id, 'subgroup', before, row.subgroup_id)
        notify(db, row.student_id, 'Участие в подгруппе изменилось', subgroup.code if subgroup else 'Общая группа',
               '/app/schedule', category='schedule')
    db.commit()
    return {'subgroup_id': row.subgroup_id, 'version': row.version}


def validate_member_schedule(db, member, subgroup):
    from .schedule_occurrences import legacy_occurrences

    now = utc_now()
    personal = list(db.scalars(select(ScheduledClass).where(
        ScheduledClass.student_id == member.student_id, ScheduledClass.status == 'active', ScheduledClass.ends_at > now)))
    events = db.scalars(select(ScheduledClass).where(
        ScheduledClass.subgroup_id == subgroup.id, ScheduledClass.status == 'active', ScheduledClass.ends_at > now))
    for event in events:
        start, end = as_utc(event.starts_at), as_utc(event.ends_at)
        day = start.astimezone(CAMPUS_TZ).date()
        if any(as_utc(other.starts_at) < end and as_utc(other.ends_at) > start for other in personal):
            raise HTTPException(409, 'Занятие подгруппы пересекается с индивидуальным расписанием студента')
        lessons = legacy_occurrences(db, day, day, student_id=member.student_id)
        if any(item['status'] == 'active' and campus_instant(day, item['start']) < end
               and campus_instant(day, item['end']) > start for item in lessons):
            raise HTTPException(409, 'Занятие подгруппы пересекается с расписанием студента')
