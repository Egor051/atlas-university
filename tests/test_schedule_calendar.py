"""Academic date rules and publication across student audiences."""
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db import Deadline, SessionLocal
from app.schedule_occurrences import campus_instant
from app.services_db import CampusEvent, ConsultationBooking, ConsultationSlot, EventRegistration
from test_academic_workspace import HEAD, body, roles, step


CALENDAR = '/api/scheduling/calendar'
CHANGES = '/api/scheduling/changes'


def term(admin, first, last, year, number, periods, **scope):
    return body(admin.put(CALENDAR+'/terms', headers=HEAD, json=dict(
        academic_year=year, number=number, starts_on=first, ends_on=last, weekdays='01234',
        source='Учебный график изолированного теста',
        periods=[dict(kind=kind, start=start, end=end) for kind, start, end in periods], **scope)))


def schedule(api, day, view='week'):
    return body(api.get('/api/schedule', params={'week': day, 'view': view}))


def one_day(api, day):
    return next(row for row in schedule(api, day)['days'] if row['date'] == day)


def publish(dispatcher, office, admin, **data):
    draft = body(dispatcher.post(CHANGES, json=data, headers=HEAD), 201)
    return step(admin, step(office, step(dispatcher, draft, 'submit'), 'agree'), 'publish')


def test_academic_phases_holidays_and_scope(roles):
    admin, dispatcher, student, other = (roles(role) for role in ('admin', 'scheduler', 'student', 'other'))
    assert student.get(CALENDAR+'?year=2030').status_code == 403
    assert dispatcher.put(CALENDAR+'/terms', json={}, headers=HEAD).status_code == 403
    group = next(row for row in body(admin.get(CALENDAR+'?year=2030'))['groups'] if row['code'] == 'ИТ-24-03')
    term(admin, '2030-09-02', '2031-01-30', 2030, 1, [
        ('teaching', '2030-09-02', '2030-12-08'), ('credit', '2030-12-09', '2030-12-15'),
        ('exam', '2030-12-16', '2031-01-17'),
    ], program=group['program'])
    term(admin, '2031-02-03', '2031-06-30', 2030, 2, [('teaching', '2031-02-03', '2031-06-30')],
         group_id=group['id'])
    term(admin, '2031-09-01', '2032-01-16', 2031, 1, [('teaching', '2031-09-01', '2032-01-16')])
    for kind, first, last in (('break', '2031-01-18', '2031-02-02'), ('summer', '2031-07-01', '2031-08-31')):
        body(admin.put(CALENDAR+'/rules', headers=HEAD, json=dict(
            kind=kind, starts_on=first, ends_on=last, group_id=group['id'], source='Настройка тестовой группы')))
    cases = {
        '2030-09-01': 'weekend', '2030-09-02': 'teaching', '2030-11-04': 'holiday',
        '2030-12-10': 'credit', '2030-12-16': 'exam', '2031-01-01': 'holiday',
        '2031-01-20': 'break', '2031-02-03': 'teaching', '2031-07-14': 'summer',
        '2031-09-01': 'teaching', '2026-12-31': 'weekend', '2027-02-22': 'weekend',
        '2027-02-20': 'unconfigured', '2027-11-05': 'weekend', '2027-11-04': 'holiday',
    }
    for day, code in cases.items():
        row = one_day(student, day)
        assert row['reason']['code'] == code
        assert not any(item['is_lesson'] for item in row['items'])
    assert one_day(other, '2030-12-10')['reason']['code'] == 'unconfigured'
    assert one_day(student, '2031-02-03')['reason']['semester'] == 2
    assert one_day(student, '2031-09-01')['reason']['academic_year'] == 2031
    month = schedule(student, '2030-12-10', 'month')
    assert month['days'][0]['date'] == '2030-11-25'
    assert len(month['days']) % 7 == 0


