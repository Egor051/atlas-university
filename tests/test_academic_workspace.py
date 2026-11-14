"""Academic writes use real scopes, history and serialized publication."""
import base64
import csv
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, time, timedelta, timezone
from io import BytesIO, StringIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from test_api import client, sign_in
from test_university_api import ACCOUNTS
from app.db import CAMPUS_TZ, campus_today
from app.table_formats import table_bytes

HEAD={'X-Requested-With':'ATLAS'}
ACTORS={**ACCOUNTS,'scheduler':('schedule.demo','AtlasRooms!2026-S'),'admin':('registry.demo','AtlasRegistry!2026-R')}


@pytest.fixture
def roles():
    with ExitStack() as stack:
        def open_role(role):
            api=stack.enter_context(client())
            sign_in(api,*ACTORS[role])
            return api
        yield open_role


def body(response,status=200):
    assert response.status_code==status,response.text
    return response.json()


def orlov(teacher):
    return body(teacher.get('/api/teaching'))['items'][0]


def new_slot(api, day):
    data=body(api.get('/api/scheduling/options'))
    load=next(row for row in data['loads'] if row['teacher']=='Михаил Орлов')
    teacher=next(row for row in data['teachers'] if row['name']=='Михаил Орлов')
    room=next(row for row in data['rooms'] if row['code']=='А-301')
    return dict(load_id=load['id'],teacher_id=teacher['id'],room_id=room['id'],day=day.isoformat(),
                start='18:00',end='19:00',kind='seminar',equipment='проектор',weeks=1)


def step(api, row, name, status=200, comment=''):
    return body(api.post(f"/api/scheduling/changes/{row['id']}/step",
                         json=dict(step=name,version=row['version'],comment=comment),headers=HEAD),status)


def test_assessment_history_roster_and_stale_writes(roles):
    teacher,student,other,colleague,admin=(roles(r) for r in ('teacher','student','other','colleague','admin'))
    load=orlov(teacher)
    path=f"/api/teaching/{load['id']}"
    own=body(teacher.get(path))['students'][0]
    outsider=body(other.get('/api/me'))['id']
    other_before = body(other.get('/api/grades'))
    assert own['id']!=outsider
    assert colleague.get(path).status_code==404
    assert admin.get(path).status_code==403
    assert teacher.get('/api/grades').status_code==403
    result=(own['grade']['score'] or 0)+4
    data={'student_id':own['id'],'score':result,'version':own['grade']['version'],'reason':'Решение задачи'}
    assert teacher.put(path+'/grade',json=data).status_code==403
    assert teacher.put(path+'/grade',json={**data,'student_id':outsider},headers=HEAD).status_code==404
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies=list(pool.map(lambda _:teacher.put(path+'/grade',json=data,headers=HEAD),range(2)))
    assert sorted(response.status_code for response in replies)==[200,409]
    present=dict(student_id=own['id'],day=campus_today().isoformat(),status='present',version=own['attendance']['version'])
    assert teacher.put(path+'/attendance',json={**present,'student_id':outsider},headers=HEAD).status_code==404
    body(teacher.put(path+'/attendance',json=present,headers=HEAD))
    records=body(teacher.get(path))
    assert records['students'][0]['grade']['score']==result
    assert records['students'][0]['attendance']['status']=='present'
    assert {x['action'] for x in records['history']} >= {'grade','attendance'}
    assert all(x['author']=='Михаил Орлов' and x['created_at'] for x in records['history'])
    assert next(x for x in body(student.get('/api/grades'))['items'] if x['subject']==load['discipline'])['score']==result
    assert body(other.get('/api/grades')) == other_before


