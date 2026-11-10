"""Additive contest-hardening storage. No connections or seeding on import."""
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class PersonalDraft(Base):
    __tablename__ = 'personal_drafts'
    __table_args__ = (UniqueConstraint('user_id','name',name='uq_personal_draft_owner_name'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    name: Mapped[str] = mapped_column(String(100))
    values_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),index=True)

class WriteQuota(Base):
    __tablename__ = 'write_quotas'
    __table_args__ = (UniqueConstraint('user_id','bucket','window',name='uq_write_quota_window'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'))
    bucket: Mapped[str] = mapped_column(String(24))
    window: Mapped[str] = mapped_column(String(20),index=True)
    count: Mapped[int] = mapped_column(Integer,default=1)

class FollowupReceipt(Base):
    __tablename__ = 'request_followup_receipts'
    __table_args__ = (UniqueConstraint('user_id','request_id','key',name='uq_followup_owner_request_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'))
    request_id: Mapped[int] = mapped_column(ForeignKey('document_requests.id',ondelete='CASCADE'))
    key: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[str] = mapped_column(String(64))
