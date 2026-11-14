"""Assignment data shared by the existing learning and teaching APIs."""
import base64
import binascii
import json
import re
from datetime import datetime, time, timedelta
from pathlib import PurePath
from urllib.parse import quote, urlsplit

from fastapi import HTTPException, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import aliased

from .assignment_db import SubmissionAttachment, SubmissionAttempt
from .db import CAMPUS_TZ, Deadline, Notification, User, utc_now
from .learning_db import AssignmentSubmission
from .session_security import as_utc
from .workspace import notify
from .workspace_db import GroupMember, GroupWork, TeachingLoad, WorkDelivery, WorkFeedback


WORK_KINDS = ('homework', 'lab', 'practice', 'test', 'independent', 'essay', 'talk',
              'project', 'term_paper', 'individual', 'group', 'other')
FORMATS = ('pdf', 'txt', 'md', 'csv', 'png', 'jpg', 'jpeg', 'docx', 'xlsx', 'pptx')
MAX_UPLOAD_BYTES = 1024 * 1024
DEFAULT_POLICY = {
    'kind': 'homework', 'custom_kind': '', 'description': '', 'criteria': '', 'max_points': 100,
    'methods': ['text', 'url'], 'formats': list(FORMATS), 'allow_resubmission': True,
    'max_attempts': None, 'allow_late': True, 'materials': [], 'recipient_ids': [],
    'team_lead_id': None, 'award_mode': 'all', 'class_id': None,
}
ACTIONABLE = ('not_started', 'in_progress', 'withdrawn', 'revision_required')
SUBMITTED = ('submitted', 'resubmitted', 'in_review', 'accepted', 'completed')
DEFAULT_INSTRUCTIONS = 'Подготовьте решение, опишите ход работы и приложите результат.'


def iso(value):
    return as_utc(value).isoformat() if value is not None else None


def work_policy(row):
    return {**DEFAULT_POLICY, **json.loads(row.policy_json)} if row else DEFAULT_POLICY


def effective_state(work, now=None):
    if work is None:
        return 'published'
    if work.state == 'scheduled' and as_utc(work.publish_at) <= (now or utc_now()):
        return 'published'
    return work.state


def visible_deadline(now=None):
    """Correlate to Deadline so every student projection uses the same visibility rule."""
    hidden = select(WorkDelivery.deadline_id).join(GroupWork).where(
        WorkDelivery.deadline_id == Deadline.id,
        or_(WorkDelivery.active.is_(False), GroupWork.state == 'draft',
            and_(GroupWork.state == 'scheduled', GroupWork.publish_at > (now or utc_now()))),
    )
    return ~hidden.correlate(Deadline).exists()


def base_due(day):
    return as_utc(datetime.combine(day, time(23, 59, 59), CAMPUS_TZ))


def effective_due(deadline, delivery, work):
    due = as_utc(work.due_at) if work is not None and work.due_at else base_due(work.due if work else deadline.due_date)
    if delivery is not None and delivery.extended_until:
        due = max(due, as_utc(delivery.extended_until))
    return due


def work_data(row):
    return {
        **work_policy(row), 'id': row.id, 'title': row.title, 'instructions': row.instructions,
        'due': row.due.isoformat(), 'version': row.version, 'state': effective_state(row),
        'publish_at': iso(row.publish_at), 'due_at': iso(row.due_at or base_due(row.due)),
    }


def assignment_notice(db, deadline, title, body, *, event_key=None):
    target = f'/app/assignments?id={deadline.id}'
    if event_key is None:
        notify(db, deadline.student_id, title, body, target, student=True)
        return
    insert = pg_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
    db.execute(insert(Notification).values(student_id=deadline.student_id, title=title, body=body,
               target=target, category='academic', is_read=False, created_at=utc_now(), event_key=event_key)
               .on_conflict_do_nothing(index_elements=['event_key']))


def deliver_work(db, load, work, student_id, *, notify_student=True):
    deadline = Deadline(student_id=student_id, subject=load.discipline.title, title=work.title, due_date=work.due)
    db.add(deadline)
    db.flush()
    db.add(WorkDelivery(deadline_id=deadline.id, work_id=work.id))
    if notify_student and effective_state(work) == 'published':
        assignment_notice(db, deadline, 'Опубликовано учебное задание', work.title,
                          event_key=f'work-publish:{work.id}:{deadline.id}')
    return deadline


