"""Campus service authorization, persistence and capacity regressions."""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, func

_directory = tempfile.TemporaryDirectory(prefix='atlas-services-')
if 'app.db' not in sys.modules:
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_directory.name) / 'services.db')

from app.main import app
from app.db import SessionLocal, engine, utc_now, User, Notification
from app.services_db import (ConsultationSlot, ConsultationBooking, CampusEvent,
                             EventRegistration, LibraryBook, LibraryLoan,
                             SupportTicket, TicketMessage, StudentPreference,
                             seed_services)

atexit.register(engine.dispose)
HEADERS = {'X-Requested-With': 'ATLAS'}


def login(api, account='alina.demo'):
    password = {'alina.demo': 'AtlasDemo!2026-A', 'mark.demo': 'AtlasDemo!2026-M', 'dean.demo': 'AtlasStaff!2026-D'}[account]
    result = api.post('/api/login', json={'login': account, 'password': password}, headers=HEADERS)
    assert result.status_code == 200, result.text
    return result.json()['user']


def slot_payload(capacity=1):
    start = utc_now()+timedelta(days=20)
    return dict(teacher='Вымышленный преподаватель', subject='Проверка консультации', start_at=start.isoformat(), end_at=(start+timedelta(hours=1)).isoformat(), room='Тест-А-100', capacity=capacity)


def event_payload(capacity=1):
    start = utc_now()+timedelta(days=21)
    return dict(title='Вымышленное учебное событие', category='science', description='Описание вымышленного события для проверки регистрации.', start_at=start.isoformat(), end_at=(start+timedelta(hours=2)).isoformat(), location='Тестовый учебный корпус', capacity=capacity)


def new_ticket(api, title='Вопрос по учебному плану'):
    result = api.post('/api/services/tickets', json={'topic': 'academic', 'title': title, 'message': 'Пожалуйста, уточните демонстрационные требования по учебному плану.'}, headers=HEADERS)
    assert result.status_code == 201, result.text
    return result.json()


def test_services_require_login_and_separate_roles():
    paths = ['contacts', 'knowledge', 'consultations', 'bookings', 'tickets', 'events', 'registrations', 'library', 'loans', 'finance', 'preferences']
    with TestClient(app) as anonymous, TestClient(app) as student, TestClient(app) as staff:
        login(student)
        login(staff, 'dean.demo')
        for path in paths:
            assert anonymous.get('/api/services/'+path).status_code == 401
            assert student.get('/api/services/'+path).status_code == 200
            assert staff.get('/api/services/'+path).status_code == (200 if path == 'preferences' else 403)
        for path in ['overview', 'tickets', 'consultations', 'events']:
            assert anonymous.get('/api/staff/'+path).status_code == 401
            assert student.get('/api/staff/'+path).status_code == 403
            assert staff.get('/api/staff/'+path).status_code == 200

        path = '/api/services/preferences'
        student_before = student.get(path).json()
        staff_before = staff.get(path).json()
        changed = staff.post(path, json={'compact_mode': not staff_before['compact_mode']}, headers=HEADERS)
        assert changed.status_code == 200
        assert changed.json()['compact_mode'] is not staff_before['compact_mode']
        assert staff.get(path).json() == changed.json()
        assert student.get(path).json() == student_before
        assert staff.post(path, json={'compact_mode': staff_before['compact_mode']}, headers=HEADERS).json() == staff_before


def test_contacts_search_and_finance_are_fictional_and_isolated():
    with TestClient(app) as a, TestClient(app) as b:
        login(a)
        login(b, 'mark.demo')
        contacts = a.get('/api/services/contacts?q=ОРЛОВ').json()['items']
        assert len(contacts) == 1 and contacts[0]['email'].endswith('.example')
        assert a.get('/api/services/knowledge?q=КОНСПЕКТЫ').json()['items']
        assert not a.get('/api/services/knowledge?q=КНИГУ').json()['items']
        first = a.get('/api/services/finance').json()
        other = b.get('/api/services/finance').json()
        assert first['summary']['concept'] is True
        assert first['summary']['credits_kopecks'] != other['summary']['credits_kopecks']
        assert not set(x['id'] for x in first['items']) & set(x['id'] for x in other['items'])
        assert a.get('/api/services/finance?student_id=2').json() == first
        assert all(isinstance(x['amount_kopecks'], int) for x in first['items'])


