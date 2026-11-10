"""Adversarial hardening checks on temporary fictional data; never real accounts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
import uuid

from fastapi import HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session
from test_api import client, sign_in
from app.db import SessionLocal, RequestEvent, utc_now
from app.improvement_db import WriteQuota
from app import improvements

HEAD={'X-Requested-With':'ATLAS'}

def alina(api): sign_in(api,'alina.demo','AtlasDemo!2026-A')

def test_followup_concurrent_same_key_is_one_successful_change(monkeypatch):
    with client() as a,client() as b:
        alina(a);alina(b)
        created=a.post('/api/requests',json={'type':'study'},headers=HEAD).json()
        body={'message':'Уточняю вымышленную цель справки.','kind':'clarification','expected_version':created['version']}
        headers={**HEAD,'Idempotency-Key':uuid.uuid4().hex}
        barrier=threading.Barrier(2)
        lock=threading.Lock();remaining=[2]
        original=Session.scalar
        def synchronize_old_receipt_read(db,statement,*args,**kwargs):
            result=original(db,statement,*args,**kwargs)
            # Align both handlers immediately after they read an absent legacy
            # receipt. This reproduces the stale-version race deterministically.
            if result is None and 'FROM request_followup_receipts' in str(statement):
                with lock:
                    wait=remaining[0]>0
                    if wait:remaining[0]-=1
                if wait:barrier.wait(timeout=10)
            return result
        monkeypatch.setattr(Session,'scalar',synchronize_old_receipt_read)
        url=f'/api/requests/{created["id"]}/followup'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda api:api.post(url,json=body,headers=headers),[a,b]))
        assert [r.status_code for r in results]==[200,200],[r.text for r in results]
        current=a.get(f'/api/requests/{created["id"]}').json()
        assert current['version']==created['version']+1
        assert len(current['history'])==2

def test_followup_rejects_boolean_and_coerced_versions():
    with client() as api:
        alina(api)
        created=api.post('/api/requests',json={'type':'study'},headers=HEAD).json()
        for version in [True,'1',1.1]:
            result=api.post(f'/api/requests/{created["id"]}/followup',json={'message':'Вымышленное уточнение к заявке.','expected_version':version},headers={**HEAD,'Idempotency-Key':uuid.uuid4().hex})
            assert result.status_code==422,result.text

def test_parallel_quota_never_exceeds_day_limit_and_rolls_back_partial_windows(monkeypatch):
    with client() as api:
        alina(api);uid=api.get('/api/me').json()['id']
        now=datetime(2026,11,9,9,13,tzinfo=timezone.utc)
        monkeypatch.setattr(improvements,'quota_limit',lambda bucket,period:3 if period==0 else 2)
        def reserve(_):
            with SessionLocal() as db:
                try:
                    improvements.reserve_write(db,uid,'security_probe',now);db.commit();return True
                except HTTPException as error:
                    db.rollback();assert error.status_code==429;return False
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(16)))
            assert sum(results)==2
            with SessionLocal() as db:
                counts=db.scalars(select(WriteQuota.count).where(WriteQuota.user_id==uid,WriteQuota.bucket.in_(['security_probe0','security_probe1']))).all()
                assert sorted(counts)==[2,2]
        finally:
            with SessionLocal() as db:
                db.execute(delete(WriteQuota).where(WriteQuota.user_id==uid,WriteQuota.bucket.in_(['security_probe0','security_probe1'])));db.commit()

def test_late_draft_cleanup_cannot_mutate_new_users_draft():
    # A deterministic callback-order test, not a real-browser or human test.
    root=Path(__file__).resolve().parents[1]
    source=r'''
const fs=require('fs'),vm=require('vm');
global.window={addEventListener:()=>{}};
global.document={addEventListener:()=>{},querySelector:()=>null,querySelectorAll:()=>[]};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
let release,startedResolve;const blocked=new Promise(r=>release=r),started=new Promise(r=>startedResolve=r);
const calls=[];
const context={state:{user:{id:1},sessionEpoch:1,pending:0},api:async(path,options)=>{
  calls.push({path,method:options.method,user:context.state.user.id});
  if(options.method==='PUT'){startedResolve();await blocked;}
  return {};
}};
const form={dataset:{cForm:'note'},id:'',elements:[{name:'body',type:'textarea',value:'Вымышленный текст'}],isConnected:false};
window.ATLASImprovements.init(context);
(async()=>{
 const save=window.ATLASImprovements.saveFormDraft(form);await started;
 const cleanup=window.ATLASImprovements.clearFormDraft(form);
 context.state.user={id:2};context.state.sessionEpoch++;
 release();await save;await cleanup;
 if(calls.some(c=>c.method==='DELETE'&&c.user===2))throw Error('Old user cleanup deleted the new user draft');
 process.stdout.write(JSON.stringify(calls));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result=subprocess.run(['node','-e',source,str(root/'static/improvements.js')],capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==[{'path':'drafts/note','user':1},{'path':'drafts/note','method':'PUT','user':1}]

