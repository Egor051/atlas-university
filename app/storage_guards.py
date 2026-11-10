"""Owner locks and immutable identities for student-created personal records."""
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update, delete


def new_record_token():
    return uuid4().hex


def lock_owner(db, user_id):
    """Hold the owner's write lock until the caller commits the whole operation."""
    from .db import User
    if db.get_bind().dialect.name == 'sqlite':
        # SELECT alone does not start a sqlite3 legacy-mode transaction.
        db.execute(update(User).where(User.id == user_id).values(id=User.id))
    else:
        # NO KEY UPDATE serializes owner operations without conflicting with
        # concurrent child inserts' foreign-key KEY SHARE locks.
        db.scalar(select(User.id).where(User.id == user_id).with_for_update(key_share=True))


def require_record_token(request, row):
    expected = request.headers.get('X-ATLAS-Record') if request is not None else None
    if expected is not None:
        if not re.fullmatch(r'[a-f0-9]{32}', expected):
            raise HTTPException(422, 'Недопустимый идентификатор записи')
        if expected != row.record_token:
            raise HTTPException(409, {'code': 'record_changed', 'message': 'Эта запись удалена или заменена. Обновите раздел.'})
    return row.record_token


def identity_conditions(model, row, user):
    return (model.id == row.id, model.student_id == user.id,
            model.record_token == row.record_token)


def identity_conflict(db):
    db.rollback()
    raise HTTPException(409, {'code': 'record_changed', 'message': 'Запись изменилась или удалена. Обновите раздел.'})


def update_personal(db, model, row, user, values, request):
    require_record_token(request, row)
    changed = db.execute(update(model).where(*identity_conditions(model, row, user))
                         .values(**values).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        identity_conflict(db)
    # Refresh while the write lock is still held, never after commit/reuse.
    db.refresh(row)
    return row


def delete_personal(db, model, row, user, request, draft_kind=None):
    require_record_token(request, row)
    changed = db.execute(delete(model).where(*identity_conditions(model, row, user))
                         .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        identity_conflict(db)
    if draft_kind:
        from .improvement_db import PersonalDraft
        name = f'{draft_kind}:{row.id}:{row.record_token}'
        db.execute(delete(PersonalDraft).where(PersonalDraft.user_id == user.id,
                                             PersonalDraft.name == name))