def assignment_recipients(db, load, work, *, current_members=True):
    query = (select(Deadline, WorkDelivery, User.full_name).select_from(WorkDelivery).join(Deadline)
             .join(User, User.id == Deadline.student_id)
             .where(WorkDelivery.work_id == work.id, WorkDelivery.active.is_(True), User.role == 'student'))
    if current_members:
        query = query.join(GroupMember, GroupMember.student_id == Deadline.student_id).where(
            GroupMember.group_id == load.group_id)
    return db.execute(query.order_by(Deadline.student_id, Deadline.id)).all()


def team_reference(db, delivery, work, viewer_id):
    """Resolve one canonical submission for a team, scoped to the current group."""
    lead = work_policy(work)['team_lead_id']
    if not lead:
        return None, None
    query = (select(Deadline.id, User.full_name).select_from(WorkDelivery).join(Deadline)
             .join(User, User.id == Deadline.student_id)
             .join(GroupMember, GroupMember.student_id == Deadline.student_id)
             .join(TeachingLoad, TeachingLoad.id == work.load_id)
             .where(WorkDelivery.work_id == delivery.work_id, WorkDelivery.active.is_(True),
                    Deadline.student_id == lead, GroupMember.group_id == TeachingLoad.group_id,
                    select(GroupMember.student_id).where(GroupMember.student_id == viewer_id,
                         GroupMember.group_id == TeachingLoad.group_id).correlate(TeachingLoad).exists())
             .order_by(Deadline.id).limit(1))
    reference = db.execute(query).one_or_none()
    return (reference.id, reference.full_name) if reference else (None, None)


def student_assignment(db, student_id, deadline_id):
    found = db.execute(select(Deadline, WorkDelivery, GroupWork).select_from(Deadline)
                       .outerjoin(WorkDelivery, WorkDelivery.deadline_id == Deadline.id)
                       .outerjoin(GroupWork, GroupWork.id == WorkDelivery.work_id).where(Deadline.id == deadline_id,
                            Deadline.student_id == student_id, visible_deadline())).one_or_none()
    if found is None:
        raise HTTPException(404, 'Учебная запись не найдена')
    return found


def feedback_data(row, author):
    return dict(id=row.id, version=row.submitted_version, score=row.score, comment=row.comment,
                author=author, created_at=iso(row.created_at), action=row.action,
                extended_until=iso(row.extended_until))


def attempt_details(db, submission_id):
    feedback = [feedback_data(row, name) for row, name in db.execute(
        select(WorkFeedback, User.full_name).join(User, User.id == WorkFeedback.author_id)
        .where(WorkFeedback.submission_id == submission_id).order_by(WorkFeedback.id.desc()))]
    attempts = db.scalars(select(SubmissionAttempt).where(SubmissionAttempt.submission_id == submission_id)
                          .order_by(SubmissionAttempt.id.desc())).all()
    attachments = {}
    if attempts:
        for row in db.execute(select(SubmissionAttachment.id, SubmissionAttachment.attempt_id,
                                     SubmissionAttachment.name, SubmissionAttachment.size)
                              .where(SubmissionAttachment.attempt_id.in_([attempt.id for attempt in attempts]))
                              .order_by(SubmissionAttachment.id)):
            attachments.setdefault(row.attempt_id, []).append(dict(id=row.id, name=row.name, size=row.size))
    reviews = {}
    for item in feedback:
        reviews.setdefault(item['version'], []).append(item)
    return feedback, [dict(id=row.id, number=row.number, version=row.version, text=row.text, url=row.url,
                           completed=row.completed, late=row.late, submitted_at=iso(row.submitted_at),
                           feedback=reviews.get(row.version, []), files=attachments.get(row.id, []))
                      for row in attempts]


def submission_data(row, *, include_text=True):
    if row is None:
        return None
    return dict(id=row.id, text=row.text if include_text else '', url=row.url if include_text else '', status=row.status,
                version=row.version, attempt_version=row.attempt_version,
                submitted_at=iso(row.submitted_at) if row.attempt_version else None, updated_at=iso(row.updated_at))


def submission_for(db, deadline, delivery, work):
    owner_id = work_policy(work)['team_lead_id'] or deadline.student_id
    submission_deadline, lead_name = (deadline.id, None)
    if work_policy(work)['team_lead_id']:
        submission_deadline, lead_name = team_reference(db, delivery, work, deadline.student_id)
    row = db.scalar(select(AssignmentSubmission).where(AssignmentSubmission.deadline_id == submission_deadline,
                                                       AssignmentSubmission.student_id == owner_id)) if submission_deadline else None
    return row, owner_id, lead_name


