"""Real isolated Chromium regressions for context navigation and growing catalogs.

Fictional fixtures are changed in this test's own temporary SQLite database.
Successful API responses are never fabricated. These are automated scenarios,
not interviews or evidence about real students' task completion.
"""
from datetime import datetime, timezone, timedelta
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import tempfile

import pytest
from playwright.sync_api import expect

from scripts.browser_check import start_server, stop_server
from test_frontend_contracts import frontend_browser, enter_demo

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in real Chromium checks')


@pytest.fixture
def campus_page(frontend_browser):
    with tempfile.TemporaryDirectory(prefix='atlas-campus-context-') as directory:
        base, db, process, log = start_server(directory)
        context = frontend_browser.new_context(viewport={'width': 360, 'height': 800}, locale='ru-RU')
        page = context.new_page()
        page.set_default_timeout(10000)
        try:
            page.goto(base)
            enter_demo(page, 0, 'Алина')
            yield page, base, db
        finally:
            context.close()
            stop_server(process, log)


def visit(page, base, section):
    page.goto(base + '/app/' + section, wait_until='networkidle')
    expect(page.locator('#page-content')).not_to_have_attribute('aria-busy', 'true')
    expect(page.locator('.error-state')).to_have_count(0)


def calendar_day(page, base, day):
    visit(page, base, 'calendar')
    page.locator('.calendar-options summary').click()
    page.locator('#calendar-date').fill(day)
    page.locator('#calendar-date').dispatch_event('change')
    expect(page.locator(f'[data-calendar-day="{day}"]')).to_have_attribute('aria-pressed', 'true')


def moscow_day(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=3))).date().isoformat()


@pytest.mark.parametrize('width', [360, 390])
def test_calendar_opens_exact_work_and_personal_mark_does_not_submit(campus_page, width):
    page, base, _ = campus_page
    page.set_viewport_size({'width': width, 'height': 800})
    work = page.request.get(base + '/api/learning/assignments').json()['items'][0]
    grades_before = page.request.get(base + '/api/grades').json()
    calendar_day(page, base, work['due_date'])
    page.locator(f'.campus-agenda-entry[data-route="assignments"][data-record-id="{work["id"]}"]').click()
    form = page.locator(f'form[data-c-form="assignment"][data-id="{work["id"]}"]')
    expect(form).to_be_visible()
    expect(page.get_by_role('dialog')).to_contain_text(work['title'])
    marker = form.locator(f'[data-deadline="{work["id"]}"]')
    marker.set_checked(not work['is_done'])
    expect(marker).to_be_enabled()
    saved = page.request.get(base + f'/api/learning/assignments/{work["id"]}').json()
    assert saved['is_done'] is not work['is_done']
    assert saved['submission'] == work['submission']
    assert page.request.get(base + '/api/grades').json() == grades_before
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_calendar_opens_booked_slot_and_registered_event_not_generic_catalog(campus_page):
    page, base, _ = campus_page
    headers = {'X-Requested-With': 'ATLAS'}
    slot = page.request.get(base + '/api/services/consultations?scope=upcoming&limit=300').json()['items'][0]
    booked = page.request.post(base + f'/api/services/consultations/{slot["id"]}/book', headers=headers, data={})
    assert booked.status in (200, 201), booked.text()
    event = page.request.get(base + '/api/services/events?scope=upcoming&limit=300').json()['items'][0]
    registered = page.request.post(base + f'/api/services/events/{event["id"]}/register', headers=headers, data={})
    assert registered.status in (200, 201), registered.text()
    for item, target in [(slot, 'consultations'), (event, 'events')]:
        calendar_day(page, base, moscow_day(item['start_at']))
        page.locator(f'.campus-agenda-entry[data-route="{target}"][data-record-id="{item["id"]}"]').click()
        selected = page.locator(f'.campus-context-target[data-campus-record-id="{item["id"]}"]')
        expect(selected).to_be_visible()
        expect(selected).to_be_focused()
        expect(page.locator('.campus-grid > article')).to_have_count(1)
        expect(page.locator('[data-c-action="clear-context"]')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_retired_library_api_preserves_paging_search_and_loan_history(campus_page):
    page, base, db = campus_page
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.executemany('INSERT INTO library_books(title,author,subject,description,total,available) VALUES (?,?,?,?,?,?)',
            [(f'Automation catalog book {i:03}', 'Вымышленный автор', 'Тестовый предмет', 'Синтетическая запись проверки каталога', 2, 2) for i in range(310)])
    library = base + '/api/services/library'
    first = page.request.get(library, params={'limit': 20}).json()
    second = page.request.get(library, params={'limit': 20, 'offset': 20}).json()
    assert first['has_more'] and second['offset'] == 20
    assert {row['id'] for row in first['items']}.isdisjoint(row['id'] for row in second['items'])
    query = page.request.get(library, params={'q': 'Automation catalog book 309'}).json()
    book, = query['items']
    assert book['title'] == 'Automation catalog book 309'
    headers = {'X-Requested-With': 'ATLAS'}
    loan = page.request.post(f"{library}/{book['id']}/borrow", headers=headers, data={})
    assert loan.status == 201, loan.text()
    loan_id = loan.json()['id']
    loans = base + '/api/services/loans'
    assert loan_id in {row['id'] for row in page.request.get(loans, params={'filter': 'active'}).json()['items']}
    returned = page.request.post(f'{loans}/{loan_id}/return', headers=headers, data={})
    assert returned.status == 200, returned.text()
    saved = page.request.get(loans, params={'filter': 'returned'}).json()['items']
    assert any(row['id'] == loan_id and row['book']['id'] == book['id'] for row in saved)


def test_subject_context_with_no_future_slot_offers_materials_and_prefilled_office_question(campus_page):
    page, base, db = campus_page
    exam = page.request.get(base + '/api/learning/exams').json()['items'][0]
    with closing(sqlite3.connect(db)) as connection, connection:
        # Real isolated data change models a subject without any available future slot.
        connection.execute("UPDATE consultation_slots SET start_at='2020-01-01 09:00:00',end_at='2020-01-01 10:00:00' WHERE subject=?", (exam['subject'],))
        connection.execute("UPDATE grades SET assessment='Не допущен' WHERE id=?", (exam['id'],))
    visit(page, base, 'exams')
    row = page.locator(f'[data-campus-record-id="{exam["id"]}"]')
    row.locator('[data-route="consultations"]').click()
    expect(page.locator('.campus-context')).to_contain_text(exam['subject'])
    expect(page.get_by_role('heading', name='Как продолжить подготовку')).to_be_visible()
    page.locator('.campus-section [data-route="messages"][data-subject]').click()
    page.locator('[data-c-action="ticket-new"]').click()
    expect(page.locator('#campus-field-title')).to_have_value('Консультация: ' + exam['subject'])
    expect(page.locator('#campus-field-message')).to_contain_text(exam['subject'])
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_dialog_opens_latest_messages_and_can_reach_earliest_history(campus_page):
    page, base, db = campus_page
    created=page.request.post(base+'/api/services/tickets',headers={'X-Requested-With':'ATLAS'},
        data={'topic':'academic','title':'Проверка длинной истории','message':'Начальный вымышленный вопрос для проверки истории'})
    assert created.status==201,created.text()
    ticket=created.json();user=page.request.get(base+'/api/me').json()
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.executemany('INSERT INTO ticket_messages(ticket_id,actor_id,actor_role,actor_name,body,created_at) VALUES (?,?,?,?,?,?)',
            [(ticket['id'],user['id'],'student',user['full_name'],f'History message {i:03}',datetime.now(timezone.utc).replace(tzinfo=None).isoformat()) for i in range(50)])
    visit(page,base,'messages')
    page.locator(f'[data-c-action="ticket-open"][data-id="{ticket["id"]}"]').click()
    expect(page.locator('.campus-conversation')).to_contain_text('History message 049')
    page.get_by_role('button',name='Ранее',exact=True).click()
    expect(page.locator('.campus-conversation')).to_contain_text('Начальный вымышленный вопрос для проверки истории')
    expect(page.locator('.campus-conversation')).not_to_contain_text('History message 049')
    expect(page.get_by_role('button',name='Позже',exact=True)).to_be_enabled()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [320, 360, 390, 1440])
