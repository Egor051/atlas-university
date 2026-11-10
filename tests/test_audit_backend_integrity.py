"""Audit regressions use fresh, disposable databases, never the workspace DB."""
import json
import os
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, func, text
from sqlalchemy.orm import Session

_initial = tempfile.TemporaryDirectory(prefix='atlas-audit-backend-import-')
if 'app.db' not in sys.modules:
    os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(_initial.name) / 'import.sqlite3').as_posix()
from app import db as database, main, improvements, learning, campus, services
from app.learning_db import StudyNote, PersonalTask, Flashcard, FocusSession, QuizAttempt
from app.campus_db import PortfolioItem
from app.services_db import ServiceIdempotency, SupportTicket, TicketMessage
from app.improvement_db import PersonalDraft, WriteQuota
from app.receipt_codec import encode_receipt, decode_receipt, MARKER, _child_payload

H = {'X-Requested-With': 'ATLAS'}


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    url = 'sqlite:///' + (tmp_path / 'isolated.sqlite3').as_posix()
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 15})
    event.listen(engine, 'connect', database.sqlite_foreign_keys)
    previous = database.SessionLocal.kw['bind']
    database.SessionLocal.configure(bind=engine)
    for module in (database, main, improvements):
        monkeypatch.setattr(module, 'engine', engine)
    monkeypatch.setattr(database, 'DATABASE_URL', url)
    try:
        yield engine
    finally:
        database.SessionLocal.configure(bind=previous)
        engine.dispose()


def login(api, account='alina.demo'):
    passwords = {'alina.demo': 'AtlasDemo!2026-A', 'mark.demo': 'AtlasDemo!2026-M', 'dean.demo': 'AtlasStaff!2026-D'}
    result = api.post('/api/login', json={'login': account, 'password': passwords[account]}, headers=H)
    assert result.status_code == 200, result.text
    return result.json()['user']


def note(title):
    return {'title': title, 'subject': 'Audit', 'body': title + ' fictional text'}


@pytest.mark.parametrize('family,action', [('notes','edit'), ('notes','delete'),
    ('tasks','edit'), ('tasks','toggle'), ('tasks','delete'), ('flashcards','review'),
    ('flashcards','delete'), ('focus-sessions','delete'), ('portfolio','edit'), ('portfolio','delete')])
def test_sqlite_aba_inflight_mutation_cannot_cross_owners(isolated, monkeypatch, family, action):
    with TestClient(main.app) as a, TestClient(main.app) as a2, TestClient(main.app) as b:
        login(a); login(a2); other_uid = login(b, 'mark.demo')['id']
        model = {'notes':StudyNote, 'tasks':PersonalTask, 'flashcards':Flashcard,
                 'focus-sessions':FocusSession, 'portfolio':PortfolioItem}[family]
        base = '/api/campus/portfolio' if family == 'portfolio' else '/api/learning/' + family
        def body(title):
            return {'notes':note(title), 'tasks':dict(title=title,subject='Audit',due_date=str(database.campus_today()),priority='normal'),
                    'flashcards':dict(front=title,back='Fictional answer',subject='Audit'),
                    'focus-sessions':dict(subject=title,minutes=25),
                    'portfolio':dict(title=title,description='Audit',kind='project',day=str(database.campus_today()),url='')}[family]
        original = a.post(base, json=body('Original A'), headers=H).json()
        rid = original['id']
        loaded, release = threading.Event(), threading.Event()
        guard = threading.Lock(); captured = [False]
        scalar = Session.scalar
        def pause(db, statement, *args, **kwargs):
            row = scalar(db, statement, *args, **kwargs)
            if isinstance(row, model) and row.id == rid:
                with guard:
                    wait = not captured[0]
                    captured[0] = True
                if wait:
                    loaded.set(); assert release.wait(15)
            return row
        monkeypatch.setattr(Session, 'scalar', pause)
        path = f'{base}/{rid}' + ('/' + action if action in {'delete','review','toggle'} else '')
        delayed_body = {} if action == 'delete' else {'known':True} if action == 'review' else {'is_done':True} if action == 'toggle' else body('Delayed A')
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                delayed = pool.submit(lambda: a.post(path, json=delayed_body, headers=H))
                assert loaded.wait(15)
                assert a2.post(f'{base}/{rid}/delete', json={}, headers=H).status_code == 200
                replacement = b.post(base, json=body('Fresh B'), headers=H)
                assert replacement.status_code == 201, replacement.text
                assert replacement.json()['id'] == rid  # Actual SQLite row-id reuse.
                assert replacement.json()['record_token'] != original['record_token']
                release.set()
                assert delayed.result(15).status_code == 409
        finally:
            release.set()
        with database.SessionLocal() as db:
            row = db.get(model,rid)
            assert row is not None and row.student_id == other_uid
            assert row.record_token == replacement.json()['record_token']
            for key,value in body('Fresh B').items():
                assert str(getattr(row,key)) == str(value)
            if family == 'flashcards': assert row.reviews == 0
            if family == 'tasks': assert row.is_done is False
        assert all(item['id'] != rid for item in a.get(base).json()['items'])


