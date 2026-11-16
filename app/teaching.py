"""Teacher-owned roster, assessment, group work and consultations."""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, ValidationError, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .academic_points import (AssignmentPointCorrection, PointAward, award_data, award_points,
                              correct_assignment_points, correction_data, grade_record as student_grade)
from .db import CAMPUS_TZ, Deadline, Grade, User, campus_today, utc_now
from .assignment_files import (download_feedback_file, download_source_file, replace_source_files,
                               save_feedback_files, source_files)
from .assignment_grades import official_score_query, score_from_history
from .assignment_inputs import ExtendBody, FeedbackBody, ScoreCorrectionBody, WorkBody, WorkEdit
from .assignment_workflow import (DEFAULT_POLICY, FORMATS, MAX_UPLOAD_BYTES, SUBMITTED, assignment_notice, assignment_recipients,
                                  attachment_payload, attachment_response, attempt_count, attempt_details, base_due, deadline_fields,
                                  deliver_work, effective_due, effective_state, feedback_data, iso,
                                  submission_data, sync_due_date, validate_due, work_data, work_policy)
from .learning_db import AssignmentSubmission, Attendance
from .main import StrictBody, date_iso, get_db, require_roles, require_same_origin
from .services import begin_idempotent, commit_idempotent
from .services_db import ConsultationBooking, ConsultationSlot
from .session_security import as_utc
from .university_db import Discipline, Teacher, TeachingAssignment, TeachingMaterial
from .work_materials import eligible_materials, set_work_materials
from .workspace import (check_member, event_payload, load_payload, load_query, lock_workspace, notify,
                        owned_load, recorded, roster)
from .workspace_db import (AcademicSubgroup, Classroom, GroupMember, GroupWork, OperationEvent, ScheduledClass, TeacherConsultation,
                           AcademicGroup, TeachingLoad, WorkDelivery, WorkFeedback, WorkMaterial)

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


def class_participants(db, meeting):
    from .scheduling import recipients
    return recipients(db, dict(group_id=meeting.group_id, subgroup_id=meeting.subgroup_id, student_id=meeting.student_id))


def save_attendance(db, user, load, body, *, apply=True):
    check_member(db, load, body.student_id)
    if not campus_today()-timedelta(days=370) <= body.day <= campus_today():
        raise HTTPException(422, 'Отметка посещаемости относится к прошедшему учебному дню')
    if body.class_id:
        meeting = scoped_class(db, load, body.class_id)
        if body.student_id not in class_participants(db, meeting):
            raise HTTPException(404, 'Студент не участвует в этом занятии')
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


@router.get('/workbench')
def workbench(user=Depends(teacher_only), db: Session = Depends(get_db)):
    groups = loads(user=user, db=db)['items']
    pending = db.execute(select(GroupWork.id, GroupWork.title, TeachingLoad.id, Discipline.title, AcademicGroup.code,
                               func.count(AssignmentSubmission.id).label('pending'))
                         .select_from(GroupWork).join(TeachingLoad).join(Discipline).join(AcademicGroup)
                         .join(WorkDelivery, WorkDelivery.work_id == GroupWork.id)
                         .join(AssignmentSubmission, AssignmentSubmission.deadline_id == WorkDelivery.deadline_id)
                         .join(GroupMember, and_(GroupMember.student_id == AssignmentSubmission.student_id,
                                                 GroupMember.group_id == TeachingLoad.group_id))
                         .where(TeachingLoad.id.in_([group['id'] for group in groups]), WorkDelivery.active.is_(True),
                                AssignmentSubmission.status.in_(('submitted', 'resubmitted', 'in_review')),
                                or_(GroupWork.state.in_(('published', 'closed')), and_(GroupWork.state == 'scheduled',
                                                                         GroupWork.publish_at <= utc_now())))
                         .group_by(GroupWork.id, GroupWork.title, TeachingLoad.id, Discipline.title, AcademicGroup.code)
                         .order_by(func.max(AssignmentSubmission.updated_at).desc(), GroupWork.id.desc()).limit(20))
    return dict(groups=groups, pending=[dict(work_id=key, title=title, load_id=load_id, discipline=subject, group=group, count=count)
                                         for key, title, load_id, subject, group, count in pending])


