"""Generate account-scoped deadline reminders without repeating an event."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .db import Deadline, Notification, campus_today, utc_now
from .services_db import StudentPreference


def create_deadline_reminders(db, user_id):
    preferences = db.get(StudentPreference, user_id)
    if preferences is not None and not preferences.deadline_reminders:
        return 0
    today = campus_today()
    due = db.scalars(select(Deadline).where(Deadline.student_id == user_id,
                     Deadline.is_done.is_(False), Deadline.due_date.between(today, today + timedelta(days=3)))
                     .order_by(Deadline.due_date, Deadline.id).limit(200)).all()
    if not due:
        return 0
    now = utc_now()
    insert = pg_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
    values = [dict(student_id=user_id, title='Приближается срок сдачи',
                   body=f'{row.title} · до {row.due_date:%d.%m.%Y}', category='deadline',
                   is_read=False, created_at=now, target=f'/app/assignments?id={row.id}',
                   event_key=f'deadline:{user_id}:{row.id}:{row.due_date.isoformat()}') for row in due]
    statement = (insert(Notification).values(values).on_conflict_do_nothing(index_elements=['event_key'])
                 .returning(Notification.id))
    created = db.scalars(statement).all()
    db.commit()
    return len(created)
