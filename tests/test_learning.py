"""Learning workspace behavior and negative authorization regressions."""
import atexit
import os
import sys
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

_test_directory = tempfile.TemporaryDirectory(prefix='atlas-learning-')
if 'app.db' not in sys.modules:
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_directory.name) / 'learning.db')
from app.main import app
from app.db import SessionLocal, User, Deadline, Grade, engine, initialize_database, campus_today
from app.learning_db import FocusSession, Quiz, LearningSeed, StudyNote
atexit.register(engine.dispose)

HEADERS = {'X-Requested-With': 'ATLAS'}
ACCOUNTS = {'a': ('alina.demo', 'AtlasDemo!2026-A'), 'b': ('mark.demo', 'AtlasDemo!2026-M'), 'staff': ('dean.demo', 'AtlasStaff!2026-D')}
ROOT = '/api/learning/'


def signed(api, account='a'):
    login, password = ACCOUNTS[account]
    result = api.post('/api/login', json={'login': login, 'password': password}, headers=HEADERS)
    assert result.status_code == 200, result.text
    return api


def post(api, path, body=None):
    return api.post(ROOT + path, json=body, headers=HEADERS)


def fresh_title():
    return 'Учебный пример ' + uuid.uuid4().hex[:12]


@pytest.mark.parametrize('path', ['courses', 'assignments', 'exams', 'notes', 'flashcards', 'quizzes', 'quiz-attempts', 'attendance', 'tasks', 'focus-sessions'])
def test_learning_lists_require_student_and_never_accept_staff_role(path):
    with TestClient(app) as api:
        assert api.get(ROOT + path).status_code == 401
        signed(api, 'staff')
        assert api.get(ROOT + path).status_code == 403


def test_course_progress_is_owned_persistent_and_does_not_change_grades():
    with TestClient(app) as a, TestClient(app) as b:
        signed(a); signed(b, 'b')
        course = a.get(ROOT + 'courses').json()['items'][0]
        other = b.get(ROOT + 'courses').json()['items'][0]
        assert course['subject'] != other['subject']
        grades_before = a.get('/api/grades').json()
        module = course['modules'][0]
        route = f'courses/{course["id"]}/modules/{module["id"]}'
        assert b.get(ROOT + f'courses/{course["id"]}').status_code == 404
        assert post(b, route, {'is_done': True}).status_code == 404
        assert post(a, f'courses/{course["id"]}/modules/{other["modules"][0]["id"]}', {'is_done': True}).status_code == 404
        assert post(a, route, {'is_done': 'true'}).status_code == 422
        assert a.post(ROOT + route, json={'is_done': True}).status_code == 403
        changed = post(a, route, {'is_done': not module['is_done']})
        assert changed.status_code == 200, changed.text
        initialize_database()
        restored = a.get(ROOT + f'courses/{course["id"]}').json()
        assert restored['modules'][0]['is_done'] is not module['is_done']
        assert a.get('/api/grades').json() == grades_before


def test_assignment_submission_withdrawal_resubmission_preserves_personal_plan_and_blocks_idor():
    with TestClient(app) as a, TestClient(app) as b:
        signed(a); signed(b, 'b')
        task = a.get(ROOT + 'assignments').json()['items'][0]
        route = f'assignments/{task["id"]}'
        before = a.get('/api/deadlines').json()
        assert b.get(ROOT + route).status_code == 404
        assert post(b, route + '/submit', {'text': 'Чужая тестовая работа'}).status_code == 404
        assert post(b, route + '/withdraw').status_code == 404
        assert a.post(ROOT + route + '/submit', json={'text': 'Пробная учебная работа'}).status_code == 403
        result = post(a, route + '/submit', {'text': '  Решение и проверка учебного задания.  ', 'url': 'https://example.test/demo'})
        assert result.status_code == 200, result.text
        sub = result.json()['submission']
        assert sub['status'] == 'submitted' and sub['text'] == 'Решение и проверка учебного задания.'
        withdrawn = post(a, route + '/withdraw')
        assert withdrawn.status_code == 200
        assert withdrawn.json()['submission']['status'] == 'withdrawn'
        assert withdrawn.json()['submission']['version'] == sub['version'] + 1
        assert post(a, route + '/withdraw').status_code == 409
        again = post(a, route + '/submit', {'text': 'Обновлённое решение учебной задачи'})
        assert again.status_code == 200
        assert again.json()['submission']['version'] == sub['version'] + 2
        assert a.get('/api/deadlines').json() == before
        initialize_database()
        assert a.get(ROOT + route).json()['submission']['text'] == 'Обновлённое решение учебной задачи'


