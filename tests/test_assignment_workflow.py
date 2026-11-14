"""Exercise the work lifecycle on isolated student and teacher fixtures."""
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update

from app.db import Deadline, Notification, SessionLocal, utc_now
from app.workspace_db import GroupMember
from test_academic_workspace import HEAD, body, orlov, roles


def work_options(title, **overrides):
    return {'title': title, 'instructions': 'Приложите решение и объясните ход проверки результата.',
            'due_at': (utc_now() + timedelta(days=5)).isoformat(), **overrides}


def student_work(student, title):
    return next(row for row in body(student.get('/api/learning/assignments'))['items'] if row['title'] == title)


def current_score(student, subject):
    return next(row['score'] for row in body(student.get('/api/grades'))['items'] if row['subject'] == subject)


def test_draft_publish_revision_files_award_and_archive(roles):
    teacher, student, other, colleague = (roles(r) for r in ('teacher', 'student', 'other', 'colleague'))
    load = orlov(teacher)
    path = f'/api/teaching/{load["id"]}/works'
    prefix = '/api/learning/assignments'
    title = 'Проверка цепочки сдачи ' + uuid4().hex[:7]
    student_id = body(student.get('/api/me'))['id']
    draft = body(teacher.post(path, json={'title': title, 'state': 'draft'}, headers=HEAD), 201)
    work = f'{path}/{draft["id"]}'
    assert body(teacher.get(work))['submissions'] == []
    assert all(row['title'] != title for row in body(student.get(prefix))['items'])
    body(teacher.patch(work, json=work_options(title, version=draft['version'], state='published',
                                                          recipient_ids=[student_id],
                                                          methods=['text', 'files', 'complete'],
                                                          formats=['txt'], max_points=14, max_attempts=2,
                                                          allow_late=False), headers=HEAD))
    assert colleague.get(work).status_code == 404
    lesson = student_work(student, title)
    deadline = f'{prefix}/{lesson["id"]}'
    assert other.get(deadline).status_code == 404
    assert all(row['title'] != title for row in body(other.get(prefix))['items'])
    started = body(student.post(deadline+'/start', json={'version': 0}, headers=HEAD))
    assert started['status'] == 'in_progress'
    contents = b'ASCII lab notes\n' * 8400
    payload = {'text':'Разбор первого варианта решения.', 'version': started['submission']['version'],
               'files':[{'name':'решение.txt','content':b64encode(contents).decode()}]}
    key = {**HEAD, 'Idempotency-Key':uuid4().hex}
    sent = body(student.post(deadline+'/submit', json=payload, headers=key))
    assert body(student.post(deadline+'/submit', json=payload, headers=key)) == sent
    assert sent['status'] == 'submitted'
    file_id = sent['attempts'][0]['files'][0]['id']
    submission_id = sent['submission']['id']
    student_file = deadline + f'/files/{file_id}'
    teacher_file = work + f'/submissions/{submission_id}/files/{file_id}'
    assert student.get(student_file).content == contents
    assert teacher.get(teacher_file).content == contents
    assert other.get(student_file).status_code == colleague.get(teacher_file).status_code == 404
    assert {word.strip() for word in student.get(student_file).headers['Cache-Control'].split(',')} == {'private', 'no-store'}

    review = f'{work}/feedback/{submission_id}'
    version = sent['submission']['attempt_version']
    body(teacher.post(review, json={'action':'review', 'submitted_version':version}, headers=HEAD), 201)
    assert student.post(deadline+'/withdraw', headers=HEAD).status_code == 409
    extension = utc_now() + timedelta(days=7)
    revision = {'action':'revise','submitted_version':version,'comment':'Добавьте разбор пограничного случая.',
                'extended_until':extension.isoformat()}
    body(teacher.post(review, json=revision, headers=HEAD), 201)
    returned = body(student.get(deadline))
    assert returned['status'] == 'revision_required' and returned['due_at'] == extension.isoformat()
    fixed = body(student.post(deadline+'/submit', json={'completed': True, 'version':returned['submission']['version']},
                              headers=HEAD))
    assert fixed['status'] == 'resubmitted'
    assert [x['number'] for x in fixed['attempts']] == [2, 1]
    assert fixed['attempts'][1]['text'] == payload['text']
    assert fixed['attempts'][1]['feedback'][0]['comment'] == revision['comment']
    assert student.get(student_file).content == contents

    balance = current_score(student, load['discipline'])
    acceptance = {'action':'accept','submitted_version':fixed['submission']['attempt_version'],'score':8}
    h = {**HEAD, 'Idempotency-Key':uuid4().hex}
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _:teacher.post(review, json=acceptance, headers=h), range(2)))
    assert sorted(r.status_code for r in replies) == [200,201]
    assert replies[0].json() == replies[1].json()
    assert teacher.post(review, json=acceptance, headers=HEAD).status_code == 409
    assert current_score(student, load['discipline']) == balance + 8
    assert body(student.get(deadline))['status'] == 'accepted'
    with SessionLocal() as db:
        notices = db.scalars(select(Notification).where(Notification.student_id == student_id,
                                                        Notification.target == f'/app/assignments?id={lesson["id"]}')).all()
        assert sum(row.title == 'Начислены баллы за работу' for row in notices) == 1

    body(teacher.post(review, json={'action':'complete','submitted_version':acceptance['submitted_version']},
                      headers=HEAD), 201)
    archived = body(teacher.patch(work, json={'state':'archived','version':body(teacher.get(work))['version']}, headers=HEAD))
    assert archived['state'] == 'archived'
    details = body(student.get(deadline))
    assert details['state'] == 'archived' and details['status'] == 'completed' and not details['can_submit']
    assert student.post(deadline+'/submit', json={'completed':True}, headers=HEAD).status_code == 409
    assert student.get(student_file).content == contents


