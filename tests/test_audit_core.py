"""Audit regressions for session identity, UTC expiry, readiness and replay.

The shared API fixture selects a temporary fictional database before app import.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from test_api import client, sign_in
from app import main
from app.session_security import as_utc, validate_expected_actor, PasswordAdmission

HEAD = {'X-Requested-With': 'ATLAS'}


def student(api):
    sign_in(api, 'alina.demo', 'AtlasDemo!2026-A')


@pytest.mark.parametrize('offset,hour,expired', [(3, 10, True), (-3, 6, False), (0, 7, True)])
def test_b11_expiry_compares_instants_not_wall_clock(monkeypatch, offset, hour, expired):
    now = datetime(2030, 1, 2, 8, tzinfo=timezone.utc)
    user = SimpleNamespace(id=11, login='fictional-private')
    row = SimpleNamespace(expires_at=datetime(2030, 1, 2, hour, tzinfo=timezone(timedelta(hours=offset))),
                          user=user, user_id=user.id)
    request = Request({'type': 'http', 'headers': [(b'cookie', b'atlas_session=fictional-test-token')]})
    monkeypatch.setattr(main, 'utc_now', lambda: now)
    db = SimpleNamespace(scalar=lambda *_: row)
    if expired:
        with pytest.raises(HTTPException) as caught:
            main.require_user(request, db)
        assert caught.value.status_code == 401
    else:
        assert main.require_user(request, db) is user
    assert as_utc(datetime(2030, 1, 2, 7)) == datetime(2030, 1, 2, 7, tzinfo=timezone.utc)


def test_b29_actor_header_blocks_cross_account_reads_writes_and_logout():
    with client() as api:
        student(api)
        uid = api.get('/api/me').json()['id']
        wrong = {**HEAD, 'X-ATLAS-User': str(uid + 100)}
        before = api.get('/api/requests', params={'paginated': True}).json()['total']
        for method, path, body in [('GET', '/api/grades', None),
                                   ('POST', '/api/requests', {'type': 'study'}),
                                   ('POST', '/api/logout', None)]:
            response = api.request(method, path, headers=wrong, json=body)
            assert response.status_code == 409, response.text
            assert response.json()['detail']['code'] == 'account_changed'
        assert api.get('/api/me').json()['id'] == uid
        assert api.get('/api/requests', params={'paginated': True}).json()['total'] == before
        assert api.get('/api/grades', headers={'X-ATLAS-User': str(uid)}).status_code == 200
        # Existing clients remain compatible without the optional affinity header.
        assert api.get('/api/grades').status_code == 200


@pytest.mark.parametrize('value', ['', '0', '-1', '1.0', 'true', '1\n', '9' * 20])
def test_b29_malformed_actor_context_is_rejected(value):
    with pytest.raises(HTTPException) as caught:
        validate_expected_actor(value, 1)
    assert caught.value.status_code == 422


def test_b23_ready_catches_connection_creation_failure(monkeypatch):
    with client() as api:
        def unavailable():
            raise SQLAlchemyError('Fictional connection failure')
        monkeypatch.setattr(main, 'SessionLocal', unavailable)
        response = api.get('/api/ready')
        assert response.status_code == 503
        assert response.json() == {'ok': False, 'service': 'ATLAS Campus'}
        assert api.get('/api/health').status_code == 200


def test_b11_datetime_payload_is_canonical_utc():
    instant = datetime(2030, 1, 2, 10, 30, tzinfo=timezone(timedelta(hours=3)))
    assert main.date_iso(instant) == '2030-01-02T07:30:00+00:00'
    assert main.date_iso(instant.replace(tzinfo=None)) == '2030-01-02T10:30:00+00:00'
    assert main.date_iso(instant.date()) == '2030-01-02'


def test_b16_retake_replay_survives_moscow_midnight(monkeypatch):
    today = date(2030, 2, 15)
    monkeypatch.setattr(main, 'campus_today', lambda: today)
    with client() as api:
        student(api)
        subject = api.get('/api/grades').json()['items'][0]['subject']
        body = {'type': 'retake', 'comment': 'Fictional retake date for audit regression',
                'details': {'subject': subject, 'preferred_date': today.isoformat()}}
        headers = {**HEAD, 'Idempotency-Key': uuid.uuid4().hex}
        first = api.post('/api/requests', headers=headers, json=body)
        assert first.status_code == 201, first.text
        today += timedelta(days=1)
        retry = api.post('/api/requests', headers=headers, json=body)
        assert retry.status_code == 200, retry.text
        assert retry.json() == first.json()
        assert api.post('/api/requests', headers=HEAD, json=body).status_code == 422


def test_p01_pg_admission_has_bounded_shared_slots_and_overload_retry():
    # Real PostgreSQL/two-process verification is performed by the isolated
    # deployment check; this verifies denial and lock namespace deterministically.
    class Busy:
        def __init__(self): self.calls = []
        def scalar(self, statement, params):
            self.calls.append((str(statement), params.copy()))
            return False
    db = Busy()
    with pytest.raises(HTTPException) as caught:
        with PasswordAdmission(db, 'postgresql'):
            pytest.fail('A full admission set must never enter the KDF')
    assert caught.value.status_code == 429
    assert caught.value.headers['Retry-After'] == '1'
    assert len(db.calls) == 2
    assert {params['slot'] for _, params in db.calls} == {0, 1}


def test_p01_local_admission_releases_after_verifier_exception():
    with pytest.raises(ValueError):
        with PasswordAdmission(None, 'sqlite'):
            raise ValueError('Fictional verifier failure')
    with PasswordAdmission(None, 'sqlite'), PasswordAdmission(None, 'sqlite'):
        with pytest.raises(HTTPException) as caught:
            with PasswordAdmission(None, 'sqlite'):
                pytest.fail('Bounded admission exceeded')
        assert caught.value.status_code == 429
