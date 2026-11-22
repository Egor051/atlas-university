"""Acceptance for the synthetic semester, isolated from all other fixtures."""
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from secrets import token_urlsafe

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select

from app import db, main
from app.academic_points import AssignmentPointCorrection, PointAward
from app.assignment_db import SubmissionAttempt
from app.contest import seed
from app.learning_db import AssignmentSubmission, Attendance
from app.schedule_occurrences import campus_instant
from app.services_db import CampusEvent, ConsultationBooking, ConsultationSlot, EventRegistration, FinanceEntry
from app.session_security import as_utc
from app.vuc import TRANSITIONS as VUC_TRANSITIONS
from app.vuc_db import VucApplication, VucApplicationEvent
from app.workspace_db import GroupMember, GroupWork, ScheduledClass, WorkDelivery, WorkFeedback


@contextmanager
def use_database(path, patch):
    url = 'sqlite:///' + path.as_posix()
    engine = create_engine(url, connect_args={'check_same_thread': False})
    event.listen(engine, 'connect', db.sqlite_foreign_keys)
    old_bind = db.SessionLocal.kw['bind']
    db.SessionLocal.configure(bind=engine)
    patch.setenv('DATABASE_URL', url)
    patch.setattr(seed, 'DATABASE_URL', url)
    patch.setattr(db, 'DATABASE_URL', url)
    patch.setattr(db, 'engine', engine)
    patch.setattr(main, 'engine', engine)
    try:
        yield engine
    finally:
        db.SessionLocal.configure(bind=old_bind)
        engine.dispose()


