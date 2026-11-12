"""Exact search destinations and owner-only notification lookup.

The imported API fixture sets an isolated temporary database before app import.
"""
import pytest

from test_api import client, sign_in

ACCOUNTS = [('alina.demo', 'AtlasDemo!2026-A'), ('mark.demo', 'AtlasDemo!2026-M')]


@pytest.mark.parametrize('account', ACCOUNTS)
def test_search_grade_and_deadline_ids_belong_to_the_returned_destination(account):
    with client() as api:
        sign_in(api, *account)
        for listing, category, target, field in [('grades', 'Дисциплина', 'grades', 'subject'),
                                                  ('deadlines', 'Задание', 'plan', 'title')]:
            response = api.get('/api/' + listing).json()
            records = response['items'] if isinstance(response, dict) else response
            assert records
            selected = records[0]
            result = api.get('/api/campus/search', params={'q': selected[field]}).json()['items']
            matches = [row for row in result if row['category'] == category]
            assert any(row['id'] == selected['id'] for row in matches)
            own_ids = {row['id'] for row in records}
            assert all(row['target'] == target and row['id'] in own_ids for row in matches)


def test_notification_detail_requires_authentication_and_owner():
    with client() as anonymous, client() as staff:
        for path in ['/api/notifications/1', '/api/notifications/2147483647']:
            response = anonymous.get(path)
            assert response.status_code == 401
            assert 'no-store' in response.headers.get('cache-control', '')
        sign_in(staff, 'dean.demo', 'AtlasStaff!2026-D')
        for path in ['/api/notifications/1', '/api/notifications/2147483647']:
            assert staff.get(path).status_code == 404


def test_notification_detail_idor_query_injection_and_read_side_effects():
    with client() as a, client() as b:
        sign_in(a, *ACCOUNTS[0])
        sign_in(b, *ACCOUNTS[1])
        own = a.get('/api/notifications').json()[0]
        foreign = b.get('/api/notifications').json()[0]
        assert own['id'] != foreign['id']
        response = a.get(f"/api/notifications/{own['id']}")
        assert response.status_code == 200
        assert response.json() == own
        assert set(response.json()) == {'id', 'title', 'body', 'category', 'created_at',
                                       'is_read', 'target', 'request_id'}
        assert 'no-store' in response.headers.get('cache-control', '')
        other_id = b.get('/api/me').json()['id']
        assert a.get(f"/api/notifications/{own['id']}", params={'student_id': other_id}).json() == own
        absent = a.get('/api/notifications/2147483647')
        blocked = a.get(f"/api/notifications/{foreign['id']}", params={'student_id': other_id})
        assert blocked.status_code == absent.status_code == 404
        assert blocked.json() == absent.json()
        assert b.get(f"/api/notifications/{own['id']}").status_code == 404
        # GET preserves unread state for both the own and foreign notification.
        assert next(row for row in a.get('/api/notifications').json() if row['id'] == own['id']) == own
        assert b.get(f"/api/notifications/{foreign['id']}").json() == foreign
