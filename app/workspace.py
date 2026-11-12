"""Shared authorization scope, audit and notices for academic operations."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload

from .db import Notification, User, utc_now
from .storage_guards import lock_owner
from .university_db import Teacher, TeachingAssignment
from .workspace_db import GroupMember, OperationEvent, TeachingLoad


def lock_workspace(db, actor_id):
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(2026111103)'))
    else:
        lock_owner(db, actor_id)


def recorded(db, actor, area, object_id, action, before=None, after=None):
    db.add(OperationEvent(area=area, object_id=object_id, actor_id=actor.id, action=action,
                          before=json.dumps(before, ensure_ascii=False, default=str),
                          after=json.dumps(after, ensure_ascii=False, default=str), created_at=utc_now()))


def notify(db, user_id, title, body, target, *, student=False, category='academic'):
    row = Notification(student_id=user_id, title=title, body=body, target=target,
                       category=category, is_read=False, created_at=utc_now())
    db.add(row)
    return row


def load_query():
    return select(TeachingLoad).options(joinedload(TeachingLoad.group), joinedload(TeachingLoad.discipline),
           joinedload(TeachingLoad.assignment).joinedload(TeachingAssignment.teacher).joinedload(Teacher.user))


def owned_load(db, user, load_id):
    query = load_query().join(TeachingAssignment).join(Teacher).where(
        TeachingLoad.id == load_id, Teacher.user_id == user.id)
    row = db.scalar(query)
    if row is None:
        raise HTTPException(404, 'Учебное назначение не найдено')
    return row


def student_ids(db, group_id):
    return db.scalars(select(GroupMember.student_id).where(GroupMember.group_id == group_id).order_by(GroupMember.student_id)).all()


def roster(db, group_id):
    return db.scalars(select(User).join(GroupMember).where(GroupMember.group_id == group_id, User.role == 'student')
                      .order_by(User.full_name, User.id)).all()


def check_member(db, load, student_id):
    if db.scalar(select(GroupMember.student_id).join(User).where(GroupMember.student_id == student_id,
                 GroupMember.group_id == load.group_id, User.role == 'student')) is None:
        raise HTTPException(404, 'Студент не найден в этой группе')


def load_payload(row):
    return dict(id=row.id, group_id=row.group_id, group=row.group.code, assignment_id=row.assignment_id,
                discipline=row.discipline.title, teacher=row.assignment.teacher.user.full_name, version=row.version)


def event_payload(row, author, date_iso):
    return dict(id=row.id, action=row.action, before=json.loads(row.before), after=json.loads(row.after),
                author=author, created_at=date_iso(row.created_at))


def create_router():
    from .main import date_iso, get_db, require_same_origin, require_user
    router = APIRouter(prefix='/api/workspace')

    @router.get('/notices')
    def notices(offset: int = Query(0, ge=0, le=2147483647), user=Depends(require_user), db: Session = Depends(get_db)):
        scope = Notification.student_id == user.id
        rows = db.scalars(select(Notification).where(scope).order_by(Notification.created_at.desc(), Notification.id.desc())
                          .offset(offset).limit(31)).all()
        unread = db.scalar(select(func.count()).select_from(Notification).where(scope, Notification.is_read.is_(False)))
        return dict(items=[dict(id=row.id, title=row.title, body=row.body, target=row.target, is_read=row.is_read,
                                created_at=date_iso(row.created_at)) for row in rows[:30]], unread=unread, more=len(rows)>30, offset=offset)

    @router.post('/notices/{notice_id}/read', dependencies=[Depends(require_same_origin)])
    def read(notice_id: int, user=Depends(require_user), db: Session = Depends(get_db)):
        row = db.scalar(select(Notification).where(Notification.id == notice_id, Notification.student_id == user.id))
        if row is None:
            raise HTTPException(404, 'Уведомление не найдено')
        row.is_read = True
        db.commit()
        return {'ok': True, 'target': row.target}

    return router
