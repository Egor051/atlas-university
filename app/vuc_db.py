"""Admission records for the reserve-training model of the campus VUC."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class VucProgram(Base):
    __tablename__ = 'vuc_programs'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(180), unique=True)
    category: Mapped[str] = mapped_column(String(24))
    outcome: Mapped[str] = mapped_column(Text)
    duration_months: Mapped[int | None]
    academic_link: Mapped[str] = mapped_column(Text)
    requirements: Mapped[str] = mapped_column(Text)
    selection: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(12))
    source_title: Mapped[str] = mapped_column(String(240))
    source_url: Mapped[str] = mapped_column(String(1000))
    verified_on: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(default=1)


def program_data(row):
    return dict(
        id=row.id, title=row.title, category=row.category, outcome=row.outcome,
        duration_months=row.duration_months, academic_link=row.academic_link,
        requirements=row.requirements, selection=row.selection, state=row.state,
        source_title=row.source_title, source_url=row.source_url,
        verified_on=row.verified_on.isoformat() if row.verified_on else None, version=row.version,
    )


class VucCampaign(Base):
    __tablename__ = 'vuc_campaigns'
    __table_args__ = (
        UniqueConstraint('program_id', 'academic_year', 'title', name='uq_vuc_campaign_round'),
        Index('ix_vuc_campaign_year', 'state', 'academic_year', 'id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey('vuc_programs.id'))
    academic_year: Mapped[int]
    title: Mapped[str] = mapped_column(String(180))
    state: Mapped[str] = mapped_column(String(12))
    opens_on: Mapped[date | None] = mapped_column(Date)
    closes_on: Mapped[date | None] = mapped_column(Date)
    intake_enabled: Mapped[bool]
    seats: Mapped[int | None]
    documents: Mapped[list] = mapped_column(JSON)
    procedure: Mapped[str] = mapped_column(Text)
    requirements: Mapped[str] = mapped_column(Text)
    stages: Mapped[dict] = mapped_column(JSON)
    source_title: Mapped[str] = mapped_column(String(240))
    source_url: Mapped[str] = mapped_column(String(1000))
    verified_on: Mapped[date | None] = mapped_column(Date)
    program_snapshot: Mapped[dict | None] = mapped_column(JSON, default=None)
    version: Mapped[int] = mapped_column(default=1)
    program: Mapped[VucProgram] = relationship()


class VucApplication(Base):
    __tablename__ = 'vuc_applications'
    __table_args__ = (
        UniqueConstraint('student_id', 'campaign_id', name='uq_vuc_application_student_campaign'),
        Index('ix_vuc_application_queue', 'status', 'updated_at', 'id'),
        Index('ix_vuc_application_campaign', 'campaign_id', 'id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    campaign_id: Mapped[int] = mapped_column(ForeignKey('vuc_campaigns.id'))
    status: Mapped[str] = mapped_column(String(24))
    next_action: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    campaign: Mapped[VucCampaign] = relationship()


class VucApplicationEvent(Base):
    __tablename__ = 'vuc_application_events'
    __table_args__ = (Index('ix_vuc_application_event', 'application_id', 'id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey('vuc_applications.id'))
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(12))
    message: Mapped[str] = mapped_column(Text)
    basis_ref: Mapped[str] = mapped_column(String(160), default='')
    basis_on: Mapped[date | None] = mapped_column(Date)
    contract_ref: Mapped[str] = mapped_column(String(160), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
