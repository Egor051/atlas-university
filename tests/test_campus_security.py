"""Independent adversarial checks of the expanded fictional campus.

This module uses only an isolated test database, including when run alone.
The route inventory checks complement resource-level IDOR tests in the
learning and services suites; they are not a claim about a public deployment.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

_temporary = tempfile.TemporaryDirectory(prefix='atlas-campus-security-')
if 'app.db' not in sys.modules:
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_temporary.name) / 'campus-security.db')
os.environ.setdefault('DEMO_MODE', 'true')

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal, engine, utc_now

HEADERS = {'X-Requested-With': 'ATLAS'}
A = ('alina.demo', 'AtlasDemo!2026-A')
B = ('mark.demo', 'AtlasDemo!2026-M')
STAFF = ('dean.demo', 'AtlasStaff!2026-D')
_ips = itertools.count(1)
PREFIXES = ('/api/learning/', '/api/services/', '/api/campus/', '/api/account/')


@pytest.fixture(scope='module', autouse=True)
def release_handles():
    yield
    engine.dispose()


def client():
    return TestClient(app, client=(f'198.51.100.{next(_ips)}', 50000))


def login(api, account=A):
    result = api.post('/api/login', headers=HEADERS, json={'login': account[0], 'password': account[1]})
    assert result.status_code == 200, result.text


def concrete(path):
    return re.sub(r'\{[^}]+\}', '2147483647', path)


def test_all_extension_routes_require_sessions_and_all_mutations_check_source():
    routes = [route for route in app.routes if route.path.startswith(PREFIXES)]
    assert any(route.path == '/api/campus/portfolio' for route in routes)
    assert any(route.path == '/api/learning/courses' for route in routes)
    assert any(route.path == '/api/services/consultations' for route in routes)
    with client() as anonymous, client() as student, client() as staff:
        login(student)
        login(staff, STAFF)
        for route in routes:
            path = concrete(route.path)
            for method in route.methods & {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
                response = anonymous.request(method, path, headers=HEADERS,
                                             **({'json': {}} if method != 'GET' else {}))
                assert response.status_code == 401, (method, path, response.text)
                assert 'no-store' in response.headers.get('cache-control', ''), path
                if method != 'GET':
                    rejected = student.request(method, path, json={})
                    assert rejected.status_code == 403, (method, path, rejected.text)
                    rejected = student.request(method, path, json={}, headers={**HEADERS, 'Origin': 'https://evil.invalid'})
                    assert rejected.status_code == 403, (method, path, rejected.text)
            if route.path.startswith(('/api/learning/', '/api/services/', '/api/campus/')) and 'GET' in route.methods:
                assert staff.get(path).status_code == (200 if path == '/api/services/preferences' else 403), path
        for route in app.routes:
            if not route.path.startswith('/api/staff/'):
                continue
            path = concrete(route.path)
            if 'GET' in route.methods:
                assert student.get(path).status_code == 403, path
            if 'POST' in route.methods:
                assert student.post(path, json={}, headers=HEADERS).status_code == 403, path
                assert staff.post(path, json={}).status_code == 403, path


def test_portfolio_owner_export_search_and_overposting():
    marker = 'PrivatePortfolio' + uuid.uuid4().hex
    body = {'title': marker + ' <script>alert(1)</script>', 'kind': 'project',
            'description': 'Private description <img src=x onerror=alert(2)>',
            'url': 'https://example.invalid/?q="quoted"', 'day': '2026-11-07'}
    with client() as a, client() as b:
        login(a, A)
        login(b, B)
        foreign_user_id = b.get('/api/me').json()['id']
        assert a.post('/api/campus/portfolio', json={**body, 'student_id': foreign_user_id}, headers=HEADERS).status_code == 422
        result = a.post('/api/campus/portfolio', json=body, headers=HEADERS)
        assert result.status_code == 201, result.text
        row = result.json()
        own = a.get('/api/campus/portfolio').json()['items']
        assert any(item['id'] == row['id'] and marker in item['title'] for item in own)
        assert all(item['id'] != row['id'] for item in b.get('/api/campus/portfolio').json()['items'])
        # The browser cannot select another student by query parameter.
        assert a.get(f'/api/campus/portfolio?student_id={foreign_user_id}').json()['items'] == own
        for suffix, payload in [('', body), ('/delete', {})]:
            foreign = b.post(f"/api/campus/portfolio/{row['id']}{suffix}", json=payload, headers=HEADERS)
            absent = b.post(f'/api/campus/portfolio/2147483647{suffix}', json=payload, headers=HEADERS)
            assert foreign.status_code == absent.status_code == 404
            assert foreign.json() == absent.json()
        assert a.get('/api/campus/search', params={'q': marker}).json()['items']
        assert b.get('/api/campus/search', params={'q': marker, 'student_id': a.get('/api/me').json()['id']}).json()['items'] == []
        exported = a.get('/api/campus/portfolio/export')
        assert exported.status_code == 200
        assert marker in exported.text
        assert '<script>' not in exported.text and '<img src=x' not in exported.text
        assert '&lt;script&gt;' in exported.text and '&lt;img' in exported.text
        assert 'sandbox' in exported.headers['content-security-policy']
        assert 'attachment' in exported.headers['content-disposition']
        assert marker not in b.get('/api/campus/portfolio/export').text
        assert a.post(f"/api/campus/portfolio/{row['id']}/delete", headers=HEADERS).status_code == 200


def test_portfolio_links_reject_executable_schemes_credentials_and_control_bytes():
    with client() as api:
        login(api)
        body = {'title': 'URL validation example', 'kind': 'project', 'description': 'Fictional security exercise.', 'day': '2026-11-07'}
        for unsafe in ('javascript:alert(1)', 'data:text/html,hi', 'https://user:secret@example.invalid',
                       'https://example.invalid/space here', 'https://example.invalid/\x00'):
            result = api.post('/api/campus/portfolio', json={**body, 'url': unsafe}, headers=HEADERS)
            assert result.status_code == 422, (unsafe, result.text)


def test_session_inventory_and_revoke_others_do_not_cross_accounts():
    with client() as primary, client() as older, client() as other:
        login(primary, A)
        login(older, A)
        login(other, B)
        inventory = primary.get('/api/account/sessions').json()['items']
        assert sum(row['is_current'] for row in inventory) == 1
        assert len(inventory) >= 2
        assert all(set(row) == {'id', 'is_current', 'expires_at'} for row in inventory)
        token = primary.cookies.get('atlas_session')
        assert token and token not in str(inventory)
        assert hashlib.sha256(token.encode()).hexdigest() not in str(inventory)
        other_before = other.get('/api/account/sessions').json()
        assert primary.post('/api/account/sessions/revoke-others').status_code == 403
        result = primary.post('/api/account/sessions/revoke-others', headers=HEADERS)
        assert result.status_code == 200, result.text
        assert result.json()['revoked'] >= 1
        assert primary.get('/api/me').status_code == 200
        assert older.get('/api/me').status_code == 401
        assert other.get('/api/me').status_code == 200
        assert other.get('/api/account/sessions').json() == other_before
        assert len(primary.get('/api/account/sessions').json()['items']) == 1


@pytest.mark.parametrize('family', ['consultation', 'event', 'library'])
def test_concurrent_last_place_has_one_winner_and_return_releases_exactly_once(family):
    """Actual concurrent SQL writes, not a mocked capacity decision."""
    from app.services_db import LibraryBook

    with client() as a, client() as b, client() as staff, client() as second_winner_session:
        login(a, A)
        login(b, B)
        login(staff, STAFF)
        start = utc_now() + timedelta(days=10)
        if family == 'consultation':
            created = staff.post('/api/staff/consultations', headers=HEADERS, json={
                'teacher': 'Fictional capacity teacher', 'subject': 'Independent capacity check',
                'start_at': start.isoformat(), 'end_at': (start + timedelta(hours=1)).isoformat(),
                'room': 'Test room A-101', 'capacity': 1,
            })
            assert created.status_code == 201, created.text
            resource_id = created.json()['id']
            consume_path = f'/api/services/consultations/{resource_id}/book'
            release_path = lambda row_id: f'/api/services/bookings/{row_id}/cancel'
            catalog_path, field, occupied = '/api/services/consultations', 'booked_count', 1
        elif family == 'event':
            created = staff.post('/api/staff/events', headers=HEADERS, json={
                'title': 'Independent fictional capacity event', 'category': 'academic',
                'description': 'An isolated capacity regression, no real participant information.',
                'start_at': start.isoformat(), 'end_at': (start + timedelta(hours=1)).isoformat(),
                'location': 'Test location B-101', 'capacity': 1,
            })
            assert created.status_code == 201, created.text
            resource_id = created.json()['id']
            consume_path = f'/api/services/events/{resource_id}/register'
            release_path = lambda row_id: f'/api/services/registrations/{row_id}/cancel'
            catalog_path, field, occupied = '/api/services/events', 'registered_count', 1
        else:
            with SessionLocal() as db:
                book = LibraryBook(title='Capacity ' + uuid.uuid4().hex, author='Fictional reviewer',
                                   subject='Security exercise', description='Isolated test book.', total=1, available=1)
                db.add(book)
                db.commit()
                resource_id = book.id
            consume_path = f'/api/services/library/{resource_id}/borrow'
            release_path = lambda row_id: f'/api/services/loans/{row_id}/return'
            catalog_path, field, occupied = '/api/services/library', 'available', 0

        def consume(api):
            return api.post(consume_path, json={}, headers=HEADERS)

        with ThreadPoolExecutor(max_workers=2) as workers:
            responses = list(workers.map(consume, (a, b)))
        assert sorted(result.status_code for result in responses) == [201, 409], [result.text for result in responses]
        winner_index = next(index for index, response in enumerate(responses) if response.status_code == 201)
        winner, loser = ((a, b) if winner_index == 0 else (b, a))
        row_id = responses[winner_index].json()['id']
        before = next(item for item in winner.get(catalog_path).json()['items'] if item['id'] == resource_id)
        assert before[field] == occupied
        assert loser.post(release_path(row_id), json={}, headers=HEADERS).status_code == 404
        # A second browser session of the winner races the first one to release.
        login(second_winner_session, A if winner_index == 0 else B)

        def release(api):
            return api.post(release_path(row_id), json={}, headers=HEADERS)

        with ThreadPoolExecutor(max_workers=2) as workers:
            released = list(workers.map(release, (winner, second_winner_session)))
        assert sorted(result.status_code for result in released) == [200, 409], [result.text for result in released]
        after = next(item for item in winner.get(catalog_path).json()['items'] if item['id'] == resource_id)
        assert after[field] == (1 if family == 'library' else 0)
        acquired = consume(loser)
        assert acquired.status_code == 201, acquired.text
        assert loser.post(release_path(acquired.json()['id']), json={}, headers=HEADERS).status_code == 200


def test_extension_records_and_intentional_deletions_survive_real_process_restart():
    """A fresh process migrates/reseeds the same DB without undoing user actions."""
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='atlas-extension-restart-') as directory:
        env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + str(Path(directory) / 'restart.db'),
               'APP_ENV': 'development', 'DEMO_MODE': 'true', 'COOKIE_SECURE': 'false',
               'PUBLIC_ORIGIN': '', 'ALLOWED_HOSTS': 'localhost,127.0.0.1,testserver'}
        prelude = '''
import json
from fastapi.testclient import TestClient
from app.main import app
from app.db import engine
h = {'X-Requested-With':'ATLAS'}
def post(api, path, body):
    result=api.post(path, json=body, headers=h)
    assert result.status_code in (200,201), (path,result.status_code,result.text)
    return result.json()
def enter(api):
    post(api,'/api/login',{'login':'alina.demo','password':'AtlasDemo!2026-A'})
'''
        create_code = prelude + '''
with TestClient(app) as api:
    enter(api)
    note=api.get('/api/learning/notes').json()['items'][0]
    post(api,f"/api/learning/notes/{note['id']}",{'title':'Persisted restart marker','subject':note['subject'],'body':'This edit must survive demo reseeding.'})
    for task in api.get('/api/learning/tasks').json()['items']:
        post(api,f"/api/learning/tasks/{task['id']}/delete",{})
    course=api.get('/api/learning/courses').json()['items'][0]
    module=course['modules'][0]
    post(api,f"/api/learning/courses/{course['id']}/modules/{module['id']}",{'is_done':False})
    post(api,'/api/services/preferences',{'email_notifications':True,'deadline_reminders':False,'compact_mode':True,'weekly_goal':37})
    work=api.get('/api/learning/assignments').json()['items'][0]
    post(api,f"/api/learning/assignments/{work['id']}/submit",{'text':'Persistent fictional assignment submission.','url':'https://example.invalid/restart'})
    slot=api.get('/api/services/consultations').json()['items'][0]
    booking=post(api,f"/api/services/consultations/{slot['id']}/book",{})
    book=api.get('/api/services/library').json()['items'][0]
    loan=post(api,f"/api/services/library/{book['id']}/borrow",{})
    topic=post(api,'/api/services/tickets',{'topic':'academic','title':'Persistent restart topic','message':'A fictional conversation persisted across process restart.'})
    print(json.dumps({'note_id':note['id'],'course_id':course['id'],'module_id':module['id'],'work_id':work['id'],'slot_id':slot['id'],'booking_id':booking['id'],'book_id':book['id'],'loan_id':loan['id'],'ticket_id':topic['id'],'available':book['available']-1}))
engine.dispose()
'''
        created = subprocess.run([sys.executable, '-c', create_code], cwd=root, env=env,
                                 capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=35)
        assert created.returncode == 0, created.stderr
        saved = json.loads(created.stdout)
        read_code = prelude + '\nsaved=' + repr(saved) + '''
from app.db import initialize_database
initialize_database()
initialize_database()
with TestClient(app) as api:
    enter(api)
    assert api.get('/api/learning/tasks').json()['items']==[]
    notes=api.get('/api/learning/notes').json()['items']
    assert len(notes)==1 and notes[0]['id']==saved['note_id'] and notes[0]['title']=='Persisted restart marker'
    course=api.get(f"/api/learning/courses/{saved['course_id']}").json()
    assert next(m for m in course['modules'] if m['id']==saved['module_id'])['is_done'] is False
    prefs=api.get('/api/services/preferences').json()
    assert prefs=={'email_notifications':True,'deadline_reminders':False,'compact_mode':True,'weekly_goal':37}
    work=api.get(f"/api/learning/assignments/{saved['work_id']}").json()
    assert work['submission']['text']=='Persistent fictional assignment submission.' and work['submission']['version']==1
    bookings=api.get('/api/services/bookings').json()['items']
    assert len(bookings)==1 and bookings[0]['id']==saved['booking_id'] and bookings[0]['status']=='active'
    slot=next(s for s in api.get('/api/services/consultations').json()['items'] if s['id']==saved['slot_id'])
    assert slot['booked_count']==1 and slot['my_booking_id']==saved['booking_id']
    loans=api.get('/api/services/loans').json()['items']
    assert len(loans)==1 and loans[0]['id']==saved['loan_id'] and loans[0]['status']=='active'
    book=next(b for b in api.get('/api/services/library').json()['items'] if b['id']==saved['book_id'])
    assert book['available']==saved['available']
    ticket=api.get(f"/api/services/tickets/{saved['ticket_id']}").json()
    assert ticket['title']=='Persistent restart topic' and len(ticket['messages'])==1
    print(json.dumps({'persisted':True}))
engine.dispose()
'''
        reloaded = subprocess.run([sys.executable, '-c', read_code], cwd=root, env=env,
                                  capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=35)
        assert reloaded.returncode == 0, reloaded.stderr
        assert json.loads(reloaded.stdout) == {'persisted': True}
