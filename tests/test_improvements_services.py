"""Contest hardening regressions. Every operation uses a temporary fictional DB."""
from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import uuid
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import select, func, event, delete

_temporary = tempfile.TemporaryDirectory(prefix='atlas-services-hardening-')
if 'app.db' not in sys.modules:
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_temporary.name)/'hardening.db')
from app.main import app
from app.db import SessionLocal, User, Deadline, Grade, CAMPUS_TZ, engine, utc_now
from app.services_db import (ConsultationSlot, ConsultationBooking, CampusEvent,
    EventRegistration, LibraryBook, LibraryLoan, SupportTicket, TicketMessage,
    ServiceIdempotency, seed_services)
from app.learning_db import Course, CourseModule, AssignmentSubmission

atexit.register(engine.dispose)
HEADERS={'X-Requested-With':'ATLAS'}

def login(api, account='alina.demo'):
    password={'alina.demo':'AtlasDemo!2026-A','mark.demo':'AtlasDemo!2026-M','dean.demo':'AtlasStaff!2026-D'}[account]
    r=api.post('/api/login',json={'login':account,'password':password},headers=HEADERS)
    assert r.status_code==200,r.text
    return r.json()['user']

def key(): return uuid.uuid4().hex

def test_filtering_precedes_limit_and_explicit_record_opens_archive():
    marker='boundary-'+key()
    with TestClient(app) as api:
        login(api)
        with SessionLocal() as db:
            past=utc_now()-timedelta(days=30)
            books=[LibraryBook(title=f'AAA {marker} {i:03}',author='Вымышленный автор',subject=marker,description='Тестовый каталог.',total=1,available=1) for i in range(311)]
            slots=[ConsultationSlot(teacher='Вымышленный преподаватель',subject=marker,start_at=past+timedelta(minutes=i),end_at=past+timedelta(minutes=i+20),room='Тест-А-100',capacity=1,booked_count=0) for i in range(311)]
            events=[CampusEvent(title=marker,category='science',description='Вымышленное событие.',start_at=past+timedelta(minutes=i),end_at=past+timedelta(minutes=i+20),location='Тест-А',capacity=1,registered_count=0) for i in range(311)]
            future=utc_now()+timedelta(days=5)
            slots.append(ConsultationSlot(teacher='Вымышленный преподаватель',subject=marker,start_at=future,end_at=future+timedelta(hours=1),room='Тест-А-100',capacity=1,booked_count=0))
            events.append(CampusEvent(title=marker,category='science',description='Вымышленное событие.',start_at=future,end_at=future+timedelta(hours=1),location='Тест-А',capacity=1,registered_count=0))
            db.add_all([*books,*slots,*events]);db.commit()
            book_ids=[b.id for b in books];slot_ids=[s.id for s in slots];event_ids=[e.id for e in events]
        try:
            result=api.get('/api/services/library',params={'q':books[-1].title,'limit':20}).json()
            assert result['total']==1 and result['items'][0]['id']==book_ids[-1]
            assert api.get('/api/services/library',params={'q':'ВЫМЫШЛЕННЫЙ АВТОР','limit':20}).json()['total']>=311
            for path,ids in [('consultations',slot_ids),('events',event_ids)]:
                result=api.get('/api/services/'+path,params={'q':marker,'limit':20}).json()
                assert result['total']==1 and result['items'][0]['id']==ids[-1]
                result=api.get('/api/services/'+path,params={'q':marker,'scope':'archive','limit':20,'offset':300}).json()
                assert result['total']==311 and len(result['items'])==11 and not result['has_more']
                result=api.get('/api/services/'+path,params={'record_id':ids[0]}).json()
                assert result['total']==1 and result['items'][0]['id']==ids[0]
            assert api.get('/api/services/library?limit=0').status_code==422
            assert api.get('/api/services/events?offset=-1').status_code==422
        finally:
            with SessionLocal() as db:
                for model,ids in [(LibraryBook,book_ids),(ConsultationSlot,slot_ids),(CampusEvent,event_ids)]: db.execute(delete(model).where(model.id.in_(ids)))
                db.commit()