def test_campus_context_pages_automated_accessibility_and_text_size_stress(campus_page, width):
    """Automated rules + 2x computed text stress; not a screen-reader/user study.

    Width 320 checks CSS reflow. Doubling current text sizes is a deliberate
    CSS stress simulation, not a claim about a physical device's zoom setting.
    """
    page, base, _ = campus_page
    page.set_viewport_size({'width':width,'height':900})
    axe=Path(__file__).resolve().parents[1]/'node_modules/axe-core/axe.min.js'
    assert axe.is_file(), 'Install dev-only axe-core before running accessibility tests'
    page.add_init_script(path=str(axe))
    for section in ['courses','assignments','exams','consultations','events','learning/notes']:
        visit(page,base,section)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (section,width,'normal reflow')
        violations=page.evaluate("""async () => {
          const result=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}});
          return result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}));
        }""")
        assert violations==[], (section,width,violations)
        page.evaluate("""() => {
          const targets=[...document.querySelectorAll('#page-content *')].filter(el=>
            [...el.childNodes].some(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim())||['INPUT','SELECT','TEXTAREA'].includes(el.tagName));
          const sizes=targets.map(el=>[el,parseFloat(getComputedStyle(el).fontSize)*2]);
          for(const [el,size] of sizes)el.style.fontSize=size+'px';
        }""")
        overflow=page.evaluate("""() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,bad:[...document.querySelectorAll('#page-content *')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.right>innerWidth+1&&el.children.length<3;}).slice(0,10).map(el=>({tag:el.tagName,cls:el.className,text:el.innerText?.slice(0,90),width:el.getBoundingClientRect().width,right:el.getBoundingClientRect().right}))})""")
        assert overflow['scrollWidth']<=overflow['width'], (section,width,'simulated 200% text',overflow)
