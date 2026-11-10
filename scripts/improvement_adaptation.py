"""Demonstrate a different fictional faculty on a fresh isolated database.

No existing database is accepted as a target; the working atlas.db is never read.
"""
from pathlib import Path
from contextlib import closing
import argparse,json,sqlite3,tempfile
from urllib.request import Request,urlopen
from http.cookiejar import CookieJar
from urllib.request import build_opener,HTTPCookieProcessor
from improvement_runtime import ROOT,DEFAULT_REPORTS,isolated_server,report_start,save_report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',type=Path,default=ROOT/'docs/examples/fictional-faculty.json')
    parser.add_argument('--output-db',type=Path)
    parser.add_argument('--report',type=Path,default=DEFAULT_REPORTS/'adaptation.json')
    args=parser.parse_args();report=report_start('Configuration-driven adaptation of a new fictional database; no real institution or user research.')
    profile=json.loads(args.profile.read_text(encoding='utf-8'))
    if args.output_db and args.output_db.exists():raise SystemExit('Refusing to change an existing database.')
    with tempfile.TemporaryDirectory(prefix='atlas-faculty-') as directory:
        target=args.output_db.resolve() if args.output_db else Path(directory)/'adapted.sqlite3'
        target.parent.mkdir(parents=True,exist_ok=True)
        try:
            with isolated_server(database_path=target) as server:
                with closing(sqlite3.connect(target)) as db:
                    for index,program in enumerate(profile['programs'],start=1):
                        db.execute('UPDATE users SET faculty=?,program=?,group_name=? WHERE id=?',(profile['faculty'],program['name'],program['group'],index))
                        subjects=db.execute('SELECT id,subject FROM grades WHERE student_id=? ORDER BY id',(index,)).fetchall()
                        for (grade_id,old),new in zip(subjects,program['subjects']):
                            for table,column in [('grades','subject'),('lessons','title'),('deadlines','subject'),('learning_courses','subject')]:
                                db.execute(f'UPDATE {table} SET {column}=? WHERE student_id=? AND {column}=?',(new,index,old))
                    db.commit()
                opener=build_opener(HTTPCookieProcessor(CookieJar()))
                def call(path,body=None):
                    req=Request(server['base']+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Requested-With':'ATLAS'})
                    with opener.open(req) as response:return json.loads(response.read())
                call('/api/login',{'login':'alina.demo','password':'AtlasDemo!2026-A'})
                user=call('/api/me');grades=call('/api/grades');courses=call('/api/learning/courses')
                assert user['faculty']==profile['faculty'] and user['program']==profile['programs'][0]['name']
                assert grades['items'][0]['subject']==profile['programs'][0]['subjects'][0]
                assert courses['items'][0]['subject']==grades['items'][0]['subject']
                request=call('/api/requests',{'type':'study','comment':'Проверка вымышленного факультета.'});assert request['id']
                report['checks']=['fresh database only','two fictional programs','profile/grades/courses agree','request workflow uses adapted profile']
                report['profile']=profile;report['new_database_retained']=str(target) if args.output_db else False
        except Exception:
            import traceback;report['failures'].append(traceback.format_exc())
    save_report(args.report,report);print(json.dumps({'status':report['status'],'failures':report['failures']},ensure_ascii=False))
    return int(report['status']!='PASS')
if __name__=='__main__':raise SystemExit(main())