@pytest.fixture(scope='module')
def contest_db(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('ATLAS_CERTIFICATE_KEY', token_urlsafe(32))
        freeze(patch, date(2026, 11, 22), '12:30')
        path = tmp_path_factory.mktemp('contest-data') / 'semester.db'
        with use_database(path, patch):
            yield seed.install()


def login(name, password, role):
    client = TestClient(main.app)
    response = client.post('/api/login', headers={'Origin': 'http://testserver', 'X-Requested-With': 'ATLAS'},
                           json={'login': name, 'password': password})
    assert response.status_code == 200, response.text
    assert response.json()['user']['role'] == role
    return client


def get(client, path):
    response = client.get(path)
    assert response.status_code == 200, (path, response.text)
    return response.json()


def freeze(monkeypatch, day, clock):
    now = campus_instant(day, clock)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(db, 'datetime', Frozen)


def test_install_retry_and_app_restart_preserve_snapshot(contest_db):
    assert contest_db['status'] == 'initialized'
    assert contest_db['rows']['absence_certificate_files'] == 4
    db.initialize_database()
    repeated = seed.install()
    assert repeated == {**contest_db, 'status': 'already_initialized'}
    with db.SessionLocal() as session:
        assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').first() is None
        assert session.get(db.ContestDataset, seed.NAME)


def test_refuses_an_occupied_target_before_touching_its_schema(tmp_path, monkeypatch):
    with use_database(tmp_path / 'occupied.db', monkeypatch) as engine:
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE existing_data (name TEXT NOT NULL)')
            connection.exec_driver_sql("INSERT INTO existing_data VALUES ('keep')")
        with pytest.raises(seed.DatasetError, match='already has tables'):
            seed.install()
        with engine.connect() as connection:
            assert inspect(connection).get_table_names() == ['existing_data']
            assert connection.exec_driver_sql('SELECT name FROM existing_data').scalar_one() == 'keep'


def test_failed_install_is_retryable(tmp_path, monkeypatch):
    from app.contest import campus

    def fail(*_):
        raise RuntimeError('forced fixture failure')

    with use_database(tmp_path / 'retry.db', monkeypatch) as engine:
        with monkeypatch.context() as failure:
            failure.setattr(campus, 'seed_campus', fail)
            with pytest.raises(RuntimeError, match='forced fixture failure'):
                seed.install()
        assert inspect(engine).get_table_names() == []
        assert seed.install()['status'] == 'initialized'


def test_semester_history_and_schedule_are_consistent(contest_db):
    with db.SessionLocal() as session:
        seed.verify_ledger(session)
        windows = defaultdict(list)
        lessons = {row.id: row for row in session.scalars(select(ScheduledClass).order_by(ScheduledClass.starts_at))}
        for lesson in lessons.values():
            if lesson.status == 'active':
                for scope, identity in (('room', lesson.room_id), ('teacher', lesson.teacher_id), ('group', lesson.group_id)):
                    windows[scope, identity].append(lesson)
        assert all(first.ends_at <= second.starts_at for rows in windows.values() for first, second in zip(rows, rows[1:]))
        for mark in session.scalars(select(Attendance)):
            lesson = lessons[mark.class_id]
            assert lesson.status == 'active'
            assert as_utc(lesson.ends_at) <= seed.HISTORY_THROUGH
            assert session.get(GroupMember, mark.student_id).group_id == lesson.group_id
            assert lesson.load.discipline.title == mark.subject
        dates = set()
        for award in session.scalars(select(PointAward)):
            lesson = lessons[award.class_id]
            assert lesson.load.discipline_id == award.discipline_id
            assert lesson.teacher.user_id == award.actor_id
            assert as_utc(lesson.ends_at) <= as_utc(award.created_at) <= seed.HISTORY_THROUGH
            assert session.get(GroupMember, award.student_id).group_id == lesson.group_id
            if award.source_kind == 'assignment':
                feedback = session.get(WorkFeedback, award.review_id)
                assert feedback.score == award.points and feedback.created_at == award.created_at
                assert feedback.author_id == award.actor_id
            dates.add(award.created_at.month)
        assert dates == {9, 10, 11}
        for row in session.scalars(select(AssignmentPointCorrection)):
            assert row.corrected_points > row.previous_points
        attempts = {(row.submission_id, row.version): row for row in session.scalars(select(SubmissionAttempt))}
        for item in attempts.values():
            submission = session.get(AssignmentSubmission, item.submission_id)
            delivery = session.get(WorkDelivery, submission.deadline_id)
            work = session.get(GroupWork, delivery.work_id)
            assert work.created_at <= work.publish_at <= item.submitted_at
            assert as_utc(item.submitted_at) <= seed.HISTORY_THROUGH
        assert any(row.late for row in attempts.values())
        assert any(row.number == 2 for row in attempts.values())
        for feedback in session.scalars(select(WorkFeedback)):
            assert attempts[feedback.submission_id, feedback.submitted_version].submitted_at <= feedback.created_at
            assert as_utc(feedback.created_at) <= seed.HISTORY_THROUGH
        for work in session.scalars(select(GroupWork).where(GroupWork.state == 'scheduled')):
            assert as_utc(work.created_at) <= seed.HISTORY_THROUGH < as_utc(work.publish_at) < as_utc(work.due_at)
        for row in session.scalars(select(db.DocumentRequest)):
            history = list(session.scalars(select(db.RequestEvent).where(
                db.RequestEvent.request_id == row.id).order_by(db.RequestEvent.created_at)))
            assert history[0].status == 'submitted' and history[-1].status == row.status
            assert history[0].created_at == row.created_at and history[-1].created_at == row.updated_at
            for first, second in zip(history, history[1:]):
                assert first.status == second.status or second.status in main.ALLOWED_TRANSITIONS[first.status]
        for row in session.scalars(select(VucApplication)):
            events = list(session.scalars(select(VucApplicationEvent).where(
                VucApplicationEvent.application_id == row.id).order_by(VucApplicationEvent.created_at)))
            assert events[0].status == 'inquiry' and events[-1].status == row.status
            assert all(second.status in VUC_TRANSITIONS[first.status] for first, second in zip(events, events[1:]))
            assert row.campaign.program_snapshot['id'] == row.campaign.program_id


@pytest.mark.parametrize('day,clock', [(23, '00:00'), (25, '12:15'), (28, '23:59')])
def test_contest_dates_at_public_entry_points(contest_db, monkeypatch, day, clock):
    freeze(monkeypatch, date(2026, 11, day), clock)
    with login('alina.demo', 'AtlasDemo!2026-A', 'student') as student:
        home = get(student, '/api/dashboard')
        assert home['next_lesson'] and home['week_classes'] and home['deadlines'] and home['unread_count']
        assert {row['score'] for row in home['grades']['items']} <= set(range(101))
        assert get(student, '/api/schedule')['days']
        assert get(student, '/api/disciplines')['items']
        assert get(student, '/api/learning/progress')['items']
        assert get(student, '/api/learning/attendance-register')['items']
        assert get(student, '/api/learning/exams')['items']
        assert get(student, '/api/services/consultations')['items']
        assert get(student, '/api/services/events?scope=upcoming')['items']
        assert get(student, '/api/announcements')['items']
        assert get(student, '/api/services/finance')['summary']['balance_kopecks'] > 0
        rows = get(student, '/api/learning/assignments')['items']
        states = {row['status'] for row in rows}
        assert {'not_started', 'accepted', 'in_review', 'revision_required'} <= states
        assert any(row['title'] == 'Сравнение списка и матрицы смежности' for row in rows) == (day >= 25)
        revised = next(row for row in rows if row['status'] == 'revision_required')
        detail = get(student, f"/api/learning/assignments/{revised['id']}")
        assert detail['feedback'] and detail['attempts'] and detail['revision_due_at']
        assert get(student, '/api/campus/search?q=граф')['items']
        assert get(student, '/api/units/vuc/admission')['campaigns']
        assert get(student, '/api/units/vuc/admission/applications')['items']
        assert get(student, '/api/units/union/cases')['items']


def test_roles_and_foreign_records(contest_db, monkeypatch):
    freeze(monkeypatch, date(2026, 11, 25), '12:15')
    with (login('alina.demo', 'AtlasDemo!2026-A', 'student') as alina,
          login('mark.demo', 'AtlasDemo!2026-M', 'student') as mark,
          login('dean.demo', 'AtlasStaff!2026-D', 'staff') as office,
          login('orlov.demo', 'AtlasTeach!2026-M', 'teacher') as teacher,
          login('schedule.demo', 'AtlasRooms!2026-S', 'scheduler') as scheduler,
          login('registry.demo', 'AtlasRegistry!2026-R', 'admin') as registry,
          login('union.demo', 'AtlasUnion!2026-U', 'union') as union,
          login('vuc.demo', 'AtlasCenter!2026-V', 'vuc') as vuc):
        resources = (
            ('/api/requests?limit=30', '/api/requests/'),
            ('/api/notifications?limit=30', '/api/notifications/'),
            ('/api/learning/assignments', '/api/learning/assignments/'),
            ('/api/direct/dialogs', '/api/direct/dialogs/'),
            ('/api/units/union/cases', '/api/units/union/cases/'),
            ('/api/units/vuc/admission/applications', '/api/units/vuc/admission/applications/'),
        )
        for listing, resource in resources:
            owned = get(alina, listing)
            row = (owned if isinstance(owned, list) else owned['items'])[0]
            assert mark.get(resource + str(row['id'])).status_code == 404
        assert alina.get('/api/staff/overview').status_code == 403
        assert office.get('/api/grades').status_code == 403
        assert office.get('/api/schedule').status_code == 403
        assert get(office, '/api/staff/overview')['requests_total'] == contest_db['rows']['document_requests']
        load = get(teacher, '/api/teaching')['items'][0]
        assert get(teacher, f"/api/teaching/{load['id']}/works")['items']
        assert get(scheduler, '/api/scheduling/changes')['items']
        assert get(registry, '/api/registry')['groups']
        assert get(union, '/api/units/union/cases')['items']
        assert get(vuc, '/api/units/vuc/admission/applications')['items']


def test_service_counters_follow_owned_history(contest_db):
    with db.SessionLocal() as session:
        for model, booking_model, foreign_key, current in (
            (ConsultationSlot, ConsultationBooking, ConsultationBooking.slot_id, 'booked_count'),
            (CampusEvent, EventRegistration, EventRegistration.event_id, 'registered_count'),
        ):
            for row in session.scalars(select(model)):
                bookings = list(session.scalars(select(booking_model).where(foreign_key == row.id)))
                assert getattr(row, current) == sum(item.status == 'active' for item in bookings)
                assert all(item.created_at < row.start_at for item in bookings)
        for row in session.scalars(select(FinanceEntry)):
            assert row.amount_kopecks > 0 and row.date < seed.FIRST_REVIEW
