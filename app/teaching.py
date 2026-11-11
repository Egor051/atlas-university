"""Teacher-owned roster, assessment, group work and consultations."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Deadline, Grade, User, campus_today, utc_now
from .learning_db import AssignmentSubmission, Attendance
from .main import StrictBody, date_iso, get_db, require_roles, require_same_origin
from .services import begin_idempotent, commit_idempotent
from .services_db import ConsultationBooking, ConsultationSlot
from .session_security import as_utc
from .university_db import Teacher, TeachingAssignment
from .workspace import (check_member, event_payload, load_payload, load_query, lock_workspace, notify,
                        owned_load, recorded, roster)
from .workspace_db import (Classroom, GroupMember, GroupWork, OperationEvent, TeacherConsultation,
                           TeachingLoad, WorkDelivery, WorkFeedback)

teacher_only = require_roles('teacher')
router = APIRouter(prefix='/api/teaching')
write = [Depends(require_same_origin)]


class MarkBody(StrictBody):
    student_id: int = Field(strict=True, ge=1)
    score: int | None = Field(strict=True, ge=0, le=100)
    version: int = Field(strict=True, ge=0)
    reason: str = Field(default='', max_length=300)


class AttendanceBody(StrictBody):
    student_id: int = Field(strict=True, ge=1)
    day: date
    status: Literal['present', 'absent', 'excused']
    note: str = Field(default='', max_length=300)
    version: int = Field(strict=True, ge=0)


class WorkBody(StrictBody):
    title: str = Field(min_length=4, max_length=180)
    instructions: str = Field(min_length=12, max_length=4000)
    due: date

    @field_validator('title', 'instructions', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class WorkEdit(WorkBody):
    version: int = Field(strict=True, ge=1)


class FeedbackBody(StrictBody):
    submitted_version: int = Field(strict=True, ge=1)
    score: int | None = Field(default=None, strict=True, ge=0, le=100)
    comment: str = Field(min_length=3, max_length=2000)

    @field_validator('comment', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


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
    return db.scalar(select(Grade).where(Grade.student_id == student_id, Grade.subject == load.discipline.title).order_by(Grade.id))


def attendance_record(db, load, student_id, day):
    return db.scalar(select(Attendance).where(Attendance.student_id == student_id,
                                              Attendance.subject == load.discipline.title, Attendance.day == day)
                     .order_by(Attendance.id))


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
    if body.score is not None and body.score > (row.max_grade if row else 100):
        raise HTTPException(422, 'Балл превышает максимум дисциплины')
    if not apply:
        return
    if row is None:
        row = Grade(student_id=body.student_id, subject=load.discipline.title, teacher=load.assignment.teacher.user.full_name,
                    kind='exam', exam_kind='Экзамен', max_grade=100, assessment='Допуск', color='violet', trend=0)
        db.add(row)
    row.trend = body.score-row.current if body.score is not None and row.current is not None else 0
    row.current = body.score
    row.version = body.version+1
    if row.kind == 'credit':
        row.assessment = 'Зачтено' if body.score is not None and body.score >= 65 else 'Не зачтено'
    after = grade_data(row)
    recorded(db, user, 'teaching', load.id, 'grade', {'student_id': body.student_id, **before},
             {'student_id': body.student_id, **after, 'reason': body.reason})
    notify(db, body.student_id, 'Успеваемость обновлена', load.discipline.title, '/app/grades', student=True)
    return after


def save_attendance(db, user, load, body, *, apply=True):
    check_member(db, load, body.student_id)
    if not campus_today()-timedelta(days=370) <= body.day <= campus_today():
        raise HTTPException(422, 'Отметка посещаемости относится к прошедшему учебному дню')
    row = attendance_record(db, load, body.student_id, body.day)
    before = attendance_data(row)
    if before['version'] != body.version:
        raise HTTPException(409, 'Посещаемость уже изменена. Загрузите актуальный журнал.')
    if not apply:
        return
    if row is None:
        row = Attendance(student_id=body.student_id, subject=load.discipline.title, day=body.day)
        db.add(row)
    row.status, row.note, row.version = body.status, body.note, body.version+1
    after = attendance_data(row)
    identity = {'student_id': body.student_id, 'day': body.day.isoformat()}
    recorded(db, user, 'teaching', load.id, 'attendance', {**identity, **before}, {**identity, **after})
    return after


def deliver_work(db, load, work, student_id):
    deadline = Deadline(student_id=student_id, subject=load.discipline.title, title=work.title, due_date=work.due)
    db.add(deadline)
    db.flush()
    db.add(WorkDelivery(deadline_id=deadline.id, work_id=work.id))
    notify(db, student_id, 'Новое учебное задание', work.title, f'/app/assignments?id={deadline.id}', student=True)


def feedback_data(row, author):
    return dict(id=row.id, version=row.submitted_version, score=row.score, comment=row.comment,
                author=author, created_at=date_iso(row.created_at))


def assignment_feedback(db, submissions):
    feedback = {}
    ids = [row.id for row in submissions]
    if not ids:
        return feedback
    for row, author in db.execute(select(WorkFeedback, User.full_name).join(User, User.id == WorkFeedback.author_id)
                                  .where(WorkFeedback.submission_id.in_(ids))
                                  .order_by(WorkFeedback.id.desc())):
        items = feedback.setdefault(row.submission_id, [])
        if len(items) < 20:
            items.append(feedback_data(row, author))
    return feedback


def submission_notice(db, deadline):
    target = db.execute(select(TeachingLoad.id, Teacher.user_id).select_from(WorkDelivery).join(GroupWork)
                        .join(TeachingLoad).join(TeachingAssignment).join(Teacher)
                        .join(GroupMember, GroupMember.group_id == TeachingLoad.group_id)
                        .where(WorkDelivery.deadline_id == deadline.id,
                               GroupMember.student_id == deadline.student_id)).one_or_none()
    if target:
        notify(db, target.user_id, 'Работа отправлена на проверку', deadline.title, f'/app/teaching/{target.id}?tab=works')


def work_data(row):
    return dict(id=row.id, title=row.title, instructions=row.instructions, due=row.due.isoformat(), version=row.version)


def validate_due(day):
    if not campus_today() <= day <= campus_today()+timedelta(days=370):
        raise HTTPException(422, 'Укажите срок в пределах учебного года')


@router.get('')
def loads(user=Depends(teacher_only), db: Session = Depends(get_db)):
    query = load_query().join(TeachingAssignment).join(Teacher).where(Teacher.user_id == user.id).order_by(TeachingLoad.id)
    return {'items': [load_payload(row) for row in db.scalars(query)]}


@router.get('/{load_id:int}')
def details(load_id: int, day: date | None = None, user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    day = day or campus_today()
    people = roster(db, load.group_id)
    ids = [person.id for person in people]
    grades, attendance = {}, {}
    for row in db.scalars(select(Grade).where(Grade.student_id.in_(ids), Grade.subject == load.discipline.title).order_by(Grade.id)):
        grades.setdefault(row.student_id, row)
    for row in db.scalars(select(Attendance).where(Attendance.student_id.in_(ids), Attendance.subject == load.discipline.title,
                                                   Attendance.day == day).order_by(Attendance.id)):
        attendance.setdefault(row.student_id, row)
    history = db.execute(select(OperationEvent, User.full_name).join(User, User.id == OperationEvent.actor_id)
                         .where(OperationEvent.area == 'teaching', OperationEvent.object_id == load.id)
                         .order_by(OperationEvent.id.desc()).limit(30))
    submitted = db.scalar(select(func.count()).select_from(AssignmentSubmission).join(WorkDelivery,
                          WorkDelivery.deadline_id == AssignmentSubmission.deadline_id).join(GroupWork)
                          .where(GroupWork.load_id == load.id, AssignmentSubmission.student_id.in_(ids),
                                 AssignmentSubmission.status == 'submitted'))
    totals = db.execute(select(Attendance.status, func.count()).where(Attendance.student_id.in_(ids),
                        Attendance.subject == load.discipline.title).group_by(Attendance.status)).all()
    scores = [g.current for g in grades.values() if g.current is not None]
    return {**load_payload(load), 'day': day.isoformat(),
            'students': [dict(id=p.id, name=p.full_name, number=p.student_number,
                              grade=grade_data(grades.get(p.id)), attendance=attendance_data(attendance.get(p.id))) for p in people],
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


@router.put('/{load_id:int}/attendance', dependencies=write)
def attendance(load_id: int, body: AttendanceBody, user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    result = save_attendance(db, user, owned_load(db, user, load_id), body)
    db.commit()
    return result


@router.get('/{load_id:int}/works')
def works(load_id: int, offset: int = Query(0, ge=0, le=2147483647), user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    rows = db.scalars(select(GroupWork).where(GroupWork.load_id == load.id).order_by(GroupWork.id.desc()).offset(offset).limit(21)).all()
    counts = dict(db.execute(select(WorkDelivery.work_id, func.count()).join(AssignmentSubmission,
                             AssignmentSubmission.deadline_id == WorkDelivery.deadline_id)
                             .join(GroupMember, GroupMember.student_id == AssignmentSubmission.student_id)
                             .where(WorkDelivery.work_id.in_([row.id for row in rows[:20]]), GroupMember.group_id == load.group_id,
                                    AssignmentSubmission.status == 'submitted').group_by(WorkDelivery.work_id)).all())
    return {'items': [{**work_data(row), 'submitted': counts.get(row.id, 0)} for row in rows[:20]], 'more': len(rows)>20, 'offset': offset}


@router.post('/{load_id:int}/works', status_code=201, dependencies=write)
def new_work(load_id: int, body: WorkBody, request: Request, response: Response,
             user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    receipt, replay = begin_idempotent(db, request, response, user, f'group-work:{load_id}', body.model_dump())
    if replay is not None:
        return replay
    validate_due(body.due)
    members = roster(db, load.group_id)
    if not members:
        raise HTTPException(409, 'Добавьте студентов в группу перед публикацией задания')
    row = GroupWork(load_id=load.id, author_id=user.id, created_at=utc_now(), **body.model_dump())
    db.add(row)
    db.flush()
    for member in members:
        deliver_work(db, load, row, member.id)
    recorded(db, user, 'teaching', load.id, 'work_created', after=work_data(row))
    return commit_idempotent(db, receipt, work_data(row))


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
    if body.due != row.due:
        validate_due(body.due)
    before = work_data(row)
    row.title, row.instructions, row.due, row.version = body.title, body.instructions, body.due, row.version+1
    for deadline in db.scalars(select(Deadline).join(WorkDelivery).where(WorkDelivery.work_id == row.id)):
        deadline.title, deadline.due_date = row.title, row.due
        notify(db, deadline.student_id, 'Учебное задание обновлено', row.title, f'/app/assignments?id={deadline.id}', student=True)
    recorded(db, user, 'teaching', load.id, 'work_edited', before, work_data(row))
    db.commit()
    return work_data(row)


def submissions_query(load, work_id):
    return (select(AssignmentSubmission, User.full_name).join(WorkDelivery, WorkDelivery.deadline_id == AssignmentSubmission.deadline_id)
            .join(GroupMember, GroupMember.student_id == AssignmentSubmission.student_id)
            .join(User, User.id == GroupMember.student_id)
            .where(WorkDelivery.work_id == work_id, GroupMember.group_id == load.group_id))


@router.get('/{load_id:int}/works/{work_id}')
def work_detail(load_id: int, work_id: int, user=Depends(teacher_only), db: Session = Depends(get_db)):
    load = owned_load(db, user, load_id)
    work = owned_work(db, load, work_id)
    submissions = db.execute(submissions_query(load, work_id).order_by(AssignmentSubmission.id)).all()
    feedback = assignment_feedback(db, (row for row, _ in submissions))
    return {**work_data(work), 'submissions': [dict(id=row.id, student=name, status=row.status, version=row.version,
                  text=row.text if row.status=='submitted' else '', url=row.url if row.status=='submitted' else '',
                  submitted_at=date_iso(row.submitted_at), feedback=feedback.get(row.id, []))
                  for row, name in submissions]}


@router.post('/{load_id:int}/works/{work_id}/feedback/{submission_id}', status_code=201, dependencies=write)
def feedback(load_id: int, work_id: int, submission_id: int, body: FeedbackBody, request: Request, response: Response,
             user=Depends(teacher_only), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    load = owned_load(db, user, load_id)
    owned_work(db, load, work_id)
    found = db.execute(submissions_query(load, work_id).where(AssignmentSubmission.id == submission_id)
                       .with_for_update(of=AssignmentSubmission)).one_or_none()
    if found is None:
        raise HTTPException(404, 'Работа студента не найдена')
    row = found[0]
    receipt, replay = begin_idempotent(db, request, response, user, f'feedback:{submission_id}', body.model_dump())
    if replay is not None:
        return replay
    if row.version != body.submitted_version or row.status != 'submitted':
        raise HTTPException(409, 'Версия работы изменилась. Откройте её снова.')
    entry = WorkFeedback(submission_id=row.id, author_id=user.id, created_at=utc_now(), **body.model_dump())
    db.add(entry)
    db.flush()
    notify(db, row.student_id, 'Преподаватель проверил работу', 'Комментарий доступен в истории задания.',
           f'/app/assignments?id={row.deadline_id}', student=True)
    recorded(db, user, 'teaching', load.id, 'feedback', after={'work_id': work_id, 'submission_id': row.id, 'version': row.version})
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
