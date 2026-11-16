"""Private evidence, per-lesson decisions and metadata-only audit."""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class AbsenceCertificate(Base):
    __tablename__ = 'absence_certificates'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AbsenceCertificateFile(Base):
    __tablename__ = 'absence_certificate_files'
    certificate_id: Mapped[int] = mapped_column(ForeignKey('absence_certificates.id', ondelete='CASCADE'), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)


class AbsenceCertificateNote(Base):
    __tablename__ = 'absence_certificate_notes'
    certificate_id: Mapped[int] = mapped_column(ForeignKey('absence_certificates.id', ondelete='CASCADE'), primary_key=True)
    # Entry zero is the student's explanation. Other entries are decision IDs.
    entry: Mapped[int] = mapped_column(primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)


class AbsenceCertificateReview(Base):
    __tablename__ = 'absence_certificate_reviews'
    __table_args__ = (
        UniqueConstraint('certificate_id', 'occurrence', name='uq_absence_certificate_occurrence'),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name='ck_absence_review_status'),
        Index('ix_absence_reviews_attendance_status', 'attendance_id', 'status'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey('absence_certificates.id', ondelete='CASCADE'))
    attendance_id: Mapped[int] = mapped_column(ForeignKey('learning_attendance.id'))
    occurrence: Mapped[str] = mapped_column(String(48))
    day: Mapped[date]
    start: Mapped[str] = mapped_column(String(5))
    end: Mapped[str] = mapped_column(String(5))
    discipline: Mapped[str] = mapped_column(String(180))
    kind_label: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default='pending')
    notified_teacher_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired: Mapped[bool] = mapped_column(default=False)


class AbsenceCertificateAudit(Base):
    __tablename__ = 'absence_certificate_audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey('absence_certificates.id', ondelete='CASCADE'), index=True)
    review_id: Mapped[int | None] = mapped_column(ForeignKey('absence_certificate_reviews.id', ondelete='CASCADE'))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
