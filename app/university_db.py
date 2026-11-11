"""Directory, teaching materials and participant-owned direct conversations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, User


class Faculty(Base):
    __tablename__ = 'university_faculties'
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    directions: Mapped[str] = mapped_column(Text)


class Department(Base):
    __tablename__ = 'university_departments'
    __table_args__ = (UniqueConstraint('faculty_id', 'slug', name='uq_university_department_slug'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey('university_faculties.id'))
    slug: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    directions: Mapped[str] = mapped_column(Text)
    faculty: Mapped[Faculty] = relationship()


class Discipline(Base):
    __tablename__ = 'university_disciplines'
    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey('university_departments.id'), index=True)
    title: Mapped[str] = mapped_column(String(130))
    description: Mapped[str] = mapped_column(Text)
    department: Mapped[Department] = relationship()


class Teacher(Base):
    __tablename__ = 'university_teachers'
    __table_args__ = (UniqueConstraint('department_id', 'slug', name='uq_university_teacher_slug'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey('university_departments.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True)
    slug: Mapped[str] = mapped_column(String(60))
    position: Mapped[str] = mapped_column(String(130))
    academic: Mapped[str] = mapped_column(Text)
    department: Mapped[Department] = relationship()
    user: Mapped[User] = relationship()


class TeachingAssignment(Base):
    __tablename__ = 'university_teaching_assignments'
    __table_args__ = (UniqueConstraint('teacher_id', 'discipline_id', name='uq_university_teacher_discipline'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey('university_teachers.id'))
    discipline_id: Mapped[int] = mapped_column(ForeignKey('university_disciplines.id'), index=True)
    teacher: Mapped[Teacher] = relationship()
    discipline: Mapped[Discipline] = relationship()


class TeachingSlot(Base):
    __tablename__ = 'university_teaching_slots'
    __table_args__ = (CheckConstraint('weekday BETWEEN 0 AND 6', name='ck_teaching_slot_weekday'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('university_teaching_assignments.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    weekday: Mapped[int]
    starts: Mapped[str] = mapped_column(String(5))
    ends: Mapped[str] = mapped_column(String(5))
    room: Mapped[str] = mapped_column(String(100))
    assignment: Mapped[TeachingAssignment] = relationship()


class TeachingMaterial(Base):
    __tablename__ = 'teaching_materials'
    __table_args__ = ({'sqlite_autoincrement': True},)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('university_teaching_assignments.id'), index=True)
    publisher_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(24), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(String(600))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    assignment: Mapped[TeachingAssignment] = relationship()


class DirectContact(Base):
    __tablename__ = 'direct_contacts'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    label: Mapped[str] = mapped_column(String(180))


class DirectDialog(Base):
    __tablename__ = 'direct_dialogs'
    __table_args__ = (
        UniqueConstraint('student_id', 'contact_id', name='uq_direct_dialog_participants'),
        CheckConstraint('student_id <> contact_id', name='ck_direct_dialog_distinct_users'),
        Index('ix_direct_dialog_student_updated', 'student_id', 'updated_at', 'id'),
        Index('ix_direct_dialog_contact_updated', 'contact_id', 'updated_at', 'id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    contact_id: Mapped[int] = mapped_column(ForeignKey('direct_contacts.user_id'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DirectMessage(Base):
    __tablename__ = 'direct_messages'
    __table_args__ = (Index('ix_direct_message_dialog_id', 'dialog_id', 'id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey('direct_dialogs.id'))
    sender_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_id: Mapped[int | None] = mapped_column(ForeignKey('notifications.id', ondelete='SET NULL'), unique=True)