def test_schedule_subgroups_specials_moves_and_dismissal(roles, monkeypatch):
    monkeypatch.setattr('app.scheduling.utc_now', lambda: datetime(2029, 1, 1, tzinfo=timezone.utc))
    admin, dispatcher, office, student, other = (roles(role) for role in ('admin', 'scheduler', 'staff', 'student', 'other'))
    settings = body(admin.get(CALENDAR+'?year=2033'))
    member = next(row for row in settings['members'] if row['id'] == body(student.get('/api/me'))['id'])
    other_id = body(other.get('/api/me'))['id']
    subgroup = body(admin.put(CALENDAR+'/subgroups', headers=HEAD,
                               json=dict(group_id=member['group_id'], code='Лабораторная А', capacity=10)))
    body(admin.put(CALENDAR+'/members', headers=HEAD, json=dict(
        student_id=member['id'], subgroup_id=subgroup['id'], version=member['version'])))
    term(admin, '2033-09-01', '2033-11-30', 2033, 1, [
        ('teaching', '2033-09-01', '2033-11-05'),
        ('credit', '2033-11-06', '2033-11-12'), ('exam', '2033-11-13', '2033-11-30'),
    ], group_id=member['group_id'])
    options = body(dispatcher.get('/api/scheduling/options'))
    load = next(x for x in options['loads'] if x['teacher'] == 'Михаил Орлов')
    teacher = next(x['id'] for x in options['teachers'] if x['name'] == load['teacher'])
    rooms = {x['code']: x['id'] for x in options['rooms']}
    slot = dict(load_id=load['id'], teacher_id=teacher, room_id=rooms['А-301'],
                start='11:00', end='12:00', day='2033-09-06', kind='lecture')
    lab = publish(dispatcher, office, admin, action='create', slot={**slot, 'kind': 'lab', 'start': '13:00',
                  'end': '14:30', 'room_id': rooms['Б-208'], 'subgroup_id': subgroup['id'], 'weeks': 2, 'interval': 2})
    assert one_day(student, '2033-09-06')['items'][0]['subgroup'] == 'Лабораторная А'
    assert not one_day(student, '2033-09-13')['items']
    assert one_day(student, '2033-09-20')['items'][0]['type'] == 'lab'
    assert not one_day(other, '2033-09-06')['items']
    assert 'Лабораторная А' not in other.get('/api/schedule?week=2033-09-06').text
    assert dispatcher.post(CHANGES, headers=HEAD, json=dict(
        action='create', slot={**slot, 'student_id': other_id})).status_code == 404
    assert dispatcher.post(CHANGES, headers=HEAD, json=dict(
        action='create', slot={**slot, 'day': '2033-11-04'})).status_code == 422
    assert dispatcher.post(CHANGES, headers=HEAD, json=dict(
        action='create', slot={**slot, 'day': '2033-11-08'})).status_code == 422
    lecture = publish(dispatcher, office, admin, action='create', slot=slot)
    practice = publish(dispatcher, office, admin, action='create', slot={**slot, 'day': '2033-09-07',
                       'kind': 'practice', 'room_id': rooms['Онлайн']})
    assert one_day(student, '2033-09-07')['items'][0]['format'] == 'online'
    event_id, item_id = lecture['event_id'], 1_000_000_000+lecture['event_id']
    before = schedule(student, slot['day'])
    keys = [row['key'] for row in before['changes']]
    assert len(keys) >= 3 and f'class:{lab["event_id"]}:1' in keys
    dismiss = dict(date=slot['day'], keys=keys)
    assert student.post('/api/schedule/dismiss', json=dismiss).status_code == 403
    assert body(student.post('/api/schedule/dismiss', json=dismiss, headers=HEAD))['changes'] == []
    assert schedule(student, slot['day'])['changes'] == []
    assert body(other.post('/api/schedule/dismiss', json=dismiss, headers=HEAD))['changes'] == []

    new_day = '2033-09-13'
    publish(dispatcher, office, admin, action='update', event_id=event_id, event_version=1,
            slot={**slot, 'day': new_day, 'room_id': rooms['В-404']}, note='Перенос тестового занятия')
    original = one_day(student, slot['day'])
    moved = one_day(student, new_day)['items'][0]
    assert all(item['id'] != item_id for item in original['items'])
    assert original['moves'][0]['date'] == new_day
    assert (moved['id'], moved['room'], moved['change']['previous']['day']) == (item_id, 'В-404', slot['day'])
    new_keys = [row['key'] for row in schedule(student, slot['day'])['changes']]
    assert new_keys == [f'class:{event_id}:2']
    assert body(student.post('/api/schedule/dismiss', json=dict(date=slot['day'], keys=new_keys), headers=HEAD))['changes'] == []

    publish(dispatcher, office, admin, action='cancel', event_id=event_id, event_version=2, note='Тестовая отмена')
    cancelled = one_day(student, new_day)['items'][0]
    assert cancelled['status'] == 'cancelled'
    assert cancelled['change']['key'] == f'class:{event_id}:3'
    assert one_day(student, slot['day'])['moves'][0]['status'] == 'cancelled'
    assert [row['key'] for row in schedule(student, new_day)['changes']] == [f'class:{event_id}:3']
    ics = student.get('/api/schedule/export', params={'week': new_day}).text
    assert f'UID:event-{event_id}-{member["id"]}@atlas-concept.local' in ics and 'STATUS:CANCELLED' in ics
    publish(dispatcher, office, admin, action='restore', event_id=event_id, event_version=3, note='Занятие восстановлено')
    restored = one_day(student, new_day)['items'][0]
    assert restored['uid'] == moved['uid'] and restored['status'] == 'active' and restored['change']['label'] == 'Восстановлено'
    assert dispatcher.post(CHANGES, headers=HEAD, json=dict(
        action='cancel', event_id=event_id, event_version=2, note='Устаревшая версия')).status_code == 409

    for kind, day in [('credit','2033-11-08'), ('exam','2033-11-15'), ('retake','2033-11-16'), ('organization','2033-11-17')]:
        publish(dispatcher, office, admin, action='create', slot={**slot, 'kind': kind, 'day': day,
                'title': 'Встреча группы' if kind=='organization' else '', 'student_id': member['id'] if kind=='retake' else None})
        result = one_day(student, day)
        assert result['reason']['code'] == ('credit' if kind=='credit' else 'exam')
        assert [item['type'] for item in result['items']] == [kind]
        assert not one_day(other, day)['items']
    assert practice['event_id'] != lab['event_id']


