"""Teacher-owned roster, assessment, group work and consultations."""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .academic_points import PointAward, award_data, award_points, grade_record as student_grade
from .db import CAMPUS_TZ, Deadline, Grade, User, campus_today, utc_now
from .assignment_inputs import ExtendBody, FeedbackBody, WorkBody, WorkEdit
from .assignment_workflow import (DEFAULT_POLICY, SUBMITTED, assignment_notice, assignment_recipients,
                                  attachment_response, attempt_count, attempt_details, base_due,
                                  deliver_work, effective_due, effective_state, feedback_data, iso,
                                  submission_data, validate_due, work_data, work_policy)
from .learning_db import AssignmentSubmission, Attendance
from .main import StrictBody, date_iso, get_db, require_roles, require_same_origin
from .services import begin_idempotent, commit_idempotent
from .services_db import ConsultationBooking, ConsultationSlot
from .session_security import as_utc
from .university_db import Teacher, TeachingAssignment
from .workspace import (check_member, event_payload, load_payload, load_query, lock_workspace, notify,
                        owned_load, recorded, roster)
from .workspace_db import (Classroom, GroupMember, GroupWork, OperationEvent, ScheduledClass, TeacherConsultation,
                           TeachingLoad, WorkDelivery, WorkFeedback)

teacher_only = require_roles('teacher')
router = APIRouter(prefix='/api/teaching')
write = [Depends(require_same_origin)]


class MarkBody(StrictBody):
    student_id: int = Field(strict=True, ge=1)
    score: int | None = Field(strict=True, ge=0, le=2147483647)
    version: int = Field(strict=True, ge=0)
    reason: str = Field(default='', max_length=300)


class PointsBody(StrictBody):
    student_id: int = Field(strict=True, ge=1)
    points: int = Field(strict=True, ge=1, le=100)
    version: int = Field(strict=True, ge=0)
    reason: str = Field(min_length=3, max_length=300)
    class_id: int | None = Field(default=None, strict=True, ge=1)

    @field_validator('reason', mode='before')
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class AttendanceBody(StrictBody):
    student_id: int = Field(strict=True, ge=1)
    day: date
    status: Literal['present', 'absent', 'excused', 'late']
    note: str = Field(default='', max_length=300)
    version: int = Field(strict=True, ge=0)
    class_id: int | None = Field(default=None, strict=True, ge=1)


class ConsultationBody(StrictBody):
    load_id: int = Field(strict=True, ge=1)
    starts: datetime
    ends: datetime
    room: str = Field(min_length=2, max_length=100)
    capacity: int = Field(strict=True, ge=1, le=50)

    @field_validator('room', mode='before')
    @classmethod
    def trim_room(cls, value):
        return value.strip() if isinstance(value, str) else value


def grade_record(db, load, student_id):
    return student_grade(db, student_id, load.discipline.title)


def attendance_record(db, load, student_id, day, class_id=None):
    return db.scalar(select(Attendance).where(Attendance.student_id == student_id,
                     Attendance.subject == load.discipline.title, attendance_scope(day, class_id))
                     .order_by(Attendance.id).limit(1))


def attendance_scope(day, class_id):
    return Attendance.class_id == class_id if class_id else Attendance.class_id.is_(None) & (Attendance.day == day)


def grade_data(row):
    return dict(score=row.current, version=row.version, assessment=row.assessment) if row else dict(score=None, version=0, assessment='')


def attendance_data(row):
    return dict(status=row.status, version=row.version, note=row.note) if row else dict(status='', version=0, note='')


def save_grade(db, user, load, body, *, apply=True):
    check_member(db, load, body.student_id)
    row = grade_record(db, load, body.student_id)
    before = grade_data(row)
    if before['version'] != body.version:
        raise HTTPException(409, 'Оценка уже изменена. Загрузите актуальную ведомость.')
    current = max(0, before['score'] or 0)
    if (body.score or 0) < current:
        raise HTTPException(422, 'Накопленные баллы нельзя уменьшить')
    if (body.score or 0) - current > 100:
        raise HTTPException(422, 'За одну операцию можно добавить до 100 баллов')
    if not apply:
        return
    if (body.score or 0) == current:
        return before
    return add_grade_points(db, user, load, body.student_id, body.score - current, before, body.reason)


