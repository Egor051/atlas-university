"""Submit private evidence and review it within the actual lesson's scope."""
from collections import defaultdict
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import Field, StringConstraints
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .absence_certificate_db import (AbsenceCertificate as Certificate, AbsenceCertificateAudit as Audit,
                                     AbsenceCertificateFile as File, AbsenceCertificateNote as Note,
                                     AbsenceCertificateReview as Review)
from .attendance_register import bind_mark, completed, occurrence_for_review, review_teacher, term_rows
from .config import DEMO_LOGINS, settings
from .db import User, utc_now
from .learning_db import Attendance
from .main import StrictBody, date_iso, get_db, require_roles, require_same_origin, require_student
from .medical_storage import MAX_ENCODED, certificate_key, decrypt, encrypt, sanitized_upload
from .schedule_occurrences import occurrence_key
from .services import begin_idempotent, commit_idempotent
from .session_security import as_utc
from .university_db import Teacher
from .workspace import lock_workspace, notify
from .workspace_db import GroupMember, ScheduledClass


RETAIN_FOR = timedelta(days=90)
QUEUE_LIMIT = 30
MAX_DAILY_UPLOADS = 10
STUDENT_TARGET = '/app/grades?kind=attendance'
TEACHER_TARGET = '/app/absence-certificates'

router = APIRouter()
write = [Depends(require_same_origin)]
teacher_only = require_roles('teacher')
OccurrenceKey = Annotated[str, StringConstraints(pattern=r'^(?:event-[0-9]{1,10}|lesson-[0-9]{1,10}-[0-9]{4}-[0-9]{2}-[0-9]{2})$')]
EntryId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
CertificateId = Annotated[int, Path(ge=1, le=2147483647)]


class Upload(StrictBody):
    name: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=MAX_ENCODED)


class CertificateBody(StrictBody):
    occurrences: list[OccurrenceKey] = Field(min_length=1, max_length=30)
    file: Upload
    note: str = Field(default='', max_length=500)


class DecisionBody(StrictBody):
    entries: list[EntryId] = Field(min_length=1, max_length=30)
    status: Literal['accepted', 'rejected']
    reason: str = Field(default='', max_length=500)


def availability(user):
    if settings.app_env == 'production' and user.login in DEMO_LOGINS:
        return 'В общедоступном демонстрационном кабинете справки недоступны.'
    if certificate_key() is None:
        return 'Хранилище справок пока не настроено.'
    return ''


def private_teachers(db, ids):
    stmt = select(User.id).where(User.id.in_(ids), User.role == 'teacher')
    if settings.app_env == 'production':
        stmt = stmt.where(User.login.not_in(DEMO_LOGINS))
    return set(db.scalars(stmt)) if ids else set()


def require_key(user):
    message = availability(user)
    if message:
        raise HTTPException(403 if settings.app_env == 'production' and user.login in DEMO_LOGINS else 503, message)
    return certificate_key()


def audit(db, certificate_id, action, now, *, actor=None, review=None):
    db.add(Audit(certificate_id=certificate_id, action=action, actor_id=actor, review_id=review, created_at=now))


def stored_file(certificate, file_id, now):
    return file_id is not None and now < as_utc(certificate.expires_at)


def read_note(key, note, certificate_id, entry):
    return decrypt(key, certificate_id, entry, note).decode() if key and note is not None else ''


def effective_review(row, certificate, file_available, now):
    if row.expired or (row.status == 'pending' and not file_available):
        reason = ('Срок хранения справки истёк. При необходимости отправьте документ повторно.'
                  if now >= as_utc(certificate.expires_at) else 'Файл недоступен. При необходимости отправьте документ повторно.')
        return 'rejected', reason
    return row.status, ''


def student_reviews(db, student_id, keys, now, key):
    if not keys:
        return {}
    stmt = (select(Review, Certificate, File.certificate_id, Note.ciphertext).join(Certificate, Certificate.id == Review.certificate_id)
            .outerjoin(File, File.certificate_id == Certificate.id)
            .outerjoin(Note, (Note.certificate_id == Certificate.id) & (Note.entry == Review.id))
            .where(Certificate.student_id == student_id, Review.occurrence.in_(keys)).order_by(Review.id.desc()))
    results = {}
    for row, certificate, file_id, reason in db.execute(stmt):
        if row.occurrence in results:
            continue
        file_available = stored_file(certificate, file_id, now)
        status, system_reason = effective_review(row, certificate, file_available, now)
        reason_text = read_note(key, reason, certificate.id, row.id) if file_available else ''
        results[row.occurrence] = dict(id=certificate.id, status=status, reason=system_reason or reason_text,
                                       submitted_at=date_iso(certificate.created_at), reviewed_at=date_iso(row.reviewed_at),
                                       expires_at=date_iso(certificate.expires_at), file_available=file_available and bool(key))
    return results