def test_ticket_receipts_are_actor_scoped_replay_safe_and_reject_changed_payload():
    marker=key();headers={**HEADERS,'Idempotency-Key':marker}
    body={'topic':'academic','title':'Вымышленный вопрос '+marker,'message':'Достаточно подробный вымышленный вопрос.'}
    with TestClient(app) as a,TestClient(app) as b,TestClient(app) as staff:
        login(a);login(b,'mark.demo');login(staff,'dean.demo')
        first=a.post('/api/services/tickets',json=body,headers=headers)
        repeat=a.post('/api/services/tickets',json=body,headers=headers)
        assert first.status_code==201 and repeat.status_code==200
        assert first.json()==repeat.json()
        ticket=first.json()['id']
        assert a.post('/api/services/tickets',json={**body,'message':'Совсем другое сообщение в этой отправке.'},headers=headers).status_code==409
        other=b.post('/api/services/tickets',json=body,headers=headers)
        assert other.status_code==201 and other.json()['id']!=ticket
        assert b.get('/api/services/tickets',params={'record_id':ticket}).json()['total']==0
        assert b.post(f'/api/services/tickets/{ticket}/messages',json={'message':'Чужой ответ'},headers=headers).status_code==404
        message_headers={**HEADERS,'Idempotency-Key':key()}
        message={'message':'Ответ сотрудника на вымышленный вопрос.'}
        first_reply=staff.post(f'/api/staff/tickets/{ticket}/messages',json=message,headers=message_headers)
        repeat_reply=staff.post(f'/api/staff/tickets/{ticket}/messages',json=message,headers=message_headers)
        assert first_reply.status_code==repeat_reply.status_code==200
        assert first_reply.json()==repeat_reply.json()
        assert len(a.get(f'/api/services/tickets/{ticket}').json()['messages'])==2
        assert a.post('/api/services/tickets',json=body,headers={**HEADERS,'Idempotency-Key':'../unsafe'}).status_code==422
        assert a.post('/api/services/tickets',json={**body,'student_id':2},headers=headers).status_code==422

def test_concurrent_same_key_ticket_is_created_once():
    marker=key();headers={**HEADERS,'Idempotency-Key':marker}
    body={'topic':'academic','title':'Одновременный вымышленный вопрос '+marker,'message':'Демонстрация одновременного повтора отправки.'}
    with TestClient(app) as a,TestClient(app) as b:
        login(a);login(b)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda api:api.post('/api/services/tickets',json=body,headers=headers),[a,b]))
        assert sorted(r.status_code for r in results)==[200,201],[r.text for r in results]
        assert results[0].json()['id']==results[1].json()['id']
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.title==body['title']))==1

def test_seat_and_book_receipts_replay_without_consuming_capacity_twice():
    with TestClient(app) as api:
        who=login(api)
        with SessionLocal() as db:
            start=utc_now()+timedelta(days=3)
            slot=ConsultationSlot(teacher='Вымышленный преподаватель',subject='Повтор безопасной записи',start_at=start,end_at=start+timedelta(hours=1),room='Тест',capacity=1,booked_count=0)
            item=CampusEvent(title='Повтор регистрации безопасен',category='science',description='Вымышленный сценарий.',start_at=start,end_at=start+timedelta(hours=1),location='Тест',capacity=1,registered_count=0)
            book=LibraryBook(title='Повтор выдачи безопасен',author='Вымышленный автор',subject='Тест',description='Вымышленное пособие.',total=1,available=1)
            db.add_all([slot,item,book]);db.commit()
        operations=[(f'/api/services/consultations/{slot.id}/book','bookings','cancel'),(f'/api/services/events/{item.id}/register','registrations','cancel'),(f'/api/services/library/{book.id}/borrow','loans','return')]
        for path,kind,action in operations:
            h={**HEADERS,'Idempotency-Key':key()}
            created=api.post(path,json={},headers=h);replayed=api.post(path,json={},headers=h)
            assert created.status_code==201 and replayed.status_code==200
            assert created.json()==replayed.json()
            resource=created.json()['id']
            h={**HEADERS,'Idempotency-Key':key()}
            assert api.post(f'/api/services/{kind}/{resource}/{action}',json={},headers=h).status_code==200
            assert api.post(f'/api/services/{kind}/{resource}/{action}',json={},headers=h).status_code==200
        with SessionLocal() as db:
            assert db.get(ConsultationSlot,slot.id).booked_count==0
            assert db.get(CampusEvent,item.id).registered_count==0
            assert db.get(LibraryBook,book.id).available==1