def test_positive_awards_replay_and_aggregate(roles):
    teacher, student, other, staff = (roles(role) for role in ('teacher', 'student', 'other', 'staff'))
    endpoint = '/api/learning/progress'
    assert teacher.get(endpoint).status_code == 403
    assert staff.get(endpoint).status_code == 403
    subject = orlov(teacher)['discipline']
    other_before = body(other.get(endpoint))
    path = f"/api/teaching/{orlov(teacher)['id']}"
    roster = body(teacher.get(path))
    own = roster['students'][0]
    current = own['grade']['score'] or 0
    assert student.get(path + '/points/' + str(own['id'])).status_code == 403
    payload = dict(student_id=own['id'], points=4, version=own['grade']['version'], reason='Решение задачи')
    headers = {**HEAD, 'Idempotency-Key': str(uuid4())}
    assert teacher.post(path + '/points', json={**payload, 'points': -1}, headers=headers).status_code == 422
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: teacher.post(path + '/points', json=payload, headers=headers), range(2)))
    assert sorted(response.status_code for response in replies) == [200, 201]
    award = body(next(response for response in replies if response.status_code == 201), 201)
    assert award['score'] == current + 4
    assert teacher.post(path + '/points', json={**payload, 'points': 5}, headers=headers).status_code == 409
    for invalid in (current, None):
        assert teacher.put(path+'/grade', json=dict(student_id=own['id'], score=invalid, version=award['version']),
                           headers=HEAD).status_code == 422
    body(teacher.put(path + '/attendance', json=dict(student_id=own['id'], day=campus_today().isoformat(), status='absent',
                                                    version=own['attendance']['version']), headers=HEAD))
    summary = next(row for row in body(student.get(endpoint))['items'] if row['subject'] == subject)
    assert summary['earned_points'] == current + 4 and summary['missed'] >= 1
    assert summary['awards'][0]['points'] == 4 and sum(entry['points'] for entry in summary['awards']) == summary['earned_points']
    assert body(other.get(endpoint)) == other_before


def test_assessment_status_uses_result_and_date_not_points():
    from types import SimpleNamespace
    from app.academics import assessment_status

    current = campus_today()
    grade = SimpleNamespace(assessment='Допуск', exam_kind='Экзамен', exam_date=current + timedelta(days=1), current=2)
    assert assessment_status(grade, current)['code'] == 'soon'
    assert assessment_status(grade, current)['admission'] == 'Допущен'
    grade.exam_date = current - timedelta(days=1)
    assert assessment_status(grade, current)['code'] == 'waiting_result'
    grade.assessment = 'Экзамен сдан'
    assert assessment_status(grade, current)['code'] == 'passed'
    grade.assessment, grade.exam_date = '', None
    assert assessment_status(grade, current)['code'] == 'undated'
    grade.assessment = 'Не допущен'
    assert assessment_status(grade, current)['action'] == 'consultations'


def test_class_attendance_export_and_bulk_import(roles):
    from app.db import SessionLocal, utc_now
    from app.workspace_db import ScheduledClass
    from sqlalchemy import select

    teacher, student = roles('teacher'), roles('student')
    load = orlov(teacher)
    with SessionLocal.begin() as db:
        template = db.scalar(select(ScheduledClass).where(ScheduledClass.load_id == load['id']).limit(1))
        starts = utc_now() - timedelta(days=1)
        row = ScheduledClass(load_id=template.load_id, group_id=template.group_id, teacher_id=template.teacher_id,
                             room_id=template.room_id, starts_at=starts, ends_at=starts + timedelta(hours=1),
                             kind='seminar', note='Проверка алгоритмов', series=uuid4().hex, status='active')
        db.add(row)
        db.flush()
        class_id = row.id
    scope = load['id']
    journal = teacher.get(f'/api/tables/attendance/export?format=csv&scope={scope}&class_id={class_id}')
    assert journal.status_code == 200
    data = list(csv.DictReader(StringIO(journal.content.decode('utf-8-sig')), delimiter=';'))
    assert data and all(int(row['class_id']) == class_id for row in data)
    for row in data:
        row['status'] = 'late'
    fields = list(data[0])
    payload = {'format': 'csv', 'content': base64.b64encode(table_bytes('csv', fields, data)[0]).decode()}
    preview = body(teacher.post(f'/api/tables/attendance/preview?scope={scope}', json=payload, headers=HEAD))
    assert preview['fingerprint'] and not preview['errors']
    result = body(teacher.post(f'/api/tables/attendance/apply?scope={scope}',
                               json={**payload, 'fingerprint': preview['fingerprint']}, headers=HEAD))
    assert result['count'] == len(data)
    aggregate = next(row for row in body(student.get('/api/learning/progress'))['items'] if row['subject'] == load['discipline'])
    lesson = next(item for item in aggregate['classes'] if item['class_id'] == class_id)
    assert lesson['status'] == 'late' and lesson['topic'] == 'Проверка алгоритмов'
    assert aggregate['attendance_by_semester'][lesson['semester']]['visited'] >= 1


