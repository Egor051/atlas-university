"""Actual Chromium on isolated HTTP: durable forms and authenticated recovery."""
import os
import uuid
import pytest
from playwright.sync_api import expect
from test_frontend_contracts import frontend_browser, frontend_server, frontend_page, enter_demo

pytestmark=pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS')!='1',reason='Opt-in local real Chromium')

def enter(page,base):
    page.goto(base);enter_demo(page,0,'Алина')

def visit(page,base,target):
    page.goto(base+'/app/'+target,wait_until='networkidle')
    expect(page.locator('#page-content')).not_to_have_attribute('aria-busy','true')

def request_form(page):
    if page.locator('.service-card').count()==0: page.locator('[data-request-view="services"]').click()
    page.locator('.service-card[data-type="study"]').click()
    expect(page.locator('#request-form')).to_be_visible()

def test_nearest_lesson_selects_its_date_and_changed_banner_opens_change(frontend_page):
    page,base=frontend_page;page.set_viewport_size({'width':360,'height':800});enter(page,base)
    dashboard=page.request.get(base+'/api/dashboard').json();next_lesson=dashboard['next_lesson']
    page.get_by_role('button',name='Открыть расписание',exact=True).click()
    expect(page.locator('.day-pick.selected')).to_have_attribute('data-day',next_lesson['date'])
    expect(page.locator('.lesson-row.search-match')).to_have_attribute('data-lesson-id',str(next_lesson['id']))
    if page.get_by_role('button',name='Показать изменение',exact=True).count():
        page.get_by_role('button',name='Показать изменение',exact=True).click()
        expect(page.locator('.lesson-row.search-match .change-comparison')).to_contain_text('Было:')

def test_request_survives_expired_cookie_and_same_user_reauthentication(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'requests');request_form(page)
    text='Вымышленный черновик '+str(uuid.uuid4())
    page.locator('#doc-comment').fill(text)
    page.context.clear_cookies()
    page.locator('#request-form button[type=submit]').click()
    expect(page.locator('#login-form')).to_be_visible()
    page.locator('[data-demo="0"]').click()
    expect(page.locator('#request-form')).to_be_visible()
    expect(page.locator('#doc-comment')).to_have_value(text)
    page.locator('#request-form button[type=submit]').click()
    expect(page.locator('.request-track')).to_be_visible()
    assert page.request.get(base+'/api/drafts/request').json()['values']=={}

def test_long_assignment_draft_has_compact_key_and_survives_reload(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'assignments')
    page.locator('[data-c-action="assignment"]').first.click()
    form=page.locator('form[data-c-form="assignment"]');expect(form).to_be_visible()
    assignment_id=form.get_attribute('data-id')
    text='Вымышленный ответ: '+'а'*7500
    form.locator('[name="text"]').fill(text)
    expect(form.locator('[data-personal-draft]')).to_contain_text('Черновик сохранён',timeout=10000)
    page.reload(wait_until='networkidle')
    page.locator(f'[data-c-action="assignment"][data-id="{assignment_id}"]').first.click()
    expect(page.locator('form[data-c-form="assignment"] [name="text"]')).to_have_value(text)

def test_note_draft_cannot_appear_for_another_account(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'notes')
    page.locator('[data-c-action="note-new"]').click()
    form=page.locator('[data-c-form="note"]');text='Личный вымышленный текст '+str(uuid.uuid4())
    form.locator('[name="title"]').fill('Черновик Алины');form.locator('[name="body"]').fill(text)
    expect(form.locator('[data-personal-draft]')).to_contain_text('Черновик сохранён',timeout=10000)
    page.context.clear_cookies();page.goto(base);page.locator('[data-demo="1"]').click()
    expect(page.locator('#page-title')).to_contain_text('Марк')
    visit(page,base,'notes');page.locator('[data-c-action="note-new"]').click()
    expect(page.locator('[data-c-form="note"] [name="body"]')).not_to_have_value(text)

