"""A real office-to-student publication through the browser and API."""
import os
import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import frontend_browser, frontend_page, frontend_server

pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1', reason='Opt-in local Chromium')


def login(page, base, login, password):
    page.goto(base)
    form = page.locator('#login-form')
    form.get_by_label('Логин').fill(login)
    form.get_by_label('Пароль').fill(password)
    form.get_by_role('button', name='Войти в кабинет').click()
    expect(page.locator('.shell').or_(page.locator('#login-error:visible'))).to_be_visible()
    assert page.locator('.shell').count() == 1, page.locator('#login-error').inner_text()


def test_announcement_preview_publish_and_home_layout(frontend_page):
    office, base = frontend_page
    errors = []
    office.on('pageerror', lambda error: errors.append(str(error)))
    login(office, base, 'dean.demo', 'AtlasStaff!2026-D')
    office.get_by_role('navigation', name='Работа со студентами — разделы').get_by_role('link', name='Управление объявлениями').click()
    expect(office.get_by_role('heading', name='Управление объявлениями')).to_be_visible()
    office.get_by_role('button', name='Создать объявление').click()
    form = office.get_by_role('dialog', name='Создать объявление')
    title = f'Уточнение сроков {uuid4().hex[:6]}'
    summary = 'Начало длинного анонса. ' + ('Сверьте ближайшие даты по своим дисциплинам. ' * 8) + 'Окончание анонса.'
    body = 'Первая строка\n\n## Подробности сроков\n\n' + ('ДлинныйТекст' * 120) + '\n<b>Последняя строка</b>'
    form.get_by_label('Заголовок').fill(title)
    form.get_by_label('Анонс', exact=True).fill(summary)
    form.get_by_label('Текст объявления').fill(body)
    form.get_by_label('Приоритет').select_option('critical')
    form.get_by_role('button', name='Предпросмотр').click()
    preview = form.get_by_role('region', name='Предпросмотр объявления')
    expect(preview.get_by_role('heading', name=title)).to_be_visible()
    expect(preview.locator('.announcement-body')).to_contain_text('<b>Последняя строка</b>')
    expect(preview.get_by_role('heading', name='Подробности сроков')).to_be_visible()
    form.get_by_role('button', name='Сохранить черновик').click()
    expect(form).to_have_count(0)
    expect(office.get_by_role('heading', name=title)).to_be_visible()
    office.get_by_role('button', name='Редактировать').click()
    edit = office.get_by_role('dialog', name='Редактировать объявление')
    edit.get_by_label('Статус').select_option('published')
    edit.get_by_role('button', name='Сохранить', exact=True).click()
    expect(edit).to_have_count(0)
    expect(office.locator('.announcement-history')).to_contain_text('Опубликовано')
    office.reload()
    expect(office.get_by_role('heading', name=title)).to_be_visible()

    with office.context.browser.new_context(viewport={'width': 1440, 'height': 1000}) as context:
        student = context.new_page()
        student.on('pageerror', lambda error: errors.append(str(error)))
        login(student, base, 'alina.demo', 'AtlasDemo!2026-A')
        student.goto(base + '/app/home')
        timeline = student.get_by_role('region', name='Объявления')
        item = timeline.get_by_role('link', name=title)
        expect(item).to_be_visible()
        assert timeline.bounding_box()['y'] < 850
        viewport = timeline.get_by_role('region', name='Лента последних объявлений')
        assert viewport.evaluate('node => node.scrollHeight > node.clientHeight')
        viewport.press('End')
        student.wait_for_function("() => document.querySelector('#announcement-timeline-items').scrollTop > 0")
        viewport.press('Home')
        card = item.locator('xpath=ancestor::article')
        button = card.locator('.announcement-preview-toggle')
        full = card.locator('.announcement-summary')
        teaser = card.locator('.announcement-teaser')
        collapsed = teaser.inner_text()
        assert collapsed.startswith('Начало длинного анонса.') and collapsed.endswith('…')
        assert summary.startswith(collapsed[:-1])
        assert summary[len(collapsed) - 1:].lstrip('.…')[:1].isspace()
        expect(full).to_be_hidden()
        expect(card.get_by_role('button', name='Прочитать анонс')).to_have_count(0)
        card.locator('.announcement-meta').click()
        expect(button).to_have_attribute('aria-expanded', 'false')
        height = card.bounding_box()['height']
        next_top = card.evaluate('node => node.parentElement.nextElementSibling.offsetTop')
        button.press('Space')
        expect(button).to_be_focused()
        expect(button).to_have_attribute('aria-expanded', 'true')
        expect(full).to_have_text(summary)
        expect(full).to_be_visible()
        expect(teaser).to_be_hidden()
        expect(student).to_have_url(base + '/app/home')
        student.wait_for_function('node => !node.getAnimations().length', arg=button.element_handle())
        assert card.bounding_box()['height'] > height
        assert card.evaluate('node => node.parentElement.nextElementSibling.offsetTop') > next_top
        full.click()
        expect(button).to_have_attribute('aria-expanded', 'false')
        expect(full).to_be_hidden()
        expect(teaser).to_have_text(collapsed)
        timeline.get_by_role('button', name='Важные').click()
        expect(item).to_have_count(0)
        timeline.get_by_role('button', name='Срочные').click()
        expect(item).to_be_visible()
        for width in [320, 360, 390, 768, 1024, 1280, 1440, 1920]:
            student.set_viewport_size({'width': width, 'height': 1000})
            assert student.evaluate('document.documentElement.scrollWidth') <= width
            assert student.locator('.announcement-track').evaluate('node => node.scrollWidth <= node.clientWidth')
        deadlines = student.get_by_role('heading', name='Ближайшие сроки').locator('xpath=ancestor::section[1]')
        notices = student.get_by_role('heading', name='Уведомления').locator('xpath=ancestor::section[1]')
        gap = notices.bounding_box()['y'] - (deadlines.bounding_box()['y'] + deadlines.bounding_box()['height'])
        assert 0 <= gap <= 20
        item.click()
        expect(student.get_by_role('heading', name=title)).to_be_visible()
        expect(student.locator('.announcement-detail .announcement-body')).to_contain_text('<b>Последняя строка</b>')
        expect(student.get_by_role('heading', name='Подробности сроков')).to_be_visible()
        student.get_by_role('link', name='К объявлениям').click()
        student.get_by_label('Поиск', exact=True).fill(title)
        student.get_by_role('button', name='Применить').click()
        expect(student.locator('.announcement-list .announcement-list-item')).to_have_count(1)
        student.locator('#side-nav a[data-route="notifications"]').click()
        notice = student.locator('.notification-full').filter(has_text=title)
        notice.get_by_role('button', name='Открыть', exact=True).click()
        expect(student.get_by_role('heading', name=title)).to_be_visible()
        expect(student.locator('.announcement-detail')).to_be_visible()
    assert errors == []