def assignment_payload(db, deadline, delivery, work, submission, owner_id, lead_name, *, include_history=False):
    policy = work_policy(work)
    state = effective_state(work)
    due = effective_due(deadline, delivery, work)
    status = submission.status if submission else 'not_started'
    stale = due < utc_now() and status in ACTIONABLE
    feedback, versions = attempt_details(db, submission.id) if include_history and submission else ([], [])
    used = len(versions) if include_history else None
    remaining = min(policy['max_attempts'] or 50, 50)
    if not policy['allow_resubmission'] and status != 'revision_required':
        remaining = 1
    return dict(id=deadline.id, deadline_id=deadline.id, subject=deadline.subject, title=deadline.title,
                due_date=due.astimezone(CAMPUS_TZ).date().isoformat(), due_at=iso(due), is_done=deadline.is_done,
                instructions=work.instructions if work else DEFAULT_INSTRUCTIONS, feedback=feedback, attempts=versions,
                submission=submission_data(submission, include_text=include_history), overdue=stale,
                status=status, state=state, description=policy['description'], criteria=policy['criteria'],
                kind=policy['kind'], custom_kind=policy['custom_kind'], materials=policy['materials'],
                max_points=policy['max_points'] if work else None, methods=policy['methods'], formats=policy['formats'],
                allow_late=policy['allow_late'], allow_resubmission=policy['allow_resubmission'],
                max_attempts=policy['max_attempts'], attempts_used=used, team_lead=lead_name,
                is_team=bool(policy['team_lead_id']),
                can_submit=state == 'published' and deadline.student_id == owner_id
                and (not policy['team_lead_id'] or lead_name is not None)
                and (status in ACTIONABLE or (work is None and status == 'submitted'))
                and (used is None or used < remaining) and (due >= utc_now() or policy['allow_late']),
                can_withdraw=state == 'published' and deadline.student_id == owner_id
                and status in ('submitted', 'resubmitted'))


def student_assignment_results(db, student_id, *, include_history=False, limit=200, offset=0,
                               min_date=None, max_date=None, recent_first=False):
    query = (select(Deadline, WorkDelivery, GroupWork).select_from(Deadline)
             .outerjoin(WorkDelivery, WorkDelivery.deadline_id == Deadline.id)
             .outerjoin(GroupWork, GroupWork.id == WorkDelivery.work_id)
             .where(Deadline.student_id == student_id, visible_deadline()))
    if min_date is not None:
        query = query.where(Deadline.due_date >= min_date)
    if max_date is not None:
        query = query.where(Deadline.due_date <= max_date)
    ordering = (Deadline.due_date.desc(), Deadline.id.desc()) if recent_first else (Deadline.due_date, Deadline.id)
    rows = db.execute(query.order_by(*ordering).offset(offset).limit(limit)).all()
    submissions = {}
    keys = [deadline.id for deadline, _, _ in rows]
    # Reminder scans can span multiple pages. Keep individual IN lists portable.
    team_work = {work.id for _, _, work in rows if work and work_policy(work)['team_lead_id']}
    team_member = aliased(GroupMember)
    viewer_member = aliased(GroupMember)
    for index in range(0, len(keys), 500):
        scope = and_(Deadline.student_id == student_id, Deadline.id.in_(keys[index:index + 500]))
        query = (select(WorkDelivery.work_id, AssignmentSubmission, Deadline.student_id, User.full_name)
                 .select_from(Deadline).join(User, User.id == Deadline.student_id)
                 .outerjoin(WorkDelivery, WorkDelivery.deadline_id == Deadline.id)
                 .outerjoin(AssignmentSubmission, and_(AssignmentSubmission.deadline_id == Deadline.id,
                                                       AssignmentSubmission.student_id == Deadline.student_id)))
        if index == 0 and team_work:
            query = (query.outerjoin(team_member, team_member.student_id == Deadline.student_id)
                     .outerjoin(GroupWork, GroupWork.id == WorkDelivery.work_id)
                     .outerjoin(TeachingLoad, TeachingLoad.id == GroupWork.load_id)
                     .outerjoin(viewer_member, and_(viewer_member.group_id == TeachingLoad.group_id,
                                                    viewer_member.student_id == student_id)))
            scope = or_(scope, and_(WorkDelivery.active.is_(True), WorkDelivery.work_id.in_(team_work),
                                    team_member.group_id == TeachingLoad.group_id, viewer_member.student_id == student_id))
        for work_id, row, viewer, name in db.execute(query.where(scope)):
            if row and viewer == student_id:
                submissions[row.deadline_id] = row
            if work_id in team_work:
                submissions[(work_id, viewer)] = (row, name)
    result = []
    for deadline, delivery, work in rows:
        row, owner_id, lead_name = (submissions.get(deadline.id), student_id, None)
        leader = work_policy(work)['team_lead_id']
        if leader:
            owner_id = leader
            row, lead_name = submissions.get((work.id, leader), (None, None))
        result.append(assignment_payload(db, deadline, delivery, work, row, owner_id, lead_name,
                                         include_history=include_history))
    return result


