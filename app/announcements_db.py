"""Campus-wide editorial publications, independent from personal notifications."""
from datetime import datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, User, utc_now
from .workspace_db import AcademicGroup


class Announcement(Base):
    __tablename__ = 'campus_announcements'
    __table_args__ = (Index('ix_announcements_status_published', 'status', 'published_at', 'id'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    group_id: Mapped[int | None] = mapped_column(ForeignKey('academic_groups.id'))
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(20))
    audience: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    pinned: Mapped[bool]
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fixture_key: Mapped[str | None] = mapped_column(String(30), unique=True)
    author: Mapped[User] = relationship()
    group: Mapped[AcademicGroup | None] = relationship()


def seed_announcements(db):
    """Make example publications available in the demo, once per database."""
    author_id = db.scalar(select(User.id).where(User.login == 'dean.demo', User.role == 'staff'))
    if author_id is None:
        return
    existing = set(db.scalars(select(Announcement.fixture_key).where(Announcement.fixture_key.is_not(None))))
    fixtures = [
        ('support', 'Консультации преподавателей',
         'В разделе «Консультации» можно посмотреть свободные часы и записаться на встречу с преподавателем. '
         'Если нужно обсудить задание или результаты аттестации, подготовьте вопросы заранее.', 'academic', 'normal'),
        ('deadlines', 'Ближайшие сроки сдачи работ',
         'Проверьте раздел «Задания». В нём собраны сроки, условия сдачи и комментарии преподавателей. '
         'Если требуется уточнение по работе, свяжитесь с преподавателем по дисциплине.', 'deadline', 'important'),
        ('documents', 'Справки в личном кабинете',
         'Документы можно заказать в разделе «Справки». Там указаны сроки подготовки, '
         'ответственные и перечень необходимых сведений.', 'announcement', 'normal'),
    ]
    now = utc_now()
    for age, (key, title, body, category, priority) in enumerate(fixtures):
        if key in existing:
            continue
        published = now - timedelta(days=age)
        db.add(Announcement(author_id=author_id, title=title, body=body, category=category,
                            priority=priority, audience='all', status='published', pinned=key == 'documents',
                            created_at=published, updated_at=published, published_at=published, fixture_key=key))