@pytest.mark.parametrize('width,theme,compact', [(360, 'light', False), (390, 'dark', True)])
def test_timeline_short_missing_and_unicode_previews(frontend_page, width, theme, compact):
    office, base = frontend_page
    login(office, base, 'dean.demo', 'AtlasStaff!2026-D')
    marker = uuid4().hex[:6]
    symbol = '👩‍🎓'
    long_title = 'ДлинныйЗаголовок' * 10 + marker
    short = 'Аудитория уточнена.'
    long_summary = symbol * 170 + '\n<b>Последняя строка анонса</b>'
    records = [
        ('Короткий ' + marker, short, 'Текст для короткого анонса.'),
        ('Без анонса ' + marker, '', 'Начало статьи. ' * 25 + '\n\nОкончание статьи.'),
        (long_title, long_summary, 'Полный текст отдельной публикации.'),
    ]
    for title, summary, body in records:
        response = office.request.post(base + '/api/staff/announcements', headers={'X-Requested-With': 'ATLAS'},
                                       data={'title': title, 'summary': summary, 'body': body})
        assert response.status == 201, response.text()
    with office.context.browser.new_context(viewport={'width': width, 'height': 850}, color_scheme=theme,
                                            reduced_motion='reduce', has_touch=True) as context:
        student = context.new_page()
        login(student, base, 'alina.demo', 'AtlasDemo!2026-A')
        response = student.request.post(base + '/api/services/preferences', headers={'X-Requested-With': 'ATLAS'},
                                        data={'compact_mode': compact})
        assert response.ok, response.text()
        student.reload()
        timeline = student.get_by_role('region', name='Объявления')
        if compact:
            expect(student.locator('body')).to_have_class('compact-campus')
        short_card, fallback, long_card = [timeline.get_by_role('link', name=title, exact=True).locator('xpath=ancestor::article')
                                           for title, _, _ in records]
        expect(short_card.locator('.announcement-excerpt')).to_have_text(short)
        expect(short_card.get_by_role('button')).to_have_count(0)
        expect(fallback.locator('.announcement-excerpt')).to_have_text(re.compile(r'^Начало статьи\..*…$'))
        expect(fallback.get_by_role('button')).to_have_count(0)
        button = long_card.get_by_role('button')
        expect(button.locator('.announcement-teaser')).to_have_text(symbol * 159 + '…')
        button.tap()
        expect(button).to_have_attribute('aria-expanded', 'true')
        assert button.locator('.announcement-summary').text_content() == long_summary
        assert button.evaluate('node => node.getAnimations().length') == 0
        expect(button.locator('b')).to_have_count(0)
        assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
        button.press('Enter')
        expect(button.locator('.announcement-summary')).to_be_hidden()
        long_card.get_by_role('link', name=long_title).click()
        expect(student.locator('.announcement-detail .announcement-body')).to_have_text(records[-1][2])
        assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
