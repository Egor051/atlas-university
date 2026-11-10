"""Every early public-demo guard keeps security headers and ownership checks."""
import pytest
from fastapi import HTTPException

from test_api import client, sign_in
from app import improvements


def security_headers(response):
    assert response.headers['Cache-Control'] == 'no-store, private'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']


@pytest.mark.parametrize('headers,status', [
    ({}, 403),
    ({'X-Requested-With': 'ATLAS', 'Origin': 'https://untrusted.invalid'}, 403),
    ({'X-Requested-With': 'ATLAS', 'Sec-Fetch-Site': 'same-site'}, 403),
    ({'X-Requested-With': 'ATLAS', 'Sec-Fetch-Site': 'cross-site'}, 403),
    ({'X-Requested-With': 'ATLAS', 'X-ATLAS-User': '2147483647'}, 409),
    ({'X-Requested-With': 'ATLAS', 'X-ATLAS-User': 'malformed'}, 422),
])
def test_early_write_guards_keep_private_security_headers_without_creating_request(headers, status):
    with client() as api:
        sign_in(api, 'alina.demo', 'AtlasDemo!2026-A')
        before = api.get('/api/requests?paginated=true').json()['total']
        response = api.post('/api/requests', json={'type': 'study'}, headers=headers)
        assert response.status_code == status
        security_headers(response)
        assert api.get('/api/requests?paginated=true').json()['total'] == before


def test_quota_rejection_keeps_security_headers_and_retry_without_domain_write(monkeypatch):
    with client() as api:
        sign_in(api, 'alina.demo', 'AtlasDemo!2026-A')
        before = api.get('/api/requests?paginated=true').json()['total']

        def exhausted(*args, **kwargs):
            raise HTTPException(429, 'Fictional quota exhausted', headers={'Retry-After': '60'})

        monkeypatch.setattr(improvements, 'charge_token', exhausted)
        response = api.post('/api/requests', json={'type': 'study'}, headers={'X-Requested-With': 'ATLAS'})
        assert response.status_code == 429
        assert response.headers['Retry-After'] == '60'
        security_headers(response)
        assert api.get('/api/requests?paginated=true').json()['total'] == before


def test_outer_security_headers_preserve_student_idor_and_role_denial():
    with client() as alina, client() as mark:
        sign_in(alina, 'alina.demo', 'AtlasDemo!2026-A')
        sign_in(mark, 'mark.demo', 'AtlasDemo!2026-M')
        own = alina.get('/api/requests?paginated=true&limit=1').json()['items'][0]
        for path, status in [(f'/api/requests/{own["id"]}', 404),
                             (f'/api/requests/{own["id"]}/document', 404),
                             ('/api/staff/requests', 403)]:
            response = mark.get(path)
            assert response.status_code == status
            security_headers(response)