def test_same_owner_reuse_rejects_old_token_and_draft_identity(isolated):
    with TestClient(main.app) as api:
        login(api)
        old = api.post('/api/learning/notes', json=note('Old note'), headers=H).json()
        old_name = f"note:{old['id']}:{old['record_token']}"
        assert api.put('/api/drafts/' + old_name, json={'values': {'body': 'Old draft'}}, headers=H).status_code == 200
        assert api.post(f"/api/learning/notes/{old['id']}/delete", json={}, headers=H).status_code == 200
        new = api.post('/api/learning/notes', json=note('Replacement note'), headers=H).json()
        assert old['id'] == new['id'] and old['record_token'] != new['record_token']
        stale = {**H, 'X-ATLAS-Record': old['record_token']}
        assert api.post(f"/api/learning/notes/{new['id']}", json=note('Wrong replacement'), headers=stale).status_code == 409
        assert api.get('/api/drafts/' + old_name).status_code == 409
        assert api.put('/api/drafts/' + old_name, json={'values': {'body': 'Late old draft'}}, headers=H).status_code == 409
        fresh_name = f"note:{new['id']}:{new['record_token']}"
        assert api.get('/api/drafts/' + fresh_name).json()['values'] == {}
        assert api.get(f"/api/learning/notes/{new['id']}").json()['title'] == 'Replacement note'


@pytest.mark.parametrize('record_id',['0','2147483648','9'*60])
def test_bound_draft_rejects_out_of_range_identity_without_database_overflow(isolated,record_id):
    with TestClient(main.app) as api:
        login(api)
        path='/api/drafts/note:'+record_id+':'+('a'*32)
        assert api.get(path).status_code==422
        assert api.put(path,json={'values':{'body':'Fictional draft'}},headers=H).status_code==422


