"""Versioned classrooms, groups, teaching assignments and group rosters."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import User, campus_today, utc_now
from .main import StrictBody, get_db, require_roles, require_same_origin
from .scheduling import room_problems
from .teaching import deliver_work
from .university_db import Teacher, TeachingAssignment
from .workspace import load_payload, load_query, lock_workspace, recorded
from .workspace_db import AcademicGroup, Classroom, GroupMember, GroupWork, ScheduledClass, TeachingLoad, WorkDelivery

router = APIRouter(prefix='/api/registry')
view = require_roles('scheduler', 'staff', 'admin')
rooms_write = require_roles('scheduler', 'admin')
admin = require_roles('admin')
write = [Depends(require_same_origin)]


class Versioned(StrictBody):
    id: int | None = Field(default=None, strict=True, ge=1)
    version: int = Field(default=0, strict=True, ge=0)


class RoomBody(Versioned):
    building: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=80)
    capacity: int = Field(strict=True, ge=1, le=500)
    kind: Literal['lecture','seminar','lab']
    equipment: str = Field(default='', max_length=160)
    accessible: bool = Field(default=False, strict=True)
    available: bool = Field(default=True, strict=True)

    @field_validator('building', 'code', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class GroupBody(Versioned):
    code: str = Field(min_length=2, max_length=80)
    program: str = Field(min_length=3, max_length=180)
    capacity: int = Field(strict=True, ge=1, le=200)
    accessible: bool = Field(default=False, strict=True)

    @field_validator('code', 'program', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class LoadBody(Versioned):
    group_id: int = Field(strict=True, ge=1)
    assignment_id: int = Field(strict=True, ge=1)


class MemberBody(StrictBody):
    student_id: int = Field(strict=True, ge=1)
    group_id: int = Field(strict=True, ge=1)
    version: int = Field(default=0, strict=True, ge=0)


def scalar_data(row, fields):
    return {field:getattr(row,field) for field in fields}


def room_data(row):
    return scalar_data(row, ('id','version','building','code','capacity','kind','equipment','accessible','available'))


def group_data(row):
    return scalar_data(row, ('id','version','code','program','capacity','accessible'))


def member_data(student, row):
    return dict(student_id=student.id, name=student.full_name, number=student.student_number,
                group_id=row.group_id if row else None, version=row.version if row else 0)


def require_row(db, model, row_id):
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(404, 'Запись справочника не найдена')
    return row


def versioned(db, model, body):
    row = require_row(db, model, body.id) if body.id is not None else None
    if (row.version if row else 0) != body.version:
        raise HTTPException(409, 'Запись справочника изменена')
    return row


def write_reference(db, user, dataset, body, *, apply=True):
    is_room = dataset == 'rooms'
    model, payload = (Classroom, room_data) if is_room else (AcademicGroup, group_data)
    row = versioned(db, model, body)
    values = body.model_dump(exclude={'id','version'})
    folded = func.casefold(model.code) if db.get_bind().dialect.name == 'sqlite' else func.lower(model.code)
    duplicate = select(model.id).where(folded == body.code.casefold())
    if row:
        duplicate = duplicate.where(model.id != row.id)
    if db.scalar(duplicate.limit(1)) is not None:
        raise HTTPException(409, 'Такой код уже используется')
    candidate = model(**values)
    if row:
        relation = ScheduledClass.room_id if is_room else ScheduledClass.group_id
        future = db.scalars(select(ScheduledClass).where(relation == row.id, ScheduledClass.status == 'active',
                                  ScheduledClass.ends_at > utc_now()))
        for event in future:
            errors = room_problems(candidate, event.load.group, event.kind, event.equipment) if is_room else room_problems(
                event.room, candidate, event.kind, event.equipment)
            if errors:
                raise HTTPException(409, 'Опубликованное занятие не соответствует изменениям. ' + errors[0])
        if not is_room and db.scalar(select(func.count()).select_from(GroupMember)
                                     .where(GroupMember.group_id == row.id)) > body.capacity:
            raise HTTPException(409, 'Вместимость меньше числа студентов')
    if not apply:
        return
    before = payload(row) if row else None
    if row is None:
        row = candidate
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.version += 1
        if not is_room:
            for student in db.scalars(select(User).join(GroupMember).where(GroupMember.group_id == row.id, User.role == 'student')):
                student.group_name = body.code
    db.flush()
    after = payload(row)
    recorded(db, user, dataset, row.id, 'updated' if before else 'created', before, after)
    return after


def write_load(db, user, body, *, apply=True):
    row = versioned(db, TeachingLoad, body)
    group = require_row(db, AcademicGroup, body.group_id)
    assignment = require_row(db, TeachingAssignment, body.assignment_id)
    if row and (row.group_id != group.id or row.discipline_id != assignment.discipline_id):
        raise HTTPException(422, 'У существующего назначения меняется преподаватель той же дисциплины')
    if row is None and db.scalar(select(TeachingLoad.id).where(TeachingLoad.group_id == group.id,
                                                             TeachingLoad.discipline_id == assignment.discipline_id)):
        raise HTTPException(409, 'Дисциплина уже закреплена за группой')
    if not apply:
        return assignment.discipline_id
    before = load_payload(row) if row else None
    if row is None:
        row = TeachingLoad(group=group, assignment=assignment, discipline_id=assignment.discipline_id)
        db.add(row)
    else:
        row.assignment = assignment
        row.version += 1
    db.flush()
    after = load_payload(row)
    recorded(db, user, 'loads', row.id, 'updated' if before else 'created', before, after)
    return after


def write_member(db, user, body, *, apply=True, capacity_check=True):
    student = db.scalar(select(User).where(User.id == body.student_id, User.role == 'student'))
    if student is None:
        raise HTTPException(404, 'Учётная запись студента не найдена')
    group = require_row(db, AcademicGroup, body.group_id)
    row = db.get(GroupMember, student.id)
    if (row.version if row else 0) != body.version:
        raise HTTPException(409, 'Состав группы уже изменён')
    old_group = row.group_id if row else None
    if capacity_check and old_group != group.id and db.scalar(select(func.count()).select_from(GroupMember)
            .where(GroupMember.group_id == group.id)) >= group.capacity:
        raise HTTPException(409, 'В учебной группе нет мест')
    if not apply:
        return old_group, group.capacity
    before = member_data(student, row)
    if row is None:
        row = GroupMember(student_id=student.id, group_id=group.id)
        db.add(row)
    elif old_group != group.id:
        row.group_id, row.version = group.id, row.version+1
    student.group_name = group.code
    db.flush()
    if old_group != group.id:
        rows = db.execute(select(GroupWork, TeachingLoad).join(TeachingLoad).where(TeachingLoad.group_id == group.id,
                                                                               GroupWork.due >= campus_today()))
        from .db import Deadline
        for work, load in rows:
            existing = db.scalar(select(WorkDelivery.deadline_id).join(Deadline).where(
                WorkDelivery.work_id == work.id, Deadline.student_id == student.id).limit(1))
            if existing is None:
                deliver_work(db, load, work, student.id)
    after = member_data(student, row)
    recorded(db, user, 'students', student.id, 'membership', before, after)
    return after


@router.get('')
def directory(user=Depends(view), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(GroupMember.group_id, func.count()).group_by(GroupMember.group_id)).all())
    loads = db.scalars(load_query().order_by(TeachingLoad.id)).all()
    result = {'rooms':[room_data(row) for row in db.scalars(select(Classroom).order_by(Classroom.code))],
              'groups':[{**group_data(row),'enrolled':counts.get(row.id,0)} for row in db.scalars(select(AcademicGroup).order_by(AcademicGroup.code))],
              'loads':[load_payload(row) for row in loads]}
    if user.role == 'admin':
        students = db.execute(select(User, GroupMember).outerjoin(GroupMember).where(User.role == 'student').order_by(User.full_name))
        from .university_db import Discipline
        choices = db.execute(select(TeachingAssignment.id, User.full_name, Discipline.title).select_from(TeachingAssignment)
            .join(Teacher, Teacher.id == TeachingAssignment.teacher_id).join(User, User.id == Teacher.user_id)
            .join(Discipline, Discipline.id == TeachingAssignment.discipline_id).order_by(Discipline.title, User.full_name))
        result.update(students=[member_data(u, member) for u, member in students],
                      assignments=[dict(id=key, teacher=name, discipline=title) for key,name,title in choices])
    return result


@router.put('/rooms', dependencies=write)
def save_room(body: RoomBody, user=Depends(rooms_write), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    result = write_reference(db, user, 'rooms', body)
    db.commit()
    return result


@router.put('/groups', dependencies=write)
def save_group(body: GroupBody, user=Depends(admin), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    result = write_reference(db, user, 'groups', body)
    db.commit()
    return result


@router.put('/loads', dependencies=write)
def save_load(body: LoadBody, user=Depends(admin), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    result = write_load(db, user, body)
    db.commit()
    return result


@router.put('/students', dependencies=write)
def save_member(body: MemberBody, user=Depends(admin), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    result = write_member(db, user, body)
    db.commit()
    return result