def test_service_history_pagination_moscow_dates_and_owner_isolation():
    with TestClient(app) as a,TestClient(app) as b:
        who=login(a);login(b,'mark.demo');marker=key()
        day=date(2026,11,28)
        at=datetime.combine(day,datetime.min.time(),CAMPUS_TZ).replace(hour=23).astimezone(timezone.utc)
        with SessionLocal() as db:
            slot=ConsultationSlot(teacher='Тестовый преподаватель',subject=marker,start_at=at,end_at=at+timedelta(minutes=30),room='Тест',capacity=1,booked_count=0)
            db.add(slot);db.flush()
            rows=[ConsultationBooking(student_id=who['id'],slot_id=slot.id,status='cancelled',created_at=utc_now()+timedelta(seconds=i)) for i in range(305)]
            db.add_all(rows);db.commit();ids=[r.id for r in rows]
        try:
            result=a.get('/api/services/bookings',params={'filter':'cancelled','date_from':str(day),'date_to':str(day),'limit':20,'offset':300}).json()
            assert result['total']==305 and len(result['items'])==5 and not result['has_more']
            assert all(r['slot']['id']==slot.id for r in result['items'])
            other=b.get('/api/services/bookings',params={'date_from':str(day),'date_to':str(day)}).json()
            assert not {r['id'] for r in other['items']} & set(ids)
            assert a.get('/api/services/bookings?date_from=2026-11-29&date_to=2026-11-28').status_code==422
        finally:
            with SessionLocal() as db:
                db.execute(delete(ConsultationBooking).where(ConsultationBooking.id.in_(ids)))
                db.delete(db.get(ConsultationSlot,slot.id));db.commit()

def test_thread_history_has_accessible_pages_and_never_exposes_other_thread():
    with TestClient(app) as a,TestClient(app) as b:
        who=login(a);login(b,'mark.demo')
        with SessionLocal() as db:
            ticket=SupportTicket(student_id=who['id'],topic='academic',title='Длинная вымышленная переписка',status='open',created_at=utc_now(),updated_at=utc_now())
            db.add(ticket);db.flush()
            db.add_all([TicketMessage(ticket_id=ticket.id,actor_id=who['id'],actor_role='student',actor_name='Вымышленный студент',body=f'Тестовое сообщение {i:03}',created_at=utc_now()+timedelta(seconds=i)) for i in range(105)])
            db.commit()
        data=a.get(f'/api/services/tickets/{ticket.id}').json()
        assert data['messages_total']==105 and data['messages_offset']==5 and len(data['messages'])==100
        first=a.get(f'/api/services/tickets/{ticket.id}?message_limit=20&message_offset=0').json()
        assert first['messages_has_more'] and first['messages'][0]['body'].endswith('000')
        assert b.get(f'/api/services/tickets/{ticket.id}?message_offset=0').status_code==404

def test_contest_fixtures_reach_final_day_without_replacing_history():
    with TestClient(app) as api:
        login(api)
        with SessionLocal() as db:
            existing={row.id:(row.seed_key,row.booked_count,row.start_at) for row in db.scalars(select(ConsultationSlot))}
            before=db.scalar(select(func.count()).select_from(CampusEvent))
            seed_services(db);seed_services(db);db.commit()
            assert db.scalar(select(func.count()).select_from(CampusEvent))==before
            assert {row.id:(row.seed_key,row.booked_count,row.start_at) for row in db.scalars(select(ConsultationSlot))}==existing
            for day in [9,15,28]:
                assert db.scalar(select(func.count()).select_from(ConsultationSlot).where(ConsultationSlot.seed_key.like(f'contest-202611-{day:02d}-%')))>=6
                assert db.scalar(select(func.count()).select_from(CampusEvent).where(CampusEvent.seed_key.like(f'contest-202611-{day:02d}-%')))>=1