@pytest.mark.parametrize('family', ['notes', 'tasks', 'flashcards', 'focus', 'portfolio', 'attempts'])
def test_owner_cap_is_atomic_across_concurrent_creates(isolated, monkeypatch, family):
    with TestClient(main.app) as a, TestClient(main.app) as b:
        uid = login(a)['id']; login(b)
        now, today = database.utc_now(), database.campus_today()
        model = {'notes': StudyNote, 'tasks': PersonalTask, 'flashcards': Flashcard,
                 'focus': FocusSession, 'portfolio': PortfolioItem, 'attempts': QuizAttempt}[family]
        maximum = 1000 if family in {'focus', 'attempts'} else 200
        quiz_id = a.get('/api/learning/quizzes').json()['items'][0]['id']
        bodies = {
            'notes': note('Concurrent note'),
            'tasks': dict(title='Concurrent task', subject='Audit', due_date=str(today), priority='normal'),
            'flashcards': dict(subject='Audit', front='Question', back='Answer'),
            'focus': dict(subject='Concurrent study', minutes=25),
            'portfolio': dict(title='Concurrent portfolio', description='Audit', kind='project', day=str(today), url=''),
            'attempts': dict(answers=[0, 0, 0]),
        }
        path = {'notes': '/api/learning/notes', 'tasks': '/api/learning/tasks',
                'flashcards': '/api/learning/flashcards', 'focus': '/api/learning/focus-sessions',
                'portfolio': '/api/campus/portfolio', 'attempts': f'/api/learning/quizzes/{quiz_id}/attempt'}[family]
        values = {
            'notes': dict(**note('Existing note'), created_at=now, updated_at=now),
            'tasks': dict(title='Existing task', subject='Audit', due_date=today, priority='normal', is_done=False, created_at=now),
            'flashcards': dict(subject='Audit', front='Question', back='Answer', due_date=today, reviews=0, known_count=0, interval_days=0),
            'focus': dict(subject='Existing study', minutes=25, created_at=now),
            'portfolio': dict(title='Existing portfolio', description='Audit', kind='project', day=today, url='', updated_at=now),
            'attempts': dict(quiz_id=quiz_id, answers_json='[0,0,0]', score=1, total=3, created_at=now),
        }[family]
        with database.SessionLocal() as db:
            count = db.scalar(select(func.count()).select_from(model).where(model.student_id == uid))
            db.add_all([model(student_id=uid, **values) for _ in range(maximum - 1 - count)])
            db.commit()
        module = campus if family == 'portfolio' else learning
        original_lock = module.lock_owner
        barrier = threading.Barrier(2)
        def synchronized_lock(db, user_id):
            barrier.wait(15)
            original_lock(db, user_id)
        monkeypatch.setattr(module, 'lock_owner', synchronized_lock)
        def create(api):
            # Legacy requests without a receipt reach the actual cap lock
            # concurrently. A SQLite receipt INSERT already holds its global
            # writer lock, so placing this barrier after that INSERT deadlocks
            # the test itself rather than exercising a count/insert race.
            return api.post(path, json=bodies[family], headers=H)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, [a, b]))
        assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
        with database.SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(model).where(model.student_id == uid)) == maximum
            # Existing over-cap rows from older races remain visible; limits
            # only reject new writes and never trim historical user data.
            db.add(model(student_id=uid, **values)); db.commit()
        listing = '/api/learning/quiz-attempts' if family == 'attempts' else path
        assert len(a.get(listing).json()['items']) == maximum+1


def test_full_size_note_draft_and_portfolio_replay(isolated):
    with TestClient(main.app) as a, TestClient(main.app) as b:
        login(a); login(b, 'mark.demo')
        body = 'я' * 12000
        assert a.put('/api/drafts/note', json={'values': {'body': body}}, headers=H).status_code == 200
        assert a.get('/api/drafts/note').json()['values']['body'] == body
        assert b.get('/api/drafts/note').json()['values'] == {}
        assert a.put('/api/drafts/note', json={'values': {'body': body + 'x'}}, headers=H).status_code == 422
        headers = {**H, 'Idempotency-Key': uuid.uuid4().hex}
        data = dict(title='Replay portfolio', kind='project', description='Fictional', url='', day=str(database.campus_today()))
        first = a.post('/api/campus/portfolio', json=data, headers=headers)
        repeated = a.post('/api/campus/portfolio', json=data, headers=headers)
        assert first.status_code == 201 and repeated.status_code == 200
        assert first.json() == repeated.json()
        assert a.post('/api/campus/portfolio', json={**data, 'title': 'Changed'}, headers=headers).status_code == 409
        assert len(a.get('/api/campus/portfolio').json()['items']) == 1


def test_partial_task_toggle_preserves_edits_and_aged_date(isolated):
    with TestClient(main.app) as a, TestClient(main.app) as b:
        uid = login(a)['id']; login(b, 'mark.demo')
        old_day = database.campus_today() - timedelta(days=500)
        with database.SessionLocal() as db:
            row = PersonalTask(student_id=uid, title='Aged original', subject='Audit', due_date=old_day, priority='normal', is_done=False, created_at=database.utc_now())
            db.add(row); db.commit(); rid = row.id; token = row.record_token
        data = dict(title='Changed in another tab', subject='Updated subject', due_date=str(old_day), priority='high', is_done=False)
        assert a.post(f'/api/learning/tasks/{rid}', json=data, headers=H).status_code == 200
        toggled = a.post(f'/api/learning/tasks/{rid}/toggle', json={'is_done': True}, headers={**H, 'X-ATLAS-Record': token})
        assert toggled.status_code == 200, toggled.text
        assert toggled.json()['title'] == data['title'] and toggled.json()['priority'] == 'high'
        assert toggled.json()['due_date'] == str(old_day) and toggled.json()['is_done'] is True
        assert a.post(f'/api/learning/tasks/{rid}/toggle', json={'is_done': 'false'}, headers=H).status_code == 422
        assert b.post(f'/api/learning/tasks/{rid}/toggle', json={'is_done': False}, headers=H).status_code == 404
        assert a.post('/api/learning/tasks', json={**data, 'due_date': str(old_day)}, headers=H).status_code == 422