def add_grade_points(db, user, load, student_id, points, before, reason, class_id=None):
    award = award_points(db, student_id=student_id, discipline_id=load.discipline_id, points=points,
                         source_kind='teacher', source_id=f'{load.id}:{before["version"]}', actor_id=user.id,
                         reason=reason, class_id=class_id)
    after = grade_data(db.get(Grade, award.grade_id))
    recorded(db, user, 'teaching', load.id, 'grade', {'student_id': student_id, **before},
             {'student_id': student_id, **after, 'reason': reason, 'points': points, 'class_id': class_id})
    notify(db, student_id, 'Начислены учебные баллы', f'{load.discipline.title} · +{points}', '/app/grades', student=True)
    return after


def scoped_class(db, load, class_id):
    row = db.scalar(select(ScheduledClass).where(ScheduledClass.id == class_id, ScheduledClass.load_id == load.id,
                                                ScheduledClass.status == 'active'))
    if row is None:
        raise HTTPException(404, 'Занятие не найдено в этом назначении')
    return row


def class_day(row):
    return as_utc(row.starts_at).astimezone(CAMPUS_TZ).date()


def save_attendance(db, user, load, body, *, apply=True):
    check_member(db, load, body.student_id)
    if not campus_today()-timedelta(days=370) <= body.day <= campus_today():
        raise HTTPException(422, 'Отметка посещаемости относится к прошедшему учебному дню')
    if body.class_id:
        meeting = scoped_class(db, load, body.class_id)
        if class_day(meeting) != body.day or as_utc(meeting.starts_at) > utc_now():
            raise HTTPException(422, 'Отметка должна относиться к начавшемуся занятию на выбранную дату')
    row = attendance_record(db, load, body.student_id, body.day, body.class_id)
    before = attendance_data(row)
    if before['version'] != body.version:
        raise HTTPException(409, 'Посещаемость уже изменена. Загрузите актуальный журнал.')
    if not apply:
        return
    if row is None:
        row = Attendance(student_id=body.student_id, subject=load.discipline.title, day=body.day, class_id=body.class_id)
        db.add(row)
    row.day, row.status, row.note, row.version = body.day, body.status, body.note, body.version+1
    after = attendance_data(row)
    identity = {'student_id': body.student_id, 'day': body.day.isoformat(), 'class_id': body.class_id}
    recorded(db, user, 'teaching', load.id, 'attendance', {**identity, **before}, {**identity, **after})
    if before['status'] != after['status']:
        notify(db, body.student_id, 'Изменилась отметка о посещении',
               f'{load.discipline.title} · {body.day:%d.%m.%Y}', '/app/grades')
    return after


@router.get('')
def loads(user=Depends(teacher_only), db: Session = Depends(get_db)):
    query = load_query().join(TeachingAssignment).join(Teacher).where(Teacher.user_id == user.id).order_by(TeachingLoad.id)
    return {'items': [load_payload(row) for row in db.scalars(query)]}