def status_for_record(row, mark, review):
    if row['status'] == 'cancelled':
        return 'cancelled'
    if mark is None or mark.status not in ('present', 'late', 'absent', 'excused'):
        return 'unmarked'
    return 'excused' if mark.status == 'absent' and review and review['status'] == 'accepted' else mark.status


def student_attendance_register(db, user, now):
    term, records = term_rows(db, user.id, now)
    message = availability(user)
    key = None if message else certificate_key()
    reviews = student_reviews(db, user.id, [view['uid'] for _, view, _, _ in records], now, key)
    eligible_teachers = private_teachers(db, {teacher for _, _, _, teacher in records if teacher}) if key else set()
    items = []
    for row, item, mark, teacher in records:
        review = reviews.get(item['uid'])
        status = status_for_record(row, mark, review)
        items.append(dict(id=item['uid'], class_id=row['id'] if not row.get('legacy_day') else None,
                          day=item['date'], start=item['start'], end=item['end'], discipline=item['subject'],
                          discipline_id=item['discipline_id'], title=item['title'], kind=item['type'], kind_label=item['kind'],
                          teacher=item['teacher'], group=item['group'], subgroup=item['subgroup'], status=status,
                          can_submit=status == 'absent' and teacher in eligible_teachers and (not review or review['status'] == 'rejected'),
                          certificate=review))
    return dict(term=term, items=items, available=not message, availability_message=message)


@router.get('/api/learning/attendance-register')
def attendance_register(user=Depends(require_student), db: Session = Depends(get_db)):
    return student_attendance_register(db, user, utc_now())


@router.post('/api/learning/absence-certificates', status_code=201, dependencies=write)
def submit(body: CertificateBody, request: Request, response: Response,
           user=Depends(require_student), db: Session = Depends(get_db)):
    key = require_key(user)
    selected = set(body.occurrences)
    if len(selected) != len(body.occurrences):
        raise HTTPException(422, 'Занятия в списке повторяются')
    student_id = user.id
    # Validate ownership before decoding the document. Release the read
    # transaction during the bounded conversion and recheck under the lock.
    _, rows = term_rows(db, student_id, utc_now())
    if not selected.issubset({view['uid'] for _, view, _, _ in rows}):
        raise HTTPException(404, 'Занятие не найдено в вашем расписании')
    db.rollback()
    content = sanitized_upload(body.file)
    lock_workspace(db, student_id)
    receipt, replay = begin_idempotent(db, request, response, user, 'absence_certificate', body.model_dump())
    if replay is not None:
        return replay
    now = utc_now()
    recent = list(db.scalars(select(Certificate.id).where(Certificate.student_id == student_id,
                             Certificate.created_at > now - timedelta(days=1)).limit(MAX_DAILY_UPLOADS)))
    if len(recent) == MAX_DAILY_UPLOADS:
        raise HTTPException(429, 'Достигнут дневной лимит справок. Один документ можно приложить к нескольким пропускам')
    _, rows = term_rows(db, student_id, now)
    chosen = [(row, view, mark, teacher) for row, view, mark, teacher in rows if view['uid'] in selected]
    teachers = private_teachers(db, {teacher for _, _, _, teacher in chosen if teacher})
    reviews = student_reviews(db, student_id, selected, now, key)
    if (len(chosen) != len(selected) or any(
            mark is None or mark.status != 'absent' or row['status'] != 'active' or teacher not in teachers
            or (view['uid'] in reviews and reviews[view['uid']]['status'] != 'rejected')
            for row, view, mark, teacher in chosen)):
        raise HTTPException(409, 'Проверьте отметки и выберите пропуски, для которых доступна отправка')
    certificate = Certificate(student_id=student_id, created_at=now, expires_at=now + RETAIN_FOR)
    db.add(certificate)
    db.flush()
    cert_id = certificate.id
    db.add(File(certificate_id=cert_id, ciphertext=encrypt(key, cert_id, 'file', content)))
    if body.note.strip():
        db.add(Note(certificate_id=cert_id, entry=0, ciphertext=encrypt(key, cert_id, 0, body.note.strip().encode())))
    for row, view, mark, teacher in chosen:
        bind_mark(mark, row)
        db.add(Review(certificate_id=cert_id, attendance_id=mark.id, occurrence=view['uid'], notified_teacher_id=teacher,
                      day=date.fromisoformat(view['date']), start=view['start'], end=view['end'],
                      discipline=view['subject'], kind_label=view['kind']))
    for teacher in teachers:
        notify(db, teacher, 'Поступила справка о пропуске', 'Документ доступен в очереди справок.', f'{TEACHER_TARGET}?id={cert_id}')
    audit(db, cert_id, 'submit', now, actor=student_id)
    return commit_idempotent(db, receipt, {'id': cert_id, 'status': 'pending'})