@pytest.mark.parametrize('bad_url', ['javascript:alert(1)', 'data:text/html,test', 'http://example.test/work', 'https://user:password@example.test/', 'https://example.test\\@other.test', 'https://example.test:bad/', 'https://example.test/with space'])
def test_assignment_reference_rejects_unsafe_or_malformed_urls(bad_url):
    with TestClient(app) as api:
        signed(api)
        task = api.get(ROOT + 'assignments').json()['items'][0]
        assert post(api, f'assignments/{task["id"]}/submit', {'text': 'Вымышленный текст решения', 'url': bad_url}).status_code == 422


def test_notes_full_lifecycle_and_owner_mass_assignment_validation():
    with TestClient(app) as a, TestClient(app) as b:
        signed(a); signed(b, 'b')
        title = fresh_title()
        body = {'title': title, 'subject': 'Личная тема', 'body': '<img src=x onerror=alert(1)>\nБезопасно храним текст.'}
        created = post(a, 'notes', body)
        assert created.status_code == 201
        note = created.json()
        route = f'notes/{note["id"]}'
        assert note['body'] == body['body']
        assert not any(item['id'] == note['id'] for item in b.get(ROOT + 'notes').json()['items'])
        assert b.get(ROOT + route).status_code == 404
        assert post(b, route, body).status_code == 404
        assert post(b, route + '/delete').status_code == 404
        assert post(a, 'notes', {**body, 'student_id': b.get('/api/me').json()['id']}).status_code == 422
        assert post(a, 'notes', {**body, 'title': '   '}).status_code == 422
        assert post(a, 'notes', {**body, 'body': 'forbidden\x00character'}).status_code == 422
        assert a.post(ROOT + route, json=body).status_code == 403
        updated = post(a, route, {**body, 'body': 'Сохранённый изменённый конспект.'})
        assert updated.status_code == 200
        assert a.get(ROOT + 'notes?q=' + title).json()['items'][0]['body'] == 'Сохранённый изменённый конспект.'
        assert post(a, route + '/delete').status_code == 200
        assert a.get(ROOT + route).status_code == 404


def test_flashcards_review_schedule_validation_and_owner_isolation():
    with TestClient(app) as a, TestClient(app) as b:
        signed(a); signed(b, 'b')
        created = post(a, 'flashcards', {'subject': 'Учебная тема', 'front': fresh_title(), 'back': 'Учебный ответ.'})
        assert created.status_code == 201
        card = created.json()
        route = f'flashcards/{card["id"]}'
        assert card['is_due'] is True
        assert b.get(ROOT + route).status_code == 404
        assert post(b, route + '/review', {'known': True}).status_code == 404
        assert post(b, route + '/delete').status_code == 404
        for value in ('true', 1, None):
            assert post(a, route + '/review', {'known': value}).status_code == 422
        assert a.post(ROOT + route + '/review', json={'known': True}).status_code == 403
        known = post(a, route + '/review', {'known': True}).json()
        assert known['reviews'] == 1 and known['known_count'] == 1
        assert known['due_date'] == (campus_today() + timedelta(days=1)).isoformat()
        again = post(a, route + '/review', {'known': True}).json()
        assert again['interval_days'] == 2
        repeat = post(a, route + '/review', {'known': False}).json()
        assert repeat['interval_days'] == 0 and repeat['is_due'] is True
        assert repeat['reviews'] == 3 and repeat['known_count'] == 2
        assert post(a, route + '/delete').status_code == 200


def test_quiz_hides_key_validates_answers_scores_server_side_and_protects_attempts():
    with TestClient(app) as a, TestClient(app) as b:
        signed(a); signed(b, 'b')
        quiz = a.get(ROOT + 'quizzes').json()['items'][0]
        route = f'quizzes/{quiz["id"]}'
        detail = a.get(ROOT + route).json()
        assert detail['questions']
        assert all(set(q) == {'prompt', 'options'} for q in detail['questions'])
        assert b.get(ROOT + route).status_code == 404
        assert post(b, route + '/attempt', {'answers': [0] * len(detail['questions'])}).status_code == 404
        assert post(a, route + '/attempt', {'answers': [0]}).status_code == 422
        assert post(a, route + '/attempt', {'answers': [False] * len(detail['questions'])}).status_code == 422
        assert post(a, route + '/attempt', {'answers': ['0'] * len(detail['questions'])}).status_code == 422
        assert post(a, route + '/attempt', {'answers': [999] * len(detail['questions'])}).status_code == 422
        assert post(a, route + '/attempt', {'answers': [0] * len(detail['questions']), 'score': 3}).status_code == 422
        assert a.post(ROOT + route + '/attempt', json={'answers': [0] * len(detail['questions'])}).status_code == 403
        # The key is read only by the test from the server database, never the GET API.
        import json
        with SessionLocal() as db:
            questions = json.loads(db.get(Quiz, quiz['id']).questions_json)
        answers = [q['correct'] for q in questions]
        before_grades = a.get('/api/grades').json()
        attempt = post(a, route + '/attempt', {'answers': answers})
        assert attempt.status_code == 201, attempt.text
        attempt = attempt.json()
        assert attempt['score'] == attempt['total'] == len(questions)
        assert attempt['percent'] == 100
        assert len(attempt['results']) == len(questions)
        assert all(result['explanation'] for result in attempt['results'])
        assert b.get(ROOT + f'quiz-attempts/{attempt["id"]}').status_code == 404
        assert not any(row['id'] == attempt['id'] for row in b.get(ROOT + 'quiz-attempts').json()['items'])
        assert a.get(ROOT + f'quiz-attempts/{attempt["id"]}').json()['percent'] == 100
        assert a.get('/api/grades').json() == before_grades


