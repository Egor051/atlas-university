"""Browser verification of the Appendix 4 workflow on the isolated API."""

import os

import pytest
from playwright.sync_api import expect

from test_frontend_contracts import enter_demo, frontend_browser, frontend_page, frontend_server


pytestmark = pytest.mark.skipif(os.environ.get('ATLAS_RUN_BROWSER_TESTS') != '1',
                                reason='Opt-in isolated Chromium')


def test_appendix_4_from_order_to_preview(frontend_page, frontend_browser):
    student, base = frontend_page
    student.set_viewport_size({'width': 360, 'height': 800})
    student.goto(base)
    enter_demo(student, 1, 'Марк')
    student.goto(base + '/app/certificates')
    expect(student.locator('#page-title')).to_have_text('Справки')
    student.locator('[data-request-view="services"]').first.click()
    student.locator('#service-search').fill('комиссариата')
    certificate = student.locator('.certificate-service')
    expect(certificate).to_have_count(1)
    expect(certificate).to_contain_text('№ 663')
    assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
    certificate.get_by_role('button', name='Заказать справку').click()
    form = student.locator('#request-form')
    expect(form.locator('#doc-type')).to_have_value('military_appendix_4')
    form.locator('[name="commissioner"]').select_option('north')
    with student.expect_response(lambda r: r.url == base + '/api/requests' and r.request.method == 'POST') as response:
        form.locator('button[type="submit"]').click()
    assert response.value.status == 201, response.value.text()
    request_id = response.value.json()['id']
    expect(student.locator('.modal .request-status.submitted')).to_be_visible()
    student.locator('.modal .close-btn').click()

    office = frontend_browser.new_context(viewport={'width': 1440, 'height': 900}, locale='ru-RU')
    try:
        staff = office.new_page()
        staff.goto(base)
        staff.get_by_role('button', name='Выбрать аккаунт', exact=True).click()
        staff.locator('[data-demo="2"]').click()
        expect(staff.locator('#page-title')).to_have_text('Учебный офис')
        staff.locator('[data-staff-kind="certificate"]').click()
        staff.locator(f'.request-row[data-id="{request_id}"]').click()
        staff.get_by_text('Сведения для приложения № 4', exact=True).click()
        expect(staff.locator('.service-details-summary')).to_contain_text(['Военный комиссариат', 'Год поступления'])
        staff.locator('#staff-status').select_option('review')
        staff.locator('#staff-form button[type="submit"]').click()
        expect(staff.locator('.modal .request-status.review')).to_be_visible()
        staff.locator('#staff-status').select_option('ready')
        staff.locator('#staff-message').fill('Сведения сверены, справка подготовлена.')
        staff.locator('#staff-form button[type="submit"]').click()
        expect(staff.locator('#staff-error')).to_contain_text('Подтвердите сверку')
        staff.locator('[name="confirmed_enrollment"]').check()
        staff.locator('#staff-form button[type="submit"]').click()
        expect(staff.locator('.modal .request-status.ready')).to_be_visible()
    finally:
        office.close()

    student.goto(base + '/app/certificates')
    student.locator('[data-request-filter="ready"]').click()
    student.locator(f'.request-row[data-id="{request_id}"]').click()
    with student.expect_popup() as opened:
        student.locator('.document-result').get_by_role('link', name='Открыть').click()
    preview = opened.value
    expect(preview.locator('h1')).to_contain_text('среднего профессионального или высшего образования')
    expect(preview.locator('main')).to_contain_text('подпись отсутствует')
    preview.close()
    assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
