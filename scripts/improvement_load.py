"""A bounded real-HTTP load experiment, not production capacity certification.

Default profile: isolated SQLite, 1,000 library books, 350 support topics,
100 notes per student, two fictional accounts, 8 concurrent clients / 800 reads.
Only loopback servers are supported by this runner.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
import json
import math
import platform
import statistics
import subprocess
import sys
import time
import traceback

import httpx
from improvement_runtime import ROOT,DEFAULT_REPORTS,isolated_server,report_start,save_report

FIXTURE = r'''
from app.main import app
from app.db import SessionLocal, User, utc_now
from app.services_db import LibraryBook,SupportTicket,TicketMessage
from app.learning_db import StudyNote
from sqlalchemy import select
with SessionLocal() as db:
    users=db.scalars(select(User).where(User.role=='student')).all()
    db.add_all([LibraryBook(title=f'Нагрузочная книга {i:04}',author='Вымышленный автор',subject='Нагрузочный стенд',description='Искусственные данные только для измерения.',total=2,available=2) for i in range(1000)])
    for user in users:
        db.add_all([StudyNote(student_id=user.id,title=f'Заметка {i:03}',subject='Нагрузочный стенд',body='Искусственный учебный текст.',created_at=utc_now(),updated_at=utc_now()) for i in range(100)])
        for i in range(175):
            row=SupportTicket(student_id=user.id,topic='other',title=f'Нагрузочная тема {i:03}',status='open',created_at=utc_now(),updated_at=utc_now())
            db.add(row);db.flush()
            db.add(TicketMessage(ticket_id=row.id,actor_id=user.id,actor_role='student',actor_name=user.full_name,body='Вымышленное обращение для измерения.',created_at=utc_now()))
    db.commit()
print('fixture complete')
'''


def percentile(values,p):
    values=sorted(values)
    return round(values[max(0,math.ceil(len(values)*p)-1)],2) if values else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients',type=int,default=8)
    parser.add_argument('--requests',type=int,default=800)
    parser.add_argument('--report',type=Path,default=DEFAULT_REPORTS/'load.json')
    args=parser.parse_args()
    assert 1<=args.clients<=32 and args.clients<=args.requests<=5000
    report=report_start('Real local HTTP and isolated fictional SQLite; bounded mixed reads/writes with same-key replay. No real users, public-site traffic or production capacity claim.')
    report['environment']={'python':platform.python_version(),'os':platform.platform(),'workers':1,'database':'SQLite'}
    report['declared_profile']={'clients':args.clients,'read_requests':args.requests,'extra_library_books':1000,
                                'extra_support_tickets':350,'extra_notes_per_student':100,'think_time_ms':5,
                                'acceptance':'0 unexpected responses; p95 <= 1000ms on this declared local profile'}
    try:
        with isolated_server() as server:
            fixture=subprocess.run([sys.executable,'-c',FIXTURE],cwd=ROOT,env=server['env'],capture_output=True,text=True,timeout=45)
            assert fixture.returncode==0,fixture.stderr[-3000:]
            endpoints=['/api/dashboard','/api/grades','/api/schedule','/api/requests?paginated=true&limit=30',
                       '/api/learning/courses','/api/learning/assignments','/api/services/library?paginated=true&limit=30',
                       '/api/services/tickets?paginated=true&limit=30','/api/services/consultations?paginated=true&limit=30',
                       '/api/services/events?paginated=true&limit=30']
            # Two logins total; clients replay their own account's cookie. No login-limit bypass.
            cookies=[]
            with httpx.Client(base_url=server['base'],timeout=20) as client:
                for login,password in [('alina.demo','AtlasDemo!2026-A'),('mark.demo','AtlasDemo!2026-M')]:
                    response=client.post('/api/login',json={'login':login,'password':password},headers={'X-Requested-With':'ATLAS','Origin':server['base']})
                    assert response.status_code==200,response.text
                    cookies.append(dict(response.cookies))
                health=client.get('/api/health').json()
            report['app_health']=health
            mixed_writes=[]
            def worker(index):
                rows=[]
                with httpx.Client(base_url=server['base'],timeout=20,cookies=cookies[index%2]) as client:
                    for n in range(index,args.requests,args.clients):
                        endpoint=endpoints[n%len(endpoints)]
                        started=time.perf_counter()
                        try:
                            response=client.get(endpoint)
                            elapsed=(time.perf_counter()-started)*1000
                            rows.append({'endpoint':endpoint,'ms':round(elapsed,2),'status':response.status_code,'bytes':len(response.content)})
                        except Exception as exc:
                            rows.append({'endpoint':endpoint,'ms':round((time.perf_counter()-started)*1000,2),'status':0,'error':type(exc).__name__})
                        time.sleep(.005)
                        if (n//args.clients)%20==0:
                            payload={'topic':'academic','title':f'Нагрузочный вопрос {index}-{n}','message':'Вымышленный вопрос только для измерения безопасного сохранения.'}
                            headers={'X-Requested-With':'ATLAS','Origin':server['base'],'Idempotency-Key':f'load-{index}-{n:05}'}
                            saved_at=time.perf_counter()
                            first=client.post('/api/services/tickets',json=payload,headers=headers)
                            replay=client.post('/api/services/tickets',json=payload,headers=headers)
                            assert first.status_code==201 and replay.status_code==200,(first.status_code,replay.status_code)
                            assert first.json()['id']==replay.json()['id']
                            mixed_writes.append({'actor':index%2,'create_status':201,'replay_status':200,'same_id':True,'write_and_replay_ms':round((time.perf_counter()-saved_at)*1000,2)})
                return rows
            start=time.perf_counter()
            with ThreadPoolExecutor(max_workers=args.clients) as pool:
                rows=[row for result in pool.map(worker,range(args.clients)) for row in result]
            elapsed=time.perf_counter()-start
            report['duration_seconds']=round(elapsed,3)
            report['throughput_reads_per_second']=round(len(rows)/elapsed,2)
            report['total_reads']=len(rows)
            report['mixed_writes']={'created':len(mixed_writes),'replayed':len(mixed_writes),'unexpected_duplicates':0,'write_and_replay_p95_ms':percentile([r['write_and_replay_ms'] for r in mixed_writes],.95),'actors':sorted({r['actor'] for r in mixed_writes})}
            report['p50_ms']=percentile([r['ms'] for r in rows],.5)
            report['p95_ms']=percentile([r['ms'] for r in rows],.95)
            report['p99_ms']=percentile([r['ms'] for r in rows],.99)
            report['endpoints']=[{'endpoint':p,'samples':sum(r['endpoint']==p for r in rows),
                                  'p95_ms':percentile([r['ms'] for r in rows if r['endpoint']==p],.95)} for p in endpoints]
            report['unexpected_responses']=[r for r in rows if r['status']!=200]
            if report['unexpected_responses']:report['failures'].append('Unexpected HTTP responses')
            if report['p95_ms']>1000:report['failures'].append('Declared local p95 budget exceeded')
            assert len(rows)==args.requests
            report['checks']=['real HTTP','isolated fixtures','both fictional student accounts','declared data volume','latency distribution','no unexpected errors' if not report['unexpected_responses'] else 'errors recorded']
    except Exception:
        report['failures'].append(traceback.format_exc())
    finally:save_report(args.report,report)
    print(json.dumps({k:report.get(k) for k in ['status','total_reads','p50_ms','p95_ms','p99_ms','throughput_reads_per_second','failures']},ensure_ascii=False))
    return 1 if report['status']=='FAIL' else 0

if __name__=='__main__':raise SystemExit(main())