def test_team_submission_roles_and_recipient_awards(roles):
    teacher, lead, partner = (roles(r) for r in ('teacher', 'student', 'other'))
    load = orlov(teacher)
    path = f'/api/teaching/{load["id"]}/works'
    lead_id = body(lead.get('/api/me'))['id']
    partner_id = body(partner.get('/api/me'))['id']
    title = 'Совместная работа ' + uuid4().hex[:7]
    with SessionLocal() as db:
        original_group = db.get(GroupMember, partner_id).group_id
        db.execute(update(GroupMember).where(GroupMember.student_id == partner_id).values(group_id=load['group_id']))
        db.commit()
    try:
        record = body(teacher.post(path, json=work_options(title, kind='group', team_lead_id=lead_id,
                                                          methods=['url'], recipient_ids=[lead_id,partner_id],
                                                          max_points=15), headers=HEAD), 201)
        lead_work = student_work(lead, title)
        other_work = student_work(partner, title)
        lead_path = f'/api/learning/assignments/{lead_work["id"]}'
        other_path = f'/api/learning/assignments/{other_work["id"]}'
        submission = {'url':'https://example.test/shared-work'}
        assert partner.post(other_path+'/submit', json=submission, headers=HEAD).status_code == 403
        sent = body(lead.post(lead_path+'/submit', json=submission, headers=HEAD))
        assert body(partner.get(other_path))['attempts'][0]['url'] == submission['url']
        review = f'{path}/{record["id"]}/feedback/{sent["submission"]["id"]}'
        body(teacher.post(review, json={'action':'accept','submitted_version':1,'score':4}, headers=HEAD), 201)
        assert body(partner.get(other_path))['status'] == 'accepted'
        assert current_score(partner, load['discipline']) == 4
    finally:
        with SessionLocal() as db:
            db.execute(update(GroupMember).where(GroupMember.student_id == partner_id).values(group_id=original_group))
            db.commit()
    assert body(partner.get(other_path))['attempts'] == []


def test_assignment_offset_keeps_recent_work_and_direct_link_available(roles):
    student = roles('student')
    student_id = body(student.get('/api/me'))['id']
    with SessionLocal() as db:
        rows = [Deadline(student_id=student_id, subject='Учебная дисциплина', title=f'Архивная работа {n}',
                         due_date=utc_now().date()-timedelta(days=400-n)) for n in range(202)]
        db.add_all(rows)
        db.flush()
        keys = [row.id for row in rows]
        db.commit()
    try:
        first = body(student.get('/api/learning/assignments'))
        second = body(student.get('/api/learning/assignments?offset=200'))
        assert first['more'] and not second['more']
        assert {r['id'] for r in first['items']}.isdisjoint({r['id'] for r in second['items']})
        assert keys[0] not in {r['id'] for r in first['items']}
        assert body(student.get(f'/api/learning/assignments/{keys[0]}'))['id'] == keys[0]
    finally:
        with SessionLocal() as db:
            db.execute(delete(Deadline).where(Deadline.id.in_(keys)))
            db.commit()
