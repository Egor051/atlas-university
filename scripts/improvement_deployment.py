"""Verify current code on a new PostgreSQL + Caddy HTTPS stack.

Uses a unique Compose project, new volumes, local-only :19443 and ephemeral
random passwords. It never connects to a pre-existing application database.
Runtime secrets are never written into the report. Docker Desktop/Engine must
already be running. The stack is stopped afterwards; its test volumes remain.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from improvement_runtime import ROOT,DEFAULT_REPORTS,report_start,save_report


class Client:
    def __init__(self,base,context):self.base=base;self.context=context;self.cookie=''
    def call(self,path,body=None,expected=200,headers=None,method=None):
        headers={'Origin':self.base,**(headers or {})}
        if self.cookie:headers['Cookie']=self.cookie
        if body is not None:headers.update({'Content-Type':'application/json','X-Requested-With':'ATLAS'})
        request=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:response=urlopen(request,context=self.context,timeout=30)
        except HTTPError as exc:response=exc
        raw=response.read()
        assert response.status in ([expected] if isinstance(expected,int) else expected),(path,response.status,raw[:250])
        cookie=response.headers.get('Set-Cookie','')
        if cookie.startswith('atlas_session='):
            assert all(x in cookie.lower() for x in ['secure','httponly','samesite=lax'])
            self.cookie=cookie.split(';',1)[0]
        data=json.loads(raw) if 'json' in response.headers.get('Content-Type','') else raw
        return data
    def login(self,index,**options):
        names=[('alina.demo','AtlasDemo!2026-A'),('mark.demo','AtlasDemo!2026-M'),('dean.demo','AtlasStaff!2026-D')]
        login,password=names[index]
        return self.call('/api/login',{'login':login,'password':password},**options)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=DEFAULT_REPORTS/'postgres-https.json')
    parser.add_argument('--keep-running',action='store_true',help='Keep only this newly created isolated stack running for follow-up checks.')
    parser.add_argument('--legacy-source',type=Path,help='Optional trusted 3.2.0 checkout: exercise its schema/data upgrading to the current code in a NEW test database.')
    args=parser.parse_args()
    report=report_start('Current local source built into a new Docker project: PostgreSQL, two web workers and Caddy HTTPS verified with explicit local CA. No public DNS/ACME, Russian connection or physical-device claim.')
    project='atlas-improvements-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')+'-'+secrets.token_hex(2)
    env={**os.environ,'DOMAIN':'localhost','POSTGRES_PASSWORD':secrets.token_hex(24),'ATLAS_APP_PASSWORD':secrets.token_hex(24),'DEMO_MODE':'true'}
    command=['docker','compose','-p',project,'-f','compose.yaml','-f','compose.improvements.yaml']
    report['project']=project;report['origin']='https://localhost:19443';report['credentials_included']=False
    started=False
    def scrub(value):
        for secret in [env['POSTGRES_PASSWORD'],env['ATLAS_APP_PASSWORD']]:value=value.replace(secret,'<redacted>')
        return value
    def run(*arguments,timeout=180,raw=False,input_data=None):
        result=subprocess.run([*command,*arguments],cwd=ROOT,env=env,capture_output=True,timeout=timeout,input=input_data)
        if result.returncode:raise RuntimeError(scrub(result.stderr.decode('utf-8','replace')[-5000:]))
        return result.stdout if raw else result.stdout.decode('utf-8','replace').strip()
    def sql(query,database='atlas'):
        return run('exec','-T','db','psql','-U','atlas_admin','-d',database,'-At','-v','ON_ERROR_STOP=1','-c',query)
    def snapshot(database='atlas'):
        tables=sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",database).splitlines()
        result={}
        for table in tables:
            assert re.fullmatch(r'[a-z_][a-z_0-9]*',table)
            digest=sql("SELECT json_build_object('rows',count(*),'md5',md5(COALESCE(string_agg(row_to_json(t)::text, E'\\n' ORDER BY row_to_json(t)::text),''))) FROM \""+table+'\" t',database)
            result[table]=json.loads(digest)
        return result
    def race(clients,path):
        barrier=threading.Barrier(len(clients))
        def invoke(client):
            barrier.wait()
            # The losers' 409 must be observed, rather than hidden by Client assertions.
            headers={'Origin':client.base,'Cookie':client.cookie,'Content-Type':'application/json','X-Requested-With':'ATLAS','Idempotency-Key':str(uuid.uuid4())}
            req=Request(client.base+path,data=b'{}',headers=headers)
            try:r=urlopen(req,context=client.context,timeout=30)
            except HTTPError as exc:r=exc
            return {'status':r.status,'data':json.loads(r.read())}
        with ThreadPoolExecutor(max_workers=len(clients)) as pool:return list(pool.map(invoke,clients))
    def verify_legacy_upgrade(source):
        """Use an actual previous release's models, not current metadata mocks.

        No database file is copied. The old code is mounted only by copying its
        app sources into this stack's temporary filesystem, then points at a
        newly created database owned by this stack's unprivileged app role.
        """
        source=source.resolve()
        assert (source/'app/db.py').is_file() and (source/'app/learning_db.py').is_file(),'Legacy source must contain the complete app package'
        database='atlas_upgrade_'+secrets.token_hex(4)
        run('exec','-T','db','createdb','-U','atlas_admin','-O','atlas_app',database)
        run('exec','-T','web','mkdir','-p','/tmp/atlas-legacy')
        bundle=io.BytesIO()
        with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((source/'app').glob('*.py')):
                archive.write(path,'app/'+path.name)
        # `docker cp` cannot reliably address a runtime tmpfs on Docker Desktop;
        # the container process writes its own temporary directory via stdin.
        extract="import io,sys,zipfile;zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).extractall('/tmp/atlas-legacy')"
        run('exec','-T','web','python','-c',extract,input_data=bundle.getvalue())
        # Run in a new interpreter rooted at the OLD app directory, with only
        # DATABASE_URL switched to the freshly created database.
        fixture=r'''
import os,json
from datetime import datetime,timezone
os.environ['DATABASE_URL']=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/'+__import__('sys').argv[1]
from app.db import initialize_database,SessionLocal,SchemaMigration,utc_now,DocumentRequest,RequestEvent
from app.learning_db import StudyNote,PersonalTask,Flashcard,FocusSession
from app.campus_db import PortfolioItem
from app.improvement_db import PersonalDraft
from app.services_db import ServiceIdempotency,SupportTicket
from app.main import request_with_history
from sqlalchemy import select,func
initialize_database()
with SessionLocal() as db:
 versions=db.scalars(select(SchemaMigration.version)).all()
 assert '0005_contest_hardening' in versions and '0006_audit_integrity' not in versions,versions
 now=utc_now();day=now.date()
 note=StudyNote(student_id=1,title='Legacy preserved note',subject='Legacy fixture',body='Fictional legacy note body',created_at=now,updated_at=now)
 task=PersonalTask(student_id=1,title='Legacy preserved task',subject='Legacy fixture',due_date=day,priority='normal',is_done=False,created_at=now)
 card=Flashcard(student_id=1,subject='Legacy fixture',front='Legacy question',back='Legacy answer',due_date=day,reviews=2,known_count=1,interval_days=1)
 focus=FocusSession(student_id=1,subject='Legacy fixture',minutes=17,created_at=now)
 portfolio=PortfolioItem(student_id=1,title='Legacy preserved portfolio',kind='project',description='Fictional legacy portfolio',url='',day=day,updated_at=now)
 db.add_all([note,task,card,focus,portfolio]);db.flush()
 ids={}
 for kind,row in [('note',note),('task',task),('flashcard',card),('focus',focus),('portfolio',portfolio)]:
  ids[kind]=row.id
  db.add(PersonalDraft(user_id=1,name=f'{kind}:{row.id}',values_json=json.dumps({'body':f'Unbound legacy {kind} content'},sort_keys=True),updated_at=now))
 request=db.scalar(select(DocumentRequest).where(DocumentRequest.student_id==1))
 payload=request_with_history(request,db)
 receipt=ServiceIdempotency(user_id=1,operation=f'request-followup:{request.id}',key='migration-preserved-receipt',payload_hash='a'*64,response_json=json.dumps(payload,ensure_ascii=False,sort_keys=True),created_at=now)
 db.add(receipt);db.commit()
 print(json.dumps({'versions':versions,'record_ids':ids,'receipt_payload':payload},ensure_ascii=False,default=str))
'''
        legacy=json.loads(run('exec','-T','-w','/tmp/atlas-legacy','web','python','-c',fixture,database))
        # Compare all original columns in every table, excluding only the
        # explicitly versioned receipt representation and migration ledger.
        schema=json.loads(sql("SELECT json_object_agg(table_name,cols) FROM (SELECT table_name,json_agg(column_name ORDER BY ordinal_position) AS cols FROM information_schema.columns WHERE table_schema='public' GROUP BY table_name) c",database))
        def original_rows():
            output={}
            for table,columns in sorted(schema.items()):
                assert re.fullmatch(r'[a-z_][a-z_0-9]*',table) and all(re.fullmatch(r'[a-z_][a-z_0-9]*',column) for column in columns)
                if table == 'schema_migrations':continue
                if table == 'service_idempotency':columns=[column for column in columns if column != 'response_json']
                names=','.join('"'+column+'"' for column in columns)
                output[table]=json.loads(sql("SELECT json_build_object('rows',count(*),'md5',md5(COALESCE(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text),''))) FROM (SELECT "+names+' FROM "'+table+'") t',database))
            return output
        before=original_rows()
        migrate="import os,sys;os.environ['DATABASE_URL']=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/'+sys.argv[1];from app.db import migrate_database;migrate_database();print('migrated')"
        run('exec','-T','web','python','-c',migrate,database)
        assert before==original_rows(),'Original PostgreSQL fields changed during additive upgrade'
        verification=r'''
import os,sys,json
os.environ['DATABASE_URL']=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/'+sys.argv[1]
from app.db import SessionLocal,SchemaMigration
from app.learning_db import StudyNote,PersonalTask,Flashcard,FocusSession
from app.campus_db import PortfolioItem
from app.improvement_db import PersonalDraft
from app.services_db import ServiceIdempotency
from app.receipt_codec import decode_receipt
from sqlalchemy import select,func
with SessionLocal() as db:
 versions=db.scalars(select(SchemaMigration.version)).all()
 assert '0006_audit_integrity' in versions
 tokens={}
 for model in (StudyNote,PersonalTask,Flashcard,FocusSession,PortfolioItem):
  rows=db.scalars(select(model)).all()
  assert rows and all(len(row.record_token)==32 and all(c in '0123456789abcdef' for c in row.record_token) for row in rows)
  assert len({row.record_token for row in rows})==len(rows)
  tokens[model.__tablename__]=len(rows)
 receipt=db.scalar(select(ServiceIdempotency).where(ServiceIdempotency.key=='migration-preserved-receipt'))
 payload=decode_receipt(db,json.loads(receipt.response_json))
 drafts=[dict(name=row.name,values=json.loads(row.values_json)) for row in db.scalars(select(PersonalDraft).where(PersonalDraft.user_id==1))]
 print(json.dumps({'versions':versions,'record_tokens':tokens,'receipt_payload':payload,'preserved_drafts':drafts},ensure_ascii=False,default=str))
'''
        upgraded=json.loads(run('exec','-T','web','python','-c',verification,database))
        assert upgraded['receipt_payload']==legacy['receipt_payload'],'Legacy idempotent response changed after compaction'
        assert len(upgraded['preserved_drafts'])==5 and all('Unbound legacy' in row['values']['body'] for row in upgraded['preserved_drafts'])
        first=snapshot(database)
        run('exec','-T','web','python','-c',migrate,database)
        assert snapshot(database)==first,'A second upgrade altered the migrated database'
        report['legacy_upgrade']={'new_database':database,'source_release':'3.2.0 / schema0005','target_revision':'0006_audit_integrity',
                                  'tables_with_original_columns_unchanged':len(before),'all_original_column_digests_equal':True,
                                  'tokens_backfilled':upgraded['record_tokens'],'legacy_drafts_preserved_unbound':5,
                                  'idempotent_replay_exact':True,'second_upgrade_unchanged':True}
        report['checks'].append('actual 3.2.0 PostgreSQL schema/data upgrades additively: original column digests, five token models, raw drafts, exact receipt replay and repeat migration preserved')
        print('Verified actual legacy PostgreSQL upgrade and unchanged original data',flush=True)
    try:
        assert subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True).returncode==0,'Docker Engine is unavailable'
        run('config','--quiet');report['checks'].append('isolated Compose configuration valid')
        started=True
        print('Building isolated PostgreSQL/HTTPS stack '+project,flush=True)
        run('up','-d','--build','--wait','--wait-timeout','240',timeout=720)
        report['checks'].append('new stack built and healthy')
        if args.legacy_source:
            verify_legacy_upgrade(args.legacy_source)
        with tempfile.TemporaryDirectory(prefix='atlas-improvement-tls-') as folder:
            ca=Path(folder)/'local-test-ca.crt'
            run('cp','caddy:/data/caddy/pki/authorities/local/root.crt',str(ca))
            context=ssl.create_default_context(cafile=str(ca))
            monitor_path=args.report.parent/'local-readiness-monitor.json'
            monitor=subprocess.run([sys.executable,str(ROOT/'scripts/improvement_monitor.py'),'--url',report['origin'],
                '--ca',str(ca),'--checks','3','--interval','1','--report',str(monitor_path)],capture_output=True,text=True,timeout=45)
            assert monitor.returncode==0,'Certificate-verified local readiness monitor failed'
            report['checks'].append('three actual local readiness samples with certificate verification; no future-uptime claim')
            students=[Client(report['origin'],context),Client(report['origin'],context)]
            staff=Client(report['origin'],context)
            a,b=students;a.login(0);b.login(1);staff.login(2)
            report['health']=a.call('/api/health');assert a.call('/api/ready')['ok']
            assert a.call('/api/me')['group']!=b.call('/api/me')['group']
            report['checks'].append('TLS certificate verified against explicit local CA; Secure/HttpOnly/SameSite cookies')
            deadline_id = int(sql("INSERT INTO deadlines (student_id, subject, title, due_date, is_done) "
                                  "SELECT id, 'ATLAS verification', 'Reminder race', "
                                  "(now() AT TIME ZONE 'Europe/Moscow')::date, false "
                                  "FROM users WHERE login='mark.demo' RETURNING id").splitlines()[0])
            with ThreadPoolExecutor(max_workers=2) as pool:
                reminder_counts = list(pool.map(lambda _: b.call('/api/notifications/deadline-reminders', {})['created'], range(2)))
            assert min(reminder_counts) == 0 < max(reminder_counts), reminder_counts
            reminder_target = f'/app/assignments?id={deadline_id}'
            assert sum(item['target'] == reminder_target for item in b.call('/api/notifications?filter=deadline')) == 1
            assert all(item['target'] != reminder_target for item in a.call('/api/notifications?filter=deadline'))
            report['checks'].append('PostgreSQL concurrent reminders count committed inserts and store one notice for its owner')
            # Fill only synthetic sessions in this newly created test database.
            # Distinct addresses are injected solely by Caddyfile.test's local
            # trusted-proxy route, so the account cap is tested across IP locks.
            existing=int(sql("SELECT count(*) FROM login_sessions WHERE user_id=(SELECT id FROM users WHERE login='alina.demo')"))
            for _ in range(max(0,19-existing)):
                sql("INSERT INTO login_sessions(token_hash,user_id,expires_at) SELECT '"+secrets.token_hex(32)+"',id,now()+interval '1 day' FROM users WHERE login='alina.demo'")
            login_barrier=threading.Barrier(2)
            def concurrent_login(index):
                client=Client(report['origin'],context)
                login_barrier.wait()
                for _ in range(8):
                    result=client.login(0,expected=[200,429],headers={'X-Atlas-Test-IP':f'198.18.200.{index+1}'})
                    if 'user' in result:return result['user']['id']
                    time.sleep(1)
                raise AssertionError('Admission never became available for a valid login')
            with ThreadPoolExecutor(max_workers=2) as pool:
                concurrent_users=list(pool.map(concurrent_login,range(2)))
            session_count=int(sql("SELECT count(*) FROM login_sessions WHERE user_id=(SELECT id FROM users WHERE login='alina.demo')"))
            assert len(set(concurrent_users))==1 and session_count==20,(concurrent_users,session_count)
            report['session_cap_race']={'initial':19,'concurrent_logins':2,'different_test_client_ips':True,'final':session_count}
            report['checks'].append('two real concurrent valid logins from distinct trusted test IPs preserve the global 20-session account cap')
            print('Verified HTTPS cookies and concurrent 20-session account cap',flush=True)
            key=str(uuid.uuid4());body={'type':'study','comment':'Изолированная проверка текущего развёртывания, все данные вымышлены.'}
            request=a.call('/api/requests',body,expected=201,headers={'Idempotency-Key':key})
            repeat=a.call('/api/requests',body,headers={'Idempotency-Key':key})
            assert request['id']==repeat['id']
            request_id=request['id'];b.call(f'/api/requests/{request_id}',expected=404)
            for status in ['review','processing','ready']:
                current=staff.call(f'/api/staff/requests/{request_id}')
                staff.call(f'/api/staff/requests/{request_id}/status',{'status':status,'expected_version':current['version'],'message':'Демонстрационный результат подготовлен в изолированной проверке.'})
            assert a.call(f'/api/requests/{request_id}')['status']=='ready'
            assert len(a.call(f'/api/requests/{request_id}/document'))>100
            b.call('/api/staff/requests',expected=403);staff.call('/api/grades',expected=403)
            report['checks'].append('two students, IDOR/roles, idempotency, complete staff workflow and private document')
            # Concurrent per-owner draft cap under PostgreSQL, not just SQLite.
            for i in range(39):a.call('/api/drafts/deploy-'+str(i),{'values':{'body':'Вымышленный черновик.'}},method='PUT')
            def save_last(i):return a.call('/api/drafts/race-'+str(i),{'values':{'body':'Последнее место черновика.'}},expected=[200,409],method='PUT')
            with ThreadPoolExecutor(max_workers=10) as pool:draft_results=list(pool.map(save_last,range(10)))
            assert sum(r.get('saved',False) for r in draft_results)==1
            assert int(sql("SELECT count(*) FROM personal_drafts WHERE user_id=1"))==40
            assert b.call('/api/drafts/deploy-0')['values']=={}
            report['checks'].append('PostgreSQL draft cap race: 39 existing + 10 concurrent saves yields one winner, owner isolation preserved')
            print('Verified request workflow, owner isolation and concurrent draft cap',flush=True)
            follow=a.call('/api/requests',{'type':'study'},expected=201)
            follow_body={'message':'Вымышленное уточнение для конкурентной проверки.','expected_version':follow['version']}
            follow_key=uuid.uuid4().hex
            def clarify(_):return a.call('/api/requests/'+str(follow['id'])+'/followup',follow_body,headers={'Idempotency-Key':follow_key})
            with ThreadPoolExecutor(max_workers=2) as pool:follow_results=list(pool.map(clarify,range(2)))
            assert all(x['version']==follow['version']+1 for x in follow_results)
            assert len(a.call('/api/requests/'+str(follow['id']))['history'])==2
            report['checks'].append('PostgreSQL same-key follow-up race appends one event and increments one version')


            # Persist actual new module data, then verify every database table through restart/restore.
            note=a.call('/api/learning/notes',{'title':'Проверка PostgreSQL','subject':'Вымышленная дисциплина','body':'Сохраняемый текст только для изолированной приёмки.'},expected=201)
            b.call(f'/api/learning/notes/{note["id"]}',expected=404)
            assignments=a.call('/api/learning/assignments')['items']
            a.call(f'/api/learning/assignments/{assignments[0]["id"]}/submit',{'text':'Демонстрационное решение с объяснением результата.','url':'https://atlas.example/fictional-work'})
            courses=a.call('/api/learning/courses')['items'];course=courses[0];module=course['modules'][0]
            a.call(f'/api/learning/courses/{course["id"]}/modules/{module["id"]}',{'is_done':True})
            ticket=a.call('/api/services/tickets',{'topic':'other','title':'Проверка PostgreSQL переписки','message':'Вымышленное сообщение для проверки переноса и восстановления.'},expected=201,headers={'Idempotency-Key':str(uuid.uuid4())})
            staff.call(f'/api/staff/tickets/{ticket["id"]}/messages',{'message':'Вымышленный ответ сотрудника сохранён.'},headers={'Idempotency-Key':str(uuid.uuid4())})
            portfolio=a.call('/api/campus/portfolio',{'title':'Сохраняемый учебный проект','kind':'project','description':'Конкурсная вымышленная запись.','url':'','day':datetime.now(timezone.utc).date().isoformat()},expected=201)
            b.call(f'/api/campus/portfolio/{portfolio["id"]}',{'title':'Чужая правка','kind':'project','description':'Нет доступа.','url':'','day':datetime.now(timezone.utc).date().isoformat()},expected=404)
            report['checks'].append('learning modules, assignment submission, note, support thread/reply and portfolio persisted with owner checks')

            start=datetime.now(timezone.utc)+timedelta(days=4)
            slot=staff.call('/api/staff/consultations',{'teacher':'Вымышленный преподаватель','subject':'Гонка за одно место','start_at':start.isoformat(),'end_at':(start+timedelta(hours=1)).isoformat(),'room':'Т-101','capacity':1},expected=201,headers={'Idempotency-Key':str(uuid.uuid4())})
            slot_race=race(students,f'/api/services/consultations/{slot["id"]}/book')
            assert sorted(x['status'] for x in slot_race)==[201,409],slot_race
            event=staff.call('/api/staff/events',{'title':'Одно место на вымышленном событии','category':'academic','description':'Изолированная проверка конкуренции без реальных участников.','start_at':start.isoformat(),'end_at':(start+timedelta(hours=1)).isoformat(),'location':'Тестовый корпус','capacity':1},expected=201,headers={'Idempotency-Key':str(uuid.uuid4())})
            event_race=race(students,f'/api/services/events/{event["id"]}/register')
            assert sorted(x['status'] for x in event_race)==[201,409],event_race
            book_id=int(sql("INSERT INTO library_books(title,author,subject,description,total,available) VALUES ('Один тестовый экземпляр','Вымышленный автор','Приёмка','Изолированная проверка.',1,1) RETURNING id").splitlines()[0])
            book_race=race(students,f'/api/services/library/{book_id}/borrow')
            assert sorted(x['status'] for x in book_race)==[201,409],book_race
            report['concurrency']={'consultation':slot_race,'event':event_race,'library_book':book_race}
            report['checks'].append('real concurrent last-place and last-copy requests across PostgreSQL/two workers yield one winner')
            # Count+insert must be serialized for the account even when the
            # requests use different idempotency keys and different workers.
            # Seed only this newly created fictional database, without spending
            # the public write quota on 199 synthetic setup requests per type.
            cap_specs = [
                ('notes', 'learning_notes',
                 'student_id,title,subject,body,created_at,updated_at',
                 "1,'Synthetic note '||n,'Cap regression','Fictional text',now(),now()",
                 {'title':'Последнее место заметки','subject':'Проверка лимита','body':'Вымышленный текст.'}),
                ('tasks', 'learning_tasks',
                 'student_id,title,subject,due_date,priority,is_done,created_at',
                 "1,'Synthetic task '||n,'Cap regression',current_date,'normal',false,now()",
                 {'title':'Последнее место задачи','subject':'Проверка лимита','due_date':datetime.now(timezone.utc).date().isoformat(),'priority':'normal','is_done':False}),
                ('flashcards', 'learning_flashcards',
                 'student_id,subject,front,back,due_date,reviews,known_count,interval_days',
                 "1,'Cap regression','Synthetic question '||n,'Fictional answer',current_date,0,0,0",
                 {'subject':'Проверка лимита','front':'Последнее место карточки?','back':'Вымышленный ответ.'}),
                ('portfolio', 'portfolio_items',
                 'student_id,title,kind,description,url,day,updated_at',
                 "1,'Synthetic portfolio '||n,'project','Fictional description','',current_date,now()",
                 {'title':'Последнее место портфолио','kind':'project','description':'Вымышленная запись.','url':'','day':datetime.now(timezone.utc).date().isoformat()}),
            ]
            report['personal_cap_races'] = {}
            for resource, table, columns, values, payload in cap_specs:
                count = int(sql(f'SELECT count(*) FROM {table} WHERE student_id=1'))
                assert count <= 199, (resource, count)
                sql(f'INSERT INTO {table}({columns}) SELECT {values} FROM generate_series(1,{199-count}) AS n')
                path = '/api/campus/portfolio' if resource == 'portfolio' else '/api/learning/'+resource
                start_cap = threading.Barrier(2)
                def add_last(_):
                    start_cap.wait()
                    return a.call(path,payload,expected=[201,409],headers={'Idempotency-Key':uuid.uuid4().hex})
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(add_last,range(2)))
                assert sum('id' in result for result in results) == 1, (resource,results)
                assert int(sql(f'SELECT count(*) FROM {table} WHERE student_id=1')) == 200,resource
                assert len(a.call(path)['items']) == 200,resource
                # Existing over-cap databases are still readable in full after
                # upgrade; the cap prevents new writes, never hides saved rows.
                sql(f'INSERT INTO {table}({columns}) SELECT {values} FROM generate_series(10000,10000) AS n')
                assert len(a.call(path)['items']) == 201,resource
                a.call(path,payload,expected=409,headers={'Idempotency-Key':uuid.uuid4().hex})
                report['personal_cap_races'][resource]={'initial':199,'concurrent_creates':2,'winners':1,'after_race':200,
                                                        'legacy_over_cap_rows':201,'all_saved_rows_visible':True}
            report['checks'].append('PostgreSQL notes/tasks/flashcards/portfolio: 199 + two concurrent creates has one winner; all 201 legacy rows remain visible')
            print('Verified concurrent resource caps and complete legacy-row access',flush=True)

            # Real PostgreSQL sessions return offset-aware timestamps according
            # to each connection's TimeZone. Test both directions rather than
            # merely comparing two naive UTC values in a unit test.
            offset_client=Client(report['origin'],context)
            offset_client.login(1,headers={'X-Atlas-Test-IP':'198.18.200.20'})
            token_hash=hashlib.sha256(offset_client.cookie.split('=',1)[1].encode()).hexdigest()
            sql("UPDATE login_sessions SET expires_at=now()-interval '1 hour' WHERE token_hash='"+token_hash+"'")
            sql("ALTER DATABASE atlas SET timezone TO 'Europe/Moscow'")
            run('restart','web');run('up','-d','--wait','--wait-timeout','180',timeout=240)
            before_quota=sql('SELECT COALESCE(sum(count),0) FROM write_quotas WHERE user_id=2')
            offset_client.call('/api/grades',expected=401)
            offset_client.call('/api/drafts/expired-offset',{'values':{'body':'Never saved'}},expected=401,method='PUT')
            assert sql('SELECT COALESCE(sum(count),0) FROM write_quotas WHERE user_id=2') == before_quota
            sql("UPDATE login_sessions SET expires_at=now()+interval '1 hour' WHERE token_hash='"+token_hash+"'")
            sql("ALTER DATABASE atlas SET timezone TO 'Etc/GMT+3'")
            run('restart','web');run('up','-d','--wait','--wait-timeout','180',timeout=240)
            offset_client.call('/api/grades')
            offset_client.call('/api/drafts/valid-offset',{'values':{'body':'Valid offset session'}},method='PUT')
            sql('ALTER DATABASE atlas RESET timezone')
            run('restart','web');run('up','-d','--wait','--wait-timeout','180',timeout=240)
            report['session_timezone']={'utc_plus_3_expired_read_status':401,'utc_plus_3_expired_write_status':401,
                                         'expired_session_quota_unchanged':True,'utc_minus_3_unexpired_read_status':200,
                                         'utc_minus_3_unexpired_write_status':200}
            report['checks'].append('real PostgreSQL UTC+3 expired sessions reject reads/writes without quota charge; UTC-3 unexpired sessions remain valid')
            print('Verified actual PostgreSQL session expiry in UTC+3 and UTC-3',flush=True)
            before=snapshot()
            run('stop','db')
            assert a.call('/api/health')['ok']
            assert a.call('/api/ready',expected=503)['ok'] is False
            run('start','db');run('up','-d','--wait','--wait-timeout','180',timeout=240)
            assert a.call('/api/ready')['ok']
            assert snapshot()==before,'Database rows changed during the isolated outage check'
            report['checks'].append('stopping only this test DB yields live HTTP health200/readiness503; readiness recovers to200 with all row digests unchanged')
            run('restart','db','web');run('up','-d','--wait','--wait-timeout','180',timeout=240)
            after=snapshot();assert before==after,'Database rows changed across restart'
            assert a.call(f'/api/learning/notes/{note["id"]}')['body'].startswith('Сохраняемый текст')
            report['restart_persistence']={'tables':len(before),'all_table_digests_equal':True}
            report['checks'].append('all table row counts and sorted-row digests identical across DB/web restart')

            source=snapshot()
            run('exec','-T','db','pg_dump','-U','atlas_admin','-d','atlas','-Fc','-f','/tmp/atlas-improvement.dump')
            restore='atlas_restore_improvements_'+secrets.token_hex(4)
            run('exec','-T','db','createdb','-U','atlas_admin',restore)
            run('exec','-T','db','pg_restore','-U','atlas_admin','-d',restore,'--exit-on-error','--single-transaction','/tmp/atlas-improvement.dump')
            restored=snapshot(restore);assert source==restored,'Restored rows do not match source'
            dump=Path(folder)/'atlas-improvement.dump';run('cp','db:/tmp/atlas-improvement.dump',str(dump))
            report['backup_restore']={'new_database':restore,'source_database_overwritten':False,'tables':len(source),
                'all_table_digests_equal':True,'dump_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'source':source,'restored':restored}
            report['checks'].append('pg_dump/pg_restore into a new DB reproduces every table, including all extension entities')
            print('Verified database outage recovery, restart persistence and full backup restoration',flush=True)
            # Current source provenance is compared to the files actually served by the new image.
            code="import hashlib,json,pathlib;print(json.dumps({p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for d in ['app','static'] for p in pathlib.Path(d).glob('*') if p.is_file()}))"
            image_hash=json.loads(run('exec','-T','web','python','-c',code))
            compared={name:image_hash.get(name)==digest for name,digest in report['source_sha256'].items() if name.startswith(('app/','static/'))}
            assert all(compared.values()),'Image source differs from baseline source'
            report['image_sources_match']=compared
            report['postgres_version']=sql('SHOW server_version')
            report['role_security']=json.loads(sql("SELECT json_build_object('role',rolname,'superuser',rolsuper,'createdb',rolcreatedb,'createrole',rolcreaterole) FROM pg_roles WHERE rolname='atlas_app'"))
            assert not any(report['role_security'][x] for x in ['superuser','createdb','createrole'])
            report['checks'].append('running image source hashes match current files; application PostgreSQL role remains unprivileged')
            report['not_verified']=['public hosting','public CA/DNS','Russian connection','physical phone','future uptime to 28 November']
    except Exception:report['failures'].append(scrub(traceback.format_exc()))
    finally:
        if started and not args.keep_running:
            try:run('down',timeout=90);report['teardown']={'containers_and_networks_stopped':True,'only_unique_project':project,'new_test_volumes_preserved':True}
            except Exception as exc:report['failures'].append('Isolated teardown: '+scrub(str(exc)))
        save_report(args.report,report)
    print(json.dumps({'status':report['status'],'project':project,'checks':len(report['checks']),'failures':report['failures']},ensure_ascii=False))
    return 1 if report['status']=='FAIL' else 0

if __name__=='__main__':raise SystemExit(main())