def test_work_feedback_and_group_consultation(roles):
    teacher,student,other,colleague=(roles(r) for r in ('teacher','student','other','colleague'))
    load=orlov(teacher)
    path=f"/api/teaching/{load['id']}/works"
    title='Разбор учебного графа '+uuid4().hex[:6]
    inputs=dict(title=title,instructions='Объясните, какие вершины посещает очередь.',due=(campus_today()+timedelta(days=4)).isoformat())
    record=body(teacher.post(path,json=inputs,headers=HEAD),201)
    assignment=next(row for row in body(student.get('/api/learning/assignments'))['items'] if row['title']==title)
    assert assignment['instructions']==inputs['instructions']
    assert all(row['title']!=title for row in body(other.get('/api/learning/assignments'))['items'])
    assert other.get(f"/api/learning/assignments/{assignment['id']}").status_code==404
    work_path=f"{path}/{record['id']}"
    assert colleague.get(work_path).status_code==404
    assert body(teacher.get(work_path))['submissions']==[]
    student_path=f"/api/learning/assignments/{assignment['id']}"
    submission=body(student.post(student_path+'/submit',json={'text':'Очередь последовательно посещает соседей графа.'},headers=HEAD))['submission']
    teacher_view=body(teacher.get(work_path))['submissions']
    assert [(row['id'],row['text'],row['version']) for row in teacher_view]==[
        (submission['id'],submission['text'],submission['version']),
    ]
    assert any('проверку' in n['title'] for n in body(teacher.get('/api/workspace/notices'))['items'])
    answer=dict(submitted_version=submission['version'],score=91,comment='Добавьте случай несвязного графа.')
    assert teacher.post(f"{work_path}/feedback/{submission['id']}",json={**answer,'submitted_version':9},headers=HEAD).status_code==409
    body(teacher.post(f"{work_path}/feedback/{submission['id']}",json=answer,headers=HEAD),201)
    assert body(teacher.get(work_path))['submissions'][0]['feedback'][0]['comment']==answer['comment']
    assert body(student.get(student_path))['feedback'][0]['score']==91
    start=datetime.combine(campus_today()+timedelta(days=10),time(20,0),CAMPUS_TZ)
    consultation=dict(load_id=load['id'],starts=start.isoformat(),ends=(start+timedelta(minutes=30)).isoformat(),
                      room='А-301',capacity=2)
    slot=body(teacher.post('/api/teaching/consultations',json=consultation,headers=HEAD),201)['id']
    assert teacher.post('/api/teaching/consultations',json=consultation,headers=HEAD).status_code==409
    same_room={**consultation,'load_id':orlov(colleague)['id'],'room':'а-301'}
    assert colleague.post('/api/teaching/consultations',json=same_room,headers=HEAD).status_code==409
    assert other.post(f'/api/services/consultations/{slot}/book',json={},headers=HEAD).status_code==404
    body(student.post(f'/api/services/consultations/{slot}/book',json={},headers=HEAD),201)
    own=next(item for item in body(teacher.get('/api/teaching/consultations'))['items'] if item['id']==slot)
    assert own['students']==['Алина Ветрова']
    assert colleague.post(f'/api/teaching/consultations/{slot}/complete',headers=HEAD).status_code==404