def test_canonical_create_quota_and_actor_affinity_before_charging(isolated):
    for segment in ('1', '+1', '01', ' 1', '1.0'):
        assert improvements.creates_resource(f'/api/services/tickets/{segment}/messages', 'POST')
        assert improvements.creates_resource(f'/api/learning/quizzes/{segment}/attempt', 'POST')
    with TestClient(main.app) as a, TestClient(main.app) as b:
        uid = login(a)['id']; other = login(b, 'mark.demo')['id']
        with database.SessionLocal() as db:
            before = db.scalar(select(func.count()).select_from(WriteQuota).where(WriteQuota.user_id == uid))
        result = a.post('/api/learning/notes', json=note('Wrong affinity'), headers={**H, 'X-ATLAS-User': str(other)})
        assert result.status_code == 409 and result.json()['detail']['code'] == 'account_changed'
        with database.SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(WriteQuota).where(WriteQuota.user_id == uid)) == before


@pytest.mark.parametrize('variant', ['+{}', '0{}', '%20{}'])
def test_noncanonical_integer_message_path_cannot_bypass_create_quota(isolated, monkeypatch, variant):
    with TestClient(main.app) as api:
        uid=login(api)['id']
        ticket=api.post('/api/services/tickets',json={'topic':'academic','title':'Quota test topic','message':'Fictional starting message'},headers=H)
        assert ticket.status_code==201,ticket.text
        rid=ticket.json()['id']
        with database.SessionLocal() as db:
            db.query(WriteQuota).filter(WriteQuota.user_id==uid).delete();db.commit()
        original=improvements.quota_limit
        monkeypatch.setattr(improvements,'quota_limit',lambda bucket,period:1 if bucket=='create' and period==0 else original(bucket,period))
        assert api.post(f'/api/services/tickets/{rid}/messages',json={'message':'First allowed message'},headers=H).status_code==200
        blocked=api.post('/api/services/tickets/'+variant.format(rid)+'/messages',json={'message':'Quota bypass attempt'},headers=H)
        assert blocked.status_code==429 and blocked.headers['retry-after']=='60'
        assert len(api.get(f'/api/services/tickets/{rid}').json()['messages'])==2


@pytest.mark.parametrize('kind', ['consultations', 'events'])
def test_staff_replay_survives_start_time_and_boundary_dates(isolated, monkeypatch, kind):
    with TestClient(main.app) as staff, TestClient(main.app) as student:
        login(staff, 'dean.demo'); login(student)
        start = database.utc_now() + timedelta(minutes=10)
        body = dict(start_at=start.isoformat(), end_at=(start + timedelta(hours=1)).isoformat(), capacity=2)
        body.update(dict(teacher='Fictional teacher', subject='Replay subject', room='A-100') if kind == 'consultations' else dict(title='Replay event', category='science', description='Fictional replay event', location='A-100'))
        headers = {**H, 'Idempotency-Key': uuid.uuid4().hex}
        first = staff.post('/api/staff/' + kind, json=body, headers=headers)
        assert first.status_code == 201, first.text
        monkeypatch.setattr(services, 'utc_now', lambda: start + timedelta(hours=2))
        replay = staff.post('/api/staff/' + kind, json=body, headers=headers)
        assert replay.status_code == 200 and replay.json() == first.json()
        assert staff.post('/api/staff/' + kind, json=body, headers={**H, 'Idempotency-Key': uuid.uuid4().hex}).status_code == 422
        for history in ('bookings', 'registrations'):
            assert student.get('/api/services/' + history + '?date_from=0001-01-01').status_code == 422
            assert student.get('/api/services/' + history + '?date_from=0001-01-02').status_code == 200
            assert student.get('/api/services/' + history + '?date_to=9999-12-31').status_code == 422
            assert student.get('/api/services/' + history + '?date_to=9999-12-30').status_code == 200