@router.get('/{load_id:int}')
def details(load_id: int, day: date | None = None, class_id: int | None = Query(None, ge=1),
            user=Depends(teacher_only), db: Session = Depends(get_db)):
    from .scheduling import KIND

    load = owned_load(db, user, load_id)
    meeting = scoped_class(db, load, class_id) if class_id else None
    day = class_day(meeting) if meeting else day or campus_today()
    sessions = db.scalars(select(ScheduledClass).where(ScheduledClass.load_id == load.id, ScheduledClass.status == 'active')
                          .order_by(ScheduledClass.starts_at.desc()).limit(200)).all()
    people = roster(db, load.group_id)
    attendance_ids = class_participants(db, meeting) if meeting else {person.id for person in people}
    ids = [person.id for person in people]
    subgroup_by_student = dict(db.execute(select(GroupMember.student_id, GroupMember.subgroup_id)
                                         .where(GroupMember.group_id == load.group_id)).all())
    subgroups = db.execute(select(AcademicSubgroup.id, AcademicSubgroup.code).where(
        AcademicSubgroup.group_id == load.group_id).order_by(AcademicSubgroup.code, AcademicSubgroup.id)).all()
    grades, attendance = {}, {}
    for row in db.scalars(select(Grade).where(Grade.student_id.in_(ids), Grade.subject == load.discipline.title).order_by(Grade.id)):
        grades.setdefault(row.student_id, row)
    for row in db.scalars(select(Attendance).where(Attendance.student_id.in_(attendance_ids), Attendance.subject == load.discipline.title,
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
            'subgroups': [dict(id=key, code=code) for key, code in subgroups],
            'students': [dict(id=p.id, name=p.full_name, number=p.student_number, subgroup_id=subgroup_by_student.get(p.id),
                              grade=grade_data(grades.get(p.id)), attendance=attendance_data(attendance.get(p.id)),
                              class_participant=p.id in attendance_ids,
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
    if body.class_id:
        meeting = scoped_class(db, load, body.class_id)
        if body.student_id not in class_participants(db, meeting):
            raise HTTPException(404, 'Студент не участвует в этом занятии')
        if as_utc(meeting.starts_at) > utc_now():
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
    corrections = db.scalars(select(AssignmentPointCorrection).where(AssignmentPointCorrection.student_id == student_id,
                              AssignmentPointCorrection.grade_id == grade.id).order_by(AssignmentPointCorrection.id.desc())) if grade else ()
    return {'items': [award_data(row, date_iso) for row in rows],
            'corrections': [correction_data(row, date_iso) for row in corrections]}


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
    scope = [GroupMember.group_id == load.group_id]
    if body.subgroup_id is not None:
        if db.scalar(select(AcademicSubgroup.id).where(
            AcademicSubgroup.id == body.subgroup_id, AcademicSubgroup.group_id == load.group_id
        )) is None:
            raise HTTPException(404, 'Подгруппа не найдена в данной учебной группе')
        scope.append(GroupMember.subgroup_id == body.subgroup_id)
    members = set(db.scalars(select(GroupMember.student_id).join(User).where(*scope, User.role == 'student')))
    selected = set(body.recipient_ids) or members
    if not selected and body.state != 'draft':
        raise HTTPException(409, 'В выбранной группе или подгруппе нет студентов')
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
    if body.state not in ('draft', 'closed', 'archived') and (prev_due is None or as_utc(prev_due) != due_at):
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
                      if body.state in ('published', 'closed', 'archived') else None)
    row.policy_json = json.dumps({name: getattr(body, name) for name in DEFAULT_POLICY}, ensure_ascii=False)


def update_deliveries(db, load, row, selected, before, after, *, was_scheduled):
    prior = {deadline.student_id: (deadline, delivery) for deadline, delivery in db.execute(
        select(Deadline, WorkDelivery).join(WorkDelivery).where(WorkDelivery.work_id == row.id))}
    if row.state in ('published', 'scheduled'):
        for student_id in sorted(selected - prior.keys()):
            deliver_work(db, load, row, student_id)
    changed = any(value != before.get(field) for field, value in after.items() if field not in ('version', 'publish_at'))
    for student_id, (deadline, delivery) in prior.items():
        was_active = delivery.active
        delivery.active = student_id in selected and row.state != 'draft'
        if not delivery.active:
            continue
        deadline.title = row.title
        sync_due_date(deadline, delivery, row)
        if row.state == 'published' and (before['state'] in ('draft', 'scheduled') or not was_active):
            assignment_notice(db, deadline, 'Опубликовано учебное задание', row.title,
                              event_key=f'work-publish:{row.id}:{deadline.id}')
            continue
        if was_scheduled and before['state'] == 'published':
            assignment_notice(db, deadline, 'Опубликовано учебное задание', row.title,
                              event_key=f'work-publish:{row.id}:{deadline.id}')
        if changed and before['state'] in ('published', 'closed'):
            title = {'closed': 'Приём работ завершён', 'archived': 'Задание перенесено в архив'}.get(
                row.state, 'Условия задания изменились')
            assignment_notice(db, deadline, title, row.title, event_key=f'work-edit:{row.id}:{deadline.id}:{row.version}')


@router.post('/{load_id:int}/works', status_code=201, dependencies=write)
def new_work(load_id: int, body: WorkBody, request: Request, response: Response,
             user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    receipt, replay = begin_idempotent(db, request, response, user, f'group-work:{load_id}',
                                       body.model_dump(exclude_unset=True))
    if replay is not None:
        return replay
    if body.state in ('closed', 'archived'):
        raise HTTPException(422, 'Сначала создайте задание')
    selected = target_students(db, load, body) if (
        body.state != 'draft' or body.subgroup_id or body.recipient_ids or body.team_lead_id or body.class_id) else set()
    row = GroupWork(load_id=load.id, author_id=user.id, created_at=utc_now())
    save_work_fields(row, body)
    db.add(row)
    db.flush()
    set_work_materials(db, load, row.id, body.material_ids)
    uploads = attachment_payload(body.source_files, FORMATS)
    files = replace_source_files(db, row.id, uploads, [], max_bytes=MAX_UPLOAD_BYTES) if uploads else []
    if row.state != 'draft':
        for student_id in sorted(selected):
            deliver_work(db, load, row, student_id)
    result = {**work_data(row), 'material_ids': sorted(set(body.material_ids)), 'source_files': files}
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
    prior_ids = list(db.scalars(select(WorkMaterial.material_id).where(WorkMaterial.work_id == row.id)
                                .order_by(WorkMaterial.material_id)))
    before = {**work_data(row), 'material_ids': prior_ids, 'source_files': source_files(db, row.id)}
    patch = body.model_dump(exclude_unset=True, exclude={'version', 'remove_source_ids'})
    if 'due' in patch and 'due_at' not in patch:
        patch['due_at'] = None
    stored = {key: before[key] for key in WorkBody.model_fields if key != 'source_files'}
    try:
        updated = WorkBody.model_validate({**stored, **patch})
    except (ValueError, ValidationError) as error:
        message = error.errors()[0]['msg'] if isinstance(error, ValidationError) else str(error)
        raise HTTPException(422, message) from None
    if before['state'] == 'archived' or (before['state'] == 'closed' and
        (updated.state != 'archived' or patch.keys() != {'state'} or body.remove_source_ids)
    ):
        raise HTTPException(409, 'Завершённое задание можно перенести в архив')
    if updated.state in ('closed', 'archived') and before['state'] not in ('published', 'closed'):
        raise HTTPException(409, 'Завершить или архивировать можно только опубликованное задание')
    if before['state'] == 'published':
        protected = {'subgroup_id', 'recipient_ids', 'team_lead_id', 'award_mode', 'class_id', 'kind', 'max_points'}
        if updated.state not in ('published', 'closed', 'archived') or any(
            getattr(updated, key) != before[key] for key in protected
        ):
            raise HTTPException(409, 'У опубликованной работы можно изменить сроки, текст и способы сдачи')
    current_recipients = assignment_recipients(db, load, row, current_members=False)
    selected = ({deadline.student_id for deadline, _, _ in current_recipients}
                if before['state'] in ('published', 'closed') else
                target_students(db, load, updated) if (
                    updated.state != 'draft' or updated.subgroup_id or updated.recipient_ids or updated.team_lead_id or updated.class_id) else set())
    was_scheduled = row.state == 'scheduled'
    save_work_fields(row, updated, prev_due=row.due_at or base_due(row.due))
    if 'material_ids' in patch:
        set_work_materials(db, load, row.id, updated.material_ids)
    files = before['source_files']
    if updated.source_files or body.remove_source_ids:
        uploads = attachment_payload(updated.source_files, FORMATS)
        files = replace_source_files(db, row.id, uploads, body.remove_source_ids, max_bytes=MAX_UPLOAD_BYTES)
    row.version += 1
    result = {**work_data(row), 'material_ids': sorted(set(updated.material_ids)), 'source_files': files}
    update_deliveries(db, load, row, selected, before, result, was_scheduled=was_scheduled)
    recorded(db, user, 'teaching', load.id, 'work_edited', before, result)
    db.commit()
    return result


def submissions_query(load, work_id):
    return (select(AssignmentSubmission, User.full_name)
            .join(WorkDelivery, WorkDelivery.deadline_id == AssignmentSubmission.deadline_id)
            .join(GroupMember, GroupMember.student_id == AssignmentSubmission.student_id)
            .join(User, User.id == GroupMember.student_id)
            .where(WorkDelivery.work_id == work_id, WorkDelivery.active.is_(True), GroupMember.group_id == load.group_id,
                   AssignmentSubmission.attempt_version > 0, User.role == 'student'))


@router.get('/{load_id:int}/works/{work_id}')
def work_detail(load_id: int, work_id: int, user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    work = owned_work(db, load, work_id)
    recipients = assignment_recipients(db, load, work)
    submissions = []
    for row, name in db.execute(submissions_query(load, work_id).order_by(AssignmentSubmission.id)):
        notes, attempts = attempt_details(db, row.id)
        submissions.append({**submission_data(row), 'student': name, 'student_id': row.student_id,
                            'deadline_id': row.deadline_id, 'score': score_from_history(notes),
                            'feedback': notes, 'attempts': attempts})
    linked = db.execute(select(TeachingMaterial.id, TeachingMaterial.title, TeachingMaterial.access)
                        .join(WorkMaterial).join(TeachingAssignment).where(WorkMaterial.work_id == work.id,
                                                                          *eligible_materials(load)))
    material_cards = [dict(id=key, title=title, access=access) for key, title, access in linked]
    material_ids = list(db.scalars(select(WorkMaterial.material_id).where(WorkMaterial.work_id == work.id)
                                   .order_by(WorkMaterial.material_id)))
    now = utc_now()
    return {**work_data(work), 'submissions': submissions, 'material_ids': material_ids,
            'course_materials': material_cards, 'source_files': source_files(db, work.id),
            'recipients': [
        dict(id=deadline.student_id, deadline_id=deadline.id, name=name, **deadline_fields(deadline, delivery, work, now=now))
        for deadline, delivery, name in recipients
    ], 'classes': [
        dict(id=row.id, day=as_utc(row.starts_at).astimezone(CAMPUS_TZ).isoformat(), topic=row.note)
        for row in db.scalars(select(ScheduledClass).where(ScheduledClass.load_id == load.id, ScheduledClass.status == 'active')
                              .order_by(ScheduledClass.starts_at).limit(100))
    ]}


@router.get('/{load_id:int}/material-options')
def work_material_options(load_id: int, q: str = Query('', max_length=100), user=Depends(teacher_only), db: Session = Depends(get_db)):
    from .main import search_text, text_search

    load = owned_load(db, user, load_id)
    query = select(TeachingMaterial.id, TeachingMaterial.title).join(TeachingAssignment).where(*eligible_materials(load))
    if q := search_text(q):
        query = query.where(text_search(TeachingMaterial.title, q))
    rows = db.execute(query.order_by(TeachingMaterial.updated_at.desc(), TeachingMaterial.id.desc()).limit(51)).all()
    return {'items': [dict(id=key, title=title) for key, title in rows[:50]], 'more': len(rows) > 50}


@router.get('/{load_id:int}/works/{work_id}/submissions/{submission_id}/files/{attachment_id}')
def teacher_attachment(load_id: int, work_id: int, submission_id: int, attachment_id: int,
                       user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    owned_work(db, load, work_id)
    if db.execute(submissions_query(load, work_id).where(AssignmentSubmission.id == submission_id)).one_or_none() is None:
        raise HTTPException(404, 'Вложение не найдено')
    return attachment_response(db, submission_id, attachment_id)


@router.get('/{load_id:int}/works/{work_id}/source-files/{file_id}')
def teacher_source_file(load_id: int, work_id: int, file_id: int, user=Depends(teacher_only),
                        db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    return download_source_file(db, owned_work(db, load, work_id).id, file_id)


@router.get('/{load_id:int}/works/{work_id}/submissions/{submission_id}/feedback-files/{file_id}')
def teacher_feedback_file(load_id: int, work_id: int, submission_id: int, file_id: int, user=Depends(teacher_only),
                          db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    owned_work(db, load, work_id)
    if db.execute(submissions_query(load, work_id).where(AssignmentSubmission.id == submission_id)).one_or_none() is None:
        raise HTTPException(404, 'Вложение не найдено')
    return download_feedback_file(db, submission_id, file_id)


def extend_deadline(deadline, delivery, work, until):
    if until <= effective_due(deadline, delivery, work):
        raise HTTPException(422, 'Новый срок должен быть позже действующего')
    if delivery.revision_due_at:
        delivery.revision_due_at = until
    else:
        delivery.extended_until = until


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
    until = body.extended_until or body.individual_due_at
    now = utc_now()
    if until is not None:
        validate_due(until, now=now)
    before = {}
    after = {}
    for deadline, delivery, _ in recipients:
        if deadline.student_id != student_id and not policy['team_lead_id']:
            continue
        old = deadline_fields(deadline, delivery, work, now=now)
        if body.extended_until:
            extend_deadline(deadline, delivery, work, body.extended_until)
        else:
            delivery.individual_due_at = body.individual_due_at
            delivery.extended_until = None
        current = deadline_fields(deadline, delivery, work, now=now)
        if old == current:
            continue
        sync_due_date(deadline, delivery, work)
        before[deadline.student_id] = old
        after[deadline.student_id] = current
        title = 'Срок сдачи продлён' if body.extended_until else 'Индивидуальный срок сдачи изменён'
        date_label = effective_due(deadline, delivery, work).astimezone(CAMPUS_TZ).strftime('%d.%m.%Y, %H:%M МСК')
        assignment_notice(db, deadline, title, f'{work.title} · до {date_label}',
                          event_key=f'work-due:{work.id}:{deadline.id}:{work.version + 1}')
    if not after:
        return work_data(work)
    work.version += 1
    recorded(db, user, 'teaching', load.id, 'work_extension' if body.extended_until else 'work_individual_due',
             {'work_id': work.id, 'recipients': before}, {'work_id': work.id, 'recipients': after})
    db.commit()
    return work_data(work)


REVIEW_TRANSITIONS = {
    'review': (('submitted', 'resubmitted'), 'in_review'),
    'revise': (('submitted', 'resubmitted', 'in_review'), 'revision_required'),
    'accept': (('submitted', 'resubmitted', 'in_review'), 'accepted'),
    'grade': (('accepted', 'completed'), None),
    'complete': (('accepted',), 'completed'),
    'comment': (('submitted', 'resubmitted', 'in_review', 'revision_required', 'accepted', 'completed'), None),
}


def review_submission(db, load, work, submission_id):
    found = db.execute(submissions_query(load, work.id).where(AssignmentSubmission.id == submission_id)
                       .with_for_update(of=AssignmentSubmission)).one_or_none()
    if found is None:
        raise HTTPException(404, 'Работа студента не найдена')
    return found[0]


def review_recipients(db, load, work, submission, policy):
    recipients = [record for record in assignment_recipients(db, load, work)
                  if policy['team_lead_id'] or record[0].student_id == submission.student_id]
    if not recipients:
        raise HTTPException(404, 'Получатель не найден')
    return recipients


@router.post('/{load_id:int}/works/{work_id}/feedback/{submission_id}', status_code=201, dependencies=write)
def feedback(load_id: int, work_id: int, submission_id: int, body: FeedbackBody, request: Request, response: Response,
             user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    work = owned_work(db, load, work_id)
    row = review_submission(db, load, work, submission_id)
    receipt, replay = begin_idempotent(db, request, response, user, f'feedback:{submission_id}',
                                       body.model_dump(exclude_unset=True))
    if replay is not None:
        return replay
    allowed, next_status = REVIEW_TRANSITIONS[body.action]
    state = effective_state(work)
    if (state not in ('published', 'closed') or (state == 'closed' and body.action == 'revise')
        or row.attempt_version != body.submitted_version or row.status not in allowed
        or (body.version is not None and row.version != body.version)):
        raise HTTPException(409, 'Состояние работы изменилось. Откройте её снова')
    policy = work_policy(work)
    if body.score is not None and body.score > policy['max_points']:
        raise HTTPException(422, 'Балл превышает максимум задания')
    if body.action == 'grade' and db.scalar(official_score_query(row.id)) is not None:
        raise HTTPException(409, 'Оценка уже выставлена. Для её изменения выберите корректировку')
    if body.action == 'revise' and attempt_count(db, row.id) >= (policy['max_attempts'] or 50):
        raise HTTPException(409, 'Лимит попыток исчерпан. Увеличьте его в условиях задания')
    recipients = review_recipients(db, load, work, row, policy)
    if body.extended_until:
        validate_due(body.extended_until)
        for deadline, delivery, _ in recipients:
            delivery.revision_due_at = body.extended_until
            sync_due_date(deadline, delivery, work)
        work.version += 1
    elif body.action == 'revise' and not policy['allow_late'] and any(
        effective_due(deadline, delivery, work) <= utc_now() for deadline, delivery, _ in recipients
    ):
        raise HTTPException(422, 'Укажите новый срок доработки')
    before_status = row.status
    if next_status:
        row.status = next_status
    if next_status or body.action == 'grade':
        row.version += 1
        row.updated_at = utc_now()
    entry = WorkFeedback(submission_id=row.id, author_id=user.id, created_at=utc_now(),
                         **body.model_dump(exclude={'version', 'files'}))
    db.add(entry)
    db.flush()
    files = save_feedback_files(db, entry.id, attachment_payload(body.files, FORMATS))
    titles = {'review': 'Работа на проверке', 'revise': 'Работа возвращена на доработку',
              'accept': 'Работа принята', 'grade': 'Опубликована оценка за работу',
              'complete': 'Работа завершена', 'comment': 'Преподаватель проверил работу'}
    for deadline, delivery, _ in recipients:
        title = titles[body.action]
        notice_body = work.title
        if body.action == 'revise':
            date_label = effective_due(deadline, delivery, work).astimezone(CAMPUS_TZ).strftime('%d.%m.%Y, %H:%M МСК')
            notice_body = f'{work.title} · до {date_label}'
        if body.action in ('accept', 'grade') and body.score is not None:
            notice_body = f'{work.title} · {body.score} из {policy["max_points"]}'
            if body.score > 0 and (policy['award_mode'] == 'all' or deadline.student_id == row.student_id):
                award_points(db, student_id=deadline.student_id, discipline_id=load.discipline_id, points=body.score,
                             source_kind='assignment', source_id=work.id, actor_id=user.id, class_id=policy['class_id'],
                             reason=work.title)
                title = 'Начислены баллы за работу'
        assignment_notice(db, deadline, title, notice_body, event_key=f'work-review:{entry.id}:{deadline.id}')
    recorded(db, user, 'teaching', load.id, 'feedback', {'status': before_status}, {
        'work_id': work.id, 'submission_id': row.id, 'student_id': row.student_id,
        'version': row.version, 'status': row.status, 'review_id': entry.id, 'score': body.score,
        'files': files,
    })
    return commit_idempotent(db, receipt, feedback_data(entry, user.full_name, files))


@router.post('/{load_id:int}/works/{work_id}/submissions/{submission_id}/score-corrections', status_code=201, dependencies=write)
def correct_score(load_id: int, work_id: int, submission_id: int, body: ScoreCorrectionBody, request: Request,
                  response: Response, user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    work = owned_work(db, load, work_id)
    row = review_submission(db, load, work, submission_id)
    receipt, replay = begin_idempotent(db, request, response, user, f'work-score-correction:{row.id}', body.model_dump())
    if replay is not None:
        return replay
    if (row.status not in ('accepted', 'completed') or row.version != body.version
        or row.attempt_version != body.submitted_version):
        raise HTTPException(409, 'Состояние работы изменилось. Откройте её снова')
    policy = work_policy(work)
    previous_score = db.scalar(official_score_query(row.id))
    if previous_score is None:
        raise HTTPException(409, 'У работы ещё нет опубликованной оценки')
    if body.score == previous_score or body.score > policy['max_points']:
        raise HTTPException(422, 'Укажите новый балл в пределах максимума задания')
    recipients = review_recipients(db, load, work, row, policy)
    row.version += 1
    row.updated_at = utc_now()
    entry = WorkFeedback(submission_id=row.id, author_id=user.id, created_at=row.updated_at,
                         submitted_version=row.attempt_version, action='correct_score', score=body.score,
                         previous_score=previous_score, comment=body.reason)
    db.add(entry)
    db.flush()
    for deadline, _, _ in recipients:
        if policy['award_mode'] == 'all' or deadline.student_id == row.student_id:
            correct_assignment_points(db, student_id=deadline.student_id, discipline_id=load.discipline_id,
                                      work_id=work.id, feedback_id=entry.id, points=body.score, actor_id=user.id,
                                      reason=body.reason, class_id=policy['class_id'])
        assignment_notice(db, deadline, 'Оценка за работу скорректирована', f'{work.title} · {previous_score} → {body.score}',
                          event_key=f'work-review:{entry.id}:{deadline.id}')
    recorded(db, user, 'teaching', load.id, 'work_score_corrected',
             {'work_id': work.id, 'submission_id': row.id, 'score': previous_score},
             {'work_id': work.id, 'submission_id': row.id, 'score': body.score, 'reason': body.reason,
              'review_id': entry.id, 'version': row.version})
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
