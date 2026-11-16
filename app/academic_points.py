"""Point awards, explicit assignment corrections and the grade projection."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, cast, literal, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, Grade, User, utc_now
from .storage_guards import lock_owner
from .university_db import Discipline


class PointAward(Base):
    __tablename__ = 'academic_point_awards'
    __table_args__ = (
        CheckConstraint('points > 0', name='ck_academic_award_positive'),
        UniqueConstraint('student_id', 'source_kind', 'source_id', name='uq_academic_award_source'),
        Index('ix_academic_awards_grade', 'grade_id', 'id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey('grades.id'))
    discipline_id: Mapped[int | None] = mapped_column(ForeignKey('university_disciplines.id'))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    class_id: Mapped[int | None] = mapped_column(ForeignKey('academic_classes.id'))
    points: Mapped[int]
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssignmentPointCorrection(Base):
    __tablename__ = 'academic_assignment_point_corrections'
    __table_args__ = (
        UniqueConstraint('feedback_id', 'student_id', name='uq_assignment_correction_review_student'),
        Index('ix_assignment_corrections_student_work', 'student_id', 'work_id', 'id'),
        Index('ix_assignment_corrections_grade', 'grade_id', 'id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    work_id: Mapped[int] = mapped_column(ForeignKey('academic_group_work.id'), index=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey('grades.id'))
    feedback_id: Mapped[int] = mapped_column(ForeignKey('academic_work_feedback.id'))
    class_id: Mapped[int | None] = mapped_column(ForeignKey('academic_classes.id'))
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    previous_points: Mapped[int]
    corrected_points: Mapped[int]
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def import_opening_balances(db):
    """Import the recorded balance and leave earlier, unknown events unspecified."""
    grades, awards = Grade.__table__, PointAward.__table__
    existing = select(awards.c.id).where(awards.c.grade_id == grades.c.id).exists()
    db.execute(awards.insert().from_select(
        ['student_id', 'grade_id', 'points', 'source_kind', 'source_id', 'reason'],
        select(grades.c.student_id, grades.c.id, grades.c.current,
               literal('opening'), cast(grades.c.id, String), literal('')).where(grades.c.current > 0, ~existing),
    ))


def grade_record(db, student_id, subject):
    return db.scalar(select(Grade).where(Grade.student_id == student_id, Grade.subject == subject).order_by(Grade.id).limit(1))


def ensure_grade(db, student_id, discipline_id, actor_id):
    discipline = db.get(Discipline, discipline_id)
    if discipline is None:
        raise HTTPException(404, 'Дисциплина не найдена')
    grade = grade_record(db, student_id, discipline.title)
    if grade is None:
        teacher = db.get(User, actor_id)
        grade = Grade(student_id=student_id, subject=discipline.title, teacher=teacher.full_name,
                      kind='', exam_kind='', assessment='', max_grade=0, color='violet', trend=0, version=0)
        db.add(grade)
        db.flush()
    return grade


def apply_point_delta(grade, delta):
    total = max(0, grade.current or 0) + delta
    if not 0 <= total <= 2147483647:
        raise HTTPException(422, 'Итоговое количество баллов выходит за допустимые пределы')
    grade.current = total
    grade.trend = delta
    grade.version += 1


def award_points(db, *, student_id, discipline_id, points, source_kind, source_id, actor_id, reason='', class_id=None):
    """Post an award with its unique source and update the grade in the same transaction."""
    if type(points) is not int or points < 1:
        raise HTTPException(422, 'Для начисления требуется положительное число баллов')
    lock_owner(db, student_id)
    source_id = str(source_id)
    previous = db.scalar(select(PointAward).where(PointAward.student_id == student_id,
                         PointAward.source_kind == source_kind, PointAward.source_id == source_id))
    if previous:
        if previous.points != points or previous.discipline_id != discipline_id or previous.class_id != class_id:
            raise HTTPException(409, 'По этому основанию баллы уже начислены')
        return previous
    grade = ensure_grade(db, student_id, discipline_id, actor_id)
    apply_point_delta(grade, points)
    award = PointAward(student_id=student_id, grade_id=grade.id, discipline_id=discipline_id, actor_id=actor_id,
                       class_id=class_id, points=points, source_kind=source_kind,
                       source_id=source_id, reason=reason, created_at=utc_now())
    db.add(award)
    return award


def correct_assignment_points(db, *, student_id, discipline_id, work_id, feedback_id, points,
                              actor_id, reason, class_id):
    """Change only this work's contribution. Original awards remain in the ledger."""
    lock_owner(db, student_id)
    previous = db.scalar(select(AssignmentPointCorrection).where(AssignmentPointCorrection.student_id == student_id,
                         AssignmentPointCorrection.work_id == work_id).order_by(AssignmentPointCorrection.id.desc()).limit(1))
    if previous is not None:
        old_points, grade_id = previous.corrected_points, previous.grade_id
    else:
        award = db.scalar(select(PointAward).where(PointAward.student_id == student_id,
                          PointAward.source_kind == 'assignment', PointAward.source_id == str(work_id)))
        old_points, grade_id = (award.points, award.grade_id) if award else (0, None)
    if old_points == points:
        return
    grade = db.get(Grade, grade_id) if grade_id else ensure_grade(db, student_id, discipline_id, actor_id)
    apply_point_delta(grade, points - old_points)
    db.add(AssignmentPointCorrection(student_id=student_id, work_id=work_id, grade_id=grade.id, feedback_id=feedback_id,
                                     class_id=class_id, actor_id=actor_id, previous_points=old_points,
                                     corrected_points=points, reason=reason, created_at=utc_now()))


def award_data(row, date_iso):
    return dict(id=row.id, points=row.points, source_kind=row.source_kind, source_id=row.source_id,
                reason=row.reason, class_id=row.class_id, created_at=date_iso(row.created_at))


def correction_data(row, date_iso):
    return dict(id=row.id, points=row.corrected_points - row.previous_points, source_kind='assignment_correction',
                source_id=str(row.work_id), reason=row.reason, class_id=row.class_id, created_at=date_iso(row.created_at),
                previous_points=row.previous_points, corrected_points=row.corrected_points, feedback_id=row.feedback_id)
