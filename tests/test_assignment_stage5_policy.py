"""Stage 5 recipient scope, independent deadlines and immutable attempts."""
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, inspect, select

from app import assignment_workflow, learning, notifications
from app.assignment_migration import upgrade_assignment_deadlines
from app.db import CAMPUS_TZ, Notification, SessionLocal, utc_now
from app.workspace_db import AcademicSubgroup, GroupMember
from test_academic_workspace import HEAD, body, orlov, roles
from test_assignment_workflow import student_work, work_options


def iso_utc(value):
    return value.astimezone(timezone.utc).isoformat()


def test_subgroup_delivery_is_scoped_to_published_recipients(roles):
    teacher, student, other = (roles(role) for role in ('teacher', 'student', 'other'))
    load = orlov(teacher)
    load_path = f"/api/teaching/{load['id']}"
    student_id = body(student.get('/api/me'))['id']
    other_id = body(other.get('/api/me'))['id']
    title = f'Задание для подгруппы {uuid4().hex[:7]}'

    with SessionLocal() as db:
        own = db.get(GroupMember, student_id)
        partner = db.get(GroupMember, other_id)
        original = {row.student_id: (row.group_id, row.subgroup_id) for row in (own, partner)}
        assert original[other_id][0] != load['group_id']
        inside = AcademicSubgroup(group_id=load['group_id'], code=uuid4().hex[:8], capacity=10)
        outside = AcademicSubgroup(group_id=original[other_id][0], code=uuid4().hex[:8], capacity=10)
        db.add_all([inside, outside])
        db.flush()
        own.subgroup_id = inside.id
        partner.group_id, partner.subgroup_id = load['group_id'], None
        db.commit()

    try:
        detail = body(teacher.get(load_path))
        assert inside.id in {row['id'] for row in detail['subgroups']}
        assert outside.id not in {row['id'] for row in detail['subgroups']}
        assert next(row for row in detail['students'] if row['id'] == student_id)['subgroup_id'] == inside.id
        works = load_path + '/works'
        assert teacher.post(works, json=work_options(title, subgroup_id=outside.id), headers=HEAD).status_code == 404
        assert teacher.post(works, json=work_options(title, subgroup_id=inside.id, recipient_ids=[student_id]),
                            headers=HEAD).status_code == 422
        created = body(teacher.post(works, json=work_options(title, subgroup_id=inside.id), headers=HEAD), 201)
        path = f"{works}/{created['id']}"
        record = student_work(student, title)
        item = f"/api/learning/assignments/{record['id']}"
        assert record['discipline_id'] == load['discipline_id']
        assert record['group'] == load['group'] and record['teacher'] == load['teacher']
        assert other.get(item).status_code == 404
        assert other.post(item + '/submit', json={'url': 'https://example.test/result'}, headers=HEAD).status_code == 404

        # A subsequent move into the subgroup does not add a recipient to an issued work.
        with SessionLocal() as db:
            db.get(GroupMember, other_id).subgroup_id = inside.id
            db.commit()
        edited = body(teacher.patch(path, json={'version': created['version'], 'description': 'Новые условия'},
                                    headers=HEAD))
        recipients = body(teacher.get(path))['recipients']
        assert [row['id'] for row in recipients] == [student_id]
        assert teacher.patch(f'{path}/recipients/{other_id}', headers=HEAD, json={
            'version': edited['version'], 'extended_until': (utc_now() + timedelta(days=8)).isoformat(),
        }).status_code == 404
        assert title not in [row['title'] for row in body(other.get('/api/learning/assignments'))['items']]
        assert student.patch(path, json={'version': edited['version'], 'state': 'archived'}, headers=HEAD).status_code == 403
        body(teacher.patch(path, json={'version': edited['version'], 'state': 'archived'}, headers=HEAD))
    finally:
        with SessionLocal() as db:
            for student_key, (group, subgroup) in original.items():
                member = db.get(GroupMember, student_key)
                member.group_id, member.subgroup_id = group, subgroup
            db.commit()


