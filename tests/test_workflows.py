"""Database migration and complete workflow regression on fictional fixtures."""
from __future__ import annotations

import json
import atexit
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from fastapi.testclient import TestClient
_test_directory = tempfile.TemporaryDirectory(prefix='atlas-workflows-')
if 'app.db' not in sys.modules:
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_directory.name) / 'workflows.db')
from app.main import app
from app.db import SessionLocal, Lesson, LessonChange, DATABASE_URL, engine
atexit.register(engine.dispose)

HEADERS = {'X-Requested-With': 'ATLAS'}
ROOT = Path(__file__).resolve().parents[1]


def client():
    return TestClient(app)


def sign_in(api, login, password):
    result = api.post('/api/login', json={'login': login, 'password': password}, headers=HEADERS)
    assert result.status_code == 200, result.text
    return result


def run_python(code, database_url):
    env = {**os.environ, 'DATABASE_URL': database_url, 'APP_ENV': 'development', 'DEMO_MODE': 'true', 'COOKIE_SECURE': 'false', 'PUBLIC_ORIGIN': '', 'ALLOWED_HOSTS': 'localhost,127.0.0.1,testserver'}
    return subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)


def test_additive_legacy_migration_preserves_records_and_is_repeatable():
    with tempfile.TemporaryDirectory(prefix='atlas-migration-') as directory:
        db_path = Path(directory) / 'legacy.db'
        with closing(sqlite3.connect(db_path)) as database:
            database.executescript('''
                CREATE TABLE document_requests (id INTEGER PRIMARY KEY,student_id INTEGER NOT NULL,type VARCHAR(100) NOT NULL,comment TEXT NOT NULL,status VARCHAR(30) NOT NULL,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL);
                INSERT INTO document_requests VALUES(101,1,'Legacy fictional request','Preserve me','ready','2026-11-01 10:00:00','2026-11-02 10:00:00');
                CREATE TABLE notifications (id INTEGER PRIMARY KEY,student_id INTEGER NOT NULL,title VARCHAR(180) NOT NULL,body TEXT NOT NULL,category VARCHAR(30) NOT NULL,created_at DATETIME NOT NULL,is_read BOOLEAN NOT NULL);
                INSERT INTO notifications VALUES(201,1,'Legacy fictional notice','Preserve notice','request','2026-11-01 10:00:00',0);
            ''')
        url = 'sqlite:///' + str(db_path)
        for _ in range(2):
            result = run_python('from app.db import migrate_database, engine; migrate_database(); engine.dispose()', url)
            assert result.returncode == 0, result.stderr
        with closing(sqlite3.connect(db_path)) as database:
            record = database.execute('SELECT id,comment,status,version,staff_message,due_at FROM document_requests').fetchone()
            assert record[:4] == (101, 'Preserve me', 'ready', 1)
            assert record[4] and record[5]
            assert database.execute('SELECT COUNT(*) FROM request_events WHERE request_id=101').fetchone()[0] == 1
            assert database.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall() == [
                ('0002_workflow',), ('0003_listing_indexes',), ('0004_full_campus',), ('0005_contest_hardening',),
                ('0006_audit_integrity',), ('0007_university_library_direct',), ('0008_academic_workspace',),
                ('0009_student_units',),
            ]
            assert database.execute('SELECT body,target FROM notifications WHERE id=201').fetchone() == ('Preserve notice', '/app/requests')


def test_request_history_and_deadline_survive_new_process():
    with client() as student, client() as staff:
        sign_in(student, 'alina.demo', 'AtlasDemo!2026-A')
        sign_in(staff, 'dean.demo', 'AtlasStaff!2026-D')
        row = student.post('/api/requests', json={'type': 'study', 'comment': 'Persistence regression'}, headers=HEADERS).json()
        for status in ('review', 'processing', 'ready'):
            detail = staff.get(f'/api/staff/requests/{row["id"]}').json()
            result = staff.post(f'/api/staff/requests/{row["id"]}/status', json={'status': status, 'expected_version': detail['version'], 'message': 'Демонстрационный документ подготовлен.'}, headers=HEADERS)
            assert result.status_code == 200, result.text
        deadline = student.get('/api/deadlines').json()[0]
        assert student.post(f'/api/deadlines/{deadline["id"]}/toggle', json={'is_done': True}, headers=HEADERS).status_code == 200
    code = f'''import json
from app.db import SessionLocal, DocumentRequest, Deadline, RequestEvent, engine
from sqlalchemy import select,func
with SessionLocal() as db:
    row=db.get(DocumentRequest,{row['id']})
    result={{'status':row.status,'version':row.version,'message':row.staff_message,'history':db.scalar(select(func.count()).select_from(RequestEvent).where(RequestEvent.request_id==row.id)),'done':db.get(Deadline,{deadline['id']}).is_done}}
    print(json.dumps(result))
engine.dispose()
'''
    result = run_python(code, DATABASE_URL)
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record['status'] == 'ready' and record['version'] == 4 and record['history'] == 4 and record['done'] is True
    assert record['message']


