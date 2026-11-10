"""Migration entry point and the expanded document-service workflows."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from test_api import client, sign_in
from app.db import DOC_TYPES

HEADERS = {'X-Requested-With': 'ATLAS'}
ROOT = Path(__file__).resolve().parents[1]


def test_cli_migrate_and_seed_share_extension_metadata_without_losing_rows():
    with tempfile.TemporaryDirectory(prefix='atlas-cli-regression-') as directory:
        target = Path(directory) / 'cli.db'
        env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + target.as_posix(),
               'APP_ENV': 'test', 'DEMO_MODE': 'true', 'COOKIE_SECURE': 'false',
               'PUBLIC_ORIGIN': '', 'ALLOWED_HOSTS': '127.0.0.1,localhost,testserver'}
        for command in ('migrate', 'seed', 'seed', 'migrate'):
            result = subprocess.run([sys.executable, '-m', 'app.db', command], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
        connection = sqlite3.connect(target)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {'learning_courses', 'consultation_slots', 'portfolio_items', 'support_tickets'} <= tables
            assert connection.execute('SELECT count(*) FROM users').fetchone()[0] == 3
            assert connection.execute('SELECT count(*) FROM learning_courses').fetchone()[0] == 10
            assert connection.execute('SELECT count(*) FROM schema_migrations WHERE version=?', ('0004_full_campus',)).fetchone()[0] == 1
        finally:
            connection.close()


def test_every_catalog_service_validates_comment_and_is_owned():
    with client() as student, client() as other:
        sign_in(student, 'alina.demo', 'AtlasDemo!2026-A')
        sign_in(other, 'mark.demo', 'AtlasDemo!2026-M')
        catalog = student.get('/api/requests/types').json()
        assert len(catalog) == len(DOC_TYPES) == 22
        for service in catalog:
            if service.get('requires_comment') or service['id'] == 'statement':
                response = student.post('/api/requests', json={'type': service['id'], 'comment': 'short'}, headers=HEADERS)
                assert response.status_code == 422, service
            response = student.post('/api/requests', json={'type': service['id'], 'comment': 'Вымышленное обращение для конкурсного сценария.'}, headers=HEADERS)
            assert response.status_code == 201, response.text
            row = response.json()
            assert row['type'] == service['name'] and row['status'] == 'submitted'
            assert other.get('/api/requests/' + str(row['id'])).status_code == 404
            assert other.get('/api/requests/' + str(row['id']) + '/document').status_code == 404


def test_additional_application_reaches_staff_answer_and_owner_document():
    with client() as student, client() as staff:
        sign_in(student, 'mark.demo', 'AtlasDemo!2026-M')
        sign_in(staff, 'dean.demo', 'AtlasStaff!2026-D')
        response = student.post('/api/requests', json={'type': 'individual_plan', 'comment': 'Прошу согласовать вымышленный индивидуальный план.'}, headers=HEADERS)
        row = response.json()
        assert student.get(f'/api/requests/{row["id"]}/document').status_code == 409
        for status in ('review', 'ready'):
            detail = staff.get(f'/api/staff/requests/{row["id"]}').json()
            saved = staff.post(f'/api/staff/requests/{row["id"]}/status', json={'status': status,
                               'expected_version': detail['version'], 'message': 'Демонстрационный план рассмотрен, ответ подготовлен.'}, headers=HEADERS)
            assert saved.status_code == 200
        result = student.get(f'/api/requests/{row["id"]}/document')
        assert result.status_code == 200
        assert 'Индивидуальный учебный план' in result.text
        assert 'КОНКУРСНЫЙ ОБРАЗЕЦ' in result.text
        assert 'Марк Северин' in result.text and 'Алина Ветрова' not in result.text
        assert staff.get(f'/api/requests/{row["id"]}/document').status_code == 403
