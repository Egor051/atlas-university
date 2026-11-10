"""Measure SQL query growth on isolated synthetic fixtures, not production data."""
from __future__ import annotations
import argparse
from datetime import timedelta
from pathlib import Path
import json
import os
import sys
import tempfile
import time
import traceback

from improvement_runtime import ROOT,DEFAULT_REPORTS,report_start,save_report
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=DEFAULT_REPORTS/'sql-growth.json')
    args=parser.parse_args()
    report=report_start('SQLAlchemy SELECT counter and real local ASGI API on isolated SQLite; no production database or user-behaviour claim.')
    report['budget']='For each endpoint, SELECT count after adding synthetic records <= baseline + 3; absolute <= 12.'
    directory=tempfile.TemporaryDirectory(prefix='atlas-improvement-sql-')
    os.environ.update(DATABASE_URL='sqlite:///'+(Path(directory.name)/'isolated.db').as_posix(),
                      APP_ENV='test',DEMO_MODE='true',COOKIE_SECURE='false',PUBLIC_ORIGIN='',ALLOWED_HOSTS='localhost,127.0.0.1,testserver')
    engine=None
    try:
        from app.main import app
        from app.db import SessionLocal,User,Grade,Deadline,utc_now,campus_today,engine
        from app.learning_db import Course,CourseModule
        from app.services_db import SupportTicket,TicketMessage
        from fastapi.testclient import TestClient
        from sqlalchemy import event,select
        queries=[]
        def count(_conn,_cursor,statement,_parameters,_context,_executemany):
            if statement.lstrip().upper().startswith('SELECT'):queries.append(statement)
        event.listen(engine,'before_cursor_execute',count)
        endpoints=['/api/learning/courses','/api/learning/assignments','/api/services/tickets?paginated=true&limit=100']
        report['samples']=[]
        with TestClient(app) as client:
            response=client.post('/api/login',json={'login':'alina.demo','password':'AtlasDemo!2026-A'},headers={'X-Requested-With':'ATLAS'})
            assert response.status_code==200,response.text
            def measure(phase):
                values={}
                for endpoint in endpoints:
                    queries.clear()
                    started=time.perf_counter();r=client.get(endpoint);elapsed=(time.perf_counter()-started)*1000
                    assert r.status_code==200,(endpoint,r.text)
                    data=r.json();count=len(queries)
                    values[endpoint]=count
                    report['samples'].append({'phase':phase,'endpoint':endpoint,'select_count':count,
                                               'elapsed_ms':round(elapsed,2),'returned_items':len(data.get('items',[]))})
                return values
            small=measure('seed baseline')
            with SessionLocal() as db:
                student=db.scalar(select(User).where(User.login=='alina.demo'))
                for i in range(40):
                    grade=Grade(student_id=student.id,subject=f'Синтетический курс {i}',kind='Баллы',current=75,max_grade=100,exam_kind='Зачёт',assessment='Зачтено',teacher='Вымышленный преподаватель',trend=0,color='purple')
                    db.add(grade);db.flush()
                    course=Course(student_id=student.id,grade_id=grade.id,subject=grade.subject,teacher=grade.teacher,credits=3,description='Измерительный пример.',color='purple')
                    db.add(course);db.flush()
                    db.add_all([CourseModule(course_id=course.id,position=j,title=f'Модуль {j}',content='Вымышленный учебный материал.',is_done=False) for j in range(4)])
                for i in range(100):
                    db.add(Deadline(student_id=student.id,subject='Синтетический предмет',title=f'Измерительное задание {i}',due_date=campus_today()+timedelta(days=10),is_done=False))
                    ticket=SupportTicket(student_id=student.id,topic='other',title=f'Синтетическая тема {i}',status='open',created_at=utc_now(),updated_at=utc_now())
                    db.add(ticket);db.flush()
                    db.add(TicketMessage(ticket_id=ticket.id,actor_id=student.id,actor_role='student',actor_name=student.full_name,body='Вымышленное сообщение только для проверки.',created_at=utc_now()))
                db.commit()
            large=measure('40 extra courses / 160 modules / 100 deadlines / 100 topics')
            for endpoint in endpoints:
                if large[endpoint]>small[endpoint]+3 or large[endpoint]>12:
                    report['failures'].append(f'Query growth budget exceeded: {endpoint}: {small[endpoint]} -> {large[endpoint]}')
            report['checks']=['isolated database','SELECT-only counter','small versus large fixture comparison','real authenticated ASGI requests']
        event.remove(engine,'before_cursor_execute',count)
    except Exception:report['failures'].append(traceback.format_exc())
    finally:
        if engine is not None:engine.dispose()
        directory.cleanup()
        save_report(args.report,report)
    print(json.dumps({'status':report['status'],'samples':report.get('samples'),'failures':report['failures']},ensure_ascii=False))
    return 1 if report['status']=='FAIL' else 0

if __name__=='__main__':raise SystemExit(main())