def test_deadline_precedence_revision_and_late_intake(roles, monkeypatch):
    from app import teaching

    teacher, student = (roles(role) for role in ('teacher', 'student'))
    load = orlov(teacher)
    student_id = body(student.get('/api/me'))['id']
    title = f'Персональный срок {uuid4().hex[:7]}'
    today = utc_now().astimezone(CAMPUS_TZ).date()
    individual = datetime.combine(today + timedelta(days=2), time(0, 5), CAMPUS_TZ)
    general = individual + timedelta(days=5)
    works = f"/api/teaching/{load['id']}/works"
    work = body(teacher.post(works, headers=HEAD, json=work_options(
        title, due_at=general.isoformat(), recipient_ids=[student_id], methods=['url'], allow_late=False,
    )), 201)
    path = f"{works}/{work['id']}"
    deadline_id = student_work(student, title)['id']
    item = f'/api/learning/assignments/{deadline_id}'
    recipient = f'{path}/recipients/{student_id}'
    changed = body(teacher.patch(recipient, json={'version': work['version'], 'individual_due_at': individual.isoformat()},
                                 headers=HEAD))
    detail = body(student.get(item))
    assert detail['general_due_at'] == iso_utc(general)
    assert detail['individual_due_at'] == detail['due_at'] == iso_utc(individual)
    assert detail['due_date'] == str(individual.date()) and detail['submission_window'] == 'open'
    schedule = body(student.get(f'/api/schedule?week={individual.date()}'))
    assert any(marker['id'] == deadline_id and marker['time'] == '00:05'
               for day in schedule['days'] if day['date'] == str(individual.date()) for marker in day['markers'])

    clock = individual.astimezone(timezone.utc) + timedelta(seconds=1)
    for module in (assignment_workflow, learning, notifications, teaching):
        monkeypatch.setattr(module, 'utc_now', lambda: clock)
    over = body(student.get(item))
    assert over['deadline_passed'] and over['submission_window'] == 'closed'
    assert over['status'] == 'not_started' and not over['can_submit']
    for _ in range(2):
        body(student.post('/api/notifications/deadline-reminders', headers=HEAD))
    result = {'url': 'https://example.test/first-version', 'version': 0}
    assert student.post(item + '/submit', json=result, headers=HEAD).status_code == 409

    extension = individual + timedelta(days=4)
    extended = body(teacher.patch(recipient, json={'version': changed['version'], 'extended_until': extension.isoformat()},
                                  headers=HEAD))
    assert extended['version'] == changed['version'] + 1
    initial = body(student.get(item))
    assert initial['individual_due_at'] == iso_utc(individual)
    assert initial['extended_until'] == initial['due_at'] == iso_utc(extension)
    assert initial['submission_window'] == 'open'
    sent = body(student.post(item + '/submit', json=result, headers=HEAD))
    assert sent['status'] == 'submitted' and sent['attempts'][0]['late'] is False
    revision = individual + timedelta(days=1)
    review = f"{path}/feedback/{sent['submission']['id']}"
    body(teacher.post(review, headers=HEAD, json={
        'action': 'revise', 'submitted_version': sent['submission']['attempt_version'], 'comment': 'Добавьте расчёт.',
        'extended_until': revision.isoformat(),
    }), 201)
    returned = body(student.get(item))
    assert returned['status'] == 'revision_required'
    assert returned['revision_due_at'] == returned['due_at'] == iso_utc(revision)
    assert returned['extended_until'] == iso_utc(extension)

    clock = revision.astimezone(timezone.utc) + timedelta(seconds=1)
    response = {'url': 'https://example.test/revised-version', 'version': returned['submission']['version']}
    assert student.post(item + '/submit', json=response, headers=HEAD).status_code == 409
    version = body(teacher.get(path))['version']
    late = body(teacher.patch(path, headers=HEAD, json={'allow_late': True, 'version': version}))
    details = body(student.get(item))
    assert details['deadline_passed'] and details['submission_window'] == 'late' and details['can_submit']
    sent_again = body(student.post(item + '/submit', json=response, headers=HEAD))
    assert sent_again['status'] == 'resubmitted'
    assert [(entry['url'], entry['late']) for entry in sent_again['attempts']] == [
        (response['url'], True), (result['url'], False),
    ]
    assert sent_again['attempts'][1]['feedback'][0]['comment'] == 'Добавьте расчёт.'
    body(teacher.patch(path, headers=HEAD, json={'version': late['version'], 'state': 'archived'}))
    with SessionLocal() as db:
        target = f'/app/assignments?id={deadline_id}'
        notices = db.scalars(select(Notification).where(Notification.student_id == student_id,
                                                        Notification.target == target)).all()
        assert len([row for row in notices if row.title == 'Срок сдачи истёк']) == 1
        assert len([row for row in notices if row.title == 'Индивидуальный срок сдачи изменён']) == 1
        assert len([row for row in notices if row.title == 'Срок сдачи продлён']) == 1


