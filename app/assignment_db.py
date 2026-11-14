"""Append-only copies of submitted work and its private attachments."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class SubmissionAttempt(Base):
    __tablename__ = 'assignment_attempts'
    __table_args__ = (UniqueConstraint('submission_id', 'version', name='uq_assignment_attempt_version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey('learning_submissions.id'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    version: Mapped[int]
    number: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(500))
    completed: Mapped[bool] = mapped_column(default=False)
    late: Mapped[bool] = mapped_column(default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubmissionAttachment(Base):
    __tablename__ = 'assignment_attachments'
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey('assignment_attempts.id'), index=True)
    name: Mapped[str] = mapped_column(String(180))
    size: Mapped[int]
    content: Mapped[bytes] = mapped_column(LargeBinary)
