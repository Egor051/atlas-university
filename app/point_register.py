"""Student point postings and confirmed results, including their original sources."""
from dataclasses import dataclass

from sqlalchemy import String, cast, literal, or_, select
from sqlalchemy.orm import aliased

from .academic_points import (POINT_KINDS, AssignmentPointCorrection, PointAward,
                              manual_correction_query)
from .assignment_workflow import iso, work_policy
from .db import CAMPUS_TZ, Deadline, Grade, Notification, User
from .learning_db import AssignmentSubmission
from .schedule_calendar import KIND, occurrence_kind
from .session_security import as_utc
from .university_db import Discipline
from .workspace_db import GroupWork, ScheduledClass, TeachingLoad, WorkDelivery, WorkFeedback


@dataclass(frozen=True)
class WorkSource:
    deadline_id: int
    discipline_id: int
    subject: str
    title: str
    policy: dict


def work_sources(db, student_id):
    rows = db.execute(
        select(GroupWork, Deadline.id, Discipline.id, Discipline.title).select_from(Deadline)
        .join(WorkDelivery).join(GroupWork).join(TeachingLoad).join(Discipline)
        .where(Deadline.student_id == student_id).order_by(Deadline.id)
    )
    works = {}
    for work, deadline_id, discipline_id, subject in rows:
        works.setdefault(str(work.id), WorkSource(deadline_id, discipline_id, subject, work.title, work_policy(work)))
    return works


def posted_work_reviews(db, student_id):
    """Read own reviews and team reviews actually delivered to this recipient."""
    issued = aliased(WorkDelivery)
    recipient = aliased(Deadline)
    notice_key = (literal('work-review:') + cast(WorkFeedback.id, String) + literal(':') + cast(recipient.id, String))
    notified = select(Notification.id).where(
        Notification.student_id == student_id, Notification.event_key == notice_key,
    ).exists()
    return db.execute(
        select(WorkFeedback, WorkDelivery.work_id, AssignmentSubmission.student_id, User.full_name)
        .select_from(WorkFeedback).join(AssignmentSubmission)
        .join(WorkDelivery, WorkDelivery.deadline_id == AssignmentSubmission.deadline_id)
        .join(issued, issued.work_id == WorkDelivery.work_id)
        .join(recipient, recipient.id == issued.deadline_id)
        .join(User, User.id == WorkFeedback.author_id)
        .where(recipient.student_id == student_id, WorkFeedback.action.in_(('accept', 'grade')),
               WorkFeedback.score.is_not(None), or_(AssignmentSubmission.student_id == student_id, notified))
        .order_by(WorkFeedback.id)
    )


def local_day(value):
    return as_utc(value).astimezone(CAMPUS_TZ).date().isoformat() if value else None


def work_activity(work):
    policy = work.policy
    return dict(title=work.title, kind=policy['kind'],
                kind_label=policy['custom_kind'] or POINT_KINDS.get(policy['kind'], POINT_KINDS['other']),
                max_points=policy['max_points'])


def award_activity(award, work, meeting):
    if award.source_kind == 'opening':
        return dict(title='Остаток из прежней ведомости', kind='opening', kind_label=POINT_KINDS['opening'], max_points=None)
    if award.source_kind == 'assignment':
        original = work_activity(work) if work else dict(
            title=award.reason or 'Проверенная работа', kind='other', kind_label=POINT_KINDS['other'], max_points=None,
        )
        kind = award.kind or original['kind']
        return dict(title=award.title or award.reason or original['title'], kind=kind,
                    kind_label=award.custom_kind or (POINT_KINDS[kind] if award.kind else original['kind_label']),
                    max_points=award.max_points if award.max_points is not None else original['max_points'])
    kind = award.kind or (occurrence_kind(meeting.kind) if meeting else 'other')
    class_title = (meeting.title or meeting.note or KIND[occurrence_kind(meeting.kind)]) if meeting else ''
    return dict(title=award.title or class_title or 'Начисление преподавателя', kind=kind,
                kind_label=POINT_KINDS.get(kind, KIND.get(kind, POINT_KINDS['other'])), max_points=award.max_points)


def register_row(entry, grade, *, key, activity, teacher, entry_type, points, result, note='',
                 discipline_id=None, work=None, meeting=None, previous_points=None, corrected_points=None):
    return dict(
        id=key, grade_id=grade.id if grade else None,
        discipline_id=discipline_id if discipline_id is not None else work.discipline_id if work else None,
        subject=grade.subject if grade else work.subject,
        day=local_day(entry.created_at), created_at=iso(entry.created_at), **activity,
        teacher=teacher or '', points=points, discipline_total=grade.current if grade and grade.current is not None else 0,
        result=result, note=note, entry_type=entry_type, previous_points=previous_points, corrected_points=corrected_points,
        class_id=meeting.id if meeting else None, class_day=local_day(meeting.starts_at) if meeting else None,
        assignment_id=work.deadline_id if work else None,
    )