def scope_reviews(user_id):
    member = select(GroupMember.student_id).where(GroupMember.student_id == Attendance.student_id,
        GroupMember.group_id == ScheduledClass.group_id,
        or_(ScheduledClass.subgroup_id.is_(None), GroupMember.subgroup_id == ScheduledClass.subgroup_id))
    member = member.correlate(Attendance, ScheduledClass).exists()
    assigned = (select(ScheduledClass.id).join(Teacher).where(ScheduledClass.id == Attendance.class_id,
        Teacher.user_id == user_id, or_(ScheduledClass.student_id == Attendance.student_id,
        ScheduledClass.student_id.is_(None) & member))).exists()
    legacy = (Attendance.legacy_lesson_id.is_not(None) & (Review.notified_teacher_id == user_id))
    return or_(assigned, legacy)


def visible_teacher_records(db, user_id, rows):
    for review, mark in rows:
        meeting = occurrence_for_review(db, mark.student_id, review.occurrence)
        if meeting is not None and review_teacher(db, meeting) == user_id:
            yield review, mark, meeting


def review_payload(review, mark, meeting, certificate, now, key, file_available, reason):
    status, system_reason = effective_review(review, certificate, file_available, now)
    return dict(id=review.id, occurrence=review.occurrence, day=meeting['day'], start=meeting['start'], end=meeting['end'],
                discipline=meeting['discipline'], kind_label=meeting['kind_label'], status=status,
                reason=system_reason or (read_note(key, reason, certificate.id, review.id) if file_available else ''),
                reviewed_at=date_iso(review.reviewed_at), can_review=status == 'pending' and mark.status == 'absent'
                and meeting['status'] == 'active' and completed(meeting, now))


@router.get('/api/teaching/absence-certificates')
def teacher_queue(status: Literal['pending', 'accepted', 'rejected'] | None = None,
                  id: int | None = Query(None, ge=1, le=2147483647), offset: int = Query(0, ge=0, le=2147483647),
                  user=Depends(teacher_only), db: Session = Depends(get_db)):
    # List metadata only. Binary payloads are fetched only by the audited action.
    message = availability(user)
    result = dict(items=[], more=False, offset=offset, limit=QUEUE_LIMIT, available=not message, availability_message=message)
    if message:
        return result
    key = certificate_key()
    now = utc_now()
    candidates = (select(Review.certificate_id).join(Attendance, Attendance.id == Review.attendance_id).where(scope_reviews(user.id)))
    file_present = select(File.certificate_id).where(File.certificate_id == Certificate.id).correlate(Certificate).exists()
    active_document = (Certificate.expires_at > now) & file_present
    if status == 'pending':
        candidates = candidates.where(Review.status == 'pending', active_document)
    elif status == 'rejected':
        candidates = candidates.where(or_(Review.status == 'rejected', (Review.status == 'pending') & ~active_document))
    elif status == 'accepted':
        candidates = candidates.where(Review.status == 'accepted')
    page = (select(Certificate, User.full_name, file_present.label('file_present')).join(User, User.id == Certificate.student_id)
            .where(candidates.where(Review.certificate_id == Certificate.id).exists())
            .order_by(Certificate.created_at.desc(), Certificate.id.desc()).offset(offset).limit(QUEUE_LIMIT + 1))
    if id is not None:
        page = page.where(Certificate.id == id)
    page_rows = db.execute(page).all()
    cert_ids = [cert.id for cert, _, _ in page_rows[:QUEUE_LIMIT]]
    result['more'] = len(page_rows) > QUEUE_LIMIT
    if not cert_ids:
        return result
    scoped = (select(Review, Attendance).join(Attendance, Attendance.id == Review.attendance_id)
              .where(Review.certificate_id.in_(cert_ids), scope_reviews(user.id)).order_by(Review.day, Review.start, Review.id))
    records = defaultdict(list)
    for review, mark, meeting in visible_teacher_records(db, user.id, db.execute(scoped)):
        records[review.certificate_id].append((review, mark, meeting))
    note_keys = {review.id for rows in records.values() for review, _, _ in rows} | {0}
    notes = {(note.certificate_id, note.entry): note.ciphertext for note in db.scalars(select(Note).where(
        Note.certificate_id.in_(cert_ids), Note.entry.in_(note_keys)))}
    for certificate, student, has_file in page_rows[:QUEUE_LIMIT]:
        file_available = stored_file(certificate, certificate.id if has_file else None, now)
        entries = [review_payload(review, mark, meeting, certificate, now, key, file_available,
                                  notes.get((certificate.id, review.id))) for review, mark, meeting in records[certificate.id]]
        if not entries or (status and all(entry['status'] != status for entry in entries)):
            continue
        note = read_note(key, notes.get((certificate.id, 0)), certificate.id, 0) if file_available else ''
        result['items'].append(dict(id=certificate.id, student=student, submitted_at=date_iso(certificate.created_at),
                                    expires_at=date_iso(certificate.expires_at), file_available=file_available, note=note, entries=entries))
    return result