def test_schedule_roles_series_conflicts_move_and_cancel(roles):
    dispatcher,dean,admin,student,other,teacher=(roles(r) for r in ('scheduler','staff','admin','student','other','teacher'))
    day=campus_today()+timedelta(days=18)
    slot={**new_slot(dispatcher,day),'weeks':2}
    draft_data={'action':'create','slot':slot,'note':'Демонстрационный разбор'}
    endpoint='/api/scheduling/changes'
    assert dean.post(endpoint,json=draft_data,headers=HEAD).status_code==403
    assert student.get('/api/scheduling').status_code==403
    assert dispatcher.get('/api/schedule').status_code==403
    assert dispatcher.post(endpoint,json={**draft_data,'slot':{**slot,'kind':'lab'}},headers=HEAD).status_code==422
    row=body(dispatcher.post(endpoint,json=draft_data,headers=HEAD),201)
    row=step(dispatcher,row,'submit')
    step(dispatcher,row,'agree',403)
    row=step(dean,row,'agree')
    step(dean,row,'publish',403)
    row=step(admin,row,'publish')
    event=row['event_id']
    items=lambda api, target: [lesson for date in body(api.get('/api/schedule',params={'week':target.isoformat()}))['days']
                              for lesson in date['items']]
    assert any(x['id']==1000000000+event for x in items(student,day))
    assert any(x['start']=='18:00' and x['date']==str(day+timedelta(days=7)) for x in items(student,day+timedelta(days=7)))
    assert not any(x['id']==1000000000+event for x in items(other,day))
    assert any(x.get('id')==event for x in body(teacher.get('/api/teaching/schedule',params={'week':str(day)}))['items'])
    assert dispatcher.post(endpoint,json=draft_data,headers=HEAD).status_code==409
    update={'action':'update','event_id':event,'event_version':1,
            'slot':{**slot,'weeks':1,'start':'19:00','end':'20:00','kind':'lecture'},'note':'Перенос по времени'}
    row=body(dispatcher.post(endpoint,json=update,headers=HEAD),201)
    step(admin,step(dean,step(dispatcher,row,'submit'),'agree'),'publish')
    assert any(x['id']==1000000000+event and x['start']=='19:00' and x['changed'] for x in items(student,day))
    cancel={'action':'cancel','event_id':event,'event_version':2,'note':'Вымышленная причина отмены'}
    row=body(dispatcher.post(endpoint,json=cancel,headers=HEAD),201)
    step(admin,step(dean,step(dispatcher,row,'submit'),'agree'),'publish')
    assert not any(x['id']==1000000000+event for x in items(student,day))
    assert any(n['title']=='Занятие отменено' for n in body(student.get('/api/notifications?filter=schedule')))


def test_concurrent_publication_resolves_shared_room_conflict(roles):
    dispatcher,dean,admin=(roles(r) for r in ('scheduler','staff','admin'))
    slot=new_slot(dispatcher,campus_today()+timedelta(days=26))
    rows=[]
    for note in ('Проект А','Проект Б'):
        row=body(dispatcher.post('/api/scheduling/changes',json={'action':'create','slot':slot,'note':note},headers=HEAD),201)
        rows.append(step(dean,step(dispatcher,row,'submit'),'agree'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda row:admin.post(f"/api/scheduling/changes/{row['id']}/step",json={
            'step':'publish','version':row['version']},headers=HEAD),rows))
    assert sorted(response.status_code for response in results)==[200,409]


def upload(format,headers,rows,mapping=None):
    data,_=table_bytes(format,headers,rows)
    return {'format':format,'content':base64.b64encode(data).decode(),'mapping':mapping or {}}


def test_spreadsheet_rejects_unreadable_or_active_files_without_changes(roles):
    dispatcher=roles('scheduler')
    initial=body(dispatcher.get('/api/registry'))['rooms']
    example={'building':'Учебный корпус','code':'АТ-ТЕСТ','capacity':30,'kind':'lab'}
    data,_=table_bytes('xlsx',list(example),[example])
    external=BytesIO(data)
    external.seek(0,2)
    with ZipFile(external,'a') as workbook:
        workbook.writestr('xl/test.rels','<Relationships><Relationship TargetMode="External" '
                         'Target="https://example.invalid/table" /></Relationships>')
    oversized=BytesIO()
    with ZipFile(oversized,'w',compression=ZIP_DEFLATED) as workbook:
        workbook.writestr('xl/test.xml',b' ' * 1_200_001)
    for format,content in [('csv',b'\xff\xfe'),('xlsx',b'not an XLSX file'),
                           ('xlsx',external.getvalue()),('xlsx',oversized.getvalue())]:
        invalid={'format':format,'content':base64.b64encode(content).decode()}
        assert dispatcher.post('/api/tables/rooms/preview',json=invalid,headers=HEAD).status_code==422
        assert dispatcher.post('/api/tables/rooms/apply',json={**invalid,'fingerprint':'0'*64},headers=HEAD).status_code==422
    assert body(dispatcher.get('/api/registry'))['rooms']==initial


