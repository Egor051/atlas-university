"""Security regression and end-to-end API tests, using only fictional fixture data."""
import os
import tempfile
import atexit
from pathlib import Path

# Configure isolated DB *before* the application imports its SQLAlchemy engine.
_testdir = tempfile.TemporaryDirectory(prefix='atlas-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_testdir.name)/'test.db')
from fastapi.testclient import TestClient
from app.main import app
from app.db import engine

# Release pooled SQLite handles before TemporaryDirectory cleanup on Windows.
atexit.register(engine.dispose)


def client(): return TestClient(app)

def sign_in(api, login, password):
    response=api.post('/api/login',json={'login':login,'password':password},headers={'X-Requested-With':'ATLAS'})
    assert response.status_code==200, response.text
    return response


def test_public_assets_and_protected_apis():
    with client() as api:
        assert api.get('/').status_code==200
        assert api.get('/static/app.js').status_code==200
        assert api.get('/api/health').json()['ok'] is True
        for url in ['/api/me','/api/grades','/api/dashboard','/api/requests','/api/staff/requests']:
            assert api.get(url).status_code==401
        assert 'service_role' not in api.get('/static/app.js').text


def test_login_and_cookie_security():
    with client() as api:
        assert api.post('/api/login',json={'login':'alina.demo','password':'incorrect'},headers={'X-Requested-With':'ATLAS'}).status_code==401
        assert api.post('/api/login',json={'login':'alina.demo','password':'AtlasDemo!2026-A'}).status_code==403
        r=sign_in(api,'alina.demo','AtlasDemo!2026-A')
        cookie=r.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=lax' in cookie
        assert 'atlas_session=' in cookie
        assert api.get('/api/me').json()['group']=='ИТ-24-03'
        assert api.post('/api/logout',headers={'X-Requested-With':'ATLAS'}).status_code==200
        assert api.get('/api/me').status_code==401


def test_isolation_by_session_and_idor_request():
    with client() as a, client() as b:
        sign_in(a,'alina.demo','AtlasDemo!2026-A')
        sign_in(b,'mark.demo','AtlasDemo!2026-M')
        ag=a.get('/api/grades').json()
        bg=b.get('/api/grades').json()
        assert ag['items'][0]['subject']!='Инженерия ПО'
        assert bg['items'][0]['subject']=='Инженерия ПО'
        ar=a.get('/api/requests').json()[0]
        br=b.get('/api/requests').json()[0]
        assert ar['id']!=br['id']
        assert a.get(f'/api/requests/{br["id"]}').status_code==404
        assert b.get(f'/api/requests/{ar["id"]}').status_code==404
        assert a.get('/api/staff/requests').status_code==403
        assert b.post('/api/staff/requests/1/status',json={'status':'ready'},headers={'X-Requested-With':'ATLAS'}).status_code==403
        a_new=a.post('/api/requests',json={'type':'study','comment':'Тестовый запрос'},headers={'X-Requested-With':'ATLAS'})
        assert a_new.status_code==201
        created=a_new.json()['id']
        assert b.get('/api/requests/'+str(created)).status_code==404
        assert not any(x['id']==created for x in b.get('/api/requests').json())
        assert any(x['id']==created for x in a.get('/api/requests').json())
        # CSRF guard on mutations.
        assert a.post('/api/requests',json={'type':'study'}).status_code==403
        assert a.post('/api/notifications/read-all').status_code==403


def test_staff_workflow_is_persistent():
    with client() as dean, client() as student:
        sign_in(dean,'dean.demo','AtlasStaff!2026-D')
        sign_in(student,'alina.demo','AtlasDemo!2026-A')
        assert dean.get('/api/grades').status_code==403
        assert dean.get('/api/requests').status_code==403
        record=student.post('/api/requests',json={'type':'transcript','comment':'Нужна выписка'},headers={'X-Requested-With':'ATLAS'}).json()
        req_id=record['id']
        for next_status in ['review','processing','ready']:
            detail=dean.get(f'/api/staff/requests/{req_id}').json()
            r=dean.post(f'/api/staff/requests/{req_id}/status',json={'status':next_status,'expected_version':detail['version'],'message':'Демонстрационная выписка подготовлена.' if next_status=='ready' else ''},headers={'X-Requested-With':'ATLAS'})
            assert r.status_code==200,r.text
        assert student.get(f'/api/requests/{req_id}').json()['status']=='ready'
        assert dean.post(f'/api/staff/requests/{req_id}/status',json={'status':'submitted'},headers={'X-Requested-With':'ATLAS'}).status_code==409
        assert any('Статус заявки изменился' in x['title'] for x in student.get('/api/notifications').json())


def test_validation_and_schedule():
    with client() as api:
        sign_in(api,'mark.demo','AtlasDemo!2026-M')
        assert api.post('/api/requests',json={'type':'statement','comment':'мало'},headers={'X-Requested-With':'ATLAS'}).status_code==422
        assert api.post('/api/requests',json={'type':'injected','comment':'test'},headers={'X-Requested-With':'ATLAS'}).status_code==422
        assert api.get('/api/schedule?week=2005-01-01').status_code==422
        from app.db import campus_today
        schedule=api.get('/api/schedule?week='+campus_today().isoformat()).json()
        assert len(schedule['days'])==7
        assert any(x['changed'] for day in schedule['days'] for x in day['items'])
        a=api.get('/api/notifications').json()[0]
        assert api.post('/api/notifications/'+str(a['id'])+'/read',headers={'X-Requested-With':'ATLAS'}).status_code==200


def test_removed_navigator_has_no_route_for_any_account():
    # Removing the UI alone must not leave a personal-data helper callable.
    assert not any(getattr(route, 'path', None) == '/api/navigator' for route in app.routes)
    for account in [None, ('alina.demo', 'AtlasDemo!2026-A'),
                    ('mark.demo', 'AtlasDemo!2026-M'), ('dean.demo', 'AtlasStaff!2026-D')]:
        with client() as api:
            if account:
                sign_in(api, *account)
            response = api.post('/api/navigator', json={'topic': 'grades'},
                                headers={'X-Requested-With': 'ATLAS'})
            assert response.status_code == 404
            assert 'answer' not in response.json()
            assert 'no-store' in response.headers.get('cache-control', '')