def test_personal_task_lifecycle_does_not_edit_curriculum_deadlines():
    with TestClient(app) as a, TestClient(app) as b:
        signed(a); signed(b, 'b')
        before = a.get('/api/deadlines').json()
        body = {'title': fresh_title(), 'subject': 'Самостоятельная работа', 'due_date': (campus_today()+timedelta(days=3)).isoformat(), 'priority': 'high', 'is_done': False}
        created = post(a, 'tasks', body)
        assert created.status_code == 201
        task = created.json()
        route = f'tasks/{task["id"]}'
        assert b.get(ROOT + route).status_code == 404
        assert post(b, route, body).status_code == 404
        assert post(b, route + '/delete').status_code == 404
        assert post(a, route, {**body, 'is_done': 1}).status_code == 422
        assert post(a, route, {**body, 'due_date': '1900-01-01'}).status_code == 422
        assert post(a, route, {**body, 'priority': 'urgent'}).status_code == 422
        assert a.post(ROOT + route, json=body).status_code == 403
        assert post(a, route, {**body, 'is_done': True}).json()['is_done'] is True
        assert a.get('/api/deadlines').json() == before
        assert post(a, route + '/delete').status_code == 200
        assert a.get(ROOT + route).status_code == 404


def test_focus_logging_is_private_bounded_and_totals_come_from_saved_rows():
    with TestClient(app) as a, TestClient(app) as b:
        signed(a); signed(b, 'b')
        before = a.get(ROOT + 'focus-sessions').json()['summary']
        for minutes in (0, 181, True, '25'):
            assert post(a, 'focus-sessions', {'subject': 'Тестовая тема', 'minutes': minutes}).status_code == 422
        assert a.post(ROOT + 'focus-sessions', json={'subject': 'Тестовая тема', 'minutes': 25}).status_code == 403
        logged = post(a, 'focus-sessions', {'subject': fresh_title(), 'minutes': 25})
        assert logged.status_code == 201
        row = logged.json()
        after = a.get(ROOT + 'focus-sessions').json()['summary']
        assert after['minutes'] == before['minutes'] + 25
        assert after['total'] == before['total'] + 1
        assert not any(item['id'] == row['id'] for item in b.get(ROOT + 'focus-sessions').json()['items'])
        assert post(b, f'focus-sessions/{row["id"]}/delete').status_code == 404
        assert post(a, f'focus-sessions/{row["id"]}/delete').status_code == 200


def test_focus_today_uses_moscow_midnight_in_sqlite_and_postgresql(monkeypatch):
    import app.learning as learning
    fixed_day = date(2030, 2, 15)
    monkeypatch.setattr(learning, 'campus_today', lambda: fixed_day)
    with TestClient(app) as api:
        signed(api)
        student_id = api.get('/api/me').json()['id']
        with SessionLocal() as db:
            inside = FocusSession(student_id=student_id, subject='UTC boundary inside', minutes=17, created_at=datetime(2030, 2, 14, 22, 0, tzinfo=timezone.utc))
            outside = FocusSession(student_id=student_id, subject='UTC boundary outside', minutes=19, created_at=datetime(2030, 2, 14, 20, 59, tzinfo=timezone.utc))
            db.add_all([inside, outside]); db.commit()
            ids = inside.id, outside.id
        try:
            assert api.get(ROOT + 'focus-sessions').json()['summary']['today_minutes'] == 17
        finally:
            for row_id in ids:
                assert post(api, f'focus-sessions/{row_id}/delete').status_code == 200


def test_learning_seed_is_repeatable_and_does_not_recreate_deleted_note():
    with TestClient(app) as api:
        signed(api)
        with SessionLocal() as db:
            student_id = api.get('/api/me').json()['id']
            seed_count = len(db.scalars(select(LearningSeed)).all())
            assert db.get(LearningSeed, student_id)
        before = api.get(ROOT + 'courses').json()
        note = post(api, 'notes', {'title': fresh_title(), 'subject': '', 'body': 'Запись для проверки удаления.'}).json()
        assert post(api, f'notes/{note["id"]}/delete').status_code == 200
        initialize_database(); initialize_database()
        assert api.get(ROOT + f'notes/{note["id"]}').status_code == 404
        assert api.get(ROOT + 'courses').json() == before
        with SessionLocal() as db:
            assert len(db.scalars(select(LearningSeed)).all()) == seed_count