def test_file_only_submit_is_atomic_through_retry_and_closing(roles):
    teacher, student, colleague = (roles(role) for role in ('teacher', 'student', 'colleague'))
    student_id = body(student.get('/api/me'))['id']
    teacher_id = body(teacher.get('/api/me'))['id']
    title = f'Отправка двух файлов {uuid4().hex[:7]}'
    works = f"/api/teaching/{orlov(teacher)['id']}/works"
    options = work_options(title, methods=['files'], required_methods=['files'], formats=['txt'],
                           min_files=2, max_files=2, recipient_ids=[student_id])
    work = body(teacher.post(works, headers=HEAD, json=options), 201)
    path = f"{works}/{work['id']}"
    deadline_id = student_work(student, title)['id']
    item = f'/api/learning/assignments/{deadline_id}'
    assert body(student.get(item))['required_methods'] == ['files']
    no_change = body(teacher.patch(path, headers=HEAD, json={'title': title, 'version': work['version']}))
    key = {**HEAD, 'Idempotency-Key': uuid4().hex}
    file_a = {'name': 'расчёты.txt', 'content': b64encode(b'result one').decode()}
    file_b = {'name': 'описание.txt', 'content': b64encode(b'result two').decode()}
    for payload in ({}, {'files': [file_a]}, {'files': [file_a, file_b, file_b]},
                    {'files': [file_a, {**file_b, 'content': '%%%%'}]},
                    {'files': [file_a, file_b], 'text': 'Текст для другой формы.'}):
        assert student.post(item + '/submit', headers=key, json={**payload, 'version': 0}).status_code == 422
    assert body(student.get(item))['attempts'] == []
    payload = {'files': [file_a, file_b], 'version': 0}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: student.post(item + '/submit', headers=key, json=payload), range(2)))
    assert all(response.status_code == 200 for response in responses)
    sent = responses[0].json()
    assert sent == responses[1].json()
    assert len(sent['attempts']) == 1
    files = sent['attempts'][0]['files']
    assert [entry['name'] for entry in files] == ['расчёты.txt', 'описание.txt']
    assert student.get(f"{item}/files/{files[1]['id']}").content == b'result two'
    assert student.post(item + '/submit', headers=HEAD, json=payload).status_code == 409

    closed = body(teacher.patch(path, headers=HEAD, json={'state': 'closed', 'version': no_change['version']}))
    assert closed['state'] == 'closed'
    submitted = body(student.get(item))
    assert submitted['submission_window'] == 'closed' and not submitted['deadline_passed']
    assert not submitted['can_withdraw']
    assert body(student.post(item + '/submit', headers=key, json=payload)) == sent
    review = f"{path}/feedback/{sent['submission']['id']}"
    version = sent['submission']['attempt_version']
    assert colleague.post(review, headers=HEAD, json={'action': 'accept', 'submitted_version': version}).status_code == 404
    assert teacher.post(review, headers=HEAD, json={'action': 'revise', 'submitted_version': version,
                                                   'comment': 'Запрос исправлений.'}).status_code == 409
    body(teacher.post(review, headers=HEAD, json={'action': 'accept', 'submitted_version': version}), 201)
    body(teacher.post(review, headers=HEAD, json={'action': 'complete', 'submitted_version': version}), 201)
    archived = body(teacher.patch(path, headers=HEAD, json={'state': 'archived', 'version': closed['version']}))
    assert archived['state'] == 'archived'
    assert body(student.get(item))['status'] == 'completed'

    with SessionLocal() as db:
        targets = db.scalars(select(Notification).where(Notification.target.in_(
            (f'/app/assignments?id={deadline_id}', f'/app/teaching/{orlov(teacher)["id"]}/works/{work["id"]}')
        ))).all()
        assert sum(row.title == 'Работа успешно отправлена' and row.student_id == student_id for row in targets) == 1
        assert sum(row.title == 'Работа отправлена на проверку' and row.student_id == teacher_id for row in targets) == 1
        assert not any(row.title == 'Условия задания изменились' for row in targets)