def academic_work_results(db, student_id):
    rows = db.execute(select(Deadline, WorkDelivery, GroupWork, TeachingLoad.discipline_id).select_from(Deadline)
                      .outerjoin(WorkDelivery, WorkDelivery.deadline_id == Deadline.id)
                      .outerjoin(GroupWork, GroupWork.id == WorkDelivery.work_id)
                      .outerjoin(TeachingLoad, TeachingLoad.id == GroupWork.load_id)
                      .where(Deadline.student_id == student_id, visible_deadline())
                      .order_by(Deadline.due_date.desc(), Deadline.id.desc()).limit(200)).all()
    result = []
    for deadline, delivery, work, discipline_id in rows:
        row, _, _ = submission_for(db, deadline, delivery, work)
        reviews = select(WorkFeedback).where(WorkFeedback.submission_id == row.id) if row else None
        latest = db.scalar(reviews.where(
                    WorkFeedback.action.in_(('accept', 'revise', 'comment')),
                    WorkFeedback.comment != '').order_by(WorkFeedback.id.desc()).limit(1)) if row else None
        policy = work_policy(work)
        accepted = db.scalar(reviews.where(WorkFeedback.action == 'accept').limit(1)) if row else None
        credited = policy['award_mode'] == 'all' or student_id == (policy['team_lead_id'] or student_id)
        legacy = db.scalar(reviews.where(WorkFeedback.action == 'comment', WorkFeedback.score.is_not(None))
                           .order_by(WorkFeedback.id.desc()).limit(1)) if row and accepted is None else None
        score = accepted.score if accepted and credited else None
        if legacy:
            score = legacy.score
        result.append(dict(id=deadline.id, discipline_id=discipline_id, class_id=policy['class_id'], subject=deadline.subject,
                           title=deadline.title, due_at=iso(effective_due(deadline, delivery, work)),
                           status=row.status if row else 'not_started', state=effective_state(work),
                           score=score, max_points=policy['max_points'] if work else None,
                           feedback=latest.comment if latest else ''))
    return result


def validate_https(value):
    value = value.strip()
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                 and not any(char.isspace() for char in value) and '\\' not in value)
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Допускается только полная HTTPS-ссылка без учётных данных')
    return value


def attachment_payload(files, allowed_formats):
    saved = []
    total = 0
    for file in files:
        name = file.name.strip()
        if (not name or not re.fullmatch(r'[^/\\\x00-\x1f\x7f]+', name) or
            PurePath(name).suffix.removeprefix('.').lower() not in allowed_formats):
            raise HTTPException(422, 'Файл не соответствует разрешённым форматам')
        try:
            content = base64.b64decode(file.content, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'Не удалось прочитать приложенный файл') from None
        total += len(content)
        if not content or total > MAX_UPLOAD_BYTES:
            raise HTTPException(422, 'Размер приложенных файлов должен быть от 1 байта до 1 МиБ суммарно')
        saved.append((name, content))
    return saved


def attachment_response(db, submission_id, attachment_id):
    row = db.scalar(select(SubmissionAttachment).join(SubmissionAttempt).where(
        SubmissionAttachment.id == attachment_id, SubmissionAttempt.submission_id == submission_id))
    if row is None:
        raise HTTPException(404, 'Вложение не найдено')
    return Response(row.content, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row.name, safe=''),
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
    })


def attempt_count(db, submission_id):
    return db.scalar(select(func.count(SubmissionAttempt.id)).where(SubmissionAttempt.submission_id == submission_id))


def time_value(value):
    if value is not None and value.utcoffset() is None:
        raise ValueError('Укажите дату и время с часовым поясом')
    return as_utc(value) if value is not None else None


def validate_due(value, *, now=None):
    now = now or utc_now()
    if not now < value <= now + timedelta(days=371):
        raise HTTPException(422, 'Укажите будущий срок в пределах учебного года')
