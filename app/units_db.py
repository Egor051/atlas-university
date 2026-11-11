"""Student union and education-centre workflows share storage with explicit scopes."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class CenterProgram(Base):
    __tablename__ = 'center_programs'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(180), unique=True)
    description: Mapped[str] = mapped_column(Text)
    requirements: Mapped[str] = mapped_column(Text)
    opens: Mapped[date] = mapped_column(Date)
    closes: Mapped[date] = mapped_column(Date)
    published: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)


class CenterGroup(Base):
    __tablename__ = 'center_groups'
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey('center_programs.id'), index=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    capacity: Mapped[int]
    version: Mapped[int] = mapped_column(default=1)
    program: Mapped[CenterProgram] = relationship()


class UnitPublication(Base):
    __tablename__ = 'unit_publications'
    __table_args__ = (Index('ix_unit_publication_area_kind', 'unit','kind','published','id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    unit: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    group_id: Mapped[int | None] = mapped_column(ForeignKey('center_groups.id'), index=True)
    event_day: Mapped[date | None] = mapped_column(Date)
    capacity: Mapped[int | None]
    published: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UnitCase(Base):
    __tablename__ = 'unit_cases'
    __table_args__ = (Index('ix_unit_cases_owner_area', 'student_id','unit','id'),
                      Index('ix_unit_cases_queue', 'unit','status','id'))
    id: Mapped[int] = mapped_column(primary_key=True)
    unit: Mapped[str] = mapped_column(String(12))
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    program_id: Mapped[int | None] = mapped_column(ForeignKey('center_programs.id'), index=True)
    publication_id: Mapped[int | None] = mapped_column(ForeignKey('unit_publications.id'), index=True)
    sample_checklist: Mapped[str] = mapped_column(Text, default='[]')
    response: Mapped[str] = mapped_column(Text, default='')
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    program: Mapped[CenterProgram | None] = relationship()
    publication: Mapped[UnitPublication | None] = relationship()


class UnitCaseEvent(Base):
    __tablename__ = 'unit_case_events'
    __table_args__ = (Index('ix_unit_case_event_case', 'case_id','id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('unit_cases.id'))
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UnionMembership(Base):
    __tablename__ = 'union_memberships'
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    active: Mapped[bool]
    case_id: Mapped[int] = mapped_column(ForeignKey('unit_cases.id'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CenterEnrollment(Base):
    __tablename__ = 'center_enrollments'
    __table_args__ = (UniqueConstraint('student_id','program_id',name='uq_center_student_program'),
                      Index('ix_center_enrollments_group','group_id','id'))
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    program_id: Mapped[int] = mapped_column(ForeignKey('center_programs.id'))
    group_id: Mapped[int] = mapped_column(ForeignKey('center_groups.id'))
    case_id: Mapped[int] = mapped_column(ForeignKey('unit_cases.id'), unique=True)
    outcome: Mapped[str] = mapped_column(String(20), default='pending')
    comment: Mapped[str] = mapped_column(Text, default='')
    version: Mapped[int] = mapped_column(default=1)
    group: Mapped[CenterGroup] = relationship()
    program: Mapped[CenterProgram] = relationship()


class CenterSession(Base):
    __tablename__ = 'center_sessions'
    __table_args__ = (Index('ix_center_session_group_start','group_id','starts_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('center_groups.id'))
    title: Mapped[str] = mapped_column(String(180))
    room: Mapped[str] = mapped_column(String(100))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)
    group: Mapped[CenterGroup] = relationship()
