"""Generate account-scoped deadline reminders without repeating an event."""
from datetime import datetime, timedelta

from sqlalchemy import String, cast, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .db import CAMPUS_TZ, Deadline, Notification, utc_now
from .services_db import StudentPreference
from .workspace_db import GroupWork, WorkDelivery


def pending_publications(db, user_id, now):
    key = literal('work-publish:') + cast(GroupWork.id, String) + ':' + cast(Deadline.id, String)
    rows = db.execute(
        select(Deadline.id, Deadline.title, key.label('event_key'))
        .join(WorkDelivery, WorkDelivery.deadline_id == Deadline.id)
        .join(GroupWork, GroupWork.id == WorkDelivery.work_id)
        .where(Deadline.student_id == user_id, WorkDelivery.active.is_(True),
               GroupWork.state == 'scheduled', GroupWork.publish_at <= now,
               ~select(Notification.id).where(Notification.event_key == key).exists())
        .order_by(GroupWork.publish_at, Deadline.id).limit(200)
    ).all()
    return [dict(student_id=user_id, title='Опубликовано учебное задание', body=row.title,
                 category='academic', is_read=False, created_at=now,
                 target=f'/app/assignments?id={row.id}', event_key=row.event_key) for row in rows]


def pending_deadlines(db, user_id, now):
    from .assignment_workflow import ACTIONABLE, student_assignment_results

    today = now.astimezone(CAMPUS_TZ).date()
    rows = student_assignment_results(db, user_id, limit=None, max_date=today + timedelta(days=3))
    values = []
    for row in rows:
        if row['state'] != 'published' or row['status'] not in ACTIONABLE:
            continue
        legacy = row['max_points'] is None
        if legacy and row['is_done']:
            continue
        deadline = datetime.fromisoformat(row['due_at']).astimezone(CAMPUS_TZ)
        overdue = deadline < now
        # Keep the previous event identity for date-only tasks, including reminders
        # already generated before this release.
        stamp = row['due_date'] if legacy else row['due_at']
        phase = 'deadline-overdue' if overdue else 'deadline'
        date_label = deadline.strftime('%d.%m.%Y' if legacy else '%d.%m.%Y, %H:%M МСК')
        values.append(dict(student_id=user_id, category='deadline', is_read=False, created_at=now,
                           title='Срок сдачи истёк' if overdue else 'Приближается срок сдачи',
                           body=f"{row['title']} · до {date_label}", target=f"/app/assignments?id={row['id']}",
                           event_key=f"{phase}:{user_id}:{row['id']}:{stamp}"))
    return values


def create_deadline_reminders(db, user_id):
    now = utc_now()
    values = pending_publications(db, user_id, now)
    preferences = db.get(StudentPreference, user_id)
    if preferences is None or preferences.deadline_reminders:
        values.extend(pending_deadlines(db, user_id, now))
    if not values:
        return 0
    seen = set(db.scalars(select(Notification.event_key).where(
        Notification.student_id == user_id, Notification.event_key.is_not(None))))
    values = [value for value in values if value['event_key'] not in seen]
    if not values:
        return 0
    insert = pg_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
    saved = 0
    for offset in range(0, len(values), 100):
        statement = (insert(Notification).values(values[offset:offset + 100])
                     .on_conflict_do_nothing(index_elements=['event_key']).returning(Notification.id))
        saved += len(db.scalars(statement).all())
    db.commit()
    return saved
