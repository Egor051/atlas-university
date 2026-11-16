"""Academic groups, teaching operations and the approved group timetable."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .university_db import Discipline, Teacher, TeachingAssignment


class AcademicGroup(Base):
    __tablename__ = 'academic_groups'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    program: Mapped[str] = mapped_column(String(180))
    capacity: Mapped[int]
    accessible: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)


class GroupMember(Base):
    __tablename__ = 'academic_group_members'
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('academic_groups.id'), index=True)
    version: Mapped[int] = mapped_column(default=1)
    subgroup_id: Mapped[int | None] = mapped_column(ForeignKey('academic_subgroups.id'))


class AcademicSubgroup(Base):
    __tablename__ = 'academic_subgroups'
    __table_args__ = (UniqueConstraint('group_id', 'code', name='uq_academic_subgroup_code'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('academic_groups.id'), index=True)
    code: Mapped[str] = mapped_column(String(60))
    capacity: Mapped[int]
    version: Mapped[int] = mapped_column(default=1)


class AcademicTerm(Base):
    __tablename__ = 'academic_terms'
    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year: Mapped[int]
    number: Mapped[int]
    group_id: Mapped[int | None] = mapped_column(ForeignKey('academic_groups.id'), index=True)
    program: Mapped[str] = mapped_column(String(180), default='')
    starts_on: Mapped[date] = mapped_column(Date, index=True)
    ends_on: Mapped[date] = mapped_column(Date)
    weekdays: Mapped[str] = mapped_column(String(7))
    periods: Mapped[list] = mapped_column(JSON)
    legacy: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(default=1)


class AcademicDayRule(Base):
    __tablename__ = 'academic_day_rules'
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey('academic_groups.id'), index=True)
    program: Mapped[str] = mapped_column(String(180), default='')
    starts_on: Mapped[date] = mapped_column(Date, index=True)
    ends_on: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(130), default='')
    source: Mapped[str] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(default=1)


class TeachingLoad(Base):
    __tablename__ = 'academic_teaching_loads'
    __table_args__ = (UniqueConstraint('group_id', 'discipline_id', name='uq_academic_group_discipline'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('academic_groups.id'))
    assignment_id: Mapped[int] = mapped_column(ForeignKey('university_teaching_assignments.id'), index=True)
    discipline_id: Mapped[int] = mapped_column(ForeignKey('university_disciplines.id'), index=True)
    version: Mapped[int] = mapped_column(default=1)
    group: Mapped[AcademicGroup] = relationship()
    assignment: Mapped[TeachingAssignment] = relationship()
    discipline: Mapped[Discipline] = relationship()


class Classroom(Base):
    __tablename__ = 'academic_classrooms'
    id: Mapped[int] = mapped_column(primary_key=True)
    building: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(80), unique=True)
    capacity: Mapped[int]
    kind: Mapped[str] = mapped_column(String(20))
    equipment: Mapped[str] = mapped_column(String(160), default='')
    accessible: Mapped[bool] = mapped_column(default=False)
    available: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)


class ScheduledClass(Base):
    __tablename__ = 'academic_classes'
    __table_args__ = (
        Index('ix_academic_classes_room_start', 'room_id', 'starts_at'),
        Index('ix_academic_classes_teacher_start', 'teacher_id', 'starts_at'),
        Index('ix_academic_classes_group_start', 'group_id', 'starts_at'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey('academic_teaching_loads.id'), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('academic_groups.id'))
    teacher_id: Mapped[int] = mapped_column(ForeignKey('university_teachers.id'))
    room_id: Mapped[int] = mapped_column(ForeignKey('academic_classrooms.id'))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(20))
    equipment: Mapped[str] = mapped_column(String(160), default='')
    note: Mapped[str] = mapped_column(String(300), default='')
    series: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), default='active')
    version: Mapped[int] = mapped_column(default=1)
    subgroup_id: Mapped[int | None] = mapped_column(ForeignKey('academic_subgroups.id'))
    student_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str] = mapped_column(String(180), default='', server_default='')
    calendar_exception: Mapped[str] = mapped_column(String(300), default='', server_default='')
    change_action: Mapped[str] = mapped_column(String(20), default='', server_default='')
    previous: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    previous_day: Mapped[date | None] = mapped_column(Date, index=True)
    load: Mapped[TeachingLoad] = relationship()
    teacher: Mapped[Teacher] = relationship()
    room: Mapped[Classroom] = relationship()
    subgroup: Mapped[AcademicSubgroup | None] = relationship()


class LegacyClassOverride(Base):
    __tablename__ = 'legacy_class_overrides'
    __table_args__ = (UniqueConstraint('lesson_id', 'original_day', name='uq_legacy_occurrence'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey('lessons.id'))
    original_day: Mapped[date] = mapped_column(Date, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    previous_day: Mapped[date] = mapped_column(Date, index=True)
    start: Mapped[str] = mapped_column(String(5))
    end: Mapped[str] = mapped_column(String(5))
    room: Mapped[str] = mapped_column(String(80))
    teacher: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(300))
    calendar_exception: Mapped[str] = mapped_column(String(300), default='')
    version: Mapped[int]
    change_action: Mapped[str] = mapped_column(String(20))
    previous: Mapped[dict] = mapped_column(JSON)


class ScheduleDismissal(Base):
    __tablename__ = 'schedule_dismissals'
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    change_key: Mapped[str] = mapped_column(String(100), primary_key=True)


class ScheduleCalendarAlert(Base):
    __tablename__ = 'schedule_calendar_alerts'
    __table_args__ = (Index('ix_schedule_calendar_alert_group_start', 'group_id', 'starts_on'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('academic_groups.id'))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    days: Mapped[list] = mapped_column(JSON)


class ScheduleChange(Base):
    __tablename__ = 'academic_schedule_changes'
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey('academic_classes.id'), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    state: Mapped[str] = mapped_column(String(20), index=True)
    action: Mapped[str] = mapped_column(String(20))
    payload: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GroupWork(Base):
    __tablename__ = 'academic_group_work'
    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey('academic_teaching_loads.id'), index=True)
    title: Mapped[str] = mapped_column(String(180))
    instructions: Mapped[str] = mapped_column(Text)
    due: Mapped[date] = mapped_column(Date)
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20), default='published', server_default='published')
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy_json: Mapped[str] = mapped_column(Text, default='{}', server_default='{}')


class WorkMaterial(Base):
    __tablename__ = 'academic_work_materials'
    work_id: Mapped[int] = mapped_column(ForeignKey('academic_group_work.id'), primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey('teaching_materials.id'), primary_key=True, index=True)


class WorkDelivery(Base):
    __tablename__ = 'academic_work_deliveries'
    deadline_id: Mapped[int] = mapped_column(ForeignKey('deadlines.id'), primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey('academic_group_work.id'), index=True)
    extended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    individual_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(default=True, server_default='true')


class WorkFeedback(Base):
    __tablename__ = 'academic_work_feedback'
    __table_args__ = (Index('ix_academic_feedback_submission', 'submission_id', 'submitted_version', 'id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey('learning_submissions.id'))
    submitted_version: Mapped[int]
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    score: Mapped[int | None]
    comment: Mapped[str] = mapped_column(Text)
    remarks: Mapped[str] = mapped_column(Text, default='', server_default='')
    previous_score: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(String(20), default='comment', server_default='comment')
    extended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TeacherConsultation(Base):
    __tablename__ = 'academic_teacher_consultations'
    slot_id: Mapped[int] = mapped_column(ForeignKey('consultation_slots.id'), primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey('academic_teaching_loads.id'), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationEvent(Base):
    __tablename__ = 'workspace_operation_events'
    __table_args__ = (Index('ix_workspace_events_area_object', 'area', 'object_id', 'id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[str] = mapped_column(String(24))
    object_id: Mapped[int]
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(30))
    before: Mapped[str] = mapped_column(Text)
    after: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkspaceNotice(Base):
    __tablename__ = 'workspace_notices'
    __table_args__ = (Index('ix_workspace_notice_owner_read', 'user_id', 'is_read', 'id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(String(120))
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TableImport(Base):
    __tablename__ = 'workspace_table_imports'
    __table_args__ = (UniqueConstraint('actor_id', 'fingerprint', name='uq_workspace_import_actor_digest'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    dataset: Mapped[str] = mapped_column(String(24))
    scope: Mapped[int]
    fingerprint: Mapped[str] = mapped_column(String(64))
    count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
