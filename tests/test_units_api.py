"""Union and VUC workflows use their own role and record boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, time, timedelta
import uuid

import pytest

from test_academic_workspace import ACTORS, HEAD, body
from test_api import client, sign_in
from app.db import CAMPUS_TZ, campus_today

ROLES={**ACTORS,'union':('union.demo','AtlasUnion!2026-U'),'vuc':('vuc.demo','AtlasCenter!2026-V')}


@pytest.fixture
def units():
    with ExitStack() as stack:
        def open_role(role):
            api=stack.enter_context(client())
            sign_in(api,*ROLES[role])
            return api
        yield open_role


def move(api,path,row,status,**fields):
    return body(api.post(f"{path}/{row['id']}/step",json={'status':status,'version':row['version'],**fields},headers=HEAD))


def test_union_membership_clarification_decision_and_departure(units):
    student,other,union,vuc,dean=(units(r) for r in ('student','other','union','vuc','staff'))
    path='/api/units/union/cases'
    assert union.get('/api/grades').status_code==403
    assert union.get('/api/staff/requests').status_code==403
    assert dean.get(path).status_code==403
    assert vuc.get(path).status_code==403
    key={**HEAD,'Idempotency-Key':uuid.uuid4().hex}
    submitted=body(student.post(path,json={'kind':'join','confirmed':True},headers=key),201)
    assert body(student.post(path,json={'kind':'join','confirmed':True},headers=key))==submitted
    assert student.post(path,json={'kind':'join','confirmed':True},headers=HEAD).status_code==409
    owned=f"{path}/{submitted['id']}"
    assert student.get(owned,params={'before':2**64}).status_code==422
    assert student.get(f'{path}/{2**64}').status_code==422
    assert other.get(owned).status_code==404
    assert union.get(owned.replace('/union/','/vuc/')).status_code==403
    assert vuc.get(owned.replace('/union/','/vuc/')).status_code==404
    assert student.post(owned+'/step',json={'status':'review','version':1},headers=HEAD).status_code==403
    review=move(union,path,submitted,'review')
    clarified=move(union,path,review,'needs_info',message='Подтвердите вымышленное вступление.')
    assert other.post(owned+'/followup',json={'message':'Учебный пример','version':clarified['version']},headers=HEAD).status_code==404
    followup=body(student.post(owned+'/followup',json={'message':'Подтверждаю учебный пример.','version':clarified['version']},headers=HEAD))
    assert not body(student.get(owned))['can_followup']
    assert union.post(owned+'/step',json={'status':'review','version':clarified['version']},headers=HEAD).status_code==409
    accepted=move(union,path,move(union,path,followup,'review'),'accepted',message='Демонстрационное членство оформлено.')
    assert body(student.get('/api/units/union'))['member']['active']
    assert not body(other.get('/api/units/union'))['member']['active']
    assert other.get(accepted['file_url']).status_code==404
    assert 'все данные вымышлены' in student.get(accepted['file_url']).text
    assert len(body(student.get(owned))['history'])==6
    assert any(n['target']==f"/app/union/{accepted['id']}" for n in body(student.get('/api/notifications?filter=union')))
    aid=body(student.post(path,json={'kind':'aid','message':'Учебная заявка на поддержку проекта.'},headers=HEAD),201)
    move(union,path,move(union,path,aid,'review'),'accepted',message='Решение о демонстрационной помощи.')
    leave=body(student.post(path,json={'kind':'leave','confirmed':True},headers=HEAD),201)
    move(union,path,move(union,path,leave,'review'),'accepted',message='Демонстрационное членство завершено.')
    assert not body(student.get('/api/units/union'))['member']['active']


def test_vuc_application_selection_group_result_and_scoped_publications(units):
    student,other,vuc,union,admin=(units(r) for r in ('student','other','vuc','union','admin'))
    path='/api/units/vuc/cases'
    overview=body(student.get('/api/units/vuc'))
    program=overview['programs'][0]
    data={'kind':'apply','confirmed':True,'program_id':program['id'],'checklist':list(overview['checklist'])}
    assert student.post(path,json={**data,'medical_file':'sample'},headers=HEAD).status_code==422
    assert student.post(path,json={**data,'message':'В заявлении заполняют только флажки'},headers=HEAD).status_code==422
    assert student.post(path,json={**data,'checklist':[]},headers=HEAD).status_code==422
    application=body(student.post(path,json=data,headers=HEAD),201)
    assert body(student.get('/api/units/vuc/learning'))['enrollments']==[]
    group=next(x for x in body(vuc.get('/api/units/vuc/learning'))['groups'] if x['program_id']==program['id'])
    other_group=next(x for x in body(vuc.get('/api/units/vuc/learning'))['groups'] if x['program_id']!=program['id'])
    record=f"{path}/{application['id']}"
    assert other.get(record).status_code==404
    assert admin.get(record).status_code==403
    assert union.get(record).status_code==403
    review=move(vuc,path,application,'review')
    assert vuc.post(record+'/step',json={'status':'accepted','group_id':group['id'],'version':review['version'],
                                       'message':'Образец одобрен'},headers=HEAD).status_code==409
    selection=move(vuc,path,review,'selection')
    assert vuc.post(record+'/step',json={'status':'accepted','group_id':other_group['id'],'version':selection['version'],
                                       'message':'Образец одобрен'},headers=HEAD).status_code==422
    result=move(vuc,path,selection,'accepted',message='Учебная группа назначена.',group_id=group['id'])
    learning=body(student.get('/api/units/vuc/learning'))
    assert len(learning['sessions'])==1 and learning['groups'][0]['id']==group['id']
    assert body(other.get('/api/units/vuc/learning'))['sessions']==[]
    enrollment=learning['enrollments'][0]
    change={'outcome':'passed','comment':'Демонстрационный практикум зачтён.','version':enrollment['version']}
    result_path=f"/api/units/vuc/learning/results/{enrollment['id']}"
    assert union.put(result_path,json=change,headers=HEAD).status_code==403
    body(vuc.put(result_path,json=change,headers=HEAD))
    assert vuc.put(result_path,json=change,headers=HEAD).status_code==409
    assert body(student.get('/api/units/vuc/learning'))['enrollments'][0]['outcome']=='passed'
    assert other.get(result['file_url']).status_code==404
    post=body(vuc.put('/api/units/vuc/publications',json={'kind':'material','title':'Групповая памятка',
        'body':'<b>Вымышленное описание</b> для учебной группы.', 'group_id':group['id']},headers=HEAD))
    assert '&lt;b&gt;' in student.get(post['file_url']).text
    assert other.get(post['file_url']).status_code==404
    assert union.get(post['file_url']).status_code==403
    assert other.get('/api/units/vuc/report').status_code==403
    assert vuc.get('/api/units/vuc/report?format=xlsx').content.startswith(b'PK')
    assert any(x['action']=='result' for x in body(vuc.get('/api/units/vuc/history'))['items'])
    assert any(n['title']=='Результат ВУЦ обновлён' for n in body(student.get('/api/notifications?filter=vuc')))


def test_unit_publication_and_center_schedule_management(units):
    vuc,union,student=(units(role) for role in ('vuc','union','student'))
    now=campus_today()
    program={'title':'Новая учебная программа '+uuid.uuid4().hex[:6],
             'description':'Организационная демонстрация работы с учебным календарём.',
             'requirements':'Заполните демонстрационный чек-лист.',
             'opens':now.isoformat(),'closes':(now+timedelta(days=30)).isoformat()}
    path='/api/units/vuc/learning'
    assert union.put(path+'/programs',json=program,headers=HEAD).status_code==403
    created=body(vuc.put(path+'/programs',json=program,headers=HEAD))
    group=body(vuc.put(path+'/groups',json={'program_id':created['id'],'code':'ДЕМО-'+uuid.uuid4().hex[:6],'capacity':8},headers=HEAD))
    start=datetime.combine(now+timedelta(days=4),time(18,15),CAMPUS_TZ)
    session=dict(group_id=group['id'],title='Демонстрационный календарь',room='Кабинет АТ-314',
                 starts=start.isoformat(),ends=(start+timedelta(hours=1)).isoformat())
    entry=body(vuc.put(path+'/sessions',json=session,headers=HEAD))
    assert vuc.put(path+'/sessions',json=session,headers=HEAD).status_code==409
    assert student.put(path+'/sessions',json=session,headers=HEAD).status_code==403
    body(vuc.put(path+'/sessions',json={**session,'id':entry['id'],'version':entry['version'],'cancelled':True},headers=HEAD))
    assert not any(x['id']==entry['id'] for x in body(student.get(path))['sessions'])
    post=body(union.put('/api/units/union/publications',json={'title':'Новая консультация',
        'kind':'news','body':'Учебная консультация по заявкам на членство.'},headers=HEAD))
    assert any(x['id']==post['id'] for x in body(student.get('/api/units/union'))['publications'])
    assert vuc.put('/api/units/vuc/publications',json={
        'id':post['id'],'version':post['version'],'title':'Чужая запись','kind':'news','body':'Вымышленное содержимое.'},headers=HEAD).status_code==404


def test_center_acceptance_preserves_one_place_when_decisions_are_concurrent(units):
    student,other,worker=(units(role) for role in ('student','other','vuc'))
    today=campus_today()
    path='/api/units/vuc'
    program=body(worker.put(path+'/learning/programs',json={'title':'Практикум '+uuid.uuid4().hex[:6],
        'description':'Демонстрационная работа с календарём.','requirements':'Два учебных подтверждения.',
        'opens':today.isoformat(),'closes':(today+timedelta(days=14)).isoformat()},headers=HEAD))
    group=body(worker.put(path+'/learning/groups',json={
        'program_id':program['id'],'code':'ВУЦ-'+uuid.uuid4().hex[:6],'capacity':1},headers=HEAD))
    rows=[]
    for actor in (student,other):
        row=body(actor.post(path+'/cases',json={'kind':'apply','confirmed':True,'program_id':program['id'],
            'checklist':['sample_application','sample_status']},headers=HEAD),201)
        rows.append(move(worker,path+'/cases',move(worker,path+'/cases',row,'review'),'selection'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        def accept(row):
            return worker.post(f"{path}/cases/{row['id']}/step",json={'status':'accepted','version':row['version'],
                'group_id':group['id'],'message':'Учебная запись назначена.'},headers=HEAD)
        results=list(pool.map(accept, rows))
    assert sorted(result.status_code for result in results)==[200,409]
    roster=body(worker.get(path+'/learning'))['enrollments']
    assert sum(record['group_id']==group['id'] for record in roster)==1