@router.get('/{load_id:int}')
def details(load_id: int, day: date | None = None, class_id: int | None = Query(None, ge=1),
            user=Depends(teacher_only), db: Session = Depends(get_db)):
    from .scheduling import KIND

    load = owned_load(db, user, load_id)
    day = class_day(scoped_class(db, load, class_id)) if class_id else day or campus_today()
    sessions = db.scalars(select(ScheduledClass).where(ScheduledClass.load_id == load.id, ScheduledClass.status == 'active')
                          .order_by(ScheduledClass.starts_at.desc()).limit(200)).all()
    people = roster(db, load.group_id)
    ids = [person.id for person in people]
    grades, attendance = {}, {}
    for row in db.scalars(select(Grade).where(Grade.student_id.in_(ids), Grade.subject == load.discipline.title).order_by(Grade.id)):
        grades.setdefault(row.student_id, row)
    for row in db.scalars(select(Attendance).where(Attendance.student_id.in_(ids), Attendance.subject == load.discipline.title,
                                                   attendance_scope(day, class_id)).order_by(Attendance.id)):
        attendance.setdefault(row.student_id, row)
    attendance_by_student = {}
    for student_id, status, count in db.execute(select(Attendance.student_id, Attendance.status, func.count())
            .where(Attendance.student_id.in_(ids), Attendance.subject == load.discipline.title)
            .group_by(Attendance.student_id, Attendance.status)):
        attendance_by_student.setdefault(student_id, {})[status] = count
    history = db.execute(select(OperationEvent, User.full_name).join(User, User.id == OperationEvent.actor_id)
                         .where(OperationEvent.area == 'teaching', OperationEvent.object_id == load.id)
                         .order_by(OperationEvent.id.desc()).limit(30))
    submitted = db.scalar(select(func.count()).select_from(AssignmentSubmission).join(WorkDelivery,
                          WorkDelivery.deadline_id == AssignmentSubmission.deadline_id).join(GroupWork)
                          .where(GroupWork.load_id == load.id, AssignmentSubmission.student_id.in_(ids),
                                 AssignmentSubmission.status.in_(SUBMITTED)))
    totals = db.execute(select(Attendance.status, func.count()).where(Attendance.student_id.in_(ids),
                        Attendance.subject == load.discipline.title).group_by(Attendance.status)).all()
    scores = [g.current for g in grades.values() if g.current is not None]
    now = utc_now()
    return {**load_payload(load), 'day': day.isoformat(), 'class_id': class_id,
            'sessions': [dict(id=row.id, day=class_day(row).isoformat(), kind=KIND.get(row.kind, row.kind),
                              starts_at=date_iso(row.starts_at), topic=row.note, started=as_utc(row.starts_at) <= now)
                         for row in sessions],
            'students': [dict(id=p.id, name=p.full_name, number=p.student_number,
                              grade=grade_data(grades.get(p.id)), attendance=attendance_data(attendance.get(p.id)),
                              attendance_counts=attendance_by_student.get(p.id, {})) for p in people],
            'summary': dict(student_count=len(people), assessed=len(scores), average=round(sum(scores)/len(scores),1) if scores else None,
                            submitted=submitted, attendance=dict(totals)),
            'history': [item for row,author in history if (item:=event_payload(row,author,date_iso))['action'] not in
                        {'grade','attendance'} or item['after']['student_id'] in ids]}