def test_predicted_followup_version_cannot_bypass_terminal_state(isolated, monkeypatch):
    with TestClient(main.app) as a, TestClient(main.app) as staff:
        login(a); login(staff, 'dean.demo')
        created = a.post('/api/requests', json={'type': 'study'}, headers=H).json(); rid = created['id']
        review = staff.post(f'/api/staff/requests/{rid}/status', json={'status': 'review', 'expected_version': 1}, headers=H)
        assert review.status_code == 200
        loaded, release = threading.Event(), threading.Event(); scalar = Session.scalar; paused = [False]
        def pause(db, statement, *args, **kwargs):
            row = scalar(db, statement, *args, **kwargs)
            if isinstance(row, database.DocumentRequest) and row.id == rid and not paused[0]:
                paused[0] = True; loaded.set(); assert release.wait(15)
            return row
        monkeypatch.setattr(Session, 'scalar', pause)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(lambda: a.post(f'/api/requests/{rid}/followup', json={'message': 'Predicted next version clarification', 'expected_version': 3}, headers={**H, 'Idempotency-Key': uuid.uuid4().hex}))
                assert loaded.wait(15)
                ready = staff.post(f'/api/staff/requests/{rid}/status', json={'status': 'ready', 'expected_version': 2, 'message': 'Fictional result prepared'}, headers=H)
                assert ready.status_code == 200, ready.text
                release.set(); assert future.result(15).status_code == 409
        finally:
            release.set()
        final = a.get(f'/api/requests/{rid}').json()
        assert final['version'] == 3 and final['status'] == 'ready'
        assert [e['status'] for e in final['history']] == ['submitted', 'review', 'ready']


def test_compact_followup_receipts_are_linear_and_replay_historical_page(isolated):
    with TestClient(main.app) as a:
        uid = login(a)['id']
        request = a.post('/api/requests', json={'type': 'study'}, headers=H).json()
        rid, version = request['id'], request['version']
        first_body = first_headers = first_payload = None
        for index in range(120):
            body = {'message': ('я' * 1190) + f'{index:04}', 'expected_version': version}
            headers = {**H, 'Idempotency-Key': uuid.uuid4().hex}
            result = a.post(f'/api/requests/{rid}/followup', json=body, headers=headers)
            assert result.status_code == 200, result.text
            version = result.json()['version']
            if index == 0: first_body, first_headers, first_payload = body, headers, result.json()
        replay = a.post(f'/api/requests/{rid}/followup', json=first_body, headers=first_headers)
        assert replay.status_code == 200 and replay.json() == first_payload
        with database.SessionLocal() as db:
            receipts = db.scalars(select(ServiceIdempotency).where(ServiceIdempotency.user_id == uid, ServiceIdempotency.operation == f'request-followup:{rid}')).all()
            assert len(receipts) == 120
            assert all(json.loads(r.response_json).get(MARKER) is True for r in receipts)
            assert sum(len(r.response_json.encode()) for r in receipts) < len(receipts) * 5000
            assert all('history' not in json.loads(r.response_json)['base'] for r in receipts)