def test_server_validation_points_to_field_without_losing_input(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'assignments')
    page.locator('[data-c-action="assignment"]').first.click()
    form=page.locator('[data-c-form="assignment"]')
    # The prior scenario leaves a saved draft; finish restoring it before typing.
    expect(form).to_have_attribute('data-draft-bound','true')
    form.evaluate('form => form._atlasDraft.restore')
    form.locator('[name="text"]').fill('Вымышленный ответ для проверки ошибки ссылки.')
    form.locator('[name="url"]').fill('http://example.test/work')
    form.locator('button[type=submit]').click()
    expect(form.locator('[name="url"]')).to_have_attribute('aria-invalid','true')
    expect(form.locator('[name="url"]')).to_be_focused()
    expect(form.locator('[name="text"]')).to_have_value('Вымышленный ответ для проверки ошибки ссылки.')
    form.locator('[name="url"]').fill('https://example.test/work')
    expect(form.locator('[name="url"]')).not_to_have_attribute('aria-invalid','true')

def test_offline_indicator_persists_and_reconnection_keeps_form(frontend_page):
    page,base=frontend_page;enter(page,base);visit(page,base,'notes')
    page.locator('[data-c-action="note-new"]').click()
    form=page.locator('[data-c-form="note"]')
    form.locator('[name="title"]').fill('Вымышленный офлайн-черновик')
    form.locator('[name="body"]').fill('Текст должен сохраниться при восстановлении связи.')
    page.context.set_offline(True)
    page.wait_for_timeout(5500)  # Past the old ephemeral toast lifetime.
    expect(page.locator('#connection-state')).to_contain_text('Нет сети')
    expect(page.locator('#refresh-current')).to_be_disabled()
    page.context.set_offline(False)
    expect(page.locator('#connection-state')).not_to_contain_text('Нет сети')
    expect(form.locator('[name="body"]')).to_have_value('Текст должен сохраниться при восстановлении связи.')
    form.locator('button[type=submit]').click()
    expect(form).to_have_count(0)

def test_mobile_schedule_label_does_not_break_last_letter(frontend_page):
    page,base=frontend_page;page.set_viewport_size({'width':360,'height':800});enter(page,base)
    span=page.locator('.bottom-nav [data-route="schedule"] > span')
    assert span.evaluate('el=>{const r=document.createRange();r.selectNodeContents(el);return [...r.getClientRects()].filter(x=>x.width>0).length}')==1

def test_staff_requests_clarification_and_student_adds_history_without_changing_status(frontend_page):
    page,base=frontend_page;enter(page,base)
    created=page.request.post(base+'/api/requests',data={'type':'study'},headers={'X-Requested-With':'ATLAS'}).json();rid=created['id']
    page.request.post(base+'/api/login',data={'login':'dean.demo','password':'AtlasStaff!2026-D'},headers={'X-Requested-With':'ATLAS'})
    visit(page,base,'staff');page.locator(f'.request-row[data-id="{rid}"]').click()
    page.locator('#staff-status').select_option('needs_info')
    page.locator('#staff-message').fill('Пожалуйста уточните назначение вымышленной справки.')
    page.locator('#staff-form button[type=submit]').click()
    expect(page.locator('.modal .request-status.needs_info')).to_be_visible()
    page.request.post(base+'/api/login',data={'login':'alina.demo','password':'AtlasDemo!2026-A'},headers={'X-Requested-With':'ATLAS'})
    visit(page,base,'requests');page.locator(f'.request-row[data-id="{rid}"]').click()
    page.get_by_text('Уточнить сведения или попросить отозвать',exact=True).click()
    message='Вымышленные сведения для уточнения назначения.'
    page.locator('#followup-message').fill(message)
    with page.expect_response(lambda r:r.url.endswith(f'/requests/{rid}/followup') and r.request.method=='POST') as saved:
        page.locator('#request-followup button[type=submit]').click()
    assert saved.value.status==200
    expect(page.locator('.modal')).to_contain_text('Уточнение студента: '+message)
    expect(page.locator('.modal .request-status.needs_info')).to_be_visible()
    state=page.request.get(base+f'/api/requests/{rid}').json()
    assert state['status']=='needs_info'
    assert state['history'][-1]['message']=='Уточнение студента: '+message
