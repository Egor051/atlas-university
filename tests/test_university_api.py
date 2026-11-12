"""Directory and file contracts, permission checks and direct-message persistence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
import uuid

import pytest

from test_api import client, sign_in
from app import direct
from app.db import utc_now
from app.improvements import quota_limit

HEAD = {'X-Requested-With': 'ATLAS'}
ACCOUNTS = {
    'student': ('alina.demo', 'AtlasDemo!2026-A'),
    'other': ('mark.demo', 'AtlasDemo!2026-M'),
    'teacher': ('orlov.demo', 'AtlasTeach!2026-M'),
    'colleague': ('ryabinina.demo', 'AtlasTeach!2026-E'),
    'staff': ('dean.demo', 'AtlasStaff!2026-D'),
}
PROFILE = '/api/university/digital/systems/mikhail-orlov'


@pytest.fixture
def accounts():
    with ExitStack() as stack:
        def enter(role):
            api = stack.enter_context(client())
            sign_in(api, *ACCOUNTS[role])
            return api
        yield enter


def test_directory_nested_scope_search_and_each_material_opens(accounts):
    student = accounts('student')
    assert student.get('/api/university').status_code == 200
    institute = student.get('/api/university/digital').json()
    assert len(institute['items']) == 2 and institute['disciplines']
    department = student.get('/api/university/digital/systems').json()
    assert len(department['items']) == 2
    teacher = student.get(PROFILE).json()
    assert teacher['can_message'] and teacher['disciplines'][0]['title'] == 'Алгоритмы и структуры данных'
    assert {slot['kind'] for slot in teacher['schedule']} == {'lesson', 'consultation'}
    assert teacher['parents'][1]['href'] == '/app/university/digital/systems'
    assert student.get('/api/university/applied/systems/mikhail-orlov').status_code == 404
    result = student.get('/api/university', params={'q': 'ОРЛОВ', 'kind': 'teacher', 'faculty': 'digital'}).json()
    assert [row['id'] for row in result['items']] == [teacher['id']]
    library = student.get('/api/materials').json()
    assert set(library['kinds']) <= {row['kind'] for row in library['items']}
    for row in library['items']:
        detail = student.get(f"/api/materials/{row['id']}").json()
        assert detail['sections'] and detail['title'] == row['title']
        file = student.get(row['file_url'])
        assert file.status_code == 200 and file.headers['content-disposition'].startswith('attachment;')
        assert 'sandbox' in file.headers['content-security-policy']
        assert 'все данные вымышлены' in file.text and detail['sections'][0]['heading'] in file.text
        if row['kind'] == 'slides':
            assert 'href="#slide-2"' in file.text
    found = student.get('/api/materials', params={'q': 'ПОИСК ПУТИ', 'kind': 'lecture',
                                                  'discipline': teacher['disciplines'][0]['id'], 'limit': 1}).json()
    assert found['total'] == 1 and found['items'][0]['author']['id'] == teacher['id']
    with client() as anonymous:
        for path in ('/api/university', '/api/materials', library['items'][0]['file_url'], '/api/direct/dialogs'):
            assert anonymous.get(path).status_code == 401


def test_material_editor_permissions_validation_replay_and_version(accounts):
    student, teacher, colleague, staff = (accounts(role) for role in ('student', 'teacher', 'colleague', 'staff'))
    assignment = teacher.get('/api/materials/assignments').json()['items'][0]
    other_assignment = colleague.get('/api/materials/assignments').json()['items'][0]['id']
    assert student.get('/api/materials/assignments').status_code == 403
    assert teacher.get('/api/grades').status_code == teacher.get('/api/staff/requests').status_code == 403
    body = {'assignment_id': assignment['id'], 'kind': 'lecture', 'title': 'Тестовая лекция ' + uuid.uuid4().hex,
            'description': 'Подробное описание вымышленного учебного занятия.',
            'body': '## Пример\nРазметка <b>остаётся текстом</b> в документе.'}
    assert student.post('/api/materials', json=body, headers=HEAD).status_code == 403
    assert teacher.post('/api/materials', json=body).status_code == 403
    assert teacher.post('/api/materials', json={**body, 'assignment_id': other_assignment}, headers=HEAD).status_code == 403
    assert teacher.post('/api/materials', json={**body, 'kind': 'slides'}, headers=HEAD).status_code == 422
    key = {**HEAD, 'Idempotency-Key': uuid.uuid4().hex}
    created = teacher.post('/api/materials', json=body, headers=key)
    assert created.status_code == 201, created.text
    item = created.json()
    again = teacher.post('/api/materials', json=body, headers=key)
    assert again.status_code == 200 and again.json() == item
    path = '/api/materials/' + str(item['id'])
    assert '&lt;b&gt;' in student.get(path + '/file').text
    assert colleague.patch(path, json={**body, 'version': 1}, headers=HEAD).status_code == 403
    assert colleague.delete(path + '?version=1', headers=HEAD).status_code == 403
    edit = staff.patch(path, json={**body, 'version': 1, 'title': 'Материал после редакции'}, headers=HEAD)
    assert edit.status_code == 200 and edit.json()['version'] == 2
    assert teacher.delete(path + '?version=1', headers=HEAD).status_code == 409
    assert teacher.delete(path + '?version=2', headers=HEAD).status_code == 200
    assert student.get(path).status_code == student.get(path + '/file').status_code == 404


def test_direct_concurrent_replay_permissions_read_boundary_and_notice(accounts):
    student, other, teacher, staff = (accounts(role) for role in ('student', 'other', 'teacher', 'staff'))
    contact = student.get('/api/direct/recipients', params={'q': 'ОРЛОВ'}).json()['items'][0]
    assert contact['role'] == 'teacher'
    assert student.get('/api/direct/recipients', params={'q': 'учебный офис'}).json()['items'][0]['role'] == 'staff'
    assert teacher.get('/api/direct/recipients').status_code == 403
    start = '/api/direct/dialogs'
    body = {'recipient_id': contact['id'], 'message': 'Вопрос по обходу ' + uuid.uuid4().hex}
    assert student.post(start, json=body).status_code == 403
    assert student.post(start, json={**body, 'recipient_id': other.get('/api/me').json()['id']}, headers=HEAD).status_code == 404
    assert student.post(start, json={**body, 'sender_id': 1}, headers=HEAD).status_code == 422
    key = {**HEAD, 'Idempotency-Key': uuid.uuid4().hex}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: student.post(start, json=body, headers=key), range(2)))
    assert sorted(result.status_code for result in results) == [200, 201]
    assert results[0].json() == results[1].json()
    path = start + '/' + str(results[0].json()['dialog_id'])
    assert teacher.get('/api/direct/unread').json()['unread_count'] >= 1
    dialog_target = path.replace('/api/direct/dialogs', '/app/direct')
    teacher_notices = [row for row in teacher.get('/api/notifications?filter=direct').json()
                       if row['target'] == dialog_target]
    assert len(teacher_notices) == 1 and not teacher_notices[0]['is_read']
    assert staff.get(f"/api/notifications/{teacher_notices[0]['id']}").status_code == 404
    for nonparticipant in (other, staff):
        assert nonparticipant.get(path).status_code == 404
        assert nonparticipant.post(path + '/messages', json={'message': 'Текст'}, headers=HEAD).status_code == 404
        assert nonparticipant.post(path + '/read', json={'through_id': results[0].json()['message_id']}, headers=HEAD).status_code == 404
        assert path.rsplit('/', 1)[1] not in {str(item['id']) for item in nonparticipant.get(start).json()['items']}
    assert teacher.get(path).json()['messages'][-1]['body'] == body['message']
    assert teacher.post(path + '/read', json={'through_id': results[0].json()['message_id']}, headers=HEAD).status_code == 200
    assert teacher.get(f"/api/notifications/{teacher_notices[0]['id']}").json()['is_read']
    first = teacher.post(path + '/messages', json={'message': 'Пройдите вершины в порядке очереди.'}, headers=HEAD)
    second = teacher.post(path + '/messages', json={'message': 'Проверьте также несвязный граф.'}, headers=HEAD)
    assert first.status_code == second.status_code == 201
    assert student.post(path + '/read', json={'through_id': 2147483647}, headers=HEAD).status_code == 404
    assert student.post(path + '/read', json={'through_id': first.json()['message_id']}, headers=HEAD).json()['read_count'] >= 1
    assert student.get(path).json()['unread_count'] == 1
    notices = student.get('/api/notifications?filter=direct').json()
    own = [n for n in notices if n['target'] == path.replace('/api/direct/dialogs', '/app/direct')]
    assert any(n['is_read'] for n in own) and any(not n['is_read'] for n in own)
    assert all(n['target'] != own[0]['target'] for n in other.get('/api/notifications').json())
    student.post(path + '/read', json={'through_id': second.json()['message_id']}, headers=HEAD)
    assert student.get(path).json()['unread_count'] == 0


def test_direct_rate_and_history_limits(accounts, monkeypatch):
    student = accounts('other')
    staff = accounts('staff')
    recipient_id = staff.get('/api/me').json()['id']
    clock = utc_now() + timedelta(minutes=2)
    monkeypatch.setattr(direct, 'utc_now', lambda: clock)
    monkeypatch.setattr('app.improvements.quota_limit',
                        lambda bucket, period: 1 if bucket == 'direct' and period == 0 else quota_limit(bucket, period))
    body = {'recipient_id': recipient_id, 'message': 'Вопрос о демонстрационной справке.'}
    created = student.post('/api/direct/dialogs', json=body, headers=HEAD)
    assert created.status_code == 201
    assert student.post('/api/direct/dialogs', json=body, headers=HEAD).status_code == 429
    monkeypatch.setattr(direct, 'MAX_MESSAGES', 1)
    path = f"/api/direct/dialogs/{created.json()['dialog_id']}"
    assert staff.post(path + '/messages', json={'message': 'Ответ'}, headers=HEAD).status_code == 409
    assert len(student.get(path).json()['messages']) == 1
