"""Isolated attendance, private files, review decisions and retention."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import secrets

from PIL import Image
import pytest
from sqlalchemy import select

from app.absence_certificate_db import (AbsenceCertificate, AbsenceCertificateAudit, AbsenceCertificateFile,
                                        AbsenceCertificateNote, AbsenceCertificateReview)
from app.db import SessionLocal, campus_today, utc_now
from app.learning_db import Attendance
from app.medical_retention import purge_private_evidence
from app.schedule_occurrences import class_data
from app.workspace_db import ScheduledClass
from scripts.academic_stage6_fixture import cleanup_fixture, create_fixture
from test_academic_workspace import HEAD, body
from test_api import client, sign_in


UPLOAD = '/api/learning/absence-certificates'
QUEUE = '/api/teaching/absence-certificates'
REGISTER = '/api/learning/attendance-register'


@pytest.fixture
def stage6(monkeypatch):
    monkeypatch.setenv('ATLAS_CERTIFICATE_KEY', secrets.token_urlsafe(32))
    token = secrets.token_hex(6)
    with client(), SessionLocal.begin() as db:
        fixture = create_fixture(db, token)
    try:
        yield fixture
    finally:
        with SessionLocal.begin() as db:
            assert cleanup_fixture(db, token) == 4


def connect(api, fixture, number):
    actor = fixture['actors'][str(number)]
    sign_in(api, actor['login'], actor['password'])
    return actor['id']


def record_marks(api, student_id, records, status='absent'):
    for row in records:
        journal = f"/api/teaching/class-attendance/{row['id']}"
        data = body(api.get(journal))
        person = next(item for item in data['students'] if item['id'] == student_id)
        body(api.put(journal, headers=HEAD, json=dict(student_id=student_id, day=row['day'],
                                                     status=status, version=person['attendance']['version'])))


def evidence(rows, format='PNG'):
    buffer = BytesIO()
    Image.new('RGB', (60, 80), 'white').save(buffer, format=format)
    return dict(file=dict(name=f'Справка.{format.lower()}', content=base64.b64encode(buffer.getvalue()).decode()),
                note='Вымышленная справка для двух дат', occurrences=[row['uid'] for row in rows])


def test_published_term_and_exact_occurrences(stage6):
    classes = stage6['records']
    with client() as student, client() as other, client() as teacher:
        student_id = connect(student, stage6, 0)
        other_id = connect(other, stage6, 1)
        connect(teacher, stage6, 2)
        record_marks(teacher, student_id, [classes['lecture']], 'present')
        record_marks(teacher, student_id, [classes['moved']])
        with SessionLocal.begin() as db:
            db.add(Attendance(student_id=student_id, subject=stage6['subjects'][1], day=campus_today()-timedelta(days=11), status='absent'))
        register = body(student.get(REGISTER))
        assert register['term']['starts_on'] < classes['lecture']['day'] < register['term']['ends_on']
        rows = {row['id']: row for row in register['items']}
        assert set(rows) == {row['uid'] for key, row in classes.items() if key not in ('future', 'previous')}
        assert {row['day'] for row in rows.values() if row['kind'] == 'lab'} == {classes['lab']['day'], classes['moved']['day']}
        assert all(row['kind'] != 'lab' for row in rows.values() if row['discipline'] == stage6['subjects'][1])
        moved = rows[classes['moved']['uid']]
        assert moved['day'] != classes['moved']['previous'] and moved['subgroup'] == 'Подгруппа 1'
        assert moved['status'] == 'absent' and moved['can_submit']
        assert rows[classes['lecture']['uid']]['status'] == 'present'
        assert rows[classes['missing']['uid']]['status'] == 'unmarked'
        assert rows[classes['cancelled']['uid']]['status'] == 'cancelled'
        assert rows[classes['extra']['uid']]['status'] == 'unmarked'
        assert all(row['kind'] != 'lab' and row['id'] != classes['extra']['uid'] for row in body(other.get(REGISTER))['items'])
        wrong_group = f"/api/teaching/class-attendance/{classes['lab']['id']}"
        assert teacher.put(wrong_group, headers=HEAD, json=dict(student_id=other_id, day=classes['lab']['day'],
                                                               status='absent', version=0)).status_code == 404
        assert teacher.get(REGISTER).status_code == 403
        random_day = campus_today() - timedelta(days=7)
        teacher_path = f"/api/teaching/{stage6['loads'][0]}/attendance"
        assert teacher.put(teacher_path, headers=HEAD, json=dict(student_id=student_id, day=str(random_day),
                                                                 status='absent', version=0)).status_code == 422


def test_upload_review_scope_reassignment_and_retention(stage6):
    records = stage6['records']
    with client() as student, client() as other, client() as teacher, client() as substitute:
        student_id = connect(student, stage6, 0)
        connect(other, stage6, 1)
        teacher_id = connect(teacher, stage6, 2)
        substitute_id = connect(substitute, stage6, 3)
        record_marks(teacher, student_id, [records['lab'], records['moved']])
        record_marks(substitute, student_id, [records['practice']])
        payload = evidence([records['lab'], records['practice']])
        assert student.post(UPLOAD, json=payload).status_code == 403
        assert other.post(UPLOAD, json=payload, headers=HEAD).status_code == 404
        damaged = {**payload, 'file': {'name':'x.pdf', 'content':base64.b64encode(b'%PDF-invalid').decode()}}
        assert student.post(UPLOAD, json=damaged, headers=HEAD).status_code == 422
        idem = {**HEAD, 'Idempotency-Key': 'isolated-certificate-workflow'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: student.post(UPLOAD, json=payload, headers=idem), range(2)))
        # Converting an identical concurrent upload can temporarily occupy the
        # conversion slot. A retry with the same key returns the prior receipt.
        assert sorted(result.status_code for result in outcomes) in ([200, 201], [201, 503])
        certificate_id = body(next(result for result in outcomes if result.status_code == 201), 201)['id']
        assert body(student.post(UPLOAD, json=payload, headers=idem))['id'] == certificate_id
        single_id = body(student.post(UPLOAD, json=evidence([records['moved']], 'PDF'), headers=HEAD), 201)['id']
        assert body(student.post(UPLOAD, json=evidence([records['lab']]), headers=HEAD), 409)['detail']
        doc_url = f'/api/absence-certificates/{certificate_id}/download'
        assert other.post(doc_url, headers=HEAD).status_code == 404
        assert substitute.post(f'/api/absence-certificates/{single_id}/download', headers=HEAD).status_code == 404
        assert student.get(doc_url).status_code == 405
        assert teacher.post(doc_url).status_code == 403
        file = teacher.post(doc_url, headers=HEAD)
        assert file.status_code == 200 and file.content.startswith(b'%PDF-')
        assert file.headers['Cache-Control'] == 'no-store, private' and 'attachment;' in file.headers['Content-Disposition']
        assert student.post(doc_url, headers=HEAD).content == file.content
        certificate = body(teacher.get(QUEUE, params={'id':certificate_id, 'status':'pending'}))['items'][0]
        peer = body(substitute.get(QUEUE, params={'id':certificate_id}))['items'][0]
        assert certificate['note'] == payload['note']
        original = certificate['entries'][0]
        assert [row['occurrence'] for row in certificate['entries']] == [records['lab']['uid']]
        assert [row['occurrence'] for row in peer['entries']] == [records['practice']['uid']]
        assert teacher.post(f'{QUEUE}/{certificate_id}/decision', headers=HEAD, json={
            'entries':[original['id'], peer['entries'][0]['id']], 'status':'accepted'}).status_code == 404

        with SessionLocal.begin() as db:
            from app.absence_certificates import notify_reassigned_reviews

            meeting = db.get(ScheduledClass, records['lab']['id'])
            meeting.teacher_id = stage6['actors']['3']['teacher_id']
            db.flush()
            notify_reassigned_reviews(db, [class_data(meeting)])
        assert teacher.get(f"/api/teaching/class-attendance/{records['lab']['id']}").status_code == 404
        assert body(substitute.get(f"/api/teaching/class-attendance/{records['lab']['id']}"))['students'][0]['id'] == student_id
        assert teacher.post(doc_url, headers=HEAD).status_code == 404
        assert body(teacher.get(QUEUE, params={'id':certificate_id}))['items'] == []
        assert any(notice['target'] == f'/app/absence-certificates?id={certificate_id}'
                   for notice in body(substitute.get('/api/workspace/notices'))['items'])
        accepted = substitute.post(f'{QUEUE}/{certificate_id}/decision', headers=HEAD, json={
            'entries':[original['id'], peer['entries'][0]['id']], 'status':'accepted'})
        assert body(accepted)['status'] == 'accepted'
        separate = body(teacher.get(QUEUE, params={'id':single_id}))['items'][0]['entries'][0]
        reason = 'Медицинских подробностей нет. Дата подтверждена для другого занятия.'
        body(teacher.post(f'{QUEUE}/{single_id}/decision', headers=HEAD, json={
            'entries':[separate['id']], 'status':'rejected', 'reason':reason}))
        result = {row['id']: row for row in body(student.get(REGISTER))['items']}
        assert result[records['lab']['uid']]['status'] == 'excused'
        assert result[records['moved']['uid']]['status'] == 'absent'
        assert result[records['moved']['uid']]['certificate']['reason'] == reason
        with SessionLocal.begin() as db:
            assert db.scalar(select(Attendance.status).where(Attendance.class_id == records['lab']['id'])) == 'absent'
            assert db.get(AbsenceCertificateFile, certificate_id).ciphertext != file.content
            assert reason.encode() not in db.get(AbsenceCertificateNote, (single_id, separate['id'])).ciphertext
            log = set(db.execute(select(AbsenceCertificateAudit.action, AbsenceCertificateAudit.actor_id)
                                 .where(AbsenceCertificateAudit.certificate_id.in_((certificate_id, single_id)))))
            assert {('submit', student_id), ('download', teacher_id), ('accepted', substitute_id), ('rejected', teacher_id)} <= log
            for key in (certificate_id, single_id):
                db.get(AbsenceCertificate, key).expires_at = utc_now() - timedelta(seconds=1)
        assert student.post(doc_url, headers=HEAD).status_code == 410
        assert purge_private_evidence() == 2
        with SessionLocal() as db:
            assert db.get(AbsenceCertificateFile, certificate_id) is None
            assert db.get(AbsenceCertificateNote, (single_id, separate['id'])) is None
            assert db.get(AbsenceCertificateReview, original['id']).status == 'accepted'
        assert next(row for row in body(student.get(REGISTER))['items'] if row['id'] == records['lab']['uid'])['status'] == 'excused'