def test_staff_simultaneous_updates_have_one_winner():
    with client() as student, client() as staff_a, client() as staff_b:
        sign_in(student, 'mark.demo', 'AtlasDemo!2026-M')
        for staff in (staff_a, staff_b):
            sign_in(staff, 'dean.demo', 'AtlasStaff!2026-D')
        row = student.post('/api/requests', json={'type': 'scholarship', 'comment': 'Race regression'}, headers=HEADERS).json()
        def update_record(staff):
            return staff.post(f'/api/staff/requests/{row["id"]}/status', json={'status': 'review', 'expected_version': 1, 'message': 'Принято на рассмотрение.'}, headers=HEADERS).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(update_record, (staff_a, staff_b)))
        assert sorted(responses) == [200, 409]
        detail = student.get(f'/api/requests/{row["id"]}').json()
        assert detail['version'] == 2 and len(detail['history']) == 2


def test_simultaneous_idempotent_sends_create_one_request():
    with client() as student_a, client() as student_b:
        for student in (student_a, student_b):
            sign_in(student, 'alina.demo', 'AtlasDemo!2026-A')
        headers = {**HEADERS, 'Idempotency-Key': str(uuid.uuid4())}
        def send_record(student):
            return student.post('/api/requests', json={'type': 'study', 'comment': 'Concurrent idempotent submission'}, headers=headers)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send_record, (student_a, student_b)))
        assert sorted(response.status_code for response in responses) == [200, 201]
        assert responses[0].json()['id'] == responses[1].json()['id']
        request_id = responses[0].json()['id']
        detail = student_a.get(f'/api/requests/{request_id}').json()
        assert len(detail['history']) == 1
        assert sum(notice['request_id'] == request_id for notice in student_a.get('/api/notifications').json()) == 1


def test_control_characters_are_validation_errors_not_database_failures():
    with client() as student:
        sign_in(student, 'mark.demo', 'AtlasDemo!2026-M')
        for value in ('nul\x00character', 'surrogate\ud800character'):
            result = student.post('/api/requests', content=json.dumps({'type': 'study', 'comment': value}), headers={**HEADERS, 'Content-Type': 'application/json'})
            assert result.status_code == 422


def test_schedule_export_uses_same_isolated_lessons_and_valid_utf8_folding():
    with client() as student:
        sign_in(student, 'alina.demo', 'AtlasDemo!2026-A')
        data = student.get('/api/schedule').json()
        result = student.get('/api/schedule/export?week=' + data['week_start'])
        assert result.status_code == 200
        assert result.text.count('BEGIN:VEVENT') == sum(len(day['items']) for day in data['days'])
        assert 'DTSTART;TZID=Europe/Moscow:' in result.text
        assert 'Инженерия ПО' not in result.text
        assert result.content.endswith(b'END:VCALENDAR\r\n')
        assert all(len(line) <= 75 for line in result.content.split(b'\r\n'))
        assert all(line.decode('utf-8') is not None for line in result.content.split(b'\r\n'))


def test_moved_lesson_keeps_its_original_duration():
    with client() as student:
        sign_in(student, 'alina.demo', 'AtlasDemo!2026-A')
        with SessionLocal() as db:
            change = db.scalar(select(LessonChange).where(LessonChange.new_start.is_not(None)).order_by(LessonChange.id))
            original = db.get(Lesson, change.lesson_id)
            result = student.get('/api/schedule?week=' + str(change.day)).json()
            moved = next(lesson for day in result['days'] for lesson in day['items'] if lesson['id'] == original.id and lesson['date'] == str(change.day))
            old_duration = datetime.strptime(original.end_time, '%H:%M') - datetime.strptime(original.start_time, '%H:%M')
            new_duration = datetime.strptime(moved['end'], '%H:%M') - datetime.strptime(moved['start'], '%H:%M')
            assert old_duration == new_duration == timedelta(minutes=90)


def test_ready_transcript_contains_owner_grades_and_concept_label():
    with client() as student, client() as staff:
        sign_in(student, 'mark.demo', 'AtlasDemo!2026-M')
        sign_in(staff, 'dean.demo', 'AtlasStaff!2026-D')
        row = student.post('/api/requests', json={'type': 'transcript'}, headers=HEADERS).json()
        for status in ('review', 'ready'):
            current = staff.get(f'/api/staff/requests/{row["id"]}').json()
            response = staff.post(f'/api/staff/requests/{row["id"]}/status', json={'status': status, 'expected_version': current['version'], 'message': 'Выписка подготовлена для демонстрации.'}, headers=HEADERS)
            assert response.status_code == 200
        document = student.get(f'/api/requests/{row["id"]}/document')
        assert document.status_code == 200
        assert 'Инженерия ПО' in document.text and 'Теория вероятностей' not in document.text
        assert 'КОНКУРСНЫЙ ОБРАЗЕЦ' in document.text
        assert 'attachment' in document.headers['content-disposition']


def test_configuration_and_database_readiness():
    with client() as api:
        config = api.get('/api/config').json()
        assert config['concept'] is True and config['timezone'] == 'Europe/Moscow'
        assert api.get('/api/ready').json()['database'] == 'ready'