def count_selects(call):
    statements=[]
    def record(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'):statements.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    try:
        result=call()
        assert result.status_code==200,result.text
    finally:event.remove(engine,'before_cursor_execute',record)
    return len(statements)

def test_course_and_assignment_query_count_is_constant_as_lists_grow():
    with TestClient(app) as api:
        who=login(api)
        before_courses=count_selects(lambda:api.get('/api/learning/courses'))
        before_assignments=count_selects(lambda:api.get('/api/learning/assignments'))
        with SessionLocal() as db:
            grades=[];courses=[];deadlines=[]
            for i in range(30):
                grade=Grade(student_id=who['id'],subject=f'Вымышленная нагрузочная дисциплина {i}',teacher='Тестовый преподаватель',current=70,trend=0,kind='exam',exam_kind='Экзамен',assessment='Допуск',color='blue')
                db.add(grade);db.flush();grades.append(grade)
                course=Course(student_id=who['id'],grade_id=grade.id,subject=grade.subject,teacher=grade.teacher,credits=1,description='Вымышленный нагрузочный курс.',color='blue')
                db.add(course);db.flush();courses.append(course)
                db.add(CourseModule(course_id=course.id,position=1,title='Тестовый модуль',content='Вымышленный материал.',is_done=False))
                deadline=Deadline(student_id=who['id'],subject=grade.subject,title='Вымышленная нагрузочная работа',due_date=date(2026,11,28),is_done=False)
                db.add(deadline);deadlines.append(deadline)
            db.commit();course_ids=[r.id for r in courses];grade_ids=[r.id for r in grades];deadline_ids=[r.id for r in deadlines]
        try:
            after_courses=count_selects(lambda:api.get('/api/learning/courses'))
            after_assignments=count_selects(lambda:api.get('/api/learning/assignments'))
            assert after_courses==before_courses
            assert after_assignments==before_assignments
            assert before_courses<=5 and before_assignments<=5
            print(f'SQL SELECTs including authentication: courses {before_courses}->{after_courses}; assignments {before_assignments}->{after_assignments}; 30 additional records per list')
        finally:
            with SessionLocal() as db:
                db.execute(delete(CourseModule).where(CourseModule.course_id.in_(course_ids)))
                db.execute(delete(Course).where(Course.id.in_(course_ids)))
                db.execute(delete(Deadline).where(Deadline.id.in_(deadline_ids)))
                db.execute(delete(Grade).where(Grade.id.in_(grade_ids)));db.commit()

def test_learning_creates_and_submissions_have_replay_safe_owner_scoped_receipts():
    with TestClient(app) as a,TestClient(app) as b:
        login(a);login(b,'mark.demo')
        operations=[('/api/learning/notes',{'title':'Тестовый личный конспект','subject':'Тест','body':'Вымышленная заметка для проверки повтора.'}),
                    ('/api/learning/tasks',{'title':'Вымышленная личная задача','subject':'Тест','due_date':'2026-11-28','priority':'normal','is_done':False}),
                    ('/api/learning/flashcards',{'subject':'Тест','front':'Вымышленный вопрос','back':'Вымышленный ответ'}),
                    ('/api/learning/focus-sessions',{'subject':'Вымышленное занятие','minutes':25})]
        for path,body in operations:
            h={**HEADERS,'Idempotency-Key':key()}
            first=a.post(path,json=body,headers=h);replay=a.post(path,json=body,headers=h)
            assert first.status_code==201 and replay.status_code==200,(path,first.text,replay.text)
            assert first.json()==replay.json()
        assignment=a.get('/api/learning/assignments').json()['items'][0]
        h={**HEADERS,'Idempotency-Key':key()};body={'text':'Подробное вымышленное решение учебной работы.','url':''}
        first=a.post(f'/api/learning/assignments/{assignment["id"]}/submit',json=body,headers=h)
        replay=a.post(f'/api/learning/assignments/{assignment["id"]}/submit',json=body,headers=h)
        assert first.status_code==replay.status_code==200 and first.json()==replay.json()
        assert b.post(f'/api/learning/assignments/{assignment["id"]}/submit',json=body,headers=h).status_code==404
        card=a.get('/api/learning/flashcards').json()['items'][0]
        h={**HEADERS,'Idempotency-Key':key()}
        first=a.post(f'/api/learning/flashcards/{card["id"]}/review',json={'known':True},headers=h)
        replay=a.post(f'/api/learning/flashcards/{card["id"]}/review',json={'known':True},headers=h)
        assert first.status_code==replay.status_code==200 and first.json()==replay.json()
        assert first.json()['reviews']==card['reviews']+1
        assert a.post(f'/api/learning/flashcards/{card["id"]}/review',json={'known':False},headers=h).status_code==409
        quiz=a.get('/api/learning/quizzes').json()['items'][0]
        details=a.get(f'/api/learning/quizzes/{quiz["id"]}').json()
        h={**HEADERS,'Idempotency-Key':key()};answers={'answers':[0]*len(details['questions'])}
        first=a.post(f'/api/learning/quizzes/{quiz["id"]}/attempt',json=answers,headers=h)
        replay=a.post(f'/api/learning/quizzes/{quiz["id"]}/attempt',json=answers,headers=h)
        assert first.status_code==201 and replay.status_code==200 and first.json()==replay.json()


def test_staff_publications_and_broadcast_have_persistent_receipts():
    with TestClient(app) as staff:
        login(staff,'dean.demo')
        start=utc_now()+timedelta(days=12)
        operations=[('/api/staff/consultations',dict(teacher='Вымышленный преподаватель',subject='Повтор публикации консультации',start_at=start.isoformat(),end_at=(start+timedelta(hours=1)).isoformat(),room='Тест',capacity=5)),
                    ('/api/staff/events',dict(title='Повтор публикации события',category='science',description='Вымышленный учебный сценарий.',start_at=start.isoformat(),end_at=(start+timedelta(hours=1)).isoformat(),location='Тестовый корпус',capacity=5)),
                    ('/api/staff/announcements',dict(title='Повтор объявления безопасен',body='Вымышленное объявление для проверки единственной отправки.',category='announcement'))]
        receipts=[]
        for path,body in operations:
            h={**HEADERS,'Idempotency-Key':key()}
            first=staff.post(path,json=body,headers=h);replay=staff.post(path,json=body,headers=h)
            assert first.status_code==201 and replay.status_code==200
            assert first.json()==replay.json()
            receipts.append((path,body,h,first.json()))
    with TestClient(app) as restored:
        login(restored,'dean.demo')
        for path,body,h,payload in receipts:
            replay=restored.post(path,json=body,headers=h)
            assert replay.status_code==200 and replay.json()==payload


from test_frontend_contracts import frontend_server, frontend_browser, frontend_page, enter_demo

@pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS')!='1',reason='Opt-in real HTTP/Chromium loss-of-response regression')
def test_ticket_lost_response_after_commit_retries_same_key_without_duplicate(frontend_page):
    from playwright.sync_api import expect
    page,base=frontend_page
    page.goto(base)
    enter_demo(page,0,'Алина')
    page.goto(base+'/app/messages',wait_until='networkidle')
    expect(page.locator('[data-c-action="ticket-new"]')).to_be_visible()
    page.locator('[data-c-action="ticket-new"]').click()
    title='Вымышленный вопрос с потерянным ответом '+key()
    page.locator('#campus-field-title').fill(title)
    page.locator('#campus-field-message').fill('Вымышленный подробный вопрос для проверки безопасного повтора.')
    seen=[];saved=[]
    def lose_first_reply(route):
        seen.append(route.request.headers.get('idempotency-key'))
        if len(seen)==1:
            result=route.fetch()  # The real HTTP server commits before its response is dropped.
            assert result.status==201,result.text()
            saved.append(result.json()['id'])
            route.abort('failed')
        else:
            route.continue_()
    page.route('**/api/services/tickets',lose_first_reply)
    form=page.locator('form[data-c-form="ticket"]')
    form.locator('button[type="submit"]').click()
    expect(form.locator('[data-c-error]')).to_be_visible()
    expect(form.locator('button[type="submit"]')).to_be_enabled()
    assert page.request.get(base+f'/api/services/tickets/{saved[0]}').status==200
    form.locator('button[type="submit"]').click()
    expect(form).to_have_count(0)
    assert len(seen)==2 and seen[0] and seen[0]==seen[1]
    found=page.request.get(base+'/api/services/tickets',params={'q':title}).json()
    assert found['total']==1 and found['items'][0]['id']==saved[0]