def test_compact_receipts_preserve_exact_legacy_pages_and_all_history_access(isolated):
    with TestClient(main.app) as api,TestClient(main.app) as other:
        uid=login(api)['id'];login(other,'mark.demo')
        request=api.post('/api/requests',json={'type':'study'},headers=H).json()
        rid=request['id']
        ticket=api.post('/api/services/tickets',json={'topic':'academic','title':'Receipt page test','message':'Fictional initial message'},headers=H).json()
        with database.SessionLocal() as db:
            initial=db.scalar(select(database.RequestEvent).where(database.RequestEvent.request_id==rid))
            start=initial.created_at
            db.add_all([database.RequestEvent(request_id=rid,status='submitted',message=f'Historical event {index}',actor_role='student',actor_name='Fictional student',created_at=start+timedelta(seconds=index+1)) for index in range(174)])
            db.add_all([TicketMessage(ticket_id=ticket['id'],actor_id=uid,actor_role='student',actor_name='Fictional student',body=f'Historical message {index}',created_at=start+timedelta(seconds=index+1)) for index in range(144)])
            db.commit()
            row=db.get(database.DocumentRequest,rid)
            modern=main.request_with_history(row,db,history_limit=200,history_offset=0)
            legacy={key:value for key,value in modern.items() if not key.startswith('history_')}
            assert len(legacy['history'])==175
            for payload in (modern,legacy):
                encoded=encode_receipt(db,payload,verify_legacy=True)
                assert encoded[MARKER] is True
                assert len(json.dumps(encoded))<2500
                assert decode_receipt(db,encoded)==payload
            unverifiable={**legacy,'history':[{**legacy['history'][0],'message':'Only surviving old snapshot'}]}
            assert encode_receipt(db,unverifiable,verify_legacy=True) is unverifiable
            ticket_payload=api.get(f"/api/services/tickets/{ticket['id']}").json()
            legacy_ticket={key:value for key,value in ticket_payload.items() if not key.startswith('messages_')}
            assert len(legacy_ticket['messages'])==100
            encoded=encode_receipt(db,legacy_ticket,verify_legacy=True)
            assert encoded[MARKER] is True and decode_receipt(db,encoded)==legacy_ticket
        seen=[]
        for offset in range(0,175,50):
            page=api.get(f'/api/requests/{rid}?history_limit=50&history_offset={offset}')
            assert page.status_code==200
            assert page.json()['history_total']==175 and page.json()['history_offset']==offset
            seen.extend(event['id'] for event in page.json()['history'])
        assert len(seen)==len(set(seen))==175
        assert other.get(f'/api/requests/{rid}?history_limit=200').status_code==404


def test_legacy_flashcard_review_receipt_replays_without_rebinding_or_double_review(isolated):
    with TestClient(main.app) as api:
        login(api)
        card=api.post('/api/learning/flashcards',json={'subject':'Audit','front':'Legacy question','back':'Legacy answer'},headers=H).json()
        headers={**H,'Idempotency-Key':uuid.uuid4().hex}
        path=f"/api/learning/flashcards/{card['id']}/review"
        first=api.post(path,json={'known':True},headers=headers)
        assert first.status_code==200
        legacy={key:value for key,value in first.json().items() if key!='record_token'}
        with database.SessionLocal() as db:
            receipt=db.scalar(select(ServiceIdempotency).where(ServiceIdempotency.key==headers['Idempotency-Key']))
            receipt.operation=f"flashcard-review:{card['id']}"
            receipt.response_json=json.dumps(legacy)
            db.commit()
        replay=api.post(path,json={'known':True},headers=headers)
        assert replay.status_code==200 and replay.json()==legacy
        assert api.get(f"/api/learning/flashcards/{card['id']}").json()['reviews']==1
        assert api.post(path,json={'known':False},headers=headers).status_code==409
        fresh=api.post(path,json={'known':True},headers={**H,'Idempotency-Key':uuid.uuid4().hex})
        assert fresh.status_code==200 and fresh.json()['reviews']==2


