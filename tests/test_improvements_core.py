"""3.2 hardening: ownership, durable drafts, workflow and shared quotas."""
import uuid
from datetime import timedelta
from test_api import client, sign_in
from app.db import SessionLocal, DocumentRequest, RequestEvent, campus_today, utc_now
from app.improvement_db import PersonalDraft, WriteQuota
from app.version import VERSION

HEAD={'X-Requested-With':'ATLAS'}
def alina(api): sign_in(api,'alina.demo','AtlasDemo!2026-A')
def mark(api): sign_in(api,'mark.demo','AtlasDemo!2026-M')

def test_version_and_build_have_one_source():
    with client() as api:
        health=api.get('/api/health').json(); config=api.get('/api/config').json()
        assert health['version']==config['version']==VERSION=='3.7.0'
        assert health['build']==config['build'] and len(health['build'])==16
        assert api.get('/static/improvements.js').status_code==200

def test_drafts_persist_across_login_and_do_not_cross_accounts():
    name='note:'+str(uuid.uuid4())
    with client() as a, client() as b:
        alina(a);mark(b)
        assert a.put('/api/drafts/'+name,json={'values':{'title':'Вымышленная заметка','body':'<svg onload=alert(1)>'}},headers=HEAD).status_code==200
        assert b.get('/api/drafts/'+name).json()['values']=={}
        assert b.delete('/api/drafts/'+name,headers=HEAD).status_code==200
        a.post('/api/logout',headers=HEAD);alina(a)
        assert a.get('/api/drafts/'+name).json()['values']['title']=='Вымышленная заметка'
        assert a.put('/api/drafts/'+name,json={'user_id':2,'values':{}},headers=HEAD).status_code==422
        assert a.delete('/api/drafts/'+name,headers=HEAD).status_code==200
        assert a.get('/api/drafts/'+name).json()['values']=={}

def test_draft_security_limits_and_expiry():
    with client() as api:
        assert api.get('/api/drafts/note').status_code==401
        alina(api)
        assert api.put('/api/drafts/note',json={'values':{'body':'test'}}).status_code==403
        assert api.put('/api/drafts/note',json={'values':{'password':'secret'}},headers=HEAD).status_code==422
        assert api.put('/api/drafts/note',json={'values':{'body':'x'*12001}},headers=HEAD).status_code==422
        assert api.put('/api/drafts/note',json={'values':{'body':'\x00'}},headers=HEAD).status_code==422
        uid=api.get('/api/me').json()['id']
        with SessionLocal() as db:
            db.add(PersonalDraft(user_id=uid,name='expired',values_json='{"body":"old"}',updated_at=utc_now()-timedelta(days=15)));db.commit()
        assert api.get('/api/drafts/expired').json()['values']=={}

def test_structured_services_validate_owner_and_data():
    with client() as api:
        alina(api)
        response=api.post('/api/requests',json={'type':'study','details':{'purpose':'По месту требования','copies':'2'}},headers=HEAD)
        assert response.status_code==201,response.text
        row=response.json();assert row['details']['copies']=='2'
        assert api.get('/api/requests/'+str(row['id'])).json()['details']==row['details']
        for details in ({'copies':'9'},{'purpose':'<script>\x00'},{'student_id':'2'}):
            assert api.post('/api/requests',json={'type':'study','details':details},headers=HEAD).status_code==422
        assert api.post('/api/requests',json={'type':'retake','comment':'Прошу согласовать пересдачу','details':{'subject':'Чужая дисциплина','preferred_date':campus_today().isoformat()}},headers=HEAD).status_code==422

def test_followup_is_owned_idempotent_and_does_not_change_student_status():
    with client() as a,client() as b,client() as staff:
        alina(a);mark(b);sign_in(staff,'dean.demo','AtlasStaff!2026-D')
        row=a.post('/api/requests',json={'type':'study'},headers=HEAD).json();url=f'/api/requests/{row["id"]}/followup'
        body={'message':'Уточняю вымышленное назначение','kind':'clarification','expected_version':row['version']}
        headers={**HEAD,'Idempotency-Key':str(uuid.uuid4())}
        assert b.post(url,json=body,headers=headers).status_code==404
        assert staff.post(url,json=body,headers=headers).status_code==403
        first=a.post(url,json=body,headers=headers);second=a.post(url,json=body,headers=headers)
        assert first.status_code==second.status_code==200
        assert len(first.json()['history'])==len(second.json()['history'])==2
        assert first.json()['status']=='submitted' and first.json()['version']==2
        assert a.post(url,json={**body,'message':'Другое уточнение студента'},headers=headers).status_code==409
        assert a.post(url,json=body,headers={**HEAD,'Idempotency-Key':str(uuid.uuid4())}).status_code==409
        current=staff.get(f'/api/staff/requests/{row["id"]}').json()
        response=staff.post(f'/api/staff/requests/{row["id"]}/status',json={'status':'needs_info','expected_version':current['version'],'message':'Пожалуйста уточните цель справки.'},headers=HEAD)
        assert response.status_code==200 and response.json()['status']=='needs_info'
        current=response.json()
        assert a.post(url,json={**body,'expected_version':current['version']},headers={**HEAD,'Idempotency-Key':str(uuid.uuid4())}).json()['status']=='needs_info'

def test_shared_write_quota_reserves_before_mutation(monkeypatch):
    import app.improvements as improvements
    with client() as api:
        alina(api)
        with SessionLocal() as db: db.query(WriteQuota).delete();db.commit()
        monkeypatch.setattr(improvements,'quota_limit',lambda bucket,period:1 if period==0 else 1000)
        first=api.post('/api/requests',json={'type':'study'},headers=HEAD)
        second=api.post('/api/requests',json={'type':'study'},headers=HEAD)
        assert first.status_code==201 and second.status_code==429
        assert second.headers['retry-after']=='60'
        with SessionLocal() as db: db.query(WriteQuota).delete();db.commit()
