"""Regression for archives larger than the page size and truthful queue totals."""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

_test_directory = tempfile.TemporaryDirectory(prefix='atlas-pagination-')
if 'app.db' not in sys.modules:
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_directory.name) / 'pagination.db')

from app.main import app
from app.db import SessionLocal, User, DocumentRequest, Notification, RequestEvent, engine, password_hasher, utc_now, campus_today
atexit.register(engine.dispose)

HEADERS = {'X-Requested-With': 'ATLAS'}
TEST_LOGIN = 'pagination.demo'
TEST_PASSWORD = 'FictionalPaginationPassword!2026'


def login(api, login_name, password):
    result = api.post('/api/login', headers=HEADERS, json={'login': login_name, 'password': password})
    assert result.status_code == 200, result.text


@pytest.fixture(scope='module')
def large_archive():
    with TestClient(app):
        with SessionLocal() as db:
            user = User(login=TEST_LOGIN, password_hash=password_hasher.hash(TEST_PASSWORD), full_name='Тест Пагинации', initials='ТП', faculty='Вымышленный институт', program='Тестовая программа', course=1, group_name='ПГ-00-00', student_number='PAGINATION-FAKE-001', role='student', accent='blue')
            db.add(user)
            db.flush()
            now = utc_now()
            old = DocumentRequest(student_id=user.id, type='Справка об обучении', comment='PaginationMarker старый активный запрос literal%_match', status='submitted', created_at=now-timedelta(days=30), updated_at=now-timedelta(days=30), due_at=campus_today()-timedelta(days=20), staff_message='', version=1)
            db.add(old)
            for index in range(210):
                db.add(DocumentRequest(student_id=user.id, type='Справка об обучении', comment=f'PaginationMarker archive {index}', status='ready' if index % 2 else 'rejected', created_at=now-timedelta(minutes=index), updated_at=now-timedelta(minutes=index), due_at=campus_today(), staff_message='Вымышленный архивный ответ.', version=1))
            for index in range(212):
                db.add(Notification(student_id=user.id, title=f'Pagination notice {index}', body='PaginationMarker фиктивное уведомление', category='request', created_at=now-timedelta(minutes=index), is_read=index >= 210, target='/app/requests'))
            db.commit()
            return {'user_id': user.id, 'old_id': old.id}


def test_student_archive_has_complete_pagination_and_accurate_counts(large_archive):
    with TestClient(app) as api:
        login(api, TEST_LOGIN, TEST_PASSWORD)
        first = api.get('/api/requests?paginated=true&limit=30').json()
        assert first['total'] == 211 and len(first['items']) == 30 and first['has_more'] is True
        assert first['counts'] == {'all': 211, 'active': 1, 'submitted': 1, 'review': 0, 'processing': 0, 'needs_info': 0, 'ready': 105, 'rejected': 105, 'overdue': 1}
        ids = []
        for offset in range(0, 211, 30):
            page = api.get(f'/api/requests?paginated=true&limit=30&offset={offset}').json()
            ids.extend(record['id'] for record in page['items'])
        assert len(ids) == len(set(ids)) == 211
        assert ids[-1] == large_archive['old_id']
        assert page['has_more'] is False
        active = api.get('/api/requests?paginated=true&filter=active&limit=30').json()
        assert active['total'] == 1 and active['items'][0]['id'] == large_archive['old_id']
        overdue = api.get('/api/requests?paginated=true&filter=overdue').json()
        assert overdue['total'] == 1 and overdue['items'][0]['id'] == large_archive['old_id']
        empty_page = api.get('/api/requests?paginated=true&offset=1000').json()
        assert empty_page['items'] == [] and empty_page['total'] == 211 and empty_page['has_more'] is False


