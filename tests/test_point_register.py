"""Verify confirmed postings, correction history and the student read scope."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select

from app.db import SessionLocal, utc_now
from app.point_register_migration import upgrade_point_register
from app.workspace_db import GroupMember, OperationEvent, ScheduledClass
from test_academic_workspace import HEAD, body, orlov, roles
from test_assignment_workflow import current_score, student_work, work_options


REGISTER = '/api/learning/point-register'


@pytest.mark.parametrize('initial,revised', [(8, 3), (0, 4)])
def test_work_only_appears_after_confirmed_review(roles, initial, revised):
    teacher, student, other = (roles(role) for role in ('teacher', 'student', 'other'))
    load = orlov(teacher)
    amount = current_score(student, load['discipline']) or 0
    previous = body(student.get(REGISTER))['items']
    foreign = body(other.get(REGISTER))['items']
    assert teacher.get(REGISTER).status_code == 403
    assert body(student.get(REGISTER, params={'student_id': body(other.get('/api/me'))['id']}))['items'] == previous

    title = 'Лабораторная проверка ' + uuid4().hex[:8]
    root = f'/api/teaching/{load["id"]}/works'
    work = body(teacher.post(root, json=work_options(title, kind='lab', max_points=10), headers=HEAD), 201)
    work_path = f'{root}/{work["id"]}'
    assignment_id = student_work(student, title)['id']
    submitted = body(student.post(f'/api/learning/assignments/{assignment_id}/submit',
                                  json={'url': 'https://example.test/solution'}, headers=HEAD))
    submission_id = submitted['submission']['id']
    version = submitted['submission']['attempt_version']
    assert body(student.get(REGISTER))['items'] == previous
    reviewed = body(teacher.post(f'{work_path}/feedback/{submission_id}', headers=HEAD, json={
        'action': 'accept', 'score': initial, 'remarks': 'Проверка основной части.', 'submitted_version': version,
    }), 201)
    earned, = [row for row in body(student.get(REGISTER))['items'] if row['assignment_id'] == assignment_id]
    assert earned['title'] == title
    assert earned['kind'] == 'lab' and earned['max_points'] == 10
    assert earned['points'] == initial and earned['discipline_total'] == amount + initial
    assert earned['entry_type'] == ('award' if initial else 'result')
    assert earned['teacher'] == load['teacher'] and earned['note'] == reviewed['remarks']
    assert earned['day'] and earned['created_at']

    submission = next(row for row in body(teacher.get(work_path))['submissions'] if row['id'] == submission_id)
    reason = 'Пересмотрен результат проверки по уточнённым критериям.'
    correction_path = f'{work_path}/submissions/{submission_id}/score-corrections'
    body(teacher.post(correction_path, headers=HEAD,
                      json=dict(submitted_version=version, version=submission['version'], score=revised, reason=reason)), 201)
    entries = [row for row in body(student.get(REGISTER))['items'] if row['assignment_id'] == assignment_id]
    delta, original = entries
    assert original['id'] == earned['id'] and original['points'] == initial
    assert delta['entry_type'] == 'correction' and delta['teacher'] == load['teacher']
    assert delta['previous_points'] == initial and delta['corrected_points'] == revised
    assert delta['points'] == revised - initial and delta['note'] == reason
    assert all(row['discipline_total'] == amount + revised for row in entries)
    assert current_score(student, load['discipline']) == amount + revised
    assert body(other.get(REGISTER))['items'] == foreign


def test_manual_award_uses_class_metadata_and_history_is_append_only(roles):
    teacher, student, other, colleague = (roles(role) for role in ('teacher', 'student', 'other', 'colleague'))
    load = orlov(teacher)
    student_id = body(student.get('/api/me'))['id']
    foreign_id = body(other.get('/api/me'))['id']
    root = f'/api/teaching/{load["id"]}'
    history = f'{root}/points/{student_id}'
    grade = next(row['grade'] for row in body(teacher.get(root))['students'] if row['id'] == student_id)
    initial = grade['score'] or 0
    legacy, = [entry for entry in body(student.get(REGISTER))['items']
               if entry['subject'] == load['discipline'] and entry['entry_type'] == 'opening']
    assert legacy['day'] is None and legacy['points'] > 0

    title = 'Практикум ' + uuid4().hex[:8]
    with SessionLocal.begin() as db:
        source = db.scalar(select(ScheduledClass).where(ScheduledClass.load_id == load['id']).limit(1))
        starts = utc_now() - timedelta(days=1)
        meeting = ScheduledClass(load_id=source.load_id, group_id=source.group_id, teacher_id=source.teacher_id,
                                 room_id=source.room_id, starts_at=starts, ends_at=starts + timedelta(hours=1),
                                 kind='practice', title=title, series=uuid4().hex, status='active')
        db.add(meeting)
        db.flush()
        class_id = meeting.id
    payload = dict(student_id=student_id, points=6, version=grade['version'], reason='Задачи по теме практикума',
                   max_points=9, class_id=class_id)
    assert teacher.post(root + '/points', json={**payload, 'max_points': 5}, headers=HEAD).status_code == 422
    award_grade = body(teacher.post(root + '/points', json=payload, headers=HEAD), 201)
    assert award_grade['score'] == initial + 6
    awarded, = [row for row in body(teacher.get(history))['items'] if row['class_id'] == class_id]
    assert awarded['can_correct'] and awarded['title'] == title
    assert awarded['kind'] == 'practice' and awarded['max_points'] == 9
    target = history + f'/awards/{awarded["id"]}/corrections'
    reason = 'Исправлена запись результата практикума.'
    correction = dict(version=award_grade['version'], points=2, reason=reason)
    assert teacher.post(target, json=correction).status_code == 403
    assert student.post(target, json=correction, headers=HEAD).status_code == 403
    assert colleague.post(target, json=correction, headers=HEAD).status_code == 404
    assert teacher.post(target.replace(f'/points/{student_id}/', f'/points/{foreign_id}/'),
                        json=correction, headers=HEAD).status_code == 404
    assert teacher.post(target, json={**correction, 'points': 10}, headers=HEAD).status_code == 422
    assert teacher.post(target, json={**correction, 'reason': '  '}, headers=HEAD).status_code == 422
    opening_path = history + f'/awards/{legacy["id"].removeprefix("award-")}/corrections'
    assert teacher.post(opening_path, json=correction, headers=HEAD).status_code == 404
    key = {**HEAD, 'Idempotency-Key': str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: teacher.post(target, json=correction, headers=key), range(2)))
    assert sorted(response.status_code for response in replies) == [200, 201]
    assert replies[0].json() == replies[1].json()
    assert replies[0].json()['score'] == initial + 2
    assert teacher.post(target, json=correction, headers=HEAD).status_code == 409
    teacher_history = body(teacher.get(history))
    assert next(row for row in teacher_history['items'] if row['id'] == awarded['id'])['effective_points'] == 2
    delta, original = [row for row in body(student.get(REGISTER))['items'] if row['class_id'] == class_id]
    assert original['points'] == 6 and original['kind'] == 'practice' and original['teacher'] == load['teacher']
    assert delta['entry_type'] == 'correction' and delta['note'] == reason
    assert delta['previous_points'] == 6 and delta['corrected_points'] == 2 and delta['points'] == -4
    assert all(row['discipline_total'] == initial + 2 for row in (delta, original))
    assert all(row['class_id'] != class_id for row in body(other.get(REGISTER))['items'])
    with SessionLocal() as db:
        audits = db.scalars(select(OperationEvent).where(OperationEvent.action == 'points_corrected')).all()
        assert sum(reason in row.after and f'"award_id": {awarded["id"]}' in row.after for row in audits) == 1


def test_team_zero_result_follows_issued_review_and_award_mode(roles):
    teacher, lead, participant = (roles(role) for role in ('teacher', 'student', 'other'))
    load = orlov(teacher)
    lead_id = body(lead.get('/api/me'))['id']
    participant_id = body(participant.get('/api/me'))['id']
    with SessionLocal.begin() as db:
        peer = db.get(GroupMember, participant_id)
        original_group = peer.group_id, peer.subgroup_id
        peer.group_id, peer.subgroup_id = load['group_id'], None

    titles = {}
    try:
        for mode in ('all', 'lead'):
            title = 'Групповой проект ' + uuid4().hex[:8]
            titles[mode] = title
            root = f'/api/teaching/{load["id"]}/works'
            options = work_options(title, kind='group', max_points=12,
                                   recipient_ids=[lead_id, participant_id], team_lead_id=lead_id, award_mode=mode)
            work = body(teacher.post(root, json=options, headers=HEAD), 201)
            record = student_work(lead, title)
            sent = body(lead.post(f'/api/learning/assignments/{record["id"]}/submit',
                                  json={'url': 'https://example.test/team'}, headers=HEAD))
            submission = sent['submission']
            body(teacher.post(f'{root}/{work["id"]}/feedback/{submission["id"]}', headers=HEAD,
                              json={'action': 'accept', 'submitted_version': submission['attempt_version'], 'score': 0}), 201)
    finally:
        with SessionLocal.begin() as db:
            peer = db.get(GroupMember, participant_id)
            peer.group_id, peer.subgroup_id = original_group
    for actor, modes in [(lead, ('all', 'lead')), (participant, ('all',))]:
        rows = [row for row in body(actor.get(REGISTER))['items'] if row['title'] in titles.values()]
        assert {row['title'] for row in rows} == {titles[mode] for mode in modes}
        assert all(row['points'] == 0 and row['entry_type'] == 'result' for row in rows)


def test_point_register_migration_keeps_existing_postings():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE academic_work_feedback (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE academic_point_awards (id INTEGER PRIMARY KEY, points INTEGER NOT NULL)')
        connection.exec_driver_sql('INSERT INTO academic_point_awards VALUES (11, 7)')
        upgrade_point_register(connection)
        upgrade_point_register(connection)
        assert {column['name'] for column in inspect(connection).get_columns('academic_point_awards')} == {
            'id', 'points', 'title', 'kind', 'custom_kind', 'max_points', 'review_id',
        }
        assert connection.exec_driver_sql('SELECT * FROM academic_point_awards').one() == (11, 7, '', '', '', None, None)
    engine.dispose()