@router.post('/api/absence-certificates/{certificate_id}/download', dependencies=write)
def download(certificate_id: CertificateId, user=Depends(require_roles('student', 'teacher')), db: Session = Depends(get_db)):
    key = require_key(user)
    lock_workspace(db, user.id)
    certificate = db.get(Certificate, certificate_id)
    if certificate is None or (user.role == 'student' and certificate.student_id != user.id):
        raise HTTPException(404, 'Справка не найдена')
    if user.role == 'teacher':
        scoped = select(Review, Attendance).join(Attendance, Attendance.id == Review.attendance_id).where(
            Review.certificate_id == certificate.id, scope_reviews(user.id))
        if next(visible_teacher_records(db, user.id, db.execute(scoped)), None) is None:
            raise HTTPException(404, 'Справка не найдена')
    now = utc_now()
    file = db.get(File, certificate.id) if now < as_utc(certificate.expires_at) else None
    if file is None:
        raise HTTPException(410, 'Файл справки больше недоступен')
    payload = decrypt(key, certificate.id, 'file', file.ciphertext)
    audit(db, certificate.id, 'download', now, actor=user.id)
    db.commit()
    return Response(payload, media_type='application/pdf', headers={
        'Content-Disposition': 'attachment; filename="attendance-certificate.pdf"',
        'Content-Security-Policy': "sandbox; default-src 'none'; frame-ancestors 'none'",
        'Cross-Origin-Resource-Policy': 'same-origin',
    })


@router.post('/api/teaching/absence-certificates/{certificate_id}/decision', dependencies=write)
def decide(certificate_id: CertificateId, body: DecisionBody, user=Depends(teacher_only), db: Session = Depends(get_db)):
    key = require_key(user)
    lock_workspace(db, user.id)
    certificate = db.get(Certificate, certificate_id)
    scoped = select(Review, Attendance).join(Attendance, Attendance.id == Review.attendance_id).where(
        Review.certificate_id == certificate_id, Review.id.in_(body.entries), scope_reviews(user.id))
    rows = list(visible_teacher_records(db, user.id, db.execute(scoped)))
    if certificate is None or len(rows) != len(set(body.entries)):
        raise HTTPException(404, 'Пропуски не найдены в вашей очереди')
    reason = body.reason.strip() if body.status == 'rejected' else ''
    now = utc_now()
    if all(row.status == body.status and row.reviewed_by == user.id for row, _, _ in rows):
        return {'id': certificate.id, 'status': body.status}
    if (now >= as_utc(certificate.expires_at) or db.scalar(select(File.certificate_id).where(File.certificate_id == certificate.id)) is None
            or any(row.status != 'pending' or mark.status != 'absent' or meeting['status'] != 'active'
                   or not completed(meeting, now) for row, mark, meeting in rows)):
        raise HTTPException(409, 'Справка уже рассмотрена, файл удалён или отметка изменилась. Обновите очередь')
    for row, _, _ in rows:
        row.status, row.reviewed_by, row.reviewed_at = body.status, user.id, now
        if reason:
            db.add(Note(certificate_id=certificate.id, entry=row.id, ciphertext=encrypt(key, certificate.id, row.id, reason.encode())))
        audit(db, certificate.id, body.status, now, actor=user.id, review=row.id)
    label = 'Справка принята' if body.status == 'accepted' else 'Справка отклонена'
    notify(db, certificate.student_id, label, 'Решение доступно в таблице посещаемости.', STUDENT_TARGET)
    db.commit()
    return {'id': certificate.id, 'status': body.status}


def notify_reassigned_reviews(db, occurrences):
    keys = [occurrence_key(row) for row in occurrences]
    if not keys:
        return
    now = utc_now()
    rows = db.execute(select(Review, Certificate.student_id).join(Certificate, Certificate.id == Review.certificate_id).where(
        Review.occurrence.in_(keys), Review.status == 'pending', Certificate.expires_at > now))
    recipients = set()
    for review, student_id in rows:
        meeting = occurrence_for_review(db, student_id, review.occurrence)
        teacher = review_teacher(db, meeting) if meeting and meeting['status'] == 'active' else None
        if teacher and teacher != review.notified_teacher_id and teacher in private_teachers(db, {teacher}):
            review.notified_teacher_id = teacher
            recipients.add((teacher, review.certificate_id))
            audit(db, review.certificate_id, 'reassigned', now, review=review.id)
    for teacher, cert_id in recipients:
        notify(db, teacher, 'Поступила справка о пропуске', 'Документ доступен в очереди справок.', f'{TEACHER_TARGET}?id={cert_id}')
