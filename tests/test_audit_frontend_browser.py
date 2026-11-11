"""Actual Chromium + isolated API. Faults delay/drop actual responses only."""
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime,timezone,timedelta
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser,frontend_server,frontend_page,enter_demo,wait_for_held_response
from test_improvements_campus_ui import campus_page

pytestmark=pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS')!='1',reason='Opt-in isolated real Chromium')
HEAD={'X-Requested-With':'ATLAS'}

def enter(page,base):
    page.goto(base);enter_demo(page,0,'Алина')

def visit(page,base,section):
    page.goto(base+'/app/'+section,wait_until='networkidle')
    expect(page.locator('#page-content')).not_to_have_attribute('aria-busy','true')

def new_note(page):
    page.locator('[data-c-action="note-new"]').first.click()
    form=page.locator('[data-c-form="note"]');expect(form).to_be_visible();return form

def request_form(page):
    page.locator('[data-action="new-request"]').first.click()
    form=page.locator('#request-form');expect(form).to_be_visible();return form

def test_failed_durable_draft_stops_primary_post_and_preserves_input(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'requests')
    form=request_form(page);text='Сохранить ввод при отказе черновика '+uuid.uuid4().hex
    form.locator('[name=comment]').fill(text);posts=[]
    page.on('request',lambda r:posts.append(r) if r.method=='POST' and r.url==base+'/api/requests' else None)
    page.route('**/api/drafts/request',lambda route:route.abort('failed') if route.request.method=='PUT' else route.continue_())
    form.locator('[type=submit]').click()
    expect(form.locator('#request-error')).to_contain_text('ключ повтора')
    expect(form.locator('[name=comment]')).to_have_value(text)
    expect(form.locator('[type=submit]')).to_be_enabled();assert not posts
    page.unroute('**/api/drafts/request');form.locator('[type=submit]').click()
    expect(page.locator('.request-track')).to_be_visible()

def test_request_locks_before_draft_await_and_cannot_close(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'requests');form=request_form(page)
    held=[]
    def delay(route):
        if route.request.method=='PUT':
            actual=route.fetch();assert actual.status==200;held.append((route,actual))
        else:route.continue_()
    page.route('**/api/drafts/request',delay)
    form.locator('[type=submit]').click();wait_for_held_response(page,held)
    expect(form.locator('[type=submit]')).to_be_disabled();page.keyboard.press('Escape')
    expect(form).to_be_visible()
    route,actual=held[0];route.fulfill(response=actual);page.unroute('**/api/drafts/request')
    expect(page.locator('.request-track')).to_be_visible()
    page.locator('.close-btn').click();page.locator('.topbar [data-route=profile]').click()
    expect(page.locator('#page-title')).to_have_text('Мой профиль')

def test_request_server_field_error_focuses_after_controls_are_unlocked(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'requests');form=request_form(page)
    copies=form.locator('[name=copies]')
    copies.evaluate('node=>{node.add(new Option("Недопустимый тестовый вариант","4"));node.value="4";}')
    form.locator('[name=comment]').fill('Вымышленный комментарий для проверки возврата к ошибочному полю.')
    form.locator('[type=submit]').click()
    expect(copies).to_have_attribute('aria-invalid','true');expect(copies).to_be_enabled();expect(copies).to_be_focused()
    expect(form.locator('[name=comment]')).to_have_value('Вымышленный комментарий для проверки возврата к ошибочному полю.')
    copies.select_option('1');expect(copies).not_to_have_attribute('aria-invalid','true')

def test_followup_server_field_error_focuses_after_controls_are_unlocked(frontend_page):
    page,base=frontend_page;enter(page,base);rid=page.request.post(base+'/api/requests',headers=HEAD,data={'type':'study'}).json()['id'];visit(page,base,'requests')
    page.locator(f'.request-row[data-id="{rid}"]').click();page.get_by_text('Уточнить сведения или попросить отозвать',exact=True).click()
    form=page.locator('#request-followup');form.evaluate('node=>node.noValidate=true');message=form.locator('[name=message]');message.fill('Коротко')
    form.locator('[type=submit]').click();expect(message).to_have_attribute('aria-invalid','true');expect(message).to_be_enabled();expect(message).to_be_focused();expect(message).to_have_value('Коротко')

