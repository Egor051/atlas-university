"""Orders, staff confirmation, and immutable output for the Appendix 4 form."""

from sqlalchemy import select

from app.certificate_catalog import APPENDIX_4, APPENDIX_4_FORM
from app.certificates import CertificateEnrollment, CertificateIssue
from app.db import SessionLocal, User
from test_api import client, sign_in


WRITE = {'X-Requested-With': 'ATLAS'}


def test_appendix_4_order_requires_enrollment_and_a_known_destination():
    with client() as student, client() as eligible:
        sign_in(student, 'alina.demo', 'AtlasDemo!2026-A')
        sign_in(eligible, 'mark.demo', 'AtlasDemo!2026-M')
        for browser, expected in ((student, False), (eligible, True)):
            catalog = browser.get('/api/requests/types?kind=certificate').json()
            service = next(row for row in catalog if row['id'] == APPENDIX_4)
            assert service['available'] is expected
            assert service['department'] == 'Учебный офис'
            assert service['form'] == APPENDIX_4_FORM
            assert 'birth_year' not in service
            assert all(row['kind'] == 'certificate' for row in catalog)
            assert all(row['kind'] == 'request' for row in browser.get('/api/requests/types?kind=request').json())

        body = {'type': APPENDIX_4, 'details': {'commissioner': 'north'}}
        assert student.post('/api/requests', json=body, headers=WRITE).status_code == 403
        assert eligible.post('/api/requests', json={'type': APPENDIX_4}, headers=WRITE).status_code == 422
        assert eligible.post('/api/requests', json={'type': APPENDIX_4, 'details': {'commissioner': 'private'}},
                             headers=WRITE).status_code == 422
        assert eligible.post('/api/requests', json={'type': APPENDIX_4, 'student_id': 1, **body},
                             headers=WRITE).status_code == 422


def test_appendix_4_staff_confirmation_and_download_are_scoped():
    with client() as mark, client() as alina, client() as dean, client() as vuc:
        sign_in(mark, 'mark.demo', 'AtlasDemo!2026-M')
        sign_in(alina, 'alina.demo', 'AtlasDemo!2026-A')
        sign_in(dean, 'dean.demo', 'AtlasStaff!2026-D')
        sign_in(vuc, 'vuc.demo', 'AtlasCenter!2026-V')
        order_headers = {**WRITE, 'Idempotency-Key': 'appendix-4-test-order'}
        body = {'type': APPENDIX_4, 'details': {'commissioner': 'north'}}
        order = mark.post('/api/requests', json=body, headers=order_headers)
        assert order.status_code == 201, order.text
        request_id = order.json()['id']
        repeated = mark.post('/api/requests', json=body, headers=order_headers)
        assert repeated.status_code == 200 and repeated.json()['id'] == request_id
        path = f'/api/requests/{request_id}'
        staff_path = f'/api/staff/requests/{request_id}'
        assert mark.get(path + '/document').status_code == 409
        assert alina.get(path).status_code == 404
        assert alina.get(path + '/document?preview=true').status_code == 404
        assert vuc.get(staff_path).status_code == 403
        assert vuc.post(staff_path + '/status', json={'status': 'review'}, headers=WRITE).status_code == 403
        assert alina.post(staff_path + '/status', json={'status': 'review'}, headers=WRITE).status_code == 403
        office_notices = [row for row in dean.get('/api/notifications').json() if row['request_id'] == request_id]
        assert [row['target'] for row in office_notices] == ['/app/staff?kind=certificate']

        for browser, prefix in ((mark, '/api/requests'), (dean, '/api/staff/requests')):
            assert request_id in {row['id'] for row in browser.get(prefix + '?kind=certificate').json()}
            assert request_id not in {row['id'] for row in browser.get(prefix + '?kind=request').json()}

        detail = dean.get(staff_path).json()
        assert any(row['label'] == 'Год поступления' for row in detail['certificate_enrollment'])
        assert 'certificate_enrollment' not in mark.get(path).json()
        review = dean.post(staff_path + '/status', json={'status': 'review', 'expected_version': detail['version']}, headers=WRITE)
        assert review.status_code == 200
        finish = {'status': 'ready', 'expected_version': review.json()['version'], 'message': 'Подготовлен документ по заявке.'}
        assert dean.post(staff_path + '/status', json=finish, headers=WRITE).status_code == 422
        assert mark.get(path).json()['status'] == 'review'
        ready = dean.post(staff_path + '/status', json={**finish, 'confirmed_enrollment': True}, headers=WRITE)
        assert ready.status_code == 200, ready.text
        stale = dean.post(staff_path + '/status', json={**finish, 'confirmed_enrollment': True}, headers=WRITE)
        assert stale.status_code == 409
        history = mark.get(path).json()['history']
        assert [row['status'] for row in history] == ['submitted', 'review', 'ready']
        assert [row['title'] for row in mark.get('/api/notifications').json()
                if row['request_id'] == request_id and row['target'] == '/app/certificates'].count('Справка готова') == 1

        with SessionLocal() as db:
            issue = db.get(CertificateIssue, request_id)
            assert issue.data['commissioner'].endswith('Северный (учебный)')
            student = db.scalar(select(User).where(User.login == 'mark.demo'))
            enrolled = db.get(CertificateEnrollment, student.id)
            original = enrolled.data.copy()
            enrolled.data = {**original, 'full_name': 'Изменённая запись'}
            db.commit()
        try:
            result = mark.get(path + '/document')
            preview = mark.get(path + '/document?preview=true')
            assert result.status_code == preview.status_code == 200
            assert result.headers['Content-Disposition'].startswith('attachment;')
            assert preview.headers['Content-Disposition'].startswith('inline;')
            assert APPENDIX_4_FORM in result.text and 'Северин Марк' in result.text
            assert 'Изменённая запись' not in result.text
            assert 'подпись отсутствует' in result.text and 'Не имеет юридической силы' in result.text
        finally:
            with SessionLocal() as db:
                db.get(CertificateEnrollment, student.id).data = original
                db.commit()
