"""Announcement audience, revision and single-delivery contracts."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Notification, SessionLocal
from app.main import app
from test_api import sign_in
from test_services import HEADERS, login


def test_group_publication_workflow_and_visibility():
    with TestClient(app) as alina, TestClient(app) as mark, TestClient(app) as office:
        login(alina)
        login(mark, 'mark.demo')
        login(office, 'dean.demo')
        groups = office.get('/api/staff/announcements/groups').json()['items']
        group = next(row for row in groups if row['name'] == 'ИТ-24-03')
        original = dict(title=f'Проверка аудитории {uuid4().hex}', body='Содержание объявления учебной группе.',
                        audience='group', group_id=group['id'], category='academic',
                        priority='important', status='draft', pinned=True)
        assert alina.post('/api/staff/announcements', json=original, headers=HEADERS).status_code == 403
        assert alina.get('/api/staff/announcements').status_code == 403
        assert office.post('/api/staff/announcements', json=original).status_code == 403
        assert office.post('/api/staff/announcements', json={**original, 'group_id': None}, headers=HEADERS).status_code == 422
        created = office.post('/api/staff/announcements', json=original, headers=HEADERS)
        assert created.status_code == 201, created.text
        row = created.json()
        assert row['sent'] == 0
        target = f"/api/announcements/{row['id']}"
        editor = f"/api/staff/announcements/{row['id']}"
        assert alina.get(target).status_code == 404
        assert alina.patch(editor, json={**original, 'version': 1}, headers=HEADERS).status_code == 403

        publish = {**original, 'status': 'published', 'version': row['version']}
        key = {'Idempotency-Key': uuid4().hex, **HEADERS}
        with ThreadPoolExecutor(max_workers=2) as pool:
            sends = list(pool.map(lambda _: office.patch(editor, json=publish, headers=key), range(2)))
        assert [response.status_code for response in sends] == [200, 200]
        assert sends[0].json() == sends[1].json()
        assert sends[0].json()['sent'] == 1
        assert alina.get(target).json()['body'] == original['body']
        assert mark.get(target).status_code == 404
        assert alina.get('/api/announcements').json()['items'][0]['id'] == row['id']
        assert alina.get('/api/announcements?sort=oldest').json()['items'][-1]['id'] == row['id']
        filters = {'q': original['title'].upper(), 'category': 'academic', 'priority': 'important'}
        assert [item['id'] for item in alina.get('/api/announcements', params=filters).json()['items']] == [row['id']]
        assert mark.get('/api/announcements', params=filters).json()['items'] == []

        assert office.patch(editor, json={**publish, 'version': 2, 'audience': 'all', 'group_id': None},
                            headers=HEADERS).status_code == 409
        assert office.patch(editor, json=publish, headers=HEADERS).status_code == 409
        draft = office.patch(editor, json={**publish, 'version': 2, 'status': 'draft'}, headers=HEADERS)
        assert draft.json()['status'] == 'draft'
        assert alina.get(target).status_code == 404
        reissued = office.patch(editor, json={**publish, 'version': 3}, headers=HEADERS)
        assert reissued.json()['sent'] == 0
        archive = office.patch(editor, json={**publish, 'version': 4, 'status': 'archived'}, headers=HEADERS)
        assert archive.json()['status'] == 'archived'
        assert alina.get(target).json()['status'] == 'archived'
        assert alina.get('/api/announcements', params=filters).json()['items'] == []
        assert [item['id'] for item in alina.get('/api/announcements', params={**filters, 'status': 'archived'}).json()['items']] == [row['id']]
        assert mark.get(target).status_code == 404
        assert office.patch(editor, json={**publish, 'version': 5}, headers=HEADERS).status_code == 409
        events = office.get(editor).json()['revisions']
        assert [event['action'] for event in events] == ['archived', 'published', 'withdrawn', 'published', 'created']
        assert [event['after']['version'] for event in events] == [5, 4, 3, 2, 1]
        with SessionLocal() as db:
            notices = db.scalars(select(Notification).where(Notification.target == f"/app/announcements/{row['id']}")).all()
            assert len(notices) == 1
            assert notices[0].category == 'announcement'
            assert notices[0].body != original['body']


def test_employee_recipient_reads_through_global_notifications():
    with TestClient(app) as teacher, TestClient(app) as student, TestClient(app) as office:
        sign_in(teacher, 'orlov.demo', 'AtlasTeach!2026-M')
        login(student)
        login(office, 'dean.demo')
        body = dict(title=f'Для сотрудников {uuid4().hex}', body='Содержание публикации для сотрудников.',
                    audience='employees', status='published')
        assert teacher.post('/api/staff/announcements', json=body, headers=HEADERS).status_code == 403
        response = office.post('/api/staff/announcements', json=body, headers=HEADERS)
        assert response.status_code == 201, response.text
        target = f"/app/announcements/{response.json()['id']}"
        detail = target.replace('/app/', '/api/', 1)
        assert teacher.get(detail).json()['body'] == body['body']
        assert student.get(detail).status_code == 404
        notices = teacher.get('/api/notifications', params={'filter': 'announcement'}).json()
        assert [notice['target'] for notice in notices if notice['title'] == body['title']] == [target]