def test_bookings_and_deadlines_use_session_audience(roles):
    student, other = roles('student'), roles('other')
    uid = body(student.get('/api/me'))['id']
    day = date(2034, 7, 12)
    with SessionLocal() as db:
        slot = ConsultationSlot(teacher='Преподаватель тестовой группы', subject='Консультация по тестовой работе',
                                start_at=campus_instant(day, '10:00'), end_at=campus_instant(day, '10:30'),
                                room='Онлайн', capacity=8, booked_count=1)
        event = CampusEvent(title='Встреча на кампусе', category='studies', description='Встреча',
                            start_at=campus_instant(day, '12:00'), end_at=campus_instant(day, '13:00'),
                            location='Кампус', capacity=12, registered_count=1)
        db.add_all([slot, event, Deadline(student_id=uid, subject='Задания', title='Срок тестовой работы', due_date=day)])
        db.flush()
        db.add_all([ConsultationBooking(slot_id=slot.id, student_id=uid, status='active', created_at=slot.start_at),
                    EventRegistration(event_id=event.id, student_id=uid, status='active', created_at=event.start_at)])
        db.commit()
    row = one_day(student, str(day))
    assert [x['type'] for x in row['items']] == ['consultation', 'campus']
    assert any(x['type']=='deadline' and x['title']=='Срок тестовой работы' for x in row['markers'])
    stranger = one_day(other, str(day))
    assert not stranger['items'] and not stranger['markers']
    assert 'Срок тестовой работы' not in student.get('/api/schedule/export', params={'week':day}).text


def test_managed_override_of_published_legacy_occurrence(roles, monkeypatch):
    monkeypatch.setattr('app.scheduling.utc_now', lambda: datetime(2026, 11, 10, tzinfo=timezone.utc))
    dispatcher, office, admin, student, other = (roles(role) for role in ('scheduler', 'staff', 'admin', 'student', 'other'))
    original_day, new_day = '2026-11-16', '2026-11-24'
    event = one_day(student, original_day)['items'][0]
    reference = dict(id=event['id'], day=original_day)
    publish(dispatcher, office, admin, action='update', legacy=reference, event_version=1, note='Разовый перенос',
            slot=dict(day=new_day, start='07:00', end='08:30', room='Онлайн', teacher=event['teacher']))
    assert all(item['uid']!=event['uid'] for item in one_day(student, original_day)['items'])
    moved = next(item for item in one_day(student, new_day)['items'] if item['uid']==event['uid'])
    assert moved['change']['previous']['day'] == original_day
    assert not any(item['uid']==event['uid'] for item in one_day(other, new_day)['items'])
    publish(dispatcher, office, admin, action='cancel', legacy=reference, event_version=2, note='Разовая отмена')
    assert one_day(student, original_day)['moves'][0]['status'] == 'cancelled'
    publish(dispatcher, office, admin, action='restore', legacy=reference, event_version=3)
    restored = next(item for item in one_day(student, new_day)['items'] if item['uid']==event['uid'])
    assert restored['status'] == 'active' and restored['version'] == 4