def test_ticket_thread_idor_staff_reply_notification_and_closed_state():
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as staff:
        login(a)
        login(b, 'mark.demo')
        login(staff, 'dean.demo')
        row = new_ticket(a)
        ticket_id = row['id']
        assert len(row['messages']) == 1 and row['messages'][0]['actor_role'] == 'student'
        assert b.get(f'/api/services/tickets/{ticket_id}').status_code == 404
        assert all(x['id'] != ticket_id for x in b.get('/api/services/tickets').json()['items'])
        for action, body in [('messages', {'message': 'Чужой ответ'}), ('close', {})]:
            assert b.post(f'/api/services/tickets/{ticket_id}/{action}', json=body, headers=HEADERS).status_code == 404
        result = staff.post(f'/api/staff/tickets/{ticket_id}/messages', json={'message': 'Требования опубликованы в учебном плане.'}, headers=HEADERS)
        assert result.status_code == 200 and result.json()['messages'][-1]['actor_role'] == 'staff'
        assert 'student_name' in result.json()
        detail = a.get(f'/api/services/tickets/{ticket_id}').json()
        assert 'student_name' not in detail and len(detail['messages']) == 2
        notices = a.get('/api/notifications').json()
        assert any(x['title'] == 'Учебный офис ответил' for x in notices)
        assert a.post(f'/api/services/tickets/{ticket_id}/close', json={}, headers=HEADERS).status_code == 200
        assert staff.post(f'/api/staff/tickets/{ticket_id}/messages', json={'message': 'Поздний ответ'}, headers=HEADERS).status_code == 409
        assert a.post(f'/api/services/tickets/{ticket_id}/messages', json={'message': 'Поздний вопрос'}, headers=HEADERS).status_code == 409
        assert a.post(f'/api/services/tickets/{ticket_id}/close', json={}, headers=HEADERS).status_code == 409
        with SessionLocal() as db:
            assert db.get(SupportTicket, ticket_id).status == 'closed'
            assert db.scalar(select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == ticket_id)) == 2


def test_consultation_duplicate_capacity_owner_cancel_and_rebooking():
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as staff:
        login(a)
        login(b, 'mark.demo')
        login(staff, 'dean.demo')
        slot = staff.post('/api/staff/consultations', json=slot_payload(), headers=HEADERS).json()
        booking = a.post(f'/api/services/consultations/{slot["id"]}/book', json={}, headers=HEADERS)
        assert booking.status_code == 201, booking.text
        booking = booking.json()
        assert a.post(f'/api/services/consultations/{slot["id"]}/book', json={}, headers=HEADERS).status_code == 409
        assert b.post(f'/api/services/consultations/{slot["id"]}/book', json={}, headers=HEADERS).status_code == 409
        assert b.post(f'/api/services/bookings/{booking["id"]}/cancel', json={}, headers=HEADERS).status_code == 404
        other_view = next(x for x in b.get('/api/services/consultations').json()['items'] if x['id'] == slot['id'])
        assert other_view['my_booking_id'] is None and other_view['booked_count'] == 1
        assert a.post(f'/api/services/bookings/{booking["id"]}/cancel', json={}, headers=HEADERS).status_code == 200
        assert a.post(f'/api/services/bookings/{booking["id"]}/cancel', json={}, headers=HEADERS).status_code == 409
        assert b.post(f'/api/services/consultations/{slot["id"]}/book', json={}, headers=HEADERS).status_code == 201
        with SessionLocal() as db:
            assert db.get(ConsultationSlot, slot['id']).booked_count == 1


def test_consultation_last_seat_is_atomic_between_students():
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as staff:
        login(a)
        login(b, 'mark.demo')
        login(staff, 'dean.demo')
        row = staff.post('/api/staff/consultations', json=slot_payload(), headers=HEADERS).json()
        def reserve(api):
            return api.post(f'/api/services/consultations/{row["id"]}/book', json={}, headers=HEADERS).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(reserve, [a, b]))
        assert sorted(codes) == [201, 409]
        with SessionLocal() as db:
            assert db.get(ConsultationSlot, row['id']).booked_count == 1
            assert db.scalar(select(func.count()).select_from(ConsultationBooking).where(ConsultationBooking.slot_id == row['id'], ConsultationBooking.status == 'active')) == 1


