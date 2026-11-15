"""The same publication, permissions and file bytes across discipline workflows."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

from test_university_api import HEAD, PROFILE, accounts
from test_api import client, sign_in

from app.db import SessionLocal, campus_today
from app.university_db import Discipline
from app.workspace_seed import seed_account


def upload(text, name='Конспект.txt'):
    return {'name': name, 'content': base64.b64encode(text).decode()}


def sample(teacher, **overrides):
    assignment = next(row for row in teacher.get('/api/materials/assignments').json()['items']
                      if row['discipline'] == 'Алгоритмы и структуры данных')
    return {'assignment_id': assignment['id'], 'kind': 'lab', 'title': f'Тестовый практикум {uuid4().hex}',
            'description': 'Описание для назначенной учебной группы.', 'source': 'file', 'access': 'group',
            'file': upload(b'First file for isolated test.'), **overrides}, assignment


def publish(api, body):
    result = api.post('/api/materials', json=body, headers={**HEAD, 'Idempotency-Key': uuid4().hex})
    assert result.status_code == 201, result.text
    return result.json()


def test_group_material_lifecycle_through_course_profile_and_work(accounts):
    teacher, student, colleague, other, staff = (accounts(role) for role in ('teacher', 'student', 'colleague', 'other', 'staff'))
    payload, assignment = sample(teacher)
    discipline_id = assignment['discipline_id']
    workspace = f'/api/disciplines/{discipline_id}'
    materials = '/api/materials'
    filters = {'discipline': discipline_id, 'q': payload['title'], 'kind': 'lab', 'sort': 'updated'}
    row = publish(teacher, payload)
    material = f'{materials}/{row["id"]}'
    file_url = row['file_url']
    assert row['href'] == f'/app/courses/materials/{row["id"]}'
    assert student.get(workspace).json()['course_id']
    assert other.get(workspace).json()['course_id'] is None
    assert student.get(materials, params=filters).json()['items'][0]['id'] == row['id']
    assert row['id'] in {item['id'] for item in student.get(PROFILE).json()['materials']}
    for outsider in (other, colleague):
        assert outsider.get(materials, params=filters).json()['total'] == 0
        assert outsider.get(material).status_code == outsider.get(file_url).status_code == 404
        assert row['id'] not in {item['id'] for item in outsider.get(PROFILE).json()['materials']}
    download = student.get(file_url)
    assert download.content == b'First file for isolated test.'
    assert download.headers['content-type'] == 'application/octet-stream'
    assert 'filename*=UTF-8' in download.headers['content-disposition']
    assert download.headers['cache-control'] == 'no-store, private'
    assert 'sandbox' in download.headers['content-security-policy']
    assert student.get(f'{material}/history').status_code == 403

    load = next(item for item in teacher.get('/api/teaching').json()['items'] if item['assignment_id'] == assignment['id'])
    works = f'/api/teaching/{load["id"]}/works'
    body = {'title': payload['title'], 'instructions': 'Шаги для тестовой работы.', 'methods': ['text'],
            'due': (campus_today() + timedelta(days=7)).isoformat(), 'material_ids': [row['id']]}
    assert teacher.post(works, headers=HEAD, json={**body, 'material_ids': [2147483647]}).status_code == 404
    work = teacher.post(works, headers=HEAD, json=body)
    assert work.status_code == 201, work.text
    work_path = f'{works}/{work.json()["id"]}'
    assert teacher.get(work_path).json()['course_materials'][0]['title'] == row['title']
    deadlines = student.get(workspace + '/activity?view=works').json()['items']
    deadline = next(item for item in deadlines if item['title'] == body['title'])
    student_work = f'/api/learning/assignments/{deadline["id"]}'
    assert student.get(student_work).json()['course_materials'][0]['href'] == row['href']
    assert other.get(student_work).status_code == 404
    assert student.post(student_work + '/submit', headers=HEAD, json={'text': 'Тестовая работа студента.'}).status_code == 200
    assert teacher.get('/api/teaching/workbench').json()['pending'][0]['work_id'] == work.json()['id']
    assert all(r['work_id'] != work.json()['id'] for r in colleague.get('/api/teaching/workbench').json()['pending'])
    assert student.get('/api/teaching/workbench').status_code == 403
    assert teacher.get('/api/staff/requests').status_code == 403

    changes = {**payload, 'title': payload['title'] + ' обновлён', 'description': 'Описание для второй версии материала.',
               'version': 1, 'file': upload(b'Second file.', 'Редакция.txt')}
    assert colleague.patch(material, headers=HEAD, json=changes).status_code == 403
    assert colleague.delete(material + '?version=1', headers=HEAD).status_code == 403
    assert student.patch(material, headers=HEAD, json=changes).status_code == 403
    assert teacher.patch(material, headers=HEAD, json=changes).status_code == 200
    assert student.get(file_url).content == b'Second file.'
    assert student.get(material).json()['description'] == changes['description']
    assert student.get(student_work).json()['course_materials'][0]['title'] == changes['title']
    assert teacher.get(work_path).json()['course_materials'][0]['title'] == changes['title']
    assert student.get(materials, params=filters).json()['items'][0]['updated_at'] > row['updated_at']
    saved = {key: value for key, value in changes.items() if key != 'file'}
    assert staff.patch(material, headers=HEAD, json={**saved, 'version': 2, 'access': 'hidden'}).status_code == 200
    assert student.get(file_url).status_code == 404 and teacher.get(file_url).content == b'Second file.'
    assert teacher.patch(material, headers=HEAD, json={**saved, 'version': 3}).status_code == 200
    assert student.get(file_url).content == b'Second file.'
    assert teacher.delete(material + '?version=3', headers=HEAD).status_code == 409
    assert teacher.delete(material + '?version=4', headers=HEAD).status_code == 200
    assert student.get(material).status_code == student.get(file_url).status_code == 404
    assert student.get(student_work).json()['course_materials'] == []
    assert teacher.get(work_path).json()['material_ids'] == [row['id']]
    assert student.get(materials, params=filters).json()['total'] == 0
    assert row['id'] not in {item['id'] for item in student.get(PROFILE).json()['materials']}
    assert teacher.get(materials, params={**filters, 'mine': True, 'access': 'archived'}).json()['total'] == 1
    history = teacher.get(material + '/history').json()['items']
    assert [event['action'] for event in history] == ['archived', 'access_changed', 'access_changed', 'edited', 'created']
    assert history[2]['author'] == staff.get('/api/me').json()['full_name']
    assert all(event['created_at'] for event in history)


def test_upload_validation_link_access_and_concurrent_replacement(accounts):
    teacher, student = accounts('teacher'), accounts('student')
    payload, _ = sample(teacher)
    for invalid in (upload(b'Not a PDF', 'Document.pdf'), upload(b'data', 'folder/report.txt'),
                    upload(b'data', 'Document.exe'), upload(b'x' * (5 * 1024 * 1024 + 1))):
        assert teacher.post('/api/materials', headers=HEAD, json={**payload, 'file': invalid}).status_code == 422
    no_file = {key: value for key, value in payload.items() if key != 'file'}
    resource = {**no_file, 'source': 'link', 'url': 'https://example.org/teaching/graphs'}
    assert teacher.post('/api/materials', headers=HEAD, json={**resource, 'url': 'http://example.org/lecture'}).status_code == 422
    link = publish(teacher, resource)
    detail = student.get('/api/materials/' + str(link['id'])).json()
    assert detail['url'] == resource['url'] and detail['file_url'] is None

    row = publish(teacher, payload)
    path = f'/api/materials/{row["id"]}'
    responses = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(lambda name: teacher.patch(path, headers=HEAD, json={
            **payload, 'version': 1, 'description': name, 'file': upload(name.encode())}),
            ('Описание одной редакции', 'Описание другой редакции')):
            responses.append(result)
    assert sorted(response.status_code for response in responses) == [200, 409]
    final = student.get(path).json()
    assert student.get(row['file_url']).content.decode() == final['description']
    assert final['version'] == 2
    assert teacher.delete(path + '?version=2', headers=HEAD).status_code == 200
    assert teacher.delete(f'/api/materials/{link["id"]}?version=1', headers=HEAD).status_code == 200


def test_delegated_material_permissions_end_at_discipline_or_department(accounts):
    teacher, colleague, staff, student = (accounts(role) for role in ('teacher', 'colleague', 'staff', 'student'))
    owned, assignment = sample(teacher)
    outside = next(item for item in colleague.get('/api/materials/assignments').json()['items']
                   if item['discipline_id'] != assignment['discipline_id'])
    with SessionLocal() as db:
        department = db.get(Discipline, assignment['discipline_id']).department_id
        assert db.get(Discipline, outside['discipline_id']).department_id == department
        people = {role: seed_account(db, f'demo-{role}-{uuid4().hex}', 'IsolatedTest!44', role, 'Т',
                                    'Тестовый сотрудник', role) for role in ('coordinator', 'department')}
        profiles = {role: (person.id, person.login) for role, person in people.items()}
        db.commit()
    row = publish(teacher, owned)
    assignments = '/api/materials/assignments'
    delegations = '/api/materials/delegations'
    with client() as admin, client() as coordinator, client() as employee:
        sign_in(admin, 'registry.demo', 'AtlasRegistry!2026-R')
        sign_in(coordinator, profiles['coordinator'][1], 'IsolatedTest!44')
        sign_in(employee, profiles['department'][1], 'IsolatedTest!44')
        assert coordinator.get(assignments).json()['items'] == employee.get(assignments).json()['items'] == []
        assert admin.post('/api/materials', headers=HEAD, json=owned).status_code == 403
        course_grant = {'user_id': profiles['coordinator'][0], 'scope': 'course', 'scope_id': assignment['discipline_id']}
        department_grant = {'user_id': profiles['department'][0], 'scope': 'department', 'scope_id': department}
        for unauthorized in (teacher, colleague, student, staff, coordinator, employee):
            assert unauthorized.post(delegations, headers=HEAD, json=course_grant).status_code == 403
        allowed = admin.post(delegations, headers=HEAD, json=course_grant)
        assert allowed.status_code == 201
        assert admin.post(delegations, headers=HEAD, json=department_grant).status_code == 201
        assert admin.get(delegations).json()['actors']
        by_course = coordinator.get(assignments).json()['items']
        by_department = employee.get(assignments).json()['items']
        assert {item['discipline_id'] for item in by_course} == {assignment['discipline_id']}
        assert {item['id'] for item in by_department} >= {assignment['id'], outside['id']}
        assert coordinator.post('/api/materials', headers=HEAD, json={**owned, 'assignment_id': outside['id']}).status_code == 403
        assert coordinator.delete(f'/api/materials/{row["id"]}?version=1', headers=HEAD).status_code == 200
        assert coordinator.get('/api/teaching').status_code == employee.get('/api/staff/requests').status_code == 403
        assert admin.delete(f'{delegations}/{allowed.json()["id"]}', headers=HEAD).status_code == 200
        assert coordinator.get(f'/api/materials/{row["id"]}').status_code == 404


def test_discussion_attachment_is_available_only_to_participants(accounts):
    student, colleague, other, staff = (accounts(role) for role in ('other', 'teacher', 'student', 'staff'))
    with client() as teacher:
        sign_in(teacher, 'zorin.demo', 'AtlasTeach!2026-Z')
        recipients = student.get('/api/direct/recipients?q=Зорин').json()['items']
        body = {'recipient_id': recipients[0]['id'], 'file': upload(b'Fictional document for teacher only.')}
        response = student.post('/api/direct/dialogs', headers=HEAD, json=body)
        assert response.status_code == 201, response.text
        path = f'/api/direct/dialogs/{response.json()["dialog_id"]}'
        message = teacher.get(path).json()['messages'][-1]
        assert message['file']['name'] == 'Конспект.txt'
        for participant in (teacher, student):
            assert participant.get(message['file']['url']).content == b'Fictional document for teacher only.'
        for outsider in (colleague, other, staff):
            assert outsider.get(message['file']['url']).status_code == 404
        assert teacher.post(path + '/messages', headers=HEAD, json={'message': 'Файл получен.'}).status_code == 201
        assert student.get(path).json()['messages'][-1]['body'] == 'Файл получен.'


def test_discipline_announcements_keep_group_audience(accounts):
    staff, student, other, teacher = (accounts(role) for role in ('staff', 'student', 'other', 'teacher'))
    _data, assignment = sample(teacher)
    meta = staff.get('/api/staff/announcements/groups').json()
    group = next(row for row in meta['items'] if row['name'] == 'ИТ-24-03')
    body = {'title': 'Объявление по учебной дисциплине', 'body': 'Проверяем отображение только для адресатов.',
            'discipline_id': assignment['discipline_id'], 'group_id': group['id'], 'audience': 'group'}
    response = staff.post('/api/staff/announcements', headers=HEAD, json=body)
    assert response.status_code == 201, response.text
    key = response.json()['id']
    filters = {'discipline': assignment['discipline_id']}
    assert key in {row['id'] for row in student.get('/api/announcements', params=filters).json()['items']}
    assert key not in {row['id'] for row in other.get('/api/announcements', params=filters).json()['items']}
    assert other.get(f'/api/announcements/{key}').status_code == 404
    assert teacher.post('/api/staff/announcements', headers=HEAD, json=body).status_code == 403
