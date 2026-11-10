"""Personal portfolio for the fictional contest campus."""
from datetime import date, datetime
from sqlalchemy import ForeignKey, String, Text, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .storage_guards import new_record_token


class PortfolioItem(Base):
    __tablename__ = 'portfolio_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    record_token: Mapped[str] = mapped_column(String(32), default=new_record_token, server_default='', unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(500), default='')
    day: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
