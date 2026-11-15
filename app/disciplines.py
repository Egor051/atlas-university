"""Discipline workspaces over the existing student and teaching records."""
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .assignment_workflow import student_assignment_results
from .db import campus_today, utc_now
from .learning_db import Course
from .main import date_iso, get_db, require_student, require_user
from .material_policy import MATERIAL_MANAGERS, PUBLISHED_ACCESS, managed_assignments, student_loads, visible_materials
from .schedule_views import student_days
from .services import consultation_scope
from .services_db import ConsultationBooking, ConsultationSlot
from .university import department_card, discipline_card, teacher_card, teachers_query
from .university_db import Discipline, Teacher, TeachingAssignment, TeachingMaterial
from .workspace import load_payload, load_query
from .workspace_db import TeacherConsultation, TeachingLoad

router = APIRouter(prefix='/api/disciplines')
RecordId = Annotated[int, Path(ge=1, le=2147483647)]
Activity = Literal['schedule', 'works', 'consultations']


def checked_discipline(db, discipline_id):
    row = db.get(Discipline, discipline_id)
    if row is None:
        raise HTTPException(404, 'Дисциплина не найдена')
    return row


@router.get('')
def disciplines(user=Depends(require_user), db: Session = Depends(get_db)):
    if user.role == 'student':
        owned = set(db.scalars(student_loads(user).with_only_columns(TeachingLoad.discipline_id)))
        owned.update(db.scalars(select(Course.discipline_id).where(Course.student_id == user.id,
                                                                  Course.discipline_id.is_not(None))))
    else:
        owned = set(db.scalars(select(TeachingAssignment.discipline_id).where(managed_assignments(user))))
    counts = dict(db.execute(select(TeachingAssignment.discipline_id, func.count(TeachingMaterial.id))
                             .join(TeachingMaterial).where(visible_materials(user), TeachingMaterial.access.in_(PUBLISHED_ACCESS))
                             .group_by(TeachingAssignment.discipline_id)).all())
    rows = db.scalars(select(Discipline).where(Discipline.id.in_(owned | counts.keys())).order_by(Discipline.title)).all()
    return {'items': [{**discipline_card(row), 'mine': row.id in owned, 'material_count': counts.get(row.id, 0)}
                      for row in rows]}


@router.get('/{discipline_id}')
def discipline(discipline_id: RecordId, user=Depends(require_user), db: Session = Depends(get_db)):
    row = checked_discipline(db, discipline_id)
    assignments = select(TeachingAssignment).where(TeachingAssignment.discipline_id == row.id)
    instructors = db.scalars(teachers_query().where(Teacher.id.in_(assignments.with_only_columns(TeachingAssignment.teacher_id)))
                             .order_by(Teacher.id))
    course = db.scalar(select(Course).where(Course.student_id == user.id, Course.discipline_id == row.id)
                       .order_by(Course.id).limit(1)) if user.role == 'student' else None
    loads = []
    if user.role == 'teacher':
        own_assignments = assignments.where(managed_assignments(user)).with_only_columns(TeachingAssignment.id)
        loads = [load_payload(load) for load in db.scalars(load_query().where(TeachingLoad.assignment_id.in_(own_assignments))
                                                          .order_by(TeachingLoad.id))]
    return {**discipline_card(row), 'teachers': [teacher_card(teacher) for teacher in instructors],
            'department': department_card(row.department), 'course_id': course.id if course else None,
            'loads': loads, 'can_manage': user.role in MATERIAL_MANAGERS and db.scalar(
                assignments.where(managed_assignments(user)).with_only_columns(TeachingAssignment.id).limit(1)) is not None}


def upcoming_consultations(db, user, subject, discipline_id):
    match = ConsultationSlot.subject == subject
    linked = select(TeacherConsultation.slot_id)
    if discipline_id is not None:
        assigned = linked.join(TeachingLoad).where(TeachingLoad.discipline_id == discipline_id)
        match = or_(and_(match, ~ConsultationSlot.id.in_(linked)), ConsultationSlot.id.in_(assigned))
    else:
        match = and_(match, ~ConsultationSlot.id.in_(linked))
    booking = ConsultationBooking
    rows = db.execute(select(ConsultationSlot, booking.id).outerjoin(booking, and_(
        booking.slot_id == ConsultationSlot.id, booking.student_id == user.id, booking.status == 'active'))
        .where(match, consultation_scope(user), ConsultationSlot.start_at >= utc_now())
        .order_by(ConsultationSlot.start_at, ConsultationSlot.id).limit(12))
    return [dict(id=slot.id, teacher=slot.teacher, subject=slot.subject, start_at=date_iso(slot.start_at),
                 room=slot.room, my_booking_id=booking_id, available=slot.booked_count < slot.capacity)
            for slot, booking_id in rows]


def activity_rows(db, user, view, subject, discipline_id, offset):
    if view == 'works':
        rows = student_assignment_results(db, user.id, subject=subject, discipline_id=discipline_id,
                                          limit=21, offset=offset, recent_first=True)
        return dict(items=rows[:20], more=len(rows) > 20, offset=offset)
    if view == 'consultations':
        return {'items': upcoming_consultations(db, user, subject, discipline_id)}
    start = campus_today()
    days = student_days(db, user, start, start + timedelta(days=13), markers=False)
    items = [item for day in days for item in day['items']
             if not item['uid'].startswith(('consultation:', 'campus:', 'vuc:'))
             and (item['discipline_id'] == discipline_id if item.get('discipline_id') is not None
                  else item['subject'] == subject)]
    return dict(items=items, from_date=start.isoformat(), to_date=(start + timedelta(days=13)).isoformat())


@router.get('/{discipline_id}/activity')
def discipline_activity(discipline_id: RecordId, view: Activity, offset: int = Query(0, ge=0, le=2147483647),
                        user=Depends(require_student), db: Session = Depends(get_db)):
    row = checked_discipline(db, discipline_id)
    return activity_rows(db, user, view, row.title, row.id, offset)


@router.get('/personal/{course_id}/activity')
def personal_activity(course_id: RecordId, view: Activity, offset: int = Query(0, ge=0, le=2147483647),
                      user=Depends(require_student), db: Session = Depends(get_db)):
    course = db.scalar(select(Course).where(Course.id == course_id, Course.student_id == user.id))
    if course is None:
        raise HTTPException(404, 'Дисциплина не найдена')
    return activity_rows(db, user, view, course.subject, course.discipline_id, offset)