def test_events_last_seat_idor_cancel_and_duplicates():
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as staff:
        login(a)
        login(b, 'mark.demo')
        login(staff, 'dean.demo')
        result = staff.post('/api/staff/events', json=event_payload(), headers=HEADERS)
        assert result.status_code == 201, result.text
        event = result.json()
        def reserve(api):
            return api.post(f'/api/services/events/{event["id"]}/register', json={}, headers=HEADERS)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, [a, b]))
        assert sorted(x.status_code for x in results) == [201, 409]
        winner = a if results[0].status_code == 201 else b
        other = b if winner is a else a
        row = next(x.json() for x in results if x.status_code == 201)
        assert winner.post(f'/api/services/events/{event["id"]}/register', json={}, headers=HEADERS).status_code == 409
        assert other.post(f'/api/services/registrations/{row["id"]}/cancel', json={}, headers=HEADERS).status_code == 404
        assert winner.post(f'/api/services/registrations/{row["id"]}/cancel', json={}, headers=HEADERS).status_code == 200
        assert winner.post(f'/api/services/registrations/{row["id"]}/cancel', json={}, headers=HEADERS).status_code == 409
        with SessionLocal() as db:
            assert db.get(CampusEvent, event['id']).registered_count == 0


def test_library_last_copy_is_atomic_owner_return_cannot_be_repeated():
    with TestClient(app) as a, TestClient(app) as b:
        login(a)
        login(b, 'mark.demo')
        with SessionLocal() as db:
            book = LibraryBook(title='Тестовый единственный экземпляр', author='Тестовый автор', subject='Проверка библиотеки', description='Вымышленное учебное издание.', total=1, available=1)
            db.add(book)
            db.commit()
            book_id = book.id
        def borrow(api):
            return api.post(f'/api/services/library/{book_id}/borrow', json={}, headers=HEADERS)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(borrow, [a, b]))
        assert sorted(x.status_code for x in results) == [201, 409]
        owner = a if results[0].status_code == 201 else b
        other = b if owner is a else a
        loan = next(x.json() for x in results if x.status_code == 201)
        assert owner.post(f'/api/services/library/{book_id}/borrow', json={}, headers=HEADERS).status_code == 409
        assert all(x['id'] != loan['id'] for x in other.get('/api/services/loans').json()['items'])
        assert other.post(f'/api/services/loans/{loan["id"]}/return', json={}, headers=HEADERS).status_code == 404
        assert owner.post(f'/api/services/loans/{loan["id"]}/return', json={}, headers=HEADERS).status_code == 200
        assert owner.post(f'/api/services/loans/{loan["id"]}/return', json={}, headers=HEADERS).status_code == 409
        with SessionLocal() as db:
            assert db.get(LibraryBook, book_id).available == 1
            assert db.get(LibraryLoan, loan['id']).status == 'returned'


def test_services_csrf_extra_fields_strict_types_and_datetime_validation():
    with TestClient(app) as student, TestClient(app) as staff:
        login(student)
        login(staff, 'dean.demo')
        valid = {'topic': 'academic', 'title': 'Демонстрационный вопрос', 'message': 'Достаточно длинное сообщение.'}
        assert student.post('/api/services/tickets', json=valid).status_code == 403
        assert student.post('/api/services/tickets', json=valid, headers={**HEADERS, 'Origin': 'https://outside.example'}).status_code == 403
        assert student.post('/api/services/tickets', json={**valid, 'student_id': 2}, headers=HEADERS).status_code == 422
        assert student.post('/api/services/tickets', json={**valid, 'title': '     '}, headers=HEADERS).status_code == 422
        assert student.post('/api/services/tickets', json={**valid, 'message': 'bad\u0000text'}, headers=HEADERS).status_code == 422
        payload = slot_payload()
        assert staff.post('/api/staff/consultations', json={**payload, 'capacity': True}, headers=HEADERS).status_code == 422
        assert staff.post('/api/staff/consultations', json={**payload, 'capacity': '5'}, headers=HEADERS).status_code == 422
        assert staff.post('/api/staff/consultations', json={**payload, 'start_at': '2020-01-01T12:00:00+03:00'}, headers=HEADERS).status_code == 422
        assert staff.post('/api/staff/consultations', json={**payload, 'start_at': '2026-11-20T12:00:00'}, headers=HEADERS).status_code == 422
        assert staff.post('/api/staff/events', json={**event_payload(), 'capacity': 0}, headers=HEADERS).status_code == 422
        assert student.post('/api/services/preferences', json={'email_notifications': 'false', 'deadline_reminders': True, 'compact_mode': False, 'weekly_goal': 8}, headers=HEADERS).status_code == 422