@router.put('/{load_id:int}/grade', dependencies=write)
def grade(load_id: int, body: MarkBody, user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    result = save_grade(db, user, owned_load(db, user, load_id), body)
    db.commit()
    return result


@router.post('/{load_id:int}/points', status_code=201, dependencies=write)
def points(load_id: int, body: PointsBody, request: Request, response: Response, user=Depends(teacher_only),
           db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    check_member(db, load, body.student_id)
    receipt, replay = begin_idempotent(db, request, response, user, f'points:{load.id}', body.model_dump())
    if replay is not None:
        return replay
    if body.class_id and as_utc(scoped_class(db, load, body.class_id).starts_at) > utc_now():
        raise HTTPException(422, 'Начисление относится к уже начавшемуся занятию')
    before = grade_data(grade_record(db, load, body.student_id))
    if before['version'] != body.version:
        raise HTTPException(409, 'Ведомость уже изменилась. Обновите данные.')
    return commit_idempotent(db, receipt, add_grade_points(db, user, load, body.student_id, body.points,
                                                          before, body.reason, body.class_id))


@router.get('/{load_id:int}/points/{student_id:int}')
def point_history(load_id: int, student_id: int, user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    check_member(db, load, student_id)
    grade = grade_record(db, load, student_id)
    rows = db.scalars(select(PointAward).where(PointAward.student_id == student_id,
                      PointAward.grade_id == grade.id).order_by(PointAward.id.desc())) if grade else ()
    return {'items': [award_data(row, date_iso) for row in rows]}


@router.put('/{load_id:int}/attendance', dependencies=write)
def attendance(load_id: int, body: AttendanceBody, user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    result = save_attendance(db, user, owned_load(db, user, load_id), body)
    db.commit()
    return result


@router.get('/{load_id:int}/works')
def works(load_id: int, offset: int = Query(0, ge=0, le=2147483647),
          user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    rows = db.scalars(select(GroupWork).where(GroupWork.load_id == load.id)
                      .order_by(GroupWork.id.desc()).offset(offset).limit(21)).all()
    counts = dict(db.execute(select(WorkDelivery.work_id, func.count()).join(
        AssignmentSubmission, AssignmentSubmission.deadline_id == WorkDelivery.deadline_id)
        .join(GroupMember, GroupMember.student_id == AssignmentSubmission.student_id)
        .where(WorkDelivery.work_id.in_([row.id for row in rows[:20]]), WorkDelivery.active.is_(True),
               GroupMember.group_id == load.group_id, AssignmentSubmission.status.in_(SUBMITTED))
        .group_by(WorkDelivery.work_id)).all())
    return {'items': [{**work_data(row), 'submitted': counts.get(row.id, 0)} for row in rows[:20]],
            'more': len(rows) > 20, 'offset': offset}


def target_students(db, load, body):
    members = {person.id for person in roster(db, load.group_id)}
    selected = set(body.recipient_ids) or members
    if not selected:
        raise HTTPException(409, 'Добавьте студентов в группу перед публикацией задания')
    if not selected.issubset(members) or (body.team_lead_id is not None and body.team_lead_id not in selected):
        raise HTTPException(404, 'Студент не найден среди получателей в этой группе')
    if body.class_id is not None:
        found = db.scalar(select(ScheduledClass.id).where(ScheduledClass.id == body.class_id, ScheduledClass.load_id == load.id))
        if found is None:
            raise HTTPException(404, 'Занятие не найдено в данной дисциплине и группе')
    return selected


def save_work_fields(row, body, *, prev_due=None):
    now = utc_now()
    due_at = body.due_at or base_due(body.due or campus_today())
    if body.state not in ('draft', 'archived') and (prev_due is None or as_utc(prev_due) != due_at):
        validate_due(due_at, now=now)
    if body.state == 'scheduled':
        if not now < body.publish_at < due_at:
            raise HTTPException(422, 'Запланируйте публикацию между текущим временем и сроком сдачи')
    published_at = row.publish_at if row.publish_at and (
        row.state == 'published' or as_utc(row.publish_at) <= now) else now
    row.title, row.instructions = body.title, body.instructions
    row.due_at, row.due = due_at, due_at.astimezone(CAMPUS_TZ).date()
    row.state = body.state
    row.publish_at = (body.publish_at if body.state == 'scheduled' else published_at
                      if body.state in ('published', 'archived') else None)
    row.policy_json = json.dumps({name: getattr(body, name) for name in DEFAULT_POLICY}, ensure_ascii=False)


def update_deliveries(db, load, row, selected, before):
    prior = {deadline.student_id: (deadline, delivery) for deadline, delivery in db.execute(
        select(Deadline, WorkDelivery).join(WorkDelivery).where(WorkDelivery.work_id == row.id))}
    if row.state in ('published', 'scheduled'):
        for student_id in sorted(selected - prior.keys()):
            deliver_work(db, load, row, student_id)
    for student_id, (deadline, delivery) in prior.items():
        was_active = delivery.active
        delivery.active = student_id in selected and row.state != 'draft'
        if not delivery.active:
            continue
        deadline.title = row.title
        deadline.due_date = effective_due(deadline, delivery, row).astimezone(CAMPUS_TZ).date()
        if row.state == 'published' and (before['state'] in ('draft', 'scheduled') or not was_active):
            assignment_notice(db, deadline, 'Опубликовано учебное задание', row.title,
                              event_key=f'work-publish:{row.id}:{deadline.id}')
        elif row.state in ('published', 'archived') and before['state'] == 'published':
            assignment_notice(db, deadline, 'Задание перенесено в архив' if row.state == 'archived' else 'Условия задания изменились',
                              row.title, event_key=f'work-edit:{row.id}:{deadline.id}:{row.version}')


@router.post('/{load_id:int}/works', status_code=201, dependencies=write)
def new_work(load_id: int, body: WorkBody, request: Request, response: Response,
             user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    receipt, replay = begin_idempotent(db, request, response, user, f'group-work:{load_id}',
                                       body.model_dump(exclude_unset=True))
    if replay is not None:
        return replay
    if body.state == 'archived':
        raise HTTPException(422, 'Сначала создайте задание')
    selected = target_students(db, load, body) if (
        body.state != 'draft' or body.recipient_ids or body.team_lead_id or body.class_id) else set()
    row = GroupWork(load_id=load.id, author_id=user.id, created_at=utc_now())
    save_work_fields(row, body)
    db.add(row)
    db.flush()
    if row.state != 'draft':
        for student_id in sorted(selected):
            deliver_work(db, load, row, student_id)
    result = work_data(row)
    recorded(db, user, 'teaching', load.id, 'work_created', after=result)
    return commit_idempotent(db, receipt, result)


def owned_work(db, load, work_id):
    row = db.scalar(select(GroupWork).where(GroupWork.id == work_id, GroupWork.load_id == load.id))
    if row is None:
        raise HTTPException(404, 'Задание не найдено')
    return row


@router.patch('/{load_id:int}/works/{work_id}', dependencies=write)
def edit_work(load_id: int, work_id: int, body: WorkEdit, user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    row = owned_work(db, load, work_id)
    if row.version != body.version:
        raise HTTPException(409, 'Задание изменено. Обновите раздел.')
    before = work_data(row)
    patch = body.model_dump(exclude_unset=True, exclude={'version'})
    if 'due' in patch and 'due_at' not in patch:
        patch['due_at'] = None
    stored = {key: before[key] for key in WorkBody.model_fields}
    try:
        updated = WorkBody.model_validate({**stored, **patch})
    except (ValueError, ValidationError) as error:
        message = error.errors()[0]['msg'] if isinstance(error, ValidationError) else str(error)
        raise HTTPException(422, message) from None
    if before['state'] == 'archived' or (updated.state == 'archived' and before['state'] != 'published'):
        raise HTTPException(409, 'Архивировать можно только опубликованное задание')
    if before['state'] == 'published':
        protected = {'recipient_ids', 'team_lead_id', 'award_mode', 'class_id', 'kind', 'max_points'}
        if updated.state not in ('published', 'archived') or any(
            getattr(updated, key) != before[key] for key in protected
        ):
            raise HTTPException(409, 'У опубликованной работы можно изменить сроки, текст и способы сдачи')
    current_recipients = assignment_recipients(db, load, row, current_members=False)
    selected = ({deadline.student_id for deadline, _, _ in current_recipients}
                if before['state'] == 'published' else
                target_students(db, load, updated) if (
                    updated.state != 'draft' or updated.recipient_ids or updated.team_lead_id or updated.class_id) else set())
    save_work_fields(row, updated, prev_due=row.due_at or base_due(row.due))
    row.version += 1
    update_deliveries(db, load, row, selected, before)
    result = work_data(row)
    recorded(db, user, 'teaching', load.id, 'work_edited', before, result)
    db.commit()
    return result


def submissions_query(load, work_id):
    return (select(AssignmentSubmission, User.full_name)
            .join(WorkDelivery, WorkDelivery.deadline_id == AssignmentSubmission.deadline_id)
            .join(GroupMember, GroupMember.student_id == AssignmentSubmission.student_id)
            .join(User, User.id == GroupMember.student_id)
            .where(WorkDelivery.work_id == work_id, WorkDelivery.active.is_(True), GroupMember.group_id == load.group_id,
                   User.role == 'student'))


@router.get('/{load_id:int}/works/{work_id}')
def work_detail(load_id: int, work_id: int, user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    work = owned_work(db, load, work_id)
    recipients = assignment_recipients(db, load, work)
    submissions = []
    for row, name in db.execute(submissions_query(load, work_id).order_by(AssignmentSubmission.id)):
        notes, attempts = attempt_details(db, row.id)
        submissions.append({**submission_data(row), 'student': name, 'student_id': row.student_id,
                            'deadline_id': row.deadline_id, 'feedback': notes, 'attempts': attempts})
    return {**work_data(work), 'submissions': submissions, 'recipients': [
        dict(id=deadline.student_id, deadline_id=deadline.id, name=name, due_at=iso(effective_due(deadline, delivery, work)))
        for deadline, delivery, name in recipients
    ], 'classes': [
        dict(id=row.id, day=as_utc(row.starts_at).astimezone(CAMPUS_TZ).isoformat(), topic=row.note)
        for row in db.scalars(select(ScheduledClass).where(ScheduledClass.load_id == load.id, ScheduledClass.status == 'active')
                              .order_by(ScheduledClass.starts_at).limit(100))
    ]}


@router.get('/{load_id:int}/works/{work_id}/submissions/{submission_id}/files/{attachment_id}')
def teacher_attachment(load_id: int, work_id: int, submission_id: int, attachment_id: int,
                       user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    owned_work(db, load, work_id)
    if db.execute(submissions_query(load, work_id).where(AssignmentSubmission.id == submission_id)).one_or_none() is None:
        raise HTTPException(404, 'Вложение не найдено')
    return attachment_response(db, submission_id, attachment_id)


def extend_deadline(deadline, delivery, work, until):
    validate_due(until)
    if until <= effective_due(deadline, delivery, work):
        raise HTTPException(422, 'Новый срок должен быть позже действующего')
    delivery.extended_until = until
    deadline.due_date = until.astimezone(CAMPUS_TZ).date()


@router.patch('/{load_id:int}/works/{work_id}/recipients/{student_id}', dependencies=write)
def assign_extension(load_id: int, work_id: int, student_id: int, body: ExtendBody,
                     user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    work = owned_work(db, load, work_id)
    if effective_state(work) != 'published' or work.version != body.version:
        raise HTTPException(409, 'Откройте текущую версию опубликованного задания')
    recipients = assignment_recipients(db, load, work)
    policy = work_policy(work)
    if not any(deadline.student_id == student_id for deadline, _, _ in recipients):
        raise HTTPException(404, 'Получатель не найден')
    for deadline, delivery, _ in recipients:
        if deadline.student_id == student_id or policy['team_lead_id']:
            extend_deadline(deadline, delivery, work, body.extended_until)
            assignment_notice(db, deadline, 'Срок сдачи продлён', work.title)
    work.version += 1
    recorded(db, user, 'teaching', load.id, 'work_extension', after={
        'student_id': student_id, 'work_id': work_id, 'due_at': iso(body.extended_until),
    })
    db.commit()
    return work_data(work)


REVIEW_TRANSITIONS = {
    'review': (('submitted', 'resubmitted'), 'in_review'),
    'revise': (('submitted', 'resubmitted', 'in_review'), 'revision_required'),
    'accept': (('submitted', 'resubmitted', 'in_review'), 'accepted'),
    'complete': (('accepted',), 'completed'),
    'comment': (('submitted', 'resubmitted', 'in_review', 'accepted', 'completed'), None),
}


@router.post('/{load_id:int}/works/{work_id}/feedback/{submission_id}', status_code=201, dependencies=write)
def feedback(load_id: int, work_id: int, submission_id: int, body: FeedbackBody, request: Request, response: Response,
             user=Depends(teacher_only), db: Session = Depends(get_db)):
    from .academic_points import award_points

    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    work = owned_work(db, load, work_id)
    found = db.execute(submissions_query(load, work_id).where(AssignmentSubmission.id == submission_id)
                       .with_for_update(of=AssignmentSubmission)).one_or_none()
    if found is None:
        raise HTTPException(404, 'Работа студента не найдена')
    row = found[0]
    receipt, replay = begin_idempotent(db, request, response, user, f'feedback:{submission_id}',
                                       body.model_dump(exclude_unset=True))
    if replay is not None:
        return replay
    allowed, next_status = REVIEW_TRANSITIONS[body.action]
    if (effective_state(work) != 'published' or row.attempt_version != body.submitted_version or row.status not in allowed
        or (body.version is not None and row.version != body.version)):
        raise HTTPException(409, 'Состояние работы изменилось. Откройте её снова')
    policy = work_policy(work)
    if body.score is not None and body.score > policy['max_points']:
        raise HTTPException(422, 'Балл превышает максимум задания')
    if body.action == 'revise' and attempt_count(db, row.id) >= (policy['max_attempts'] or 50):
        raise HTTPException(409, 'Лимит попыток исчерпан. Увеличьте его в условиях задания')
    recipients = [record for record in assignment_recipients(db, load, work)
                  if policy['team_lead_id'] or record[0].student_id == row.student_id]
    if not recipients:
        raise HTTPException(404, 'Получатель не найден')
    if body.extended_until:
        for deadline, delivery, _ in recipients:
            extend_deadline(deadline, delivery, work, body.extended_until)
        work.version += 1
    elif body.action == 'revise' and not policy['allow_late'] and any(
        effective_due(deadline, delivery, work) <= utc_now() for deadline, delivery, _ in recipients
    ):
        raise HTTPException(422, 'Укажите новый срок доработки')
    before_status = row.status
    if next_status:
        row.status = next_status
        row.version += 1
        row.updated_at = utc_now()
    entry = WorkFeedback(submission_id=row.id, author_id=user.id, created_at=utc_now(),
                         **body.model_dump(exclude={'version'}))
    db.add(entry)
    db.flush()
    titles = {'review': 'Работа на проверке', 'revise': 'Работа возвращена на доработку',
              'accept': 'Работа принята', 'complete': 'Работа завершена', 'comment': 'Преподаватель проверил работу'}
    for deadline, _, _ in recipients:
        assignment_notice(db, deadline, titles[body.action], work.title, event_key=f'work-review:{entry.id}:{deadline.id}')
        if body.extended_until:
            assignment_notice(db, deadline, 'Срок доработки продлён', work.title,
                              event_key=f'work-review-due:{entry.id}:{deadline.id}')
        if body.action == 'accept' and body.score and (policy['award_mode'] == 'all' or deadline.student_id == row.student_id):
            award_points(db, student_id=deadline.student_id, discipline_id=load.discipline_id, points=body.score,
                         source_kind='assignment', source_id=work.id, actor_id=user.id, class_id=policy['class_id'],
                         reason=work.title)
            assignment_notice(db, deadline, 'Начислены баллы за работу', f'{work.title} · +{body.score}',
                              event_key=f'work-points:{work.id}:{deadline.id}')
    recorded(db, user, 'teaching', load.id, 'feedback', {'status': before_status}, {
        'work_id': work.id, 'submission_id': row.id, 'student_id': row.student_id,
        'version': row.version, 'status': row.status, 'review_id': entry.id, 'score': body.score,
    })
    return commit_idempotent(db, receipt, feedback_data(entry, user.full_name))


@router.get('/consultations')
def consultations(user=Depends(teacher_only), db: Session = Depends(get_db)):
    rows = db.execute(select(TeacherConsultation, ConsultationSlot).join(ConsultationSlot).join(TeachingLoad)
                      .join(TeachingAssignment).join(Teacher).where(Teacher.user_id == user.id)
                      .order_by(ConsultationSlot.start_at.desc()).limit(100)).all()
    ids = [slot.id for _, slot in rows]
    participants = {}
    for slot_id, name in db.execute(select(ConsultationBooking.slot_id, User.full_name).join(User)
                                    .join(TeacherConsultation, TeacherConsultation.slot_id == ConsultationBooking.slot_id)
                                    .join(TeachingLoad, TeachingLoad.id == TeacherConsultation.load_id)
                                    .join(GroupMember, GroupMember.student_id == User.id)
                                    .where(ConsultationBooking.slot_id.in_(ids), GroupMember.group_id == TeachingLoad.group_id,
                                           ConsultationBooking.status == 'active')):
        participants.setdefault(slot_id, []).append(name)
    return {'items': [dict(id=slot.id, subject=slot.subject, starts=date_iso(slot.start_at), ends=date_iso(slot.end_at),
                           room=slot.room, capacity=slot.capacity, booked=slot.booked_count, students=participants.get(slot.id, []),
                           completed=date_iso(link.completed_at)) for link, slot in rows]}


@router.post('/consultations', status_code=201, dependencies=write)
def new_consultation(body: ConsultationBody, request: Request, response: Response, user=Depends(teacher_only), db: Session = Depends(get_db)):
    from .scheduling import matching_room, room_is_busy, teacher_is_busy
    lock_workspace(db, user.id)
    load = owned_load(db, user, body.load_id)
    receipt, replay = begin_idempotent(db, request, response, user, 'teacher-consultation', body.model_dump())
    if replay is not None:
        return replay
    if body.starts.tzinfo is None or body.ends.tzinfo is None:
        raise HTTPException(422, 'Укажите часовой пояс консультации')
    try:
        start, end = body.starts.astimezone(timezone.utc), body.ends.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise HTTPException(422, 'Дата выходит за поддерживаемый диапазон') from None
    now = utc_now()
    if not now < start <= now+timedelta(days=370) or not timedelta(minutes=15) <= end-start <= timedelta(hours=3):
        raise HTTPException(422, 'Укажите будущее время приёма продолжительностью от 15 минут до 3 часов')
    if teacher_is_busy(db, load.assignment.teacher, start, end):
        raise HTTPException(409, 'В это время преподаватель уже занят')
    room = db.scalar(select(Classroom).where(matching_room(db, Classroom.code, body.room)))
    if room:
        if not room.available or body.capacity > room.capacity or (load.group.accessible and not room.accessible):
            raise HTTPException(422, 'Аудитория не подходит для консультации')
        if room_is_busy(db, room, start, end):
            raise HTTPException(409, 'В это время аудитория уже занята')
    slot = ConsultationSlot(teacher=user.full_name, subject=load.discipline.title, start_at=start, end_at=end,
                            room=room.code if room else body.room, capacity=body.capacity, booked_count=0)
    db.add(slot)
    db.flush()
    db.add(TeacherConsultation(slot_id=slot.id, load_id=load.id))
    recorded(db, user, 'teaching', load.id, 'consultation', after={'id': slot.id, 'starts': date_iso(start)})
    return commit_idempotent(db, receipt, {'id': slot.id})


@router.post('/consultations/{slot_id}/complete', dependencies=write)
def complete_consultation(slot_id: int, user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    row = db.get(TeacherConsultation, slot_id)
    if row is None:
        raise HTTPException(404, 'Консультация не найдена')
    load = owned_load(db, user, row.load_id)
    if as_utc(db.get(ConsultationSlot, slot_id).end_at) > utc_now():
        raise HTTPException(409, 'Консультация ещё не завершилась')
    if row.completed_at is None:
        row.completed_at = utc_now()
        recorded(db, user, 'teaching', load.id, 'consultation_completed', after={'id': slot_id})
    db.commit()
    return {'ok': True}