def test_staff_filter_finds_old_active_after_210_closed(large_archive):
    with TestClient(app) as api:
        login(api, 'dean.demo', 'AtlasStaff!2026-D')
        page = api.get('/api/staff/requests', params={'paginated': 'true', 'filter': 'active', 'q': 'PaginationMarker', 'limit': 30}).json()
        assert page['total'] == 1 and page['items'][0]['id'] == large_archive['old_id']
        assert page['counts']['active'] >= 1
        # Cyrillic case-insensitive search must work locally as it does on PG.
        by_student = api.get('/api/staff/requests', params={'paginated': 'true', 'q': 'тест пагинации', 'limit': 30}).json()
        assert by_student['total'] == 211
        by_number = api.get('/api/staff/requests', params={'paginated': 'true', 'q': f'№{large_archive["old_id"]}'}).json()
        assert by_number['total'] == 1
        by_literal = api.get('/api/staff/requests', params={'paginated': 'true', 'q': 'literal%_match'}).json()
        assert by_literal['total'] == 1


def test_notifications_truthful_unread_count_exceeds_first_page(large_archive):
    with TestClient(app) as api:
        login(api, TEST_LOGIN, TEST_PASSWORD)
        result = api.get('/api/notifications?paginated=true&limit=30&filter=unread')
        page = result.json()
        assert page['total'] == page['unread_count'] == page['counts']['unread'] == 210
        assert page['counts']['all'] == 212 and len(page['items']) == 30
        assert result.headers['x-unread-count'] == '210'
        assert result.headers['x-total-count'] == '210'
        assert page['has_more'] is True
        archive = api.get('/api/notifications?paginated=true&offset=210').json()
        assert len(archive['items']) == 2 and archive['has_more'] is False
        # Compatibility mode stays an array but exposes the exact full total.
        legacy = api.get('/api/notifications')
        assert isinstance(legacy.json(), list) and len(legacy.json()) == 200
        assert legacy.headers['x-unread-count'] == '210' and legacy.headers['x-total-count'] == '212'


def test_paginated_student_search_cannot_find_another_students_archive(large_archive):
    with TestClient(app) as api:
        login(api, 'mark.demo', 'AtlasDemo!2026-M')
        for path in ('requests', 'notifications'):
            page = api.get(f'/api/{path}', params={'paginated': 'true', 'q': 'PaginationMarker'}).json()
            assert page['total'] == 0 and page['items'] == []
            assert page['counts']['all'] < 200
        assert api.get('/api/staff/requests?paginated=true&filter=active').status_code == 403


def test_list_reads_are_idempotent_and_query_values_are_bounded(large_archive):
    with TestClient(app) as api:
        login(api, TEST_LOGIN, TEST_PASSWORD)
        with SessionLocal() as db:
            initial = (db.scalar(select(func.count()).select_from(DocumentRequest)), db.scalar(select(func.count()).select_from(RequestEvent)), db.scalar(select(func.count()).select_from(Notification).where(Notification.is_read.is_(True))))
        for path in ('requests', 'notifications'):
            url = f'/api/{path}?paginated=true&limit=30&offset=30'
            assert api.get(url).json() == api.get(url).json()
            for suffix in ('limit=0', 'limit=201', 'offset=-1', 'filter=unknown', 'q=' + 'x' * 101, 'q=%00bad'):
                assert api.get(f'/api/{path}?{suffix}').status_code == 422
        with SessionLocal() as db:
            final = (db.scalar(select(func.count()).select_from(DocumentRequest)), db.scalar(select(func.count()).select_from(RequestEvent)), db.scalar(select(func.count()).select_from(Notification).where(Notification.is_read.is_(True))))
        assert initial == final


@pytest.mark.parametrize('value', ['', 'yes', 'enabled', 'truthy', '2'])
def test_demo_mode_rejects_ambiguous_values(value, monkeypatch):
    from app.config import load_settings
    monkeypatch.setenv('DEMO_MODE', value)
    with pytest.raises(RuntimeError):
        load_settings()


def test_production_demo_is_disabled_without_explicit_enable(monkeypatch):
    from app.config import load_settings
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('DEMO_MODE', raising=False)
    assert load_settings().demo_mode is False
    monkeypatch.setenv('DEMO_MODE', 'true')
    assert load_settings().demo_mode is True
