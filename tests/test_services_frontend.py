"""Real browser campus workflows against a temporary, isolated HTTP server.

Opt in with ATLAS_RUN_BROWSER_TESTS=1. All state-changing operations below use
the actual forms and API; no successful response or dataset is mocked.
"""
from __future__ import annotations

import os
import uuid

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import (frontend_server, frontend_browser,
                                     frontend_page, enter_demo, leave_demo)

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in browser suite: set ATLAS_RUN_BROWSER_TESTS=1')


def go(page, address, route, title):
    page.goto(address+'/app/'+route)
    expect(page.locator('#page-title')).to_have_text(title)
    expect(page.locator('#page-content')).not_to_have_attribute('aria-busy', 'true')


def enter_staff(page):
    page.get_by_role('button',name='Выбрать аккаунт',exact=True).click()
    page.locator("button[data-demo='2']").click()
    page.wait_for_url('**/app/staff')
    expect(page.locator('#page-title')).to_have_text('Учебный офис')


def post_response(page, suffix):
    return page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith(suffix))


def submit(page, name, suffix, status=200):
    form = page.locator(f"form[data-c-form='{name}']")
    with post_response(page, suffix) as saved:
        form.locator("button[type='submit']").click()
    assert saved.value.status == status, saved.value.text()
    return saved.value.json()


def close_modal(page):
    page.locator('.modal .close-btn').click()
    expect(page.locator('.modal')).to_have_count(0)


def test_real_service_reservations_reload_and_cancel(frontend_page):
    page, address = frontend_page
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(address)
    enter_demo(page, 0, 'Алина')

    go(page, address, 'consultations', 'Консультации')
    button = page.locator("button[data-c-action='consultation-book']:enabled").first
    slot_id = button.get_attribute('data-id')
    with post_response(page, f'/consultations/{slot_id}/book') as saved:
        button.click()
    assert saved.value.status == 201, saved.value.text()
    booking_id = saved.value.json()['id']
    cancel = f".campus-log [data-c-action='booking-cancel'][data-id='{booking_id}']"
    expect(page.locator(cancel)).to_be_visible()
    page.reload()
    expect(page.locator(cancel)).to_be_visible()
    with post_response(page, f'/bookings/{booking_id}/cancel') as cancelled:
        page.locator(cancel).click()
    assert cancelled.value.status == 200 and cancelled.value.json()['status'] == 'cancelled'
    expect(page.locator(cancel)).to_have_count(0)
    expect(page.locator(f"button[data-c-action='consultation-book'][data-id='{slot_id}']")).to_be_enabled()

    go(page, address, 'events', 'Жизнь кампуса')
    button = page.locator("button[data-c-action='event-register']:enabled").first
    event_id = button.get_attribute('data-id')
    with post_response(page, f'/events/{event_id}/register') as saved:
        button.click()
    assert saved.value.status == 201, saved.value.text()
    registration_id = saved.value.json()['id']
    cancel = f"button[data-c-action='event-cancel'][data-id='{registration_id}']"
    expect(page.locator(cancel)).to_be_visible()
    page.reload()
    expect(page.locator(cancel)).to_be_visible()
    with post_response(page, f'/registrations/{registration_id}/cancel') as cancelled:
        page.locator(cancel).click()
    assert cancelled.value.status == 200 and cancelled.value.json()['status'] == 'cancelled'
    expect(page.locator(cancel)).to_have_count(0)
    expect(page.locator(f"button[data-c-action='event-register'][data-id='{event_id}']")).to_be_enabled()

    assert errors == []


def test_real_ticket_student_staff_notification_and_terminal_history(frontend_page):
    page, address = frontend_page
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    marker = uuid.uuid4().hex[:10]
    title = 'Учебный вопрос браузера '+marker
    initial = 'Нужно уточнить порядок сдачи демонстрационной работы '+marker
    student_reply = 'Добавляю подробности учебного вопроса '+marker
    staff_reply = 'Учебный офис: порядок сдачи указан в карточке задания '+marker
    page.goto(address)
    enter_demo(page, 0, 'Алина')
    go(page, address, 'messages', 'Вопросы в учебный офис')
    page.locator("[data-c-action='ticket-new']").click()
    form = page.locator("form[data-c-form='ticket']")
    form.locator('[name=title]').fill(title)
    form.locator('[name=message]').fill(initial)
    ticket = submit(page, 'ticket', '/api/services/tickets', 201)
    ticket_id = ticket['id']
    expect(page.locator('.compact-row h2', has_text=title)).to_be_visible()
    page.locator(f"[data-c-action='ticket-open'][data-id='{ticket_id}']").click()
    expect(page.locator('.campus-conversation')).to_contain_text(initial)
    page.locator("form[data-c-form='ticket-reply'] [name=message]").fill(student_reply)
    submit(page, 'ticket-reply', f'/api/services/tickets/{ticket_id}/messages')
    expect(page.locator('.campus-conversation')).to_contain_text(student_reply)
    close_modal(page)
    leave_demo(page)

    enter_staff(page)
    go(page, address, 'staffmessages', 'Вопросы студентов')
    page.locator('#campus-query').fill(marker)
    page.locator(f"[data-c-action='ticket-open'][data-id='{ticket_id}']").click()
    expect(page.locator('.campus-conversation')).to_contain_text(student_reply)
    page.locator("form[data-c-form='ticket-reply'] [name=message]").fill(staff_reply)
    submit(page, 'ticket-reply', f'/api/staff/tickets/{ticket_id}/messages')
    expect(page.locator('.campus-conversation')).to_contain_text(staff_reply)
    page.locator("[data-c-action='ticket-close']").click()
    with post_response(page, f'/api/staff/tickets/{ticket_id}/close') as closed:
        page.locator("[data-c-action='ticket-close'][data-confirmed='true']").click()
    assert closed.value.status == 200 and closed.value.json()['status'] == 'closed'
    expect(page.locator('.modal')).to_have_count(0)
    leave_demo(page)

    enter_demo(page, 0, 'Алина')
    go(page, address, 'notifications', 'Уведомления')
    notice = page.locator('.notification-full').filter(has=page.get_by_role('heading', name='Учебный офис ответил', exact=True)).filter(has_text=title).first
    expect(notice).to_be_visible()
    notice.locator("[data-action='open-notice']").click()
    page.wait_for_url(f'**/app/messages?id={ticket_id}')
    expect(page.locator('#page-title')).to_have_text('Вопросы в учебный офис')
    conversation = page.locator('.campus-conversation')
    expect(conversation).to_contain_text(initial)
    expect(conversation).to_contain_text(student_reply)
    expect(conversation).to_contain_text(staff_reply)
    expect(page.locator("form[data-c-form='ticket-reply']")).to_have_count(0)
    expect(page.locator('.modal')).to_contain_text('Обращение закрыто')
    assert errors == []