def test_note_lost_response_reload_reuses_durable_key(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'notes');form=new_note(page)
    title='DurableNote '+uuid.uuid4().hex;form.locator('[name=title]').fill(title);form.locator('[name=body]').fill('Вымышленный ответ для проверки потерянного результата.')
    keys=[]
    def drop_first(route):
        if route.request.method!='POST':route.continue_();return
        keys.append(route.request.all_headers().get('idempotency-key'))
        if len(keys)==1:
            actual=route.fetch();assert actual.status==201;route.abort('failed')
        else:route.continue_()
    page.route('**/api/learning/notes',drop_first);form.locator('[type=submit]').click()
    expect(form.locator('[data-c-error]')).to_be_visible();page.reload(wait_until='networkidle');form=new_note(page)
    expect(form.locator('[name=title]')).to_have_value(title);form.locator('[type=submit]').click()
    expect(form).to_have_count(0);assert len(keys)==2 and keys[0]==keys[1]
    rows=page.request.get(base+'/api/learning/notes').json()['items'];assert sum(x['title']==title for x in rows)==1

def test_failed_initial_read_then_edited_retry_preserves_committed_submission_key(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'notes');form=new_note(page)
    title='ReadRetry '+uuid.uuid4().hex;text='Тот же вымышленный текст после потери ответа и перезагрузки.'
    form.locator('[name=title]').fill(title);form.locator('[name=body]').fill(text);keys=[]
    def drop_first(route):
        if route.request.method!='POST':route.continue_();return
        keys.append(route.request.all_headers().get('idempotency-key'))
        if len(keys)==1:
            actual=route.fetch();assert actual.status==201;route.abort('failed')
        else:route.continue_()
    page.route('**/api/learning/notes',drop_first);form.locator('[type=submit]').click();expect(form.locator('[data-c-error]')).to_be_visible()
    page.reload(wait_until='networkidle')
    def fail_reads(route):
        if route.request.method=='GET':route.abort('failed')
        else:route.continue_()
    page.route('**/api/drafts/note',fail_reads);form=new_note(page)
    form.locator('[name=title]').fill(title);form.locator('[name=body]').fill(text);form.locator('[type=submit]').click()
    expect(form.locator('[data-c-error]')).to_be_visible();expect(form.locator('[type=submit]')).to_be_enabled();assert len(keys)==1
    # Existing server metadata must be loaded independently of restoring fields:
    # these fields have already been edited after a failed initial read.
    page.unroute('**/api/drafts/note');form.locator('[type=submit]').click();expect(form).to_have_count(0)
    assert len(keys)==2 and keys[0]==keys[1]
    rows=page.request.get(base+'/api/learning/notes').json()['items'];assert sum(x['title']==title for x in rows)==1

def test_valid_twelve_thousand_character_note_draft_survives_reload(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'notes');form=new_note(page)
    text='Вымышленный конспект '+'я'*11000;form.locator('[name=title]').fill('Длинный конспект '+uuid.uuid4().hex);form.locator('[name=body]').fill(text)
    expect(form.locator('[data-personal-draft]')).to_contain_text('Черновик сохранён',timeout=15000)
    page.reload(wait_until='networkidle');form=new_note(page);expect(form.locator('[name=body]')).to_have_value(text)
    form.locator('[type=submit]').click();expect(form).to_have_count(0)

def test_cross_tab_cookie_change_cannot_save_old_account_form(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'notes');form=new_note(page)
    marker='OldOwner '+uuid.uuid4().hex;form.locator('[name=title]').fill(marker);form.locator('[name=body]').fill('Черновик первого аккаунта не должен попасть ко второму.')
    expect(form.locator('[data-personal-draft]')).to_contain_text('Черновик сохранён',timeout=15000)
    other=page.context.new_page();other.goto(base)
    # API login changes the actual shared cookie without a client broadcast.
    response=other.request.post(base+'/api/login',headers=HEAD,data={'login':'mark.demo','password':'AtlasDemo!2026-M'})
    assert response.status==200
    page.evaluate("document.querySelector('[data-c-form=note]').requestSubmit()")
    expect(page.locator('#login-form')).to_be_visible()
    rows=other.request.get(base+'/api/learning/notes').json()['items'];assert not any(x['title']==marker for x in rows)
    assert other.request.get(base+'/api/drafts/note').json()['values']=={}
    other.close()

