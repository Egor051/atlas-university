"""Persistent direct messages. Every dialog read or write scopes its participants."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .db import Notification, User, utc_now
from .improvements import reserve_write
from .services import begin_idempotent, commit_idempotent
from .storage_guards import lock_owner
from .university_db import DirectContact, DirectDialog, DirectMessage

MAX_DIALOGS = 60
MAX_MESSAGES = 2000
CONTACT_ROLES = ('teacher', 'staff')


def owner_condition(user):
    if user.role == 'student':
        return DirectDialog.student_id == user.id
    if user.role in CONTACT_ROLES:
        return DirectDialog.contact_id == user.id
    raise HTTPException(403, 'Переписка для этой роли недоступна')


def counterpart(user):
    return DirectDialog.contact_id if user.role == 'student' else DirectDialog.student_id


def owned_dialog(db, dialog_id, user, *, for_update=False):
    query = select(DirectDialog).where(DirectDialog.id == dialog_id, owner_condition(user))
    row = db.scalar(query.with_for_update() if for_update else query)
    if row is None:
        raise HTTPException(404, 'Диалог не найден')
    return row


def unread_condition(user):
    return (DirectMessage.sender_id != user.id, DirectMessage.read_at.is_(None))


def create_router():
    from .main import StrictBody, date_iso, get_db, require_same_origin, require_student, require_user, search_text, text_search

    router = APIRouter(prefix='/api/direct')
    write = [Depends(require_same_origin)]

    class MessageBody(StrictBody):
        message: str = Field(min_length=1, max_length=3000)

        @field_validator('message', mode='before')
        @classmethod
        def trim(cls, value):
            return value.strip() if isinstance(value, str) else value

    class StartBody(MessageBody):
        recipient_id: int = Field(strict=True, ge=1, le=2147483647)

    class ReadBody(StrictBody):
        through_id: int = Field(strict=True, ge=1, le=2147483647)

    def person(row):
        return dict(id=row.id, name=row.full_name, role=row.role, initials=row.initials, accent=row.accent)

    def contacts_query():
        return select(User, DirectContact.label).join(DirectContact).where(User.role.in_(CONTACT_ROLES))

    def valid_contact(db, user_id):
        row = db.execute(contacts_query().where(User.id == user_id)).one_or_none()
        if row is None:
            raise HTTPException(404, 'Адресат недоступен')
        return row

    def message_payload(row, actor):
        return dict(id=row.id, mine=row.sender_id == actor.id, body=row.body, created_at=date_iso(row.created_at),
                    is_read=row.read_at is not None)

    @router.get('/recipients')
    def recipients(q: str = Query('', max_length=100), _user=Depends(require_student), db: Session = Depends(get_db)):
        q = search_text(q)
        query = contacts_query()
        if q:
            query = query.where(or_(*(text_search(column, q) for column in
                                      (User.full_name, User.faculty, User.program, DirectContact.label))))
        return {'items': [{**person(row), 'label': label} for row, label in
                          db.execute(query.order_by(User.full_name).limit(MAX_DIALOGS))]}

    @router.get('/recipients/{recipient_id}')
    def recipient(recipient_id: int, user=Depends(require_student), db: Session = Depends(get_db)):
        row, label = valid_contact(db, recipient_id)
        dialog_id = db.scalar(select(DirectDialog.id).where(DirectDialog.student_id == user.id,
                                                           DirectDialog.contact_id == recipient_id))
        return {**person(row), 'label': label, 'dialog_id': dialog_id}

    @router.get('/unread')
    def unread(user=Depends(require_user), db: Session = Depends(get_db)):
        count = db.scalar(select(func.count()).select_from(DirectMessage).join(DirectDialog)
                          .where(owner_condition(user), *unread_condition(user)))
        return {'unread_count': count}

    @router.get('/dialogs')
    def dialogs(q: str = Query('', max_length=100), limit: int = Query(20, ge=1, le=50),
                offset: int = Query(0, ge=0, le=2147483647), user=Depends(require_user), db: Session = Depends(get_db)):
        q = search_text(q)
        unread_count = (select(func.count()).select_from(DirectMessage)
                        .where(DirectMessage.dialog_id == DirectDialog.id, *unread_condition(user)).scalar_subquery())
        last_message = (select(func.substr(DirectMessage.body, 1, 160)).where(DirectMessage.dialog_id == DirectDialog.id)
                        .order_by(DirectMessage.id.desc()).limit(1).scalar_subquery())
        query = (select(DirectDialog, User, unread_count, last_message)
                 .join(User, User.id == counterpart(user)).where(owner_condition(user)))
        if q:
            query = query.where(text_search(User.full_name, q))
        total = db.scalar(select(func.count()).select_from(query.with_only_columns(DirectDialog.id).subquery()))
        rows = db.execute(query.order_by(DirectDialog.updated_at.desc(), DirectDialog.id.desc()).offset(offset).limit(limit))
        return dict(items=[dict(id=row.id, person=person(other), updated_at=date_iso(row.updated_at),
                                unread_count=count, preview=preview or '') for row, other, count, preview in rows],
                    total=total, offset=offset, limit=limit)

    @router.get('/dialogs/{dialog_id}')
    def dialog(dialog_id: int, before: int | None = Query(None, ge=1, le=2147483647),
               user=Depends(require_user), db: Session = Depends(get_db)):
        row = owned_dialog(db, dialog_id, user)
        other = db.get(User, row.contact_id if user.role == 'student' else row.student_id)
        query = select(DirectMessage).where(DirectMessage.dialog_id == row.id)
        if before:
            query = query.where(DirectMessage.id < before)
        latest = db.scalars(query.order_by(DirectMessage.id.desc()).limit(51)).all()
        count = db.scalar(select(func.count()).select_from(DirectMessage)
                          .where(DirectMessage.dialog_id == row.id, *unread_condition(user)))
        return dict(id=row.id, person=person(other), unread_count=count,
                    messages=[message_payload(message, user) for message in reversed(latest[:50])],
                    older_before=latest[49].id if len(latest) > 50 else None,
                    read_through=latest[0].id if latest and not before else None)

    def send(db, request, response, user, row, recipient_id, message, target):
        receipt, prior = begin_idempotent(db, request, response, user, 'direct-send', {**target, 'message': message})
        if prior is not None:
            return prior
        now = utc_now()
        reserve_write(db, user.id, 'direct', now)
        if row is None:
            count = db.scalar(select(func.count()).select_from(DirectDialog).where(DirectDialog.student_id == user.id))
            if count >= MAX_DIALOGS:
                raise HTTPException(409, 'Достигнут предел диалогов')
            row = DirectDialog(student_id=user.id, contact_id=recipient_id, updated_at=now)
            db.add(row)
            db.flush()
        else:
            count = db.scalar(select(func.count()).select_from(DirectMessage).where(DirectMessage.dialog_id == row.id))
            if count >= MAX_MESSAGES:
                raise HTTPException(409, 'Достигнут предел сообщений в диалоге. История доступна для чтения.')
            row.updated_at = now
        notice_id = None
        if user.role != 'student':
            notice = Notification(student_id=row.student_id, title='Новое личное сообщение',
                                  body=f'{user.full_name} ответил(а) в личной переписке.',
                                  category='direct', created_at=now, is_read=False, target=f'/app/direct/{row.id}')
            db.add(notice)
            db.flush()
            notice_id = notice.id
        new = DirectMessage(dialog_id=row.id, sender_id=user.id, body=message, created_at=now, notification_id=notice_id)
        db.add(new)
        db.flush()
        # The receipt needs only the stable IDs, not a second copy of the message.
        return commit_idempotent(db, receipt, {'dialog_id': row.id, 'message_id': new.id})

    @router.post('/dialogs', status_code=201, dependencies=write)
    def start(body: StartBody, request: Request, response: Response, user=Depends(require_student), db: Session = Depends(get_db)):
        lock_owner(db, user.id)
        valid_contact(db, body.recipient_id)
        row = db.scalar(select(DirectDialog).where(DirectDialog.student_id == user.id,
                                                  DirectDialog.contact_id == body.recipient_id).with_for_update())
        return send(db, request, response, user, row, body.recipient_id, body.message, {'recipient_id': body.recipient_id})

    @router.post('/dialogs/{dialog_id}/messages', status_code=201, dependencies=write)
    def reply(dialog_id: int, body: MessageBody, request: Request, response: Response,
              user=Depends(require_user), db: Session = Depends(get_db)):
        lock_owner(db, user.id)
        row = owned_dialog(db, dialog_id, user, for_update=True)
        return send(db, request, response, user, row, row.contact_id, body.message, {'dialog_id': dialog_id})

    @router.post('/dialogs/{dialog_id}/read', dependencies=write)
    def read(dialog_id: int, body: ReadBody, user=Depends(require_user), db: Session = Depends(get_db)):
        row = owned_dialog(db, dialog_id, user)
        if db.scalar(select(DirectMessage.id).where(DirectMessage.dialog_id == row.id,
                                                   DirectMessage.id == body.through_id)) is None:
            raise HTTPException(404, 'Сообщение не найдено')
        scope = (DirectMessage.dialog_id == row.id, DirectMessage.id <= body.through_id)
        result = db.execute(update(DirectMessage).where(*scope, *unread_condition(user)).values(read_at=utc_now()))
        if user.role == 'student':
            notifications = select(DirectMessage.notification_id).where(*scope, DirectMessage.notification_id.is_not(None))
            db.execute(update(Notification).where(Notification.student_id == user.id, Notification.id.in_(notifications))
                       .values(is_read=True))
        db.commit()
        return {'read_count': result.rowcount}

    return router
