"""Positive point awards and the projection used by the existing grade API."""
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
    total = max(0, grade.current or 0) + points
    if total > 2147483647:
        raise HTTPException(422, 'Превышен предел общего количества баллов')
    grade.current = total
    grade.trend = points
    grade.version += 1
    award = PointAward(student_id=student_id, grade_id=grade.id, discipline_id=discipline_id, actor_id=actor_id,
                       class_id=class_id, points=points, source_kind=source_kind,
                       source_id=source_id, reason=reason, created_at=utc_now())
    db.add(award)
    return award


def award_data(row, date_iso):
    return dict(id=row.id, points=row.points, source_kind=row.source_kind, source_id=row.source_id,
                reason=row.reason, class_id=row.class_id, created_at=date_iso(row.created_at))