def test_0006_upgrade_preserves_records_unbound_drafts_and_compacts_legacy_receipts(isolated):
    with TestClient(main.app) as api:
        uid = login(api)['id']
        old = api.post('/api/learning/notes',json=note('Deleted before upgrade'),headers=H).json()
        own=old
        assert api.put(f"/api/drafts/note:{own['id']}", json={'values': {'body': 'Preserved legacy draft'}}, headers=H).status_code == 200
        assert api.post(f"/api/learning/notes/{old['id']}/delete",json={},headers=H).status_code==200
        own=api.post('/api/learning/notes',json=note('Reused ID before upgrade'),headers=H).json()
        assert own['id']==old['id'] and own['record_token']!=old['record_token']
        assert api.put('/api/drafts/note:2147483647', json={'values': {'body': 'Unbound legacy draft'}}, headers=H).status_code == 200
        req = api.post('/api/requests', json={'type': 'study'}, headers=H).json()
        follow = api.post(f"/api/requests/{req['id']}/followup", json={'message': 'Preserved historical clarification', 'expected_version': 1}, headers={**H, 'Idempotency-Key': uuid.uuid4().hex})
        assert follow.status_code == 200
        with database.SessionLocal() as db:
            receipt = db.scalar(select(ServiceIdempotency).where(ServiceIdempotency.operation == f"request-followup:{req['id']}"))
            historical = decode_receipt(db, receipt.response_json)
            receipt.response_json = json.dumps(historical, ensure_ascii=False)
            receipt_id = receipt.id
            legacy = database.DocumentRequest(student_id=uid, type=database.DOC_NAMES['study'], comment='Legacy Moscow boundary', details='{}', status='submitted', created_at=database.utc_now().replace(year=2026, month=11, day=9, hour=22, minute=30), updated_at=database.utc_now(), due_at=date(2026, 11, 11), staff_message='', version=1)
            db.add(legacy); db.commit(); legacy_id = legacy.id
    tables = [StudyNote, PersonalTask, Flashcard, FocusSession, PortfolioItem]
    before = {}
    with isolated.begin() as conn:
        drafts_before=conn.exec_driver_sql('SELECT * FROM personal_drafts ORDER BY id').all()
        events_before=conn.exec_driver_sql('SELECT * FROM request_events ORDER BY id').all()
        for model in tables:
            name = model.__tablename__
            columns = [column.name for column in model.__table__.columns if column.name != 'record_token']
            before[name] = conn.exec_driver_sql(f"SELECT {','.join(columns)} FROM {name} ORDER BY id").all()
            conn.exec_driver_sql(f'DROP TRIGGER atlas_identity_{name}')
            conn.exec_driver_sql(f'DROP INDEX ix_{name}_record_token')
            conn.exec_driver_sql(f'ALTER TABLE {name} DROP COLUMN record_token')
        conn.execute(text("DELETE FROM schema_migrations WHERE version='0006_audit_integrity'"))
    database.migrate_database()
    database.migrate_database()
    with isolated.connect() as conn:
        assert conn.exec_driver_sql('SELECT * FROM personal_drafts ORDER BY id').all()==drafts_before
        assert conn.exec_driver_sql('SELECT * FROM request_events ORDER BY id').all()==events_before
        for model in tables:
            name = model.__tablename__
            columns = [column.name for column in model.__table__.columns if column.name != 'record_token']
            assert conn.exec_driver_sql(f"SELECT {','.join(columns)} FROM {name} ORDER BY id").all() == before[name]
            tokens=conn.exec_driver_sql(f'SELECT record_token FROM {name}').scalars().all()
            assert len(tokens)==len(set(tokens)) and all(len(token)==32 for token in tokens)
    with database.SessionLocal() as db:
        restored = db.get(StudyNote, own['id'])
        assert len(restored.record_token) == 32
        unbound = db.scalar(select(PersonalDraft).where(PersonalDraft.user_id == uid, PersonalDraft.name == f"note:{own['id']}"))
        assert json.loads(unbound.values_json)['body'] == 'Preserved legacy draft'
        assert db.scalar(select(PersonalDraft).where(PersonalDraft.user_id == uid, PersonalDraft.name == f"note:{own['id']}:{restored.record_token}")) is None
        assert db.scalar(select(PersonalDraft).where(PersonalDraft.name == 'note:2147483647')) is not None
        receipt = db.get(ServiceIdempotency, receipt_id)
        assert json.loads(receipt.response_json)[MARKER] is True
        assert decode_receipt(db, receipt.response_json) == historical
        assert db.get(database.DocumentRequest, legacy_id).due_at == date(2026, 11, 12)
        assert db.scalar(select(func.count()).select_from(database.SchemaMigration).where(database.SchemaMigration.version == '0006_audit_integrity')) == 1
    with TestClient(main.app) as api, TestClient(main.app) as other:
        login(api); login(other, 'mark.demo')
        exported = api.get('/api/drafts/export').json()['items']
        assert any(x['name'] == 'note:2147483647' and x['requires_manual_recovery'] for x in exported)
        assert any(x['name'] == f"note:{own['id']}" and x['requires_manual_recovery'] for x in exported)
        assert all(x['values'].get('body') != 'Unbound legacy draft' for x in other.get('/api/drafts/export').json()['items'])