def test_preferences_persist_without_changing_another_student_or_seeded_inventory():
    with TestClient(app) as a, TestClient(app) as b:
        who = login(a)
        login(b, 'mark.demo')
        original = b.get('/api/services/preferences').json()
        mine = dict(email_notifications=True, deadline_reminders=False, compact_mode=True, weekly_goal=12)
        assert a.post('/api/services/preferences', json=mine, headers=HEADERS).json() == mine
        assert a.get('/api/services/preferences').json() == mine
        assert b.get('/api/services/preferences').json() == original
        with SessionLocal() as db:
            counts = [db.scalar(select(func.count()).select_from(model)) for model in (ConsultationSlot, CampusEvent, LibraryBook)]
            seed_services(db)
            seed_services(db)
            db.commit()
            assert [db.scalar(select(func.count()).select_from(model)) for model in (ConsultationSlot, CampusEvent, LibraryBook)] == counts
            assert db.get(StudentPreference, who['id']).weekly_goal == 12
    with TestClient(app) as restored:
        login(restored)
        assert restored.get('/api/services/preferences').json() == mine


def test_offset_timestamps_roundtrip_as_same_instant_and_started_resources_are_closed():
    with TestClient(app) as student, TestClient(app) as staff:
        login(student)
        login(staff, 'dean.demo')
        offset = timezone(timedelta(hours=3))
        start = (utc_now()+timedelta(days=22)).astimezone(offset)
        payload = {**slot_payload(), 'start_at': start.isoformat(), 'end_at': (start+timedelta(hours=1)).isoformat()}
        created = staff.post('/api/staff/consultations', json=payload, headers=HEADERS)
        assert created.status_code == 201, created.text
        row = created.json()
        reloaded = next(x for x in student.get('/api/services/consultations').json()['items'] if x['id'] == row['id'])
        assert datetime.fromisoformat(reloaded['start_at']) == start
        event = staff.post('/api/staff/events', json={**event_payload(), 'start_at': start.isoformat(), 'end_at': (start+timedelta(hours=2)).isoformat()}, headers=HEADERS)
        assert event.status_code == 201, event.text
        saved_event = next(x for x in student.get('/api/services/events').json()['items'] if x['id'] == event.json()['id'])
        assert datetime.fromisoformat(saved_event['start_at']) == start
        with SessionLocal() as db:
            slot = db.get(ConsultationSlot, row['id'])
            slot.start_at = utc_now()-timedelta(minutes=1)
            item = db.get(CampusEvent, event.json()['id'])
            item.start_at = utc_now()-timedelta(minutes=1)
            db.commit()
        assert student.post(f'/api/services/consultations/{row["id"]}/book', json={}, headers=HEADERS).status_code == 409
        assert student.post(f'/api/services/events/{event.json()["id"]}/register', json={}, headers=HEADERS).status_code == 409


def test_broadcast_only_staff_creates_per_student_notifications():
    with TestClient(app) as student, TestClient(app) as staff:
        login(student)
        login(staff, 'dean.demo')
        body = {'title': 'Тестовое объявление учебного офиса', 'body': 'Вымышленное сообщение, опубликованное в рамках проверки.', 'category': 'announcement'}
        assert student.post('/api/staff/announcements', json=body, headers=HEADERS).status_code == 403
        assert staff.post('/api/staff/announcements', json=body).status_code == 403
        result = staff.post('/api/staff/announcements', json=body, headers=HEADERS)
        assert result.status_code == 201, result.text
        with SessionLocal() as db:
            count = db.scalar(select(func.count()).select_from(User).where(User.role == 'student'))
            assert result.json()['sent'] == count
            notices = db.scalars(select(Notification).where(Notification.title == body['title'])).all()
            assert len(notices) == count
            assert len({n.student_id for n in notices}) == count
        overview = staff.get('/api/staff/overview').json()
        assert overview['concept'] is True and 'open_tickets' in overview
        assert 'grades' not in overview and 'finance' not in overview
