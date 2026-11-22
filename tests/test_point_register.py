"""Verify confirmed postings, correction history and the student read scope."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select

from app.academic_points import award_points
from app.db import Grade, SessionLocal, utc_now
from app.point_register_migration import upgrade_point_register
from app.schedule_occurrences import campus_instant
from app.workspace import recorded
from app.workspace_db import AcademicTerm, GroupMember, GroupWork, OperationEvent, ScheduleChange, ScheduledClass, TeachingLoad
from test_academic_workspace import HEAD, body, journal_class, orlov, roles
from test_assignment_workflow import current_score, student_work, work_options
from test_contest_dataset import freeze, use_database


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
    class_id, _ = journal_class(load['id'])
    with SessionLocal.begin() as db:
        db.get(ScheduledClass, class_id).title = title
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


def test_semester_totals_follow_owned_ledger_across_years(tmp_path, monkeypatch, roles):
    freeze(monkeypatch, date(2026, 11, 22), '14:00')
    with use_database(tmp_path / 'point-periods.db', monkeypatch):
        student, teacher, other = (roles(role) for role in ('student', 'teacher', 'other'))
        load = orlov(teacher)
        root = f'/api/teaching/{load["id"]}'
        student_id = body(student.get('/api/me'))['id']
        teacher_id = body(teacher.get('/api/me'))['id']
        other_id = body(other.get('/api/me'))['id']
        class_id, _ = journal_class(load['id'])
        with SessionLocal.begin() as db:
            for academic_year, number, group_id, first, last in (
                (2025, 1, None, date(2025, 9, 1), date(2026, 1, 31)),
                (2025, 2, None, date(2026, 2, 1), date(2026, 6, 30)),
                (2026, 1, None, date(2026, 9, 1), date(2027, 1, 31)),
                (2026, 1, load['group_id'], date(2026, 9, 15), date(2027, 1, 25)),
                (2026, 3, db.get(GroupMember, other_id).group_id, date(2027, 7, 1), date(2027, 7, 5)),
            ):
                db.add(AcademicTerm(academic_year=academic_year, number=number, starts_on=first, ends_on=last,
                                    group_id=group_id, weekdays='01234', periods=[], source='Календарь теста'))
            primary = db.get(TeachingLoad, load['id'])
            secondary = db.scalar(select(TeachingLoad).where(TeachingLoad.group_id == primary.group_id,
                                                             TeachingLoad.id != primary.id).order_by(TeachingLoad.id))
            second_subject = secondary.discipline.title
            grades = {row.subject: row for row in db.scalars(select(Grade).where(Grade.student_id == student_id))}
            grades[primary.discipline.title].exam_date = date(2026, 12, 14)
            grades[second_subject].max_grade = 0

            def post(target, points, day, title, *, class_id=None, kind='practice'):
                grade = grades[target.discipline.title]
                award = award_points(db, student_id=student_id, discipline_id=target.discipline_id, points=points,
                                     source_kind='teacher', source_id=f'{target.id}:{grade.version}',
                                     actor_id=target.assignment.teacher.user_id, title=title, class_id=class_id, kind=kind)
                award.created_at = campus_instant(day, '14:00')
                return award

            meeting = db.get(ScheduledClass, class_id)
            previous_day = date(2026, 6, 26)
            prior = post(primary, 8, date(2026, 7, 2), 'Практикум весеннего семестра', class_id=class_id)
            db.flush()
            prior_id = prior.id
            meeting.previous_day = previous_day
            move = ScheduleChange(author_id=teacher_id, event_id=class_id, state='published', action='update', payload='{}',
                                  created_at=utc_now(), updated_at=utc_now())
            db.add(move)
            db.flush()
            recorded(db, primary.assignment.teacher.user, 'schedule', move.id, 'publish',
                     after={'effects': {'previous': {'id': class_id, 'day': str(previous_day)}}})
            post(primary, 4, date(2026, 10, 8), 'Задачи по графам')
            post(primary, 6, date(2026, 11, 2), 'Мини-проект', kind='project')
            post(primary, 2, date(2026, 9, 10), 'До начала семестра группы')
            post(primary, 3, date(2025, 11, 12), 'Работа прошлого учебного года')
            post(secondary, 7, date(2026, 10, 8), 'Работа по второй дисциплине')

        records = body(student.get(REGISTER))
        assert records['default_period'] == '2026-1'
        assert {period['id'] for period in records['periods']} == {'2026-1', '2025-2', '2025-1', 'unassigned'}
        assert body(student.get(REGISTER, params={'student_id': other_id})) == records
        assert teacher.get(REGISTER).status_code == 403
        assert all(row['id'] != f'award-{prior_id}' for row in body(other.get(REGISTER))['items'])
        historical = [row for row in records['items'] if row['period'] == 'unassigned']
        assert any(row['entry_type'] == 'opening' for row in historical)
        assert any(row['title'] == 'До начала семестра группы' for row in historical)

        def totals(data, period):
            return {row['subject']: row for row in next(p for p in data['periods'] if p['id'] == period)['disciplines']}

        subject = load['discipline']
        current = totals(records, '2026-1')
        assert len(current) >= 3 and any(row['earned_points'] == 0 for row in current.values())
        assert current[subject]['earned_points'] == current[subject]['percent'] == 10
        assert current[subject]['max_points'] == 100
        assert current[second_subject]['earned_points'] == 7
        assert current[second_subject]['max_points'] is current[second_subject]['percent'] is None
        assert totals(records, '2025-1')[subject]['earned_points'] == 3
        assert totals(records, '2025-2')[subject]['earned_points'] == 8

        grade = next(row['grade'] for row in body(teacher.get(root))['students'] if row['id'] == student_id)
        payload = dict(student_id=student_id, points=5, version=grade['version'], reason='Новая лабораторная работа', kind='lab')
        assert teacher.post(root + '/points', json={**payload, 'points': -5}, headers=HEAD).status_code == 422
        posted = body(teacher.post(root + '/points', json=payload, headers=HEAD), 201)
        correction = f'{root}/points/{student_id}/awards/{prior_id}/corrections'
        body(teacher.post(correction, json=dict(points=5, version=posted['version'], reason='Исправлен балл за практикум'),
                          headers=HEAD), 201)
        records = body(student.get(REGISTER))
        assert totals(records, '2026-1')[subject]['earned_points'] == 15
        spring = totals(records, '2025-2')[subject]
        assert spring['earned_points'] == 5 and spring['max_points'] is None
        assert spring['timeline'][-1] == {'day': '2026-11-22', 'change': -3, 'total': 5}
        assert spring['breakdown'] == [{'label': 'Практическая работа', 'points': 5}]

        title = 'Доработка проекта за весну'
        work = body(teacher.post(root + '/works', json=work_options(title, kind='project', max_points=10), headers=HEAD), 201)
        with SessionLocal.begin() as db:
            db.get(GroupWork, work['id']).publish_at = campus_instant(date(2026, 6, 15), '14:00')
        deadline = student_work(student, title)['id']
        submission = body(student.post(f'/api/learning/assignments/{deadline}/submit', headers=HEAD,
                                       json={'url': 'https://example.test/solution'}))['submission']
        work_path = f'{root}/works/{work["id"]}'
        attempt = submission['attempt_version']
        body(teacher.post(f'{work_path}/feedback/{submission["id"]}', headers=HEAD, json={
            'action': 'accept', 'score': 0, 'submitted_version': attempt,
        }), 201)
        reviewed = body(teacher.get(work_path))['submissions'][0]
        body(teacher.post(f'{work_path}/submissions/{submission["id"]}/score-corrections', headers=HEAD, json={
            'version': reviewed['version'], 'submitted_version': attempt, 'score': 3, 'reason': 'Уточнён балл проекта',
        }), 201)
        records = body(student.get(REGISTER))
        assert totals(records, '2026-1')[subject]['earned_points'] == 15
        assert totals(records, '2025-2')[subject]['earned_points'] == 8
        assert sorted((row['period'], row['points']) for row in records['items'] if row['assignment_id'] == deadline) == [
            ('2025-2', 0), ('2025-2', 3),
        ]
        for period in records['periods']:
            for row in period['disciplines']:
                ledger = [item for item in records['items'] if item['period'] == period['id'] and item['discipline_key'] == row['key']]
                assert len({item['id'] for item in ledger}) == len(ledger)
                assert row['earned_points'] == sum(item['points'] for item in ledger)
                assert row['earned_points'] == sum(item['points'] for item in row['breakdown'])
                assert all(item['points'] >= 0 for item in ledger if item['entry_type'] != 'correction')


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