def test_spreadsheet_reports_out_of_range_numeric_cell(roles):
    dispatcher=roles('scheduler')
    row={'building':'Учебный корпус','code':'АТ-РАЗМЕР','capacity':'1e1000000','kind':'lab'}
    payload=upload('csv',list(row),[row])
    preview=body(dispatcher.post('/api/tables/rooms/preview',json=payload,headers=HEAD))
    assert preview['fingerprint'] is None
    assert preview['errors']==[{'row':2,'message':'capacity — Число вне допустимого диапазона'}]


def test_spreadsheet_preview_mapping_atomicity_permissions_and_replay(roles):
    dispatcher,admin,teacher,student=(roles(r) for r in ('scheduler','admin','teacher','student'))
    assert body(admin.get('/api/registry'))['students']
    for dataset in ('schedule','rooms','groups','loads','students'):
        for format in ('csv','xlsx'):
            response=admin.get(f'/api/tables/{dataset}/export?format={format}')
            assert response.status_code==200 and format in response.headers['content-disposition']
    assert student.get('/api/tables/rooms/export').status_code==403
    assert admin.get('/api/tables/grades/export').status_code==403
    assert dispatcher.get('/api/tables/students/export').status_code==403
    assert teacher.get('/api/tables/grades/export?scope=99999').status_code==404
    code='ДЕМ-'+uuid4().hex[:7]
    first={'Корпус':'Тестовый корпус','Номер':code,'Места':30,'Тип':'lab'}
    columns=list(first)
    invalid=upload('xlsx',columns,[first,{**first,'Номер':code+'-Б','Места':0}],
                   {'building':'Корпус','code':'Номер','capacity':'Места','kind':'Тип'})
    preview_path='/api/tables/rooms/preview'
    assert body(dispatcher.post(preview_path,json={**invalid,'mapping':{}},headers=HEAD))['missing']
    preview=body(dispatcher.post(preview_path,json=invalid,headers=HEAD))
    assert preview['errors'][0]['row']==3 and preview['fingerprint'] is None
    assert dispatcher.post('/api/tables/rooms/apply',json={**invalid,'fingerprint':'0'*64},headers=HEAD).status_code==422
    assert not any(row['code']==code for row in body(dispatcher.get('/api/registry'))['rooms'])
    good=upload('xlsx',columns,[first],invalid['mapping'])
    preview=body(dispatcher.post(preview_path,json=good,headers=HEAD))
    assert preview['fingerprint']
    good['fingerprint']=preview['fingerprint']
    saved=body(dispatcher.post('/api/tables/rooms/apply',json=good,headers=HEAD))
    assert saved['count']==1
    assert body(dispatcher.post('/api/tables/rooms/apply',json=good,headers=HEAD))['replayed']
    assert sum(row['code']==code for row in body(dispatcher.get('/api/registry'))['rooms'])==1
    scope=orlov(teacher)['id']
    mark=body(teacher.get(f'/api/teaching/{scope}'))['students'][0]
    current=mark['grade']['score'] or 0
    grades=upload('csv',['student_id','score','version'],[
        {'student_id':mark['id'],'score':current+1,'version':mark['grade']['version']}])
    receipt=body(teacher.post(f'/api/tables/grades/preview?scope={scope}',json=grades,headers=HEAD))
    assert receipt['fingerprint'] and not receipt['errors']
    body(teacher.put(f'/api/teaching/{scope}/grade',json={
        'student_id':mark['id'],'score':current+2,'version':mark['grade']['version']},headers=HEAD))
    assert teacher.post(f'/api/tables/grades/apply?scope={scope}',json={
        **grades,'fingerprint':receipt['fingerprint']},headers=HEAD).status_code==409