def student_point_register(db, student_id):
    grades = {row.id: row for row in db.scalars(select(Grade).where(Grade.student_id == student_id).order_by(Grade.id))}
    by_subject = {}
    for grade in grades.values():
        by_subject.setdefault(grade.subject, grade)
    awards = db.execute(
        select(PointAward, User.full_name).outerjoin(User, User.id == PointAward.actor_id)
        .where(PointAward.student_id == student_id).order_by(PointAward.id)
    ).all()
    adjustments = db.execute(
        select(AssignmentPointCorrection, User.full_name).join(User, User.id == AssignmentPointCorrection.actor_id)
        .where(AssignmentPointCorrection.student_id == student_id)
    ).all()
    works = work_sources(db, student_id)
    class_ids = {row.class_id for row, _ in awards + adjustments}
    reviews = posted_work_reviews(db, student_id).all()
    class_ids.update(works[str(work_id)].policy['class_id'] for review, work_id, _, _ in reviews if review.score == 0)
    meetings = {row.id: row for row in db.scalars(select(ScheduledClass).where(ScheduledClass.id.in_(class_ids - {None})))}
    posted = {}
    reviews_by_id = {}
    items = []
    for review, work_id, submitter, teacher in reviews:
        work = works[str(work_id)]
        if submitter != student_id and work.policy['award_mode'] != 'all':
            continue
        posted.setdefault((str(work_id), review.score, review.author_id), review)
        reviews_by_id[review.id] = review
        if review.score == 0:
            items.append(register_row(
                review, by_subject.get(work.subject), key=f'result-{review.id}', work=work,
                activity=work_activity(work), teacher=teacher, entry_type='result', points=0,
                result='Подтверждённый результат', note=review.remarks or review.comment,
                meeting=meetings.get(work.policy['class_id']),
            ))
    award_by_work = {}
    awards_by_id = {}
    discipline_ids = {work.subject: work.discipline_id for work in works.values()}
    for award, _ in awards:
        if award.discipline_id is not None:
            discipline_ids[grades[award.grade_id].subject] = award.discipline_id
    for award, teacher in awards:
        grade = grades[award.grade_id]
        work = works.get(award.source_id) if award.source_kind == 'assignment' else None
        meeting = meetings.get(award.class_id)
        activity = award_activity(award, work, meeting)
        awards_by_id[award.id] = activity
        entry_type, result, note = 'award', 'Начислено преподавателем', award.reason
        if award.source_kind == 'assignment':
            award_by_work[award.source_id] = activity
            review = (reviews_by_id.get(award.review_id) if award.review_id is not None else
                      posted.get((award.source_id, award.points, award.actor_id)))
            result, note = 'Начислено за проверенную работу', (review.remarks or review.comment) if review else ''
        elif award.source_kind == 'opening':
            entry_type, result = 'opening', 'Перенесено из прежней ведомости'
            note = 'Детализация отдельных начислений отсутствует.'
        items.append(register_row(
            award, grade, key=f'award-{award.id}', activity=activity, teacher=teacher,
            entry_type=entry_type, points=award.points, result=result, note=note, work=work, meeting=meeting,
            discipline_id=award.discipline_id or discipline_ids.get(grade.subject),
        ))
    for correction, teacher in adjustments:
        grade = grades[correction.grade_id]
        work = works.get(str(correction.work_id))
        activity = award_by_work.get(str(correction.work_id))
        if activity is None:
            activity = work_activity(work) if work else dict(
                title='Проверенная работа', kind='other', kind_label=POINT_KINDS['other'], max_points=None,
            )
        items.append(register_row(
            correction, grade, key=f'assignment-correction-{correction.id}', activity=activity, teacher=teacher,
            entry_type='correction', points=correction.corrected_points - correction.previous_points,
            result='Корректировка оценки за работу', note=correction.reason, work=work,
            meeting=meetings.get(correction.class_id), discipline_id=discipline_ids.get(grade.subject),
            previous_points=correction.previous_points, corrected_points=correction.corrected_points,
        ))
    for correction, award, teacher in db.execute(manual_correction_query(student_id)):
        items.append(register_row(
            correction, grades[award.grade_id], key=f'manual-correction-{correction.id}',
            activity=awards_by_id[award.id], teacher=teacher,
            entry_type='correction', points=correction.corrected_points - correction.previous_points,
            result='Корректировка начисления', note=correction.reason, meeting=meetings.get(award.class_id),
            discipline_id=award.discipline_id,
            previous_points=correction.previous_points, corrected_points=correction.corrected_points,
        ))
    return {'items': sorted(items, key=lambda row: (row['created_at'] or '', row['id']), reverse=True)}