def test_real_staff_publishing_and_persistent_own_preferences(frontend_page):
    page, address = frontend_page
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    marker = uuid.uuid4().hex[:10]
    subject = 'Браузерная консультация '+marker
    event_title = 'Учебное событие браузера '+marker
    announcement_title = 'Объявление браузера '+marker
    page.goto(address)
    enter_staff(page)
    go(page, address, 'staffdesk', 'Сводка учебного офиса')

    page.locator("[data-c-action='staff-slot']").click()
    form = page.locator("form[data-c-form='staff-slot']")
    form.locator('[name=teacher]').fill('Вымышленный преподаватель браузера')
    form.locator('[name=subject]').fill(subject)
    form.locator('[name=room]').fill('Тестовый корпус А-510')
    form.locator('[name=capacity]').fill('3')
    slot = submit(page, 'staff-slot', '/api/staff/consultations', 201)
    expect(page.locator('.campus-log')).to_contain_text(subject)

    page.locator("[data-c-action='staff-event']").click()
    form = page.locator("form[data-c-form='staff-event']")
    form.locator('[name=title]').fill(event_title)
    form.locator('select[name=category]').select_option('academic')
    form.locator('[name=description]').fill('Вымышленная встреча для проверки публикации из кабинета сотрудника.')
    form.locator('[name=location]').fill('Конкурсный зал Б-101')
    form.locator('[name=capacity]').fill('12')
    event = submit(page, 'staff-event', '/api/staff/events', 201)
    expect(page.locator('.modal')).to_have_count(0)

    page.get_by_role('button', name='Управление объявлениями', exact=True).last.click()
    expect(page.locator('#page-title')).to_have_text('Управление объявлениями')
    page.get_by_role('button', name='Создать объявление', exact=True).click()
    form = page.locator('form[data-announcement-editor]')
    form.locator('[name=title]').fill(announcement_title)
    form.locator('[name=body]').fill('Публикация внутреннего объявления всем вымышленным студентам '+marker)
    with post_response(page, '/api/staff/announcements') as published:
        form.get_by_role('button', name='Опубликовать', exact=True).click()
    assert published.value.status == 201, published.value.text()
    announcement = published.value.json()
    assert announcement['sent'] >= 2
    expect(page.locator('.modal')).to_have_count(0)
    leave_demo(page)

    enter_demo(page, 0, 'Алина')
    go(page, address, 'consultations', 'Консультации')
    page.locator('#campus-query').fill(marker)
    expect(page.locator(f"button[data-c-action='consultation-book'][data-id='{slot['id']}']")).to_be_enabled()
    go(page, address, 'events', 'Жизнь кампуса')
    page.locator('#campus-query').fill(marker)
    expect(page.locator(f"button[data-c-action='event-register'][data-id='{event['id']}']")).to_be_enabled()
    go(page, address, 'notifications', 'Уведомления')
    expect(page.get_by_role('heading', name=announcement_title, exact=True)).to_be_visible()

    go(page, address, 'settings', 'Настройки')
    form = page.locator("form[data-c-form='preferences']")
    expect(form.locator('[name=weekly_goal]')).to_have_count(0)
    form.locator('[name=compact_mode]').check()
    form.locator('[name=email_notifications]').check()
    form.locator('[name=deadline_reminders]').uncheck()
    result = submit(page, 'preferences', '/api/services/preferences')
    assert result['email_notifications'] and not result['deadline_reminders'] and result['compact_mode']
    expect(page.locator('body')).to_have_class('compact-campus')
    page.reload()
    form = page.locator("form[data-c-form='preferences']")
    expect(form.locator('[name=weekly_goal]')).to_have_count(0)
    expect(form.locator('[name=compact_mode]')).to_be_checked()
    expect(form.locator('[name=email_notifications]')).to_be_checked()
    expect(form.locator('[name=deadline_reminders]')).not_to_be_checked()
    leave_demo(page)

    enter_demo(page, 1, 'Марк')
    go(page, address, 'settings', 'Настройки')
    form = page.locator("form[data-c-form='preferences']")
    expect(form.locator('[name=compact_mode]')).not_to_be_checked()
    expect(form.locator('[name=email_notifications]')).not_to_be_checked()
    expect(page.locator('body')).not_to_have_class('compact-campus')
    assert errors == []
