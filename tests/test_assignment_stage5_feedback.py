"""Exercise private teaching files, official marks and audit on an isolated database."""
from base64 import b64encode
from uuid import uuid4

from sqlalchemy import select

from app.db import Notification, SessionLocal
from app.workspace_db import OperationEvent
from test_academic_workspace import HEAD, body, orlov, roles
from test_assignment_workflow import current_score, student_work, work_options


def upload(name, contents):
    return {'name': name, 'content': b64encode(contents).decode()}


def test_source_review_and_score_correction_preserve_previous_records(roles):
    teacher, student, other, colleague = (roles(role) for role in ('teacher', 'student', 'other', 'colleague'))
    load = orlov(teacher)
    root = f'/api/teaching/{load["id"]}/works'
    student_id = body(student.get('/api/me'))['id']
    title = 'Проверка файлов и баллов ' + uuid4().hex[:7]
    payload = b'Fictional course file\n' * 4300
    options = work_options(title, state='draft', recipient_ids=[student_id], methods=['files'], max_points=10,
                           source_files=[upload('исходник.txt', payload)])
    draft = body(teacher.post(root, json=options, headers=HEAD), 201)
    work = f'{root}/{draft["id"]}'
    source, = draft['source_files']
    assert teacher.get(f'{work}/source-files/{source["id"]}').content == payload
    assert colleague.get(f'{work}/source-files/{source["id"]}').status_code == 404
    assert all(row['title'] != title for row in body(student.get('/api/learning/assignments'))['items'])
    published = body(teacher.patch(work, json={'version': draft['version'], 'state': 'published'}, headers=HEAD))
    deadline = f'/api/learning/assignments/{student_work(student, title)["id"]}'
    source_path = f'{deadline}/source-files/{source["id"]}'
    assert student.get(source_path).content == payload
    assert other.get(source_path).status_code == 404
    assert teacher.patch(work, json={'version': published['version'], 'remove_source_ids': [2147483647]},
                         headers=HEAD).status_code == 404
    assert body(teacher.get(work))['version'] == published['version']
    body(teacher.patch(work, json={'version': published['version'], 'remove_source_ids': [source['id']],
                                  'source_files': [upload('условия.txt', b'New source material')]}, headers=HEAD))
    assert student.get(source_path).status_code == 404
    replacement, = body(student.get(deadline))['source_files']
    assert student.get(f'{deadline}/source-files/{replacement["id"]}').content == b'New source material'

    base_score = current_score(student, load['discipline'])
    attempt = body(student.post(deadline+'/submit', json={'files': [upload('ответ.txt', b'Testing graph')]}, headers=HEAD))
    submission_id = attempt['submission']['id']
    version = attempt['submission']['attempt_version']
    review = f'{work}/feedback/{submission_id}'
    invalid_file = {'action': 'revise', 'submitted_version': version, 'remarks': 'Укажите граничный случай.',
                    'files': [upload('unsafe.html', b'Attachment format outside the allowlist')]}
    assert teacher.post(review, json=invalid_file, headers=HEAD).status_code == 422
    assert body(student.get(deadline))['status'] == 'submitted'
    revision = body(teacher.post(review, json={**invalid_file, 'files': [upload('разбор.txt', payload)]}, headers=HEAD), 201)
    feedback_file, = revision['files']
    feedback_path = f'{deadline}/feedback-files/{feedback_file["id"]}'
    response = student.get(feedback_path)
    assert response.content == payload
    assert response.headers['Content-Type'] == 'application/octet-stream'
    assert response.headers['Content-Disposition'].startswith('attachment;')
    assert other.get(feedback_path).status_code == 404
    teacher_feedback_path = f'{work}/submissions/{submission_id}/feedback-files/{feedback_file["id"]}'
    assert teacher.get(teacher_feedback_path).content == payload
    assert colleague.get(teacher_feedback_path).status_code == 404
    fixed = body(student.post(deadline+'/submit', json={'files': [upload('ответ-2.txt', b'Edge case included')]}, headers=HEAD))
    version = fixed['submission']['attempt_version']
    assert fixed['attempts'][1]['feedback'][0]['files'] == revision['files']
    body(teacher.post(review, json={'action': 'accept', 'submitted_version': version}, headers=HEAD), 201)
    assert current_score(student, load['discipline']) == base_score
    assert body(student.get(deadline))['score'] is None

    grade = {'action': 'grade', 'submitted_version': version, 'score': 8}
    body(teacher.post(review, json=grade, headers=HEAD), 201)
    assert current_score(student, load['discipline']) == base_score + 8
    assert teacher.post(review, json=grade, headers=HEAD).status_code == 409
    body(teacher.patch(work, json={'version': body(teacher.get(work))['version'], 'state': 'archived'}, headers=HEAD))
    submission, = body(teacher.get(work))['submissions']
    assert submission['score'] == 8
    correction_path = f'{work}/submissions/{submission_id}/score-corrections'
    correction = {'submitted_version': version, 'version': submission['version'], 'score': 5,
                  'reason': 'Исправлено ошибочное начисление за один критерий.'}
    assert teacher.post(correction_path, json=correction).status_code == 403
    assert student.post(correction_path, json=correction, headers=HEAD).status_code == 403
    assert colleague.post(correction_path, json=correction, headers=HEAD).status_code == 404
    assert teacher.post(correction_path, json={**correction, 'reason': ' '}, headers=HEAD).status_code == 422
    key = {**HEAD, 'Idempotency-Key': uuid4().hex}
    corrected = body(teacher.post(correction_path, json=correction, headers=key), 201)
    assert body(teacher.post(correction_path, json=correction, headers=key)) == corrected
    assert teacher.post(correction_path, json=correction, headers=HEAD).status_code == 409
    assert corrected['previous_score'] == 8 and corrected['score'] == 5
    assert current_score(student, load['discipline']) == base_score + 5
    archived = body(student.get(deadline))
    assert archived['state'] == 'archived' and archived['score'] == 5 and len(archived['attempts']) == 2
    assert {entry['action']: entry['score'] for entry in archived['feedback']}['grade'] == 8
    assert student.get(feedback_path).content == payload

    results = next(row for row in body(student.get('/api/learning/progress'))['items'] if row['subject'] == load['discipline'])
    award, = [row for row in results['awards'] if row['source_id'] == str(draft['id']) and row['source_kind'] == 'assignment']
    changed, = [row for row in results['corrections'] if row['source_id'] == str(draft['id'])]
    assert award['points'] == 8 and changed['points'] == -3
    assert any(row['title'] == title and row['score'] == 5 and row['graded'] for row in results['work'])
    with SessionLocal() as db:
        notices = db.scalars(select(Notification).where(Notification.student_id == student_id,
                                Notification.event_key.like(f'work-review:{corrected["id"]}:%'))).all()
        audits = db.scalars(select(OperationEvent).where(OperationEvent.action == 'work_score_corrected')).all()
        assert len(notices) == 1
        assert any(correction['reason'] in entry.after and '"score": 8' in entry.before for entry in audits)
