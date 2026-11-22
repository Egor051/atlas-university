"""Union and VUC workflows use their own role and record boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from datetime import date, timedelta
import uuid

import pytest

from test_academic_workspace import ACTORS, HEAD, body
from test_api import client, sign_in
from app import vuc, vuc_policy

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
    assert 'Заявление №' in student.get(accepted['file_url']).text
    assert len(body(student.get(owned))['history'])==6
    assert any(n['target']==f"/app/union/{accepted['id']}" for n in body(student.get('/api/notifications?filter=union')))
    aid=body(student.post(path,json={'kind':'aid','message':'Учебная заявка на поддержку проекта.'},headers=HEAD),201)
    move(union,path,move(union,path,aid,'review'),'accepted',message='Решение о демонстрационной помощи.')
    leave=body(student.post(path,json={'kind':'leave','confirmed':True},headers=HEAD),201)
    move(union,path,move(union,path,leave,'review'),'accepted',message='Демонстрационное членство завершено.')
    assert not body(student.get('/api/units/union'))['member']['active']



BASE = '/api/units/vuc/admission'
APPLICATIONS = BASE + '/applications'
DAY = date(2026, 11, 22)
SOURCE = {
    'source_title': 'Источник для проверки на отдельной базе',
    'source_url': 'https://vucmsu.ru/mem.html',
    'verified_on': DAY.isoformat(),
}
PROGRAM_FIELDS = ('title', 'category', 'outcome', 'duration_months', 'academic_link', 'requirements',
                  'selection', 'state', 'source_title', 'source_url', 'verified_on')
CAMPAIGN_FIELDS = ('program_id', 'academic_year', 'title', 'state', 'opens_on', 'closes_on', 'intake_enabled',
                   'seats', 'documents', 'procedure', 'requirements', 'stages', 'source_title', 'source_url', 'verified_on')


@pytest.fixture
def today(monkeypatch):
    def set_day(day):
        monkeypatch.setattr(vuc, 'campus_today', lambda: day)
    set_day(DAY)
    return set_day


def program_body(**fields):
    return {
        'title': 'Изолированная проверка ' + uuid.uuid4().hex[:8],
        'category': 'officer_reserve', 'outcome': 'Подготовка к зачислению в запас.',
        'academic_link': 'Условия направления устанавливает ВУЦ.',
        'state': 'active', **SOURCE, **fields,
    }


def campaign_body(program_id, **fields):
    return {
        'program_id': program_id, 'academic_year': DAY.year, 'title': 'Проверка кампании ' + uuid.uuid4().hex[:8],
        'state': 'published', 'opens_on': DAY.isoformat(), 'closes_on': (DAY + timedelta(days=7)).isoformat(),
        'documents': ['Заявление по утверждённой форме'], 'procedure': 'Передайте комплект сотруднику ВУЦ.',
        'stages': {'medical': {'details': 'По направлению ВУЦ.'}}, **SOURCE, **fields,
    }


def update(api, path, row, keys, **fields):
    payload = {key: row[key] for key in keys}
    return api.put(path, json={**payload, 'id': row['id'], 'version': row['version'], **fields}, headers=HEAD)


def test_vuc_catalog_visibility_sources_and_academic_years(units, today):
    student, worker, teacher = (units(role) for role in ('student', 'vuc', 'teacher'))
    catalog = body(student.get(BASE))
    assert {'officer_reserve', 'sergeant_reserve', 'soldier_reserve'} <= {item['category'] for item in catalog['programs']}
    assert all(not item['title'].startswith('Организация учебного процесса') for item in catalog['programs'])
    assert 'Гражданство РФ' in catalog['federal_requirements'][0]
    assert {'medical', 'psychological', 'physical', 'formalities'} <= catalog['stages'].keys()
    assert teacher.get(BASE).status_code == 403
    new_program = program_body()
    assert teacher.put(BASE + '/programs', json=new_program, headers=HEAD).status_code == 403
    assert student.put(BASE + '/programs', json=new_program, headers=HEAD).status_code == 403
    assert worker.put(BASE + '/programs', json=new_program).status_code == 403
    assert worker.put(BASE + '/programs', json={**new_program, 'source_url': 'javascript:alert(1)'}, headers=HEAD).status_code == 422
    program = body(worker.put(BASE + '/programs', json=new_program, headers=HEAD))
    assert program['duration_months'] is None
    first_day = DAY + timedelta(days=1)
    draft = body(worker.put(BASE + '/campaigns', json=campaign_body(
        program['id'], opens_on=first_day.isoformat(), state='draft',
    ), headers=HEAD))
    request = {'campaign_id': draft['id'], 'confirmed': True}
    assert student.post(APPLICATIONS, json=request, headers=HEAD).status_code == 404
    assert all(item['id'] != draft['id'] for item in body(student.get(BASE))['campaigns'])
    path = BASE + '/campaigns'
    assert update(worker, path, draft, CAMPAIGN_FIELDS, state='published', source_title='').status_code == 422
    assert update(worker, path, draft, CAMPAIGN_FIELDS, state='published', documents=[]).status_code == 422
    assert update(worker, path, draft, CAMPAIGN_FIELDS, opens_on='2026-12-01').status_code == 422
    assert update(worker, path, draft, CAMPAIGN_FIELDS, stages={'medical': {
        'starts_on': '2026-12-20', 'ends_on': '2026-12-10',
    }}).status_code == 422
    published = body(update(worker, path, draft, CAMPAIGN_FIELDS, state='published'))
    assert published['status'] == 'upcoming'
    assert published['seats'] is None
    assert student.post(APPLICATIONS, json=request, headers=HEAD).status_code == 409
    assert update(worker, path, draft, CAMPAIGN_FIELDS, state='published').status_code == 409

    today(first_day)
    def read_campaign():
        return next(item for item in body(student.get(BASE))['campaigns'] if item['id'] == published['id'])
    assert read_campaign()['status'] == 'open'
    program_path = BASE + '/programs'
    edited_program = body(update(worker, program_path, program, PROGRAM_FIELDS, state='inactive', title=program['title'] + ' II'))
    assert read_campaign()['status'] == 'program_inactive'
    assert student.post(APPLICATIONS, json=request, headers=HEAD).status_code == 409
    body(update(worker, program_path, edited_program, PROGRAM_FIELDS, state='active'))
    changed = body(update(worker, path, published, CAMPAIGN_FIELDS, closes_on=first_day.isoformat()))
    assert changed['status'] == 'open'
    today(first_day + timedelta(days=1))
    assert read_campaign()['status'] == 'documents_closed'
    assert student.post(APPLICATIONS, json=request, headers=HEAD).status_code == 409
    archived = body(update(worker, path, changed, CAMPAIGN_FIELDS, state='archived'))
    assert read_campaign()['program']['title'] == program['title']
    assert update(worker, path, archived, CAMPAIGN_FIELDS, opens_on=None).status_code == 409
    assert student.post(APPLICATIONS, json=request, headers=HEAD).status_code == 409

    next_year = date(2027, 9, 15)
    today(next_year)
    next_campaign = body(worker.put(path, json=campaign_body(
        program['id'], academic_year=next_year.year, opens_on=None, closes_on=None,
        documents=[], procedure='', stages={},
    ), headers=HEAD))
    assert next_campaign['status'] == 'awaiting_dates'
    assert next_campaign['program']['title'] == edited_program['title']
    assert read_campaign()['status'] == 'archived'
    assert all(item['id'] != next_campaign['id'] or item['academic_year'] == 2027 for item in body(student.get(BASE))['campaigns'])


def test_vuc_records_require_evidence_and_are_visible_only_to_owner_and_vuc(units, today):
    student, other, worker, teacher, dean, union = (units(role) for role in
                                                    ('student', 'other', 'vuc', 'teacher', 'staff', 'union'))
    program = body(worker.put(BASE + '/programs', json=program_body(), headers=HEAD))
    campaign = body(worker.put(BASE + '/campaigns', json=campaign_body(program['id']), headers=HEAD))
    payload = {'campaign_id': campaign['id'], 'confirmed': True}
    assert student.post(APPLICATIONS, json={**payload, 'student_id': 2}, headers=HEAD).status_code == 422
    assert student.post(APPLICATIONS, json={**payload, 'medical_file': 'value'}, headers=HEAD).status_code == 422
    assert student.post(APPLICATIONS, json={**payload, 'confirmed': False}, headers=HEAD).status_code == 422
    assert student.post('/api/units/vuc/cases', json={'kind': 'apply'}, headers=HEAD).status_code == 410
    headers = {**HEAD, 'Idempotency-Key': uuid.uuid4().hex}
    application = body(student.post(APPLICATIONS, json=payload, headers=headers), 201)
    assert body(student.post(APPLICATIONS, json=payload, headers=headers)) == application
    assert student.post(APPLICATIONS, json=payload, headers=HEAD).status_code == 409
    path = f"{APPLICATIONS}/{application['id']}"
    step = path + '/step'
    assert other.get(path).status_code == 404
    assert other.get(path, params={'before': 1}).status_code == 404
    assert body(other.get(APPLICATIONS, params={'campaign_id': campaign['id']}))['items'] == []
    assert next(item for item in body(other.get(BASE))['campaigns'] if item['id'] == campaign['id'])['application_id'] is None
    for denied in (teacher, dean, union):
        assert denied.get(path).status_code == 403
    initial = {'version': application['version'], 'status': 'enrolled', 'message': 'Изолированная проверка.'}
    assert student.post(step, json=initial, headers=HEAD).status_code == 403
    assert teacher.post(step, json=initial, headers=HEAD).status_code == 403
    assert worker.post(step, json=initial, headers=HEAD).status_code == 409

    def payload_for(status, **values):
        return {'version': application['version'], 'status': status, 'message': 'Следующее действие в изолированном тесте.', **values}

    evidence = {'basis_ref': 'Тестовый документ № 1', 'basis_on': DAY.isoformat()}
    assert worker.post(step, json=payload_for('documents_received'), headers=HEAD).status_code == 422
    application = body(worker.post(step, json=payload_for('documents_received', **evidence), headers=HEAD))
    application = body(worker.post(step, json=payload_for('needs_documents'), headers=HEAD))
    assert worker.post(step, json=payload_for('preliminary'), headers=HEAD).status_code == 409
    application = body(worker.post(step, json=payload_for('documents_received', **evidence), headers=HEAD))
    application = body(worker.post(step, json=payload_for('preliminary'), headers=HEAD))
    assert worker.post(step, json=payload_for('admitted', **{**evidence, 'basis_on': '2026-11-21'}), headers=HEAD).status_code == 422
    assert worker.post(step, json=payload_for('admitted', **{**evidence, 'basis_on': '2026-11-23'}), headers=HEAD).status_code == 422
    for status in ('admitted', 'selection_complete', 'recommended'):
        application = body(worker.post(step, json=payload_for(status, **evidence), headers=HEAD))
    assert worker.post(step, json=payload_for('enrolled', **evidence), headers=HEAD).status_code == 422
    application = body(worker.post(step, json=payload_for('enrolled', **evidence, contract_ref='Тестовый договор'), headers=HEAD))
    assert not application['allowed']
    assert body(student.get('/api/units/vuc/learning'))['enrollments'] == []
    notice = {'version': application['version'], 'message': 'Получите выписку в ВУЦ.'}
    result = body(worker.post(path + '/notice', json=notice, headers=HEAD))
    assert result['status'] == 'enrolled'
    assert worker.post(path + '/notice', json=notice, headers=HEAD).status_code == 409
    detail = body(student.get(path))
    assert detail['student'] is None
    assert detail['next_action'] == notice['message']
    assert [history['action'] for history in detail['history']].count('status') == 8
    assert detail['history'][-2]['contract_ref'] == 'Тестовый договор'
    assert detail['history'][-2]['author'] == 'Артём Неверов'
    assert not body(other.get('/api/notifications?filter=vuc')) or all(
        notice['target'] != f"/app/vuc/admission/{application['id']}"
        for notice in body(other.get('/api/notifications?filter=vuc'))
    )
    assert any(item['title'] == 'Сообщение ВУЦ' and item['target'] == f"/app/vuc/admission/{application['id']}"
               for item in body(student.get('/api/notifications?filter=vuc')))
    assert any(row['section'] == 'Приём в ВУЦ' for row in body(worker.get('/api/units/vuc/report'))['items'])


def test_vuc_repeated_inquiry_and_publication(units, today):
    student, worker, union = (units(role) for role in ('student', 'vuc', 'union'))
    program = body(worker.put(BASE + '/programs', json=program_body(), headers=HEAD))
    campaign = body(worker.put(BASE + '/campaigns', json=campaign_body(program['id']), headers=HEAD))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: student.post(
            APPLICATIONS, json={'campaign_id': campaign['id'], 'confirmed': True}, headers=HEAD,
        ), range(2)))
    assert sorted(result.status_code for result in results) == [201, 409]

    post = {'title': 'Объявление о консультации', 'kind': 'news', 'body': 'Уточнить комплект можно в рабочие часы.'}
    path = '/api/units/vuc/publications'
    assert union.put(path, json=post, headers=HEAD).status_code == 403
    published = body(worker.put(path, json=post, headers=HEAD))
    assert any(item['id'] == published['id'] for item in body(student.get('/api/units/vuc'))['publications'])
    assert body(worker.get('/api/notifications?filter=vuc'))[0]['target'].startswith('/app/vuc-office/admission/')


def test_public_contest_accounts_can_only_read_published_admission(units, today, monkeypatch):
    student, worker = (units(role) for role in ('student', 'vuc'))
    draft = body(worker.put(BASE + '/programs', json=program_body(state='draft'), headers=HEAD))
    monkeypatch.setattr(vuc_policy, 'settings', replace(vuc_policy.settings, app_env='production'))
    snapshot = body(worker.get(BASE))
    assert snapshot['can_manage'] is False
    assert all(item['id'] != draft['id'] for item in snapshot['programs'])
    assert not body(student.get(BASE))['can_apply']
    for path in [APPLICATIONS, '/api/units/vuc/cases', '/api/units/vuc/report', '/api/units/vuc/learning']:
        assert worker.get(path).status_code == 403
    assert worker.put(BASE + '/programs', json=program_body(), headers=HEAD).status_code == 403
    assert worker.put('/api/units/vuc/publications', json={'kind': 'news', 'title': 'Запись', 'body': 'Проверка публикации.'},
                      headers=HEAD).status_code == 403
    assert student.post(APPLICATIONS, json={'campaign_id': 1, 'confirmed': True}, headers=HEAD).status_code == 403
