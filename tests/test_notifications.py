from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select

from app.db import Deadline, Notification, SessionLocal, campus_today, utc_now
from app.notification_migration import upgrade_notifications
from app.services_db import StudentPreference
from app.workspace_db import GroupWork, TeachingLoad, WorkDelivery, WorkspaceNotice
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


def test_scheduled_work_appears_at_publication_and_reminders_follow_exact_deadline():
    with client() as student, client() as teacher:
        sign_in(student, 'alina.demo', 'AtlasDemo!2026-A')
        sign_in(teacher, 'orlov.demo', 'AtlasTeach!2026-M')
        student_id = student.get('/api/me').json()['id']
        teacher_id = teacher.get('/api/me').json()['id']
        load_id = teacher.get('/api/teaching').json()['items'][0]['id']
        with SessionLocal.begin() as db:
            title = 'Публикация по заданному времени'
            now = utc_now()
            day = campus_today()
            preferences = db.get(StudentPreference, student_id)
            old_preference = preferences.deadline_reminders
            preferences.deadline_reminders = False
            deadline = Deadline(student_id=student_id, title=title,
                                subject=db.get(TeachingLoad, load_id).discipline.title, due_date=day)
            work = GroupWork(author_id=teacher_id, load_id=load_id, title=title, instructions='Шаги работы',
                             due=day, created_at=now, state='scheduled', publish_at=now + timedelta(minutes=1),
                             due_at=now + timedelta(hours=1))
            db.add_all([deadline, work])
            db.flush()
            deadline_id, work_id = deadline.id, work.id
            db.add(WorkDelivery(deadline_id=deadline_id, work_id=work_id))
        target = f'/app/assignments?id={deadline_id}'

        def notices():
            return [row for row in student.get('/api/notifications').json() if row['target'] == target]

        def refresh():
            response = student.post(REMINDERS, headers=HEADERS)
            assert response.status_code == 200, response.text

        try:
            assert all(row['id'] != deadline_id for row in student.get('/api/deadlines').json())
            assert all(row['title'] != title for row in student.get(
                '/api/campus/search', params={'q': title}).json()['items'])
            refresh()
            assert notices() == []
            with SessionLocal.begin() as db:
                db.get(GroupWork, work_id).publish_at = now - timedelta(seconds=1)
            assert any(row['id'] == deadline_id for row in student.get('/api/deadlines').json())
            refresh()
            refresh()
            assert [row['title'] for row in notices()] == ['Опубликовано учебное задание']
            with SessionLocal.begin() as db:
                db.get(StudentPreference, student_id).deadline_reminders = True
                db.get(GroupWork, work_id).due_at = now - timedelta(seconds=1)
                db.get(WorkDelivery, deadline_id).extended_until = now + timedelta(hours=2)
            refresh()
            assert any(row['title'] == 'Приближается срок сдачи' for row in notices())
            assert all(row['title'] != 'Срок сдачи истёк' for row in notices())
            with SessionLocal.begin() as db:
                db.get(WorkDelivery, deadline_id).extended_until = None
            refresh()
            refresh()
            assert sum(row['title'] == 'Срок сдачи истёк' for row in notices()) == 1
        finally:
            with SessionLocal.begin() as db:
                db.query(Notification).filter(Notification.target == target).delete()
                db.delete(db.get(WorkDelivery, deadline_id))
                db.flush()
                db.delete(db.get(GroupWork, work_id))
                db.delete(db.get(Deadline, deadline_id))
                db.get(StudentPreference, student_id).deadline_reminders = old_preference