def test_history_paging_preserves_unsent_clarification(campus_page):
    page,base,db=campus_page
    created=page.request.post(base+'/api/requests',headers=HEAD,data={'type':'study'}).json();rid=created['id']
    with closing(sqlite3.connect(db)) as connection,connection:
        connection.executemany('INSERT INTO request_events(request_id,status,message,actor_role,actor_name,created_at) VALUES (?,?,?,?,?,?)',[(rid,'submitted',f'History audit event {i:03}','system','Система','2026-11-10 10:00:00') for i in range(120)])
    visit(page,base,'requests');page.locator(f'[data-action="request-details"][data-id="{rid}"]').click()
    page.get_by_text('Уточнить сведения или попросить отозвать',exact=True).click();text='Уточнение сохраняется при просмотре другой страницы истории.'
    page.locator('#followup-message').fill(text)
    history=page.locator('[data-request-history]');history.locator('xpath=ancestor::details').locator('summary').click()
    expect(history).to_contain_text('History audit event 119')
    history.get_by_role('button',name='Ранее',exact=True).click()
    expect(history).to_contain_text('History audit event 000');expect(page.locator('#followup-message')).to_have_value(text)
    history.get_by_role('button',name='Позже',exact=True).click();expect(history).to_contain_text('History audit event 119')

def test_deadline_refresh_keeps_write_locked_until_response_settles(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'plan')
    page.locator('[data-plan-filter="all"]').click()
    mark=page.locator('[data-deadline]').first;rid=mark.get_attribute('data-deadline');before=mark.is_checked();held=[];posts=[]
    def hold(route):
        posts.append(route.request.post_data_json)
        actual=route.fetch();assert actual.status==200;held.append((route,actual))
    page.route(f'**/api/deadlines/{rid}/toggle',hold)
    mark.set_checked(not before);wait_for_held_response(page,held)
    page.locator('#refresh-current').click()
    replacement=page.locator(f'[data-deadline="{rid}"]');expect(replacement).to_be_disabled();expect(replacement).to_be_checked(checked=not before)
    # Even a programmatic change cannot create a second overlapping write.
    replacement.evaluate('(node)=>{node.checked=!node.checked;node.dispatchEvent(new Event("change",{bubbles:true}));}')
    assert len(posts)==1
    route,actual=held[0];route.fulfill(response=actual);page.unroute(f'**/api/deadlines/{rid}/toggle')
    expect(replacement).to_be_enabled();replacement.set_checked(before)
    expect(page.locator(f'[data-deadline="{rid}"]')).to_be_enabled()
    stored=page.request.get(base+'/api/deadlines').json();assert next(x for x in stored if str(x['id'])==rid)['is_done'] is before
    expect(page.locator(f'[data-deadline="{rid}"]')).to_be_checked(checked=before)

def test_last_filtered_ticket_reloads_previous_page_after_close(campus_page):
    page,base,db=campus_page;uid=page.request.get(base+'/api/me').json()['id'];marker='PaginationAudit '+uuid.uuid4().hex
    with closing(sqlite3.connect(db)) as connection,connection:
        connection.executemany('INSERT INTO support_tickets(student_id,topic,title,status,created_at,updated_at) VALUES (?,?,?,?,?,?)',[(uid,'academic',f'{marker} {i:02}','open','2026-11-10 10:00:00','2026-11-10 10:00:00') for i in range(21)])
    visit(page,base,'messages');page.locator('[data-c-filter="messages"][data-value="open"]').click();page.locator('#campus-query').fill(marker)
    expect(page.locator('.compact-list > article')).to_have_count(20)
    page.locator('[data-page-key="messages"][data-offset="20"]').click();expect(page.locator('.compact-list > article')).to_have_count(1)
    page.locator('[data-c-action="ticket-open"]').click();page.locator('[data-c-action="ticket-close"]').click();page.locator('[data-c-action="ticket-close"][data-confirmed="true"]').click()
    expect(page.locator('.compact-list > article')).to_have_count(20)
    expect(page.locator('.search-empty')).to_have_count(0)
    assert page.request.get(base+'/api/services/tickets?filter=open&q='+marker.replace(' ','%20')).json()['total']==20