def test_deadlines_upgrade_keeps_legacy_extensions():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE academic_work_deliveries (deadline_id INTEGER, extended_until DATETIME)')
        connection.exec_driver_sql("INSERT INTO academic_work_deliveries VALUES (13, '2030-11-17 17:00:00')")
        upgrade_assignment_deadlines(connection)
        upgrade_assignment_deadlines(connection)
        columns = {column['name'] for column in inspect(connection).get_columns('academic_work_deliveries')}
        assert columns == {'deadline_id', 'extended_until', 'individual_due_at', 'revision_due_at'}
        assert connection.exec_driver_sql('SELECT * FROM academic_work_deliveries').one() == (
            13, '2030-11-17 17:00:00', None, None,
        )
    engine.dispose()


def test_elapsed_publication_is_delivered_even_when_teacher_closes_before_next_visit(roles, monkeypatch):
    from app import teaching

    teacher, student = (roles(role) for role in ('teacher', 'student'))
    student_id = body(student.get('/api/me'))['id']
    title = f'Отложенная публикация {uuid4().hex[:7]}'
    works = f"/api/teaching/{orlov(teacher)['id']}/works"
    publishing = utc_now() + timedelta(hours=1)
    work = body(teacher.post(works, headers=HEAD, json=work_options(
        title, state='scheduled', publish_at=publishing.isoformat(), recipient_ids=[student_id],
    )), 201)
    assert title not in [row['title'] for row in body(student.get('/api/learning/assignments'))['items']]
    clock = publishing + timedelta(seconds=1)
    for module in (assignment_workflow, notifications, teaching):
        monkeypatch.setattr(module, 'utc_now', lambda: clock)
    path = f"{works}/{work['id']}"
    assert body(teacher.get(path))['state'] == 'published'
    closed = body(teacher.patch(path, headers=HEAD, json={'version': work['version'], 'state': 'closed'}))
    record = student_work(student, title)
    assert record['state'] == 'closed' and record['submission_window'] == 'closed'
    for _ in range(2):
        body(student.post('/api/notifications/deadline-reminders', headers=HEAD))
    target = f"/app/assignments?id={record['id']}"
    with SessionLocal() as db:
        rows = db.scalars(select(Notification).where(Notification.student_id == student_id,
                                                      Notification.target == target)).all()
        assert [row.title for row in sorted(rows, key=lambda row: row.id)] == [
            'Опубликовано учебное задание', 'Приём работ завершён',
        ]
    body(teacher.patch(path, headers=HEAD, json={'version': closed['version'], 'state': 'archived'}))
