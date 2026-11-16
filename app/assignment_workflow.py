"""Assignment data shared by the existing learning and teaching APIs."""
import base64
import binascii
import json
import re
from datetime import datetime, time, timedelta
from pathlib import PurePath
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import aliased

from .assignment_db import SubmissionAttachment, SubmissionAttempt
from .assignment_files import download_file, feedback_files, source_files
from .assignment_grades import GRADE_ACTIONS, official_score_query, score_from_history
from .db import CAMPUS_TZ, Deadline, Notification, User, utc_now
from .learning_db import AssignmentSubmission
from .session_security import as_utc
from .workspace import load_query
from .workspace_db import GroupMember, GroupWork, TeachingLoad, WorkDelivery, WorkFeedback


WORK_KINDS = ('homework', 'lab', 'practice', 'test', 'independent', 'essay', 'talk',
              'project', 'term_paper', 'individual', 'group', 'other')
FORMATS = ('pdf', 'txt', 'md', 'csv', 'png', 'jpg', 'jpeg', 'docx', 'xlsx', 'pptx')
MAX_UPLOAD_BYTES = 1024 * 1024
DEFAULT_POLICY = {
    'kind': 'homework', 'custom_kind': '', 'description': '', 'criteria': '', 'max_points': 100,
    'methods': ['text', 'url'], 'required_methods': [], 'formats': list(FORMATS),
    'min_files': 1, 'max_files': 3, 'allow_resubmission': True,
    'max_attempts': None, 'allow_late': True, 'materials': [], 'recipient_ids': [],
    'subgroup_id': None, 'team_lead_id': None, 'award_mode': 'all', 'class_id': None,
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


def general_due(deadline, work):
    return as_utc(work.due_at) if work is not None and work.due_at else base_due(work.due if work else deadline.due_date)


def initial_due(deadline, delivery, work):
    due = general_due(deadline, work)
    if delivery is not None:
        due = as_utc(delivery.individual_due_at) if delivery.individual_due_at else due
        if delivery.extended_until:
            due = max(due, as_utc(delivery.extended_until))
    return due


def effective_due(deadline, delivery, work):
    return as_utc(delivery.revision_due_at) if delivery and delivery.revision_due_at else initial_due(deadline, delivery, work)


def deadline_fields(deadline, delivery, work, *, now=None):
    now = now or utc_now()
    due = effective_due(deadline, delivery, work)
    passed = now > due
    can_receive = effective_state(work, now) == 'published' and (not passed or work_policy(work)['allow_late'])
    return dict(
        general_due_at=iso(general_due(deadline, work)),
        individual_due_at=iso(delivery.individual_due_at) if delivery else None,
        extended_until=iso(delivery.extended_until) if delivery else None,
        revision_due_at=iso(delivery.revision_due_at) if delivery else None,
        due_at=iso(due), due_date=due.astimezone(CAMPUS_TZ).date().isoformat(),
        deadline_passed=passed, submission_window=('late' if passed else 'open') if can_receive else 'closed',
    )


def sync_due_date(deadline, delivery, work):
    deadline.due_date = effective_due(deadline, delivery, work).astimezone(CAMPUS_TZ).date()


def work_data(row):
    return {
        **work_policy(row), 'id': row.id, 'title': row.title, 'instructions': row.instructions,
        'due': row.due.isoformat(), 'version': row.version, 'state': effective_state(row),
        'publish_at': iso(row.publish_at), 'due_at': iso(row.due_at or base_due(row.due)),
    }


def work_notice(db, user_id, title, body, target, *, event_key):
    insert = pg_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
    db.execute(insert(Notification).values(student_id=user_id, title=title, body=body,
               target=target, category='academic', is_read=False, created_at=utc_now(), event_key=event_key)
               .on_conflict_do_nothing(index_elements=['event_key']))


def assignment_notice(db, deadline, title, body, *, event_key):
    work_notice(db, deadline.student_id, title, body, f'/app/assignments?id={deadline.id}', event_key=event_key)


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


def feedback_data(row, author, files=()):
    return dict(id=row.id, version=row.submitted_version, score=row.score, comment=row.comment,
                remarks=row.remarks, author=author, created_at=iso(row.created_at), action=row.action,
                extended_until=iso(row.extended_until), previous_score=row.previous_score, files=list(files))


def attempt_details(db, submission_id):
    files_by_review = feedback_files(db, submission_id)
    feedback = [feedback_data(row, name, files_by_review.get(row.id, ())) for row, name in db.execute(
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


def assignment_payload(db, deadline, delivery, work, submission, owner_id, lead_name, *,
                       include_history=False, load=None, member_group_id=None, attempts_used=None, score=None):
    policy = work_policy(work)
    now = utc_now()
    state = effective_state(work, now)
    dates = deadline_fields(deadline, delivery, work, now=now)
    status = submission.status if submission else 'not_started'
    stale = dates['deadline_passed'] and status in ACTIONABLE
    feedback, versions = attempt_details(db, submission.id) if include_history and submission else ([], [])
    if include_history:
        score = score_from_history(feedback)
    used = len(versions) if include_history else attempts_used
    materials = []
    if work and include_history:
        from .work_materials import student_work_materials
        materials = student_work_materials(db, work.id, db.get(User, deadline.student_id))
    can_act = (deadline.student_id == owner_id and (not work or (load and load.group_id == member_group_id))
               and (not policy['team_lead_id'] or lead_name is not None))
    remaining = min(policy['max_attempts'] or 50, 50)
    if not policy['allow_resubmission'] and status != 'revision_required':
        remaining = 1
    return dict(id=deadline.id, deadline_id=deadline.id, subject=deadline.subject, title=deadline.title,
                **dates, is_done=deadline.is_done, discipline_id=load.discipline_id if load else None,
                group=load.group.code if load else None, teacher=load.assignment.teacher.user.full_name if load else None,
                instructions=work.instructions if work else DEFAULT_INSTRUCTIONS, feedback=feedback, attempts=versions,
                submission=submission_data(submission, include_text=include_history), overdue=stale,
                status=status, state=state, description=policy['description'], criteria=policy['criteria'],
                kind=policy['kind'], custom_kind=policy['custom_kind'], materials=policy['materials'], course_materials=materials,
                source_files=source_files(db, work.id) if work and include_history else [], score=score,
                max_points=policy['max_points'] if work else None, methods=policy['methods'], formats=policy['formats'],
                required_methods=policy['required_methods'], min_files=policy['min_files'], max_files=policy['max_files'],
                allow_late=policy['allow_late'], allow_resubmission=policy['allow_resubmission'],
                max_attempts=policy['max_attempts'], attempts_used=used, team_lead=lead_name,
                is_team=bool(policy['team_lead_id']),
                can_submit=dates['submission_window'] != 'closed' and bool(can_act)
                and (status in ACTIONABLE or (work is None and status == 'submitted'))
                and (used is None or used < remaining),
                can_withdraw=state == 'published' and bool(can_act)
                and status in ('submitted', 'resubmitted'))


def student_assignment_results(db, student_id, *, include_history=False, limit=200, offset=0,
                               min_date=None, max_date=None, recent_first=False, subject=None, discipline_id=None):
    query = (load_query().add_columns(Deadline, WorkDelivery, GroupWork, GroupMember.group_id).select_from(Deadline)
             .outerjoin(WorkDelivery, WorkDelivery.deadline_id == Deadline.id)
             .outerjoin(GroupWork, GroupWork.id == WorkDelivery.work_id)
             .outerjoin(TeachingLoad, TeachingLoad.id == GroupWork.load_id)
             .outerjoin(GroupMember, GroupMember.student_id == Deadline.student_id)
             .where(Deadline.student_id == student_id, visible_deadline()))
    if subject is not None:
        legacy = and_(GroupWork.id.is_(None), Deadline.subject == subject)
        managed = GroupWork.load_id.in_(select(TeachingLoad.id).where(TeachingLoad.discipline_id == discipline_id))
        query = query.where(or_(legacy, managed) if discipline_id is not None else legacy)
    if min_date is not None:
        query = query.where(Deadline.due_date >= min_date)
    if max_date is not None:
        query = query.where(Deadline.due_date <= max_date)
    ordering = (Deadline.due_date.desc(), Deadline.id.desc()) if recent_first else (Deadline.due_date, Deadline.id)
    rows = db.execute(query.order_by(*ordering).offset(offset).limit(limit)).all()
    submissions, team_submissions = {}, {}
    keys = [deadline.id for _, deadline, _, _, _ in rows]
    # Reminder scans can span multiple pages. Keep individual IN lists portable.
    team_work = {work.id: work_policy(work)['team_lead_id'] for load, _, _, work, member_group in rows
                 if load and load.group_id == member_group and work_policy(work)['team_lead_id']}
    leaders = set(team_work.values())
    team_member = aliased(GroupMember)
    viewer_member = aliased(GroupMember)
    count = (select(func.count(SubmissionAttempt.id)).where(SubmissionAttempt.submission_id == AssignmentSubmission.id)
             .correlate(AssignmentSubmission).scalar_subquery())
    score = official_score_query(AssignmentSubmission.id).correlate(AssignmentSubmission).scalar_subquery()
    for index in range(0, len(keys), 500):
        scope = and_(Deadline.student_id == student_id, Deadline.id.in_(keys[index:index + 500]))
        query = (select(WorkDelivery.work_id, AssignmentSubmission, Deadline.student_id, User.full_name, count, score)
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
                                    Deadline.student_id.in_(leaders), team_member.group_id == TeachingLoad.group_id,
                                    viewer_member.student_id == student_id))
        for work_id, row, viewer, name, used, grade in db.execute(query.where(scope)):
            if row and viewer == student_id:
                submissions[row.deadline_id] = (row, used, grade)
            if team_work.get(work_id) == viewer:
                team_submissions[work_id] = (row, name, used, grade)
    result = []
    for load, deadline, delivery, work, member_group in rows:
        row, used, grade = submissions.get(deadline.id, (None, 0, None))
        owner_id, lead_name = student_id, None
        leader = work_policy(work)['team_lead_id']
        if leader:
            owner_id = leader
            row, lead_name, used, grade = team_submissions.get(work.id, (None, None, 0, None))
        result.append(assignment_payload(db, deadline, delivery, work, row, owner_id, lead_name,
                                         include_history=include_history, load=load, member_group_id=member_group,
                                         attempts_used=used, score=grade))
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
                    WorkFeedback.action.in_((*GRADE_ACTIONS, 'revise', 'comment')),
                    or_(WorkFeedback.remarks != '', WorkFeedback.comment != '')
                ).order_by(WorkFeedback.id.desc()).limit(1)) if row else None
        policy = work_policy(work)
        result_entry = db.scalar(reviews.where(WorkFeedback.action.in_(GRADE_ACTIONS))
                                 .order_by(WorkFeedback.id.desc()).limit(1)) if row else None
        credited = policy['award_mode'] == 'all' or student_id == (policy['team_lead_id'] or student_id)
        legacy = db.scalar(reviews.where(WorkFeedback.action == 'comment', WorkFeedback.score.is_not(None))
                           .order_by(WorkFeedback.id.desc()).limit(1)) if row and result_entry is None else None
        graded = result_entry is not None and result_entry.score is not None
        score = result_entry.score if graded and credited else None
        if legacy:
            score = legacy.score
        result.append(dict(id=deadline.id, discipline_id=discipline_id, class_id=policy['class_id'], subject=deadline.subject,
                           title=deadline.title, due_at=iso(effective_due(deadline, delivery, work)),
                           status=row.status if row else 'not_started', state=effective_state(work),
                           score=score, graded=graded, max_points=policy['max_points'] if work else None,
                           feedback=(latest.remarks or latest.comment) if latest else ''))
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
    return download_file(row)


def attempt_count(db, submission_id):
    return db.scalar(select(func.count(SubmissionAttempt.id)).where(SubmissionAttempt.submission_id == submission_id))


def time_value(value):
    if value is not None and value.utcoffset() is None:
        raise ValueError('Укажите дату и время с часовым поясом')
    try:
        return as_utc(value) if value is not None else None
    except (OverflowError, ValueError):
        raise ValueError('Дата выходит за поддерживаемый диапазон') from None


def validate_due(value, *, now=None):
    now = now or utc_now()
    if not now < value <= now + timedelta(days=371):
        raise HTTPException(422, 'Укажите будущий срок в пределах учебного года')
