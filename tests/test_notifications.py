from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select

from app.db import Deadline, Notification, SessionLocal, campus_today, utc_now
from app.notification_migration import upgrade_notifications
from app.services_db import StudentPreference
from app.workspace_db import WorkspaceNotice
from test_api import client, sign_in


HEADERS = {'X-Requested-With': 'ATLAS'}
REMINDERS = '/api/notifications/deadline-reminders'


def test_reminders_are_preference_scoped_and_concurrent_repeats_are_idempotent():
    with client() as student, client() as other:
        sign_in(student, 'alina.demo', 'AtlasDemo!2026-A')
        sign_in(other, 'mark.demo', 'AtlasDemo!2026-M')
        owner = student.get('/api/me').json()['id']
        with SessionLocal() as db:
            settings = db.get(StudentPreference, owner)
            original = settings.deadline_reminders
            settings.deadline_reminders = False
            deadline = Deadline(student_id=owner, subject='Сроки', title='Проверка напоминания',
                                due_date=campus_today() + timedelta(days=2))
            db.add(deadline)
            db.flush()
            target = f'/app/assignments?id={deadline.id}'
            deadline_id = deadline.id
            db.commit()
        try:
            assert student.post(REMINDERS).status_code == 403
            assert student.post(REMINDERS, headers=HEADERS).json() == {'created': 0}
            with SessionLocal.begin() as db:
                db.get(StudentPreference, owner).deadline_reminders = True
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: student.post(REMINDERS, headers=HEADERS), range(2)))
            assert [response.status_code for response in responses] == [200, 200]
            assert 0 in [response.json()['created'] for response in responses]
            entries = student.get('/api/notifications?filter=deadline').json()
            reminder, = [row for row in entries if row['target'] == target]
            assert 'Проверка напоминания' in reminder['body']
            assert other.get(f"/api/notifications/{reminder['id']}").status_code == 404
        finally:
            with SessionLocal.begin() as db:
                db.query(Notification).filter(Notification.target == target, Notification.student_id == owner).delete()
                db.delete(db.get(Deadline, deadline_id))
                db.get(StudentPreference, owner).deadline_reminders = original


def test_workspace_backfill_preserves_owner_read_status_and_does_not_duplicate():
    with client() as staff:
        sign_in(staff, 'dean.demo', 'AtlasStaff!2026-D')
        uid = staff.get('/api/me').json()['id']
        with SessionLocal() as db:
            old = WorkspaceNotice(user_id=uid, title='Расписание', body='Проверка переноса',
                                  target='/app/schedule-changes/10', is_read=True, created_at=utc_now())
            db.add(old)
            db.flush()
            for _ in range(2):
                upgrade_notifications(db.connection())
            copied, = db.scalars(select(Notification).where(Notification.event_key == f'workspace:{old.id}')).all()
            assert (copied.student_id, copied.is_read, copied.category) == (uid, True, 'schedule')
            assert (copied.title, copied.body, copied.target) == (old.title, old.body, old.target)