def test_request_list_uses_moscow_creation_day_and_rejected_contrast(campus_page):
    page,base,db=campus_page;rid=page.request.post(base+'/api/requests',headers=HEAD,data={'type':'study'}).json()['id']
    with closing(sqlite3.connect(db)) as connection,connection:
        connection.execute("UPDATE document_requests SET created_at='2026-11-10 22:30:00',status='rejected' WHERE id=?",(rid,))
    visit(page,base,'requests');row=page.locator(f'.request-row[data-id="{rid}"]')
    expect(row.locator('.request-row-main small')).to_contain_text('11 нояб.')
    badge=row.locator('.request-status.rejected');expect(badge).to_be_visible()
    ratio=badge.evaluate(r'''node=>{const c=getComputedStyle(node),lum=s=>{const v=s.match(/[\d.]+/g).slice(0,3).map(Number).map(x=>x/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*v[0]+.7152*v[1]+.0722*v[2]};const a=lum(c.color),b=lum(c.backgroundColor);return(Math.max(a,b)+.05)/(Math.min(a,b)+.05)}''')
    assert ratio>=4.5,ratio
    row.click();expect(page.locator('.detail-summary p')).to_contain_text('11 нояб.')

def test_staff_summary_counts_needs_info_and_all_consultation_pages(campus_page):
    page,base,db=campus_page;rid=page.request.post(base+'/api/requests',headers=HEAD,data={'type':'study'}).json()['id']
    with closing(sqlite3.connect(db)) as connection,connection:
        connection.execute("UPDATE document_requests SET status='needs_info' WHERE id=?",(rid,))
        connection.executemany('INSERT INTO consultation_slots(seed_key,teacher,subject,start_at,end_at,room,capacity,booked_count) VALUES (?,?,?,?,?,?,?,?)',[(None,'Вымышленный преподаватель',f'Audit slot {i}','2026-11-20 12:00:00','2026-11-20 13:00:00','Демо',4,0) for i in range(25)])
    assert page.request.post(base+'/api/login',headers=HEAD,data={'login':'dean.demo','password':'AtlasStaff!2026-D'}).status==200
    visit(page,base,'staffdesk')
    overview=page.request.get(base+'/api/staff/overview').json();counts=overview['requests'];active=sum(counts.get(s,0) for s in ['submitted','review','processing','needs_info']);total=page.request.get(base+'/api/staff/consultations').json()['total']
    stats=page.locator('.campus-metric');assert stats.count()==3
    expect(stats.nth(0).locator('b')).to_have_text(str(active));expect(stats.nth(2).locator('b')).to_have_text(str(total));assert total>20
    expect(page.locator('.campus-log > article')).to_have_count(20)

def test_downloads_are_affinity_guarded_and_legacy_drafts_are_discoverable(frontend_page,tmp_path):
    page,base=frontend_page;enter(page,base);visit(page,base,'settings')
    link=page.get_by_role('link',name='Скачать черновики',exact=True);expect(page.get_by_text('Мои черновики',exact=True)).to_be_visible()
    calls=[];page.on('request',lambda r:calls.append(r.all_headers().get('x-atlas-user')) if '/api/drafts/export' in r.url else None)
    with page.expect_download() as download:link.click()
    target=tmp_path/'drafts.json';download.value.save_as(target);assert 'items' in __import__('json').loads(target.read_text(encoding='utf-8'));assert calls==['1']
    assert page.request.post(base+'/api/login',headers=HEAD,data={'login':'mark.demo','password':'AtlasDemo!2026-M'}).status==200
    link.click();expect(page.locator('#login-form')).to_be_visible();assert calls==['1','1']

@pytest.mark.parametrize('width',[360,390,1440])
def test_revised_forms_and_history_have_no_horizontal_overflow(frontend_page,width):
    page,base=frontend_page;page.set_viewport_size({'width':width,'height':900});enter(page,base)
    for section in ['requests','calendar','tasks','notes','events','library']:
        visit(page,base,section);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(section,width)
    form=new_note(page) if page.url.endswith('/notes') else None
    visit(page,base,'notes');form=new_note(page)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    form.locator('[name=title]').fill('Проверка формы');form.locator('[name=body]').fill('Вымышленное содержимое.')
    shots=Path(__file__).resolve().parents[1]/'screenshots'/'audit-fixes-2026-11-10';shots.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(shots/f'chromium-note-{width}.png'),animations='disabled')
    page.keyboard.press('Escape');expect(page.locator('.unsaved-warning')).to_be_visible()
