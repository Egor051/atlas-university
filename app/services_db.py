"""Additive models for fictional campus services. No university integrations."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, User, CAMPUS_TZ, campus_today, utc_now


class ConsultationSlot(Base):
    __tablename__ = 'consultation_slots'
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_key: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    teacher: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(130))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    room: Mapped[str] = mapped_column(String(100))
    capacity: Mapped[int] = mapped_column(Integer)
    booked_count: Mapped[int] = mapped_column(Integer, default=0)


class ConsultationBooking(Base):
    __tablename__ = 'consultation_bookings'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey('consultation_slots.id'), index=True)
    status: Mapped[str] = mapped_column(String(20), default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupportTicket(Base):
    __tablename__ = 'support_tickets'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    topic: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(20), default='open', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TicketMessage(Base):
    __tablename__ = 'ticket_messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('support_tickets.id', ondelete='CASCADE'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    actor_role: Mapped[str] = mapped_column(String(20))
    actor_name: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CampusEvent(Base):
    __tablename__ = 'campus_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_key: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(String(150))
    capacity: Mapped[int] = mapped_column(Integer)
    registered_count: Mapped[int] = mapped_column(Integer, default=0)


class EventRegistration(Base):
    __tablename__ = 'event_registrations'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey('campus_events.id'), index=True)
    status: Mapped[str] = mapped_column(String(20), default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LibraryBook(Base):
    __tablename__ = 'library_books'
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_key: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    title: Mapped[str] = mapped_column(String(180))
    author: Mapped[str] = mapped_column(String(150))
    subject: Mapped[str] = mapped_column(String(130))
    description: Mapped[str] = mapped_column(Text)
    total: Mapped[int] = mapped_column(Integer)
    available: Mapped[int] = mapped_column(Integer)


class LibraryLoan(Base):
    __tablename__ = 'library_loans'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey('library_books.id'), index=True)
    status: Mapped[str] = mapped_column(String(20), default='active')
    borrowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date] = mapped_column(Date)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FinanceEntry(Base):
    __tablename__ = 'finance_entries'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(180))
    direction: Mapped[str] = mapped_column(String(10))
    amount_kopecks: Mapped[int] = mapped_column(Integer)


class StudentPreference(Base):
    __tablename__ = 'student_preferences'
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=False)
    deadline_reminders: Mapped[bool] = mapped_column(Boolean, default=True)
    compact_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_goal: Mapped[int] = mapped_column(Integer, default=8)


class ServiceIdempotency(Base):
    """A committed operation receipt, scoped to the authenticated actor."""
    __tablename__ = 'service_idempotency'
    __table_args__ = (UniqueConstraint('user_id', 'operation', 'key', name='uq_service_actor_operation_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    operation: Mapped[str] = mapped_column(String(150))
    key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


def seed_services(db):
    """Run under the caller's startup lock; never overwrite user operations."""
    users = db.scalars(select(User).where(User.login.in_(['alina.demo', 'mark.demo']))).all()
    if not users:
        return
    day = campus_today()
    at = lambda days, hour: datetime.combine(day + timedelta(days=days), datetime.min.time(), CAMPUS_TZ).replace(hour=hour).astimezone(timezone.utc)
    slots = [
        ('algorithms', 'М. Орлов', 'Алгоритмы и структуры данных', 2, 'А-301'),
        ('probability', 'Р. Соловьёв', 'Теория вероятностей', 3, 'В-205'),
        ('database', 'Е. Рябинина', 'Базы данных', 4, 'Б-208'),
        ('software', 'А. Громов', 'Инженерия ПО', 2, 'А-412'),
        ('data', 'Д. Зорин', 'Анализ данных', 5, 'В-404'),
        ('office', 'Кира Миронова', 'Учебные вопросы', 1, 'Учебный офис, Б-102'),
    ]
    for key, teacher, subject, offset, room in slots:
        seed_key = 'demo-consultation-' + key
        if db.scalar(select(ConsultationSlot.id).where(ConsultationSlot.seed_key == seed_key)) is None:
            db.add(ConsultationSlot(seed_key=seed_key, teacher=teacher, subject=subject, start_at=at(offset, 15), end_at=at(offset, 16), room=room, capacity=4, booked_count=0))
    events = [
        ('hackathon', 'Кампус-хакатон: сервисы для студентов', 'science', 'Соберите команду и предложите решение учебной задачи. Конкурсный демонстрационный сценарий.', 5, 'Коворкинг, корпус А', 24),
        ('career', 'Мастерская резюме и портфолио', 'career', 'Разбор структуры резюме, рассказа о проектах и подготовки к учебной стажировке.', 3, 'Центр карьеры, Б-210', 20),
        ('science', 'Как подготовить студенческую статью', 'science', 'Исследовательский вопрос, план работы и аккуратные ссылки на источники.', 7, 'Библиотека, читальный зал', 16),
        ('sport', 'Студенческая прогулка и спортивный час', 'sport', 'Открытая встреча для знакомства и отдыха после занятий.', 4, 'Спортивный зал, корпус В', 30),
        ('volunteer', 'Встреча волонтёрского клуба', 'community', 'Знакомство с направлениями добровольческих проектов кампуса.', 8, 'Студенческий центр, А-105', 15),
        ('mobility', 'Академическая мобильность: первые шаги', 'academic', 'Как собрать учебный план обмена и сформулировать вопросы координатору.', 10, 'Онлайн · ссылка не предоставляется в концепте', 40),
    ]
    for key, title, category, description, offset, location, capacity in events:
        seed_key = 'demo-event-' + key
        if db.scalar(select(CampusEvent.id).where(CampusEvent.seed_key == seed_key)) is None:
            db.add(CampusEvent(seed_key=seed_key, title=title, category=category, description=description, start_at=at(offset, 17), end_at=at(offset, 19), location=location, capacity=capacity, registered_count=0))
    # Fixed, additive contest fixtures. Restarts never move a booked event or
    # reset its capacity/history. The two-day buffer means that even late on
    # 28 November a student can still book a genuinely future event or slot.
    existing_slots = set(db.scalars(select(ConsultationSlot.seed_key).where(ConsultationSlot.seed_key.like('contest-202611-%'))))
    existing_events = set(db.scalars(select(CampusEvent.seed_key).where(CampusEvent.seed_key.like('contest-202611-%'))))
    for number in range(9, 31):
        contest_day = date(2026, 11, number)
        for key, teacher, subject, _, room in slots:
            seed_key = f'contest-202611-{number:02d}-{key}'
            if seed_key not in existing_slots:
                start = datetime.combine(contest_day, datetime.min.time(), CAMPUS_TZ).replace(hour=21).astimezone(timezone.utc)
                db.add(ConsultationSlot(seed_key=seed_key, teacher=teacher, subject=subject, start_at=start, end_at=start+timedelta(hours=1), room=room, capacity=4, booked_count=0))
        key, title, category, description, _, location, capacity = events[(number-9) % len(events)]
        seed_key = f'contest-202611-{number:02d}-{key}'
        if seed_key not in existing_events:
            start = datetime.combine(contest_day, datetime.min.time(), CAMPUS_TZ).replace(hour=22).astimezone(timezone.utc)
            db.add(CampusEvent(seed_key=seed_key, title=title, category=category, description=description, start_at=start, end_at=start+timedelta(hours=1), location=location, capacity=capacity, registered_count=0))
    books = [
        ('algorithms', 'Алгоритмы: учебный практикум', 'М. Орлов', 'Алгоритмы и структуры данных', 'Вымышленное пособие: сложность, сортировки, деревья и графы.', 5),
        ('database', 'Проектирование баз данных', 'Е. Рябинина', 'Базы данных', 'Вымышленное пособие: нормализация, запросы и транзакции.', 4),
        ('probability', 'Вероятность на примерах', 'Р. Соловьёв', 'Теория вероятностей', 'Вымышленный сборник задач с разбором учебных примеров.', 3),
        ('interfaces', 'Интерфейсы и доступность', 'Н. Ласточкина', 'Проектирование интерфейсов', 'Вымышленный практикум по сценариям и проверке доступности.', 4),
        ('software', 'Инженерия программных систем', 'А. Громов', 'Инженерия ПО', 'Вымышленный учебник по требованиям, проектированию и проверкам.', 5),
        ('networks', 'Компьютерные сети: лабораторный курс', 'С. Белова', 'Компьютерные сети', 'Вымышленные лабораторные работы по сетевым протоколам.', 3),
        ('data', 'Анализ данных в учебных проектах', 'Д. Зорин', 'Анализ данных', 'Вымышленный практикум по описанию выборок и проверке моделей.', 4),
        ('writing', 'Как учиться и работать с источниками', 'В. Весенняя', 'Самостоятельная работа', 'Вымышленное пособие: планирование, конспектирование, оформление ссылок.', 6),
    ]
    for key, title, author, subject, description, total in books:
        seed_key = 'demo-book-' + key
        if db.scalar(select(LibraryBook.id).where(LibraryBook.seed_key == seed_key)) is None:
            db.add(LibraryBook(seed_key=seed_key, title=title, author=author, subject=subject, description=description, total=total, available=total))
    db.flush()
    for user in users:
        if db.scalar(select(FinanceEntry.id).where(FinanceEntry.student_id == user.id).limit(1)) is None:
            amount = 420000 if user.login == 'alina.demo' else 560000
            for offset in (60, 30, 0):
                db.add(FinanceEntry(student_id=user.id, date=day-timedelta(days=offset), description='Демонстрационная академическая стипендия', direction='credit', amount_kopecks=amount))
            db.add(FinanceEntry(student_id=user.id, date=day-timedelta(days=10), description='Демонстрационная плата за проживание', direction='debit', amount_kopecks=85000 if user.login == 'alina.demo' else 95000))
        if db.get(StudentPreference, user.id) is None:
            db.add(StudentPreference(student_id=user.id, email_notifications=False, deadline_reminders=True, compact_mode=False, weekly_goal=8 if user.login == 'alina.demo' else 10))
    db.flush()
