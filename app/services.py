"""Authenticated campus services; every personal resource is scoped in SQL."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, StrictBool, field_validator, model_validator
from sqlalchemy import select, update, func, case, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import User, DocumentRequest, CAMPUS_TZ, campus_today, utc_now
from .workspace import notify
from .services_db import (ConsultationSlot, ConsultationBooking, SupportTicket,
                          TicketMessage, CampusEvent, EventRegistration, LibraryBook,
                          LibraryLoan, FinanceEntry, StudentPreference, ServiceIdempotency)
from .receipt_codec import encode_receipt, decode_receipt
from .storage_guards import lock_owner


def begin_idempotent(db, request, response, user, operation, payload):
    """Reserve a receipt before changing state, within the same transaction.

    Concurrent requests serialize on the unique actor/operation/key tuple. A
    failed operation rolls its reservation back, and an acknowledged receipt is
    committed atomically with the resource. No other student's receipt is read.
    """
    key = request.headers.get('Idempotency-Key')
    if key is None:
        return None, None
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', key):
        raise HTTPException(422, 'Недопустимый ключ отправки')
    payload_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

    def previous_result(row):
        if row.payload_hash != payload_hash:
            raise HTTPException(409, 'Этот ключ уже использован для другой отправки')
        if not row.response_json:
            raise HTTPException(409, 'Предыдущая отправка ещё выполняется. Повторите позже')
        response.status_code = 200
        return None, decode_receipt(db, row.response_json)

    conditions = (ServiceIdempotency.user_id == user.id, ServiceIdempotency.operation == operation, ServiceIdempotency.key == key)
    previous = db.scalar(select(ServiceIdempotency).where(*conditions))
    if previous is not None:
        return previous_result(previous)
    row = ServiceIdempotency(user_id=user.id, operation=operation, key=key, payload_hash=payload_hash, created_at=utc_now(), response_json='')
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(select(ServiceIdempotency).where(*conditions))
        if previous is not None:
            return previous_result(previous)
        raise HTTPException(409, 'Одновременная отправка. Повторите с тем же ключом') from None
    return row, None


def commit_idempotent(db, receipt, payload):
    if receipt is not None:
        receipt.response_json = json.dumps(encode_receipt(db, payload), ensure_ascii=False, sort_keys=True, default=str)
    db.commit()
    return payload


def consultation_scope(user):
    from .workspace_db import GroupMember, TeacherConsultation, TeachingLoad
    linked = select(TeacherConsultation.slot_id).where(TeacherConsultation.slot_id == ConsultationSlot.id).exists()
    assigned = (select(TeacherConsultation.slot_id).join(TeachingLoad).join(GroupMember, GroupMember.group_id == TeachingLoad.group_id)
                .where(TeacherConsultation.slot_id == ConsultationSlot.id, GroupMember.student_id == user.id).exists())
    return or_(~linked, assigned)


CONTACTS = [
    {'id': 1, 'name': 'Учебный офис', 'role': 'Заявки, справки и учебные вопросы', 'department': 'Студенческий офис', 'subject': '', 'room': 'Корпус Б, Б-102', 'hours': 'Пн–пт, 09:00–17:00 · МСК', 'email': 'office@atlas.example'},
    {'id': 2, 'name': 'М. Орлов', 'role': 'Преподаватель', 'department': 'Институт цифровых технологий', 'subject': 'Алгоритмы и структуры данных', 'room': 'Корпус А, А-301', 'hours': 'Вт, 15:00–16:00 · запись в кабинете', 'email': 'orlov@atlas.example'},
    {'id': 3, 'name': 'Р. Соловьёв', 'role': 'Преподаватель', 'department': 'Кафедра математики', 'subject': 'Теория вероятностей', 'room': 'Корпус В, В-205', 'hours': 'Ср, 15:00–16:00 · запись в кабинете', 'email': 'soloviev@atlas.example'},
    {'id': 4, 'name': 'Е. Рябинина', 'role': 'Преподаватель', 'department': 'Институт цифровых технологий', 'subject': 'Базы данных', 'room': 'Корпус Б, Б-208', 'hours': 'Чт, 15:00–16:00 · запись в кабинете', 'email': 'ryabinina@atlas.example'},
    {'id': 5, 'name': 'А. Громов', 'role': 'Преподаватель', 'department': 'Факультет прикладных наук', 'subject': 'Инженерия ПО', 'room': 'Корпус А, А-412', 'hours': 'Вт, 15:00–16:00 · запись в кабинете', 'email': 'gromov@atlas.example'},
    {'id': 6, 'name': 'Д. Зорин', 'role': 'Преподаватель', 'department': 'Факультет прикладных наук', 'subject': 'Анализ данных', 'room': 'Корпус В, В-404', 'hours': 'Пт, 15:00–16:00 · запись в кабинете', 'email': 'zorin@atlas.example'},
    {'id': 7, 'name': 'Центр карьеры', 'role': 'Учебная практика и портфолио', 'department': 'Сервисы кампуса', 'subject': '', 'room': 'Корпус Б, Б-210', 'hours': 'Пн–пт, 10:00–16:00 · МСК', 'email': 'career@atlas.example'},
    {'id': 8, 'name': 'Библиотека', 'role': 'Учебная литература и работа с источниками', 'department': 'Сервисы кампуса', 'subject': '', 'room': 'Корпус А, 1 этаж', 'hours': 'Пн–сб, 09:00–19:00 · МСК', 'email': 'library@atlas.example'},
    {'id': 9, 'name': 'Поддержка кабинета', 'role': 'Вопросы по работе кабинета', 'department': 'Цифровой кампус', 'subject': '', 'room': 'Переписка в разделе «Вопросы в учебный офис»', 'hours': 'Ответ в истории обращения', 'email': 'support@atlas.example'},
]

KNOWLEDGE = [
    {'id': 1, 'category': 'documents', 'title': 'Как заказать справку?', 'body': 'Откройте «Справки», выберите вид документа и заполните поля. Номер и история сохранятся в разделе «Мои справки». Когда документ будет готов, его можно открыть или скачать.'},
    {'id': 2, 'category': 'academic', 'title': 'Как подготовиться к пересдаче?', 'body': 'Посмотрите раздел «Сессия», выберите дисциплину и запишитесь на консультацию. Уточните требования у преподавателя через учебный офис. Для заявления на пересдачу используйте каталог заявок. Конкретную дату утверждает сотрудник.'},
    {'id': 3, 'category': 'academic', 'title': 'Как сдать учебную работу?', 'body': 'Откройте «Сдача работ», выберите задание, добавьте текст и при необходимости HTTPS-ссылку. Сдача сохраняется отдельно от личной отметки выполнения в плане.'},
    {'id': 4, 'category': 'finance', 'title': 'Стипендия и материальная поддержка', 'body': 'Начисления видны в разделе «Финансы». Справку о стипендии можно заказать в разделе «Справки», а заявление на материальную помощь подать через «Заявки». Приём платежей отключён.'},
    {'id': 5, 'category': 'campus', 'title': 'Как взять книгу?', 'body': 'В библиотеке выберите доступный учебный экземпляр. Выдача на 14 дней сохраняется в «Моих книгах». Возврат освобождает экземпляр.'},
    {'id': 6, 'category': 'academic', 'title': 'Академический отпуск и индивидуальный план', 'body': 'Создайте заявление нужного вида и опишите учебный вопрос без настоящих персональных или медицинских документов. Учебный офис ответит в истории заявки.'},
    {'id': 7, 'category': 'campus', 'title': 'Практика, стажировки и мобильность', 'body': 'Планируйте практику через каталог заявлений, открывайте мероприятия в разделе «Вне учёбы» и задавайте вопросы центру карьеры.'},
    {'id': 8, 'category': 'security', 'title': 'Кто видит мои данные?', 'body': 'Личные записи доступны только вашему студенческому аккаунту. Сотрудник отвечает на заявки и переписку, но не читает личные конспекты, оценки, расписание и финансовый журнал.'},
    {'id': 9, 'category': 'study', 'title': 'Как работает самостоятельная учёба?', 'body': 'Конспекты, карточки, личные задачи и журнал фокус-сессий сохраняются на сервере. Учебные тесты дают обратную связь и не меняют официальные оценки. Отметка модуля означает личную готовность, а не зачёт.'},
    {'id': 10, 'category': 'support', 'title': 'Как получить ответ учебного офиса?', 'body': 'Создайте тему в разделе «Вопросы в учебный офис». Переписка хранится в кабинете и доступна сотруднику. После ответа придёт внутреннее уведомление. Закройте решённую тему; для нового вопроса создайте новую.'},
    {'id': 11, 'category': 'security', 'title': 'Что означают настройки уведомлений?', 'body': 'Настройки сохраняются в вашем кабинете. Письма и push-уведомления не отправляются. Внутренние уведомления по заявкам и сообщениям остаются в кабинете независимо от настройки e-mail.'},
    {'id': 12, 'category': 'campus', 'title': 'Где находятся аудитории?', 'body': 'Учебные корпуса обозначены А, Б и В. Первая буква аудитории указывает корпус, первая цифра — этаж. Например, Б-208: корпус Б, второй этаж. Карта и адреса реального университета не используются.'},
]


def create_router():
    # Import only after main has defined its security dependencies.
    from .main import get_db, require_user, require_student, require_staff, require_same_origin, StrictBody, date_iso

    router = APIRouter()

    class TextBody(StrictBody):
        @field_validator('*', mode='before')
        @classmethod
        def trim_strings(cls, value):
            return value.strip() if isinstance(value, str) else value

    class EmptyBody(StrictBody):
        pass

    class SlotBody(TextBody):
        teacher: str = Field(min_length=2, max_length=120)
        subject: str = Field(min_length=3, max_length=130)
        start_at: datetime
        end_at: datetime
        room: str = Field(min_length=2, max_length=100)
        capacity: int = Field(strict=True, ge=1, le=100)

        @model_validator(mode='after')
        def validate_times(self):
            if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
                raise ValueError('Укажите часовой пояс')
            if not timedelta(minutes=10) <= self.end_at - self.start_at <= timedelta(hours=8):
                raise ValueError('Продолжительность от 10 минут до 8 часов')
            try:
                self.start_at = self.start_at.astimezone(timezone.utc)
                self.end_at = self.end_at.astimezone(timezone.utc)
            except (OverflowError, ValueError):
                raise ValueError('Дата выходит за поддерживаемый диапазон') from None
            return self

    class TicketBody(TextBody):
        topic: Literal['academic', 'technical', 'financial', 'other']
        title: str = Field(min_length=5, max_length=180)
        message: str = Field(min_length=10, max_length=4000)

    class MessageBody(TextBody):
        message: str = Field(min_length=1, max_length=4000)

    class EventBody(TextBody):
        title: str = Field(min_length=5, max_length=180)
        category: Literal['science', 'career', 'sport', 'community', 'academic']
        description: str = Field(min_length=10, max_length=4000)
        start_at: datetime
        end_at: datetime
        location: str = Field(min_length=3, max_length=150)
        capacity: int = Field(strict=True, ge=1, le=1000)

        @model_validator(mode='after')
        def validate_times(self):
            if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
                raise ValueError('Укажите часовой пояс')
            if not timedelta(minutes=10) <= self.end_at - self.start_at <= timedelta(days=7):
                raise ValueError('Продолжительность от 10 минут до 7 дней')
            try:
                self.start_at = self.start_at.astimezone(timezone.utc)
                self.end_at = self.end_at.astimezone(timezone.utc)
            except (OverflowError, ValueError):
                raise ValueError('Дата выходит за поддерживаемый диапазон') from None
            return self

    class PreferencesBody(StrictBody):
        email_notifications: StrictBool = False
        deadline_reminders: StrictBool = True
        compact_mode: StrictBool
        weekly_goal: int | None = Field(default=None, strict=True, ge=1, le=40)

    def owned(db, model, row_id, user):
        row = db.scalar(select(model).where(model.id == row_id, model.student_id == user.id))
        if row is None:
            raise HTTPException(404, 'Запись не найдена')
        return row

    def not_found(row):
        if row is None:
            raise HTTPException(404, 'Запись не найдена')
        return row

    def page_rows(db, query, limit, offset):
        total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        return db.scalars(query.offset(offset).limit(limit)).all(), dict(total=total, limit=limit, offset=offset, has_more=offset+limit < total)

    def scoped_catalog(model, scope, record_id):
        conditions = []
        if record_id is not None:
            conditions.append(model.id == record_id)
        elif scope == 'upcoming':
            conditions.append(model.start_at > utc_now())
        elif scope == 'archive':
            conditions.append(model.start_at <= utc_now())
        return conditions

    def search_catalog(columns, q):
        from .main import text_search, search_text
        search = search_text(q)
        return [or_(*(text_search(column, search) for column in columns))] if search else []

    def date_range(column, date_from, date_to):
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, 'Начальная дата должна быть не позже конечной')
        conditions = []
        if date_from:
            if date_from == date.min:
                raise HTTPException(422, 'Начальная дата выходит за поддерживаемый диапазон')
            conditions.append(column >= datetime.combine(date_from, datetime.min.time(), CAMPUS_TZ).astimezone(timezone.utc))
        if date_to:
            # Exclusive next midnight keeps late-evening events in the Moscow day.
            if date_to == date.max:
                raise HTTPException(422, 'Конечная дата выходит за поддерживаемый диапазон')
            conditions.append(column < datetime.combine(date_to+timedelta(days=1), datetime.min.time(), CAMPUS_TZ).astimezone(timezone.utc))
        return conditions

    def validate_future_publication(start_at):
        now = utc_now()
        if not now < start_at <= now + timedelta(days=365):
            raise HTTPException(422, 'Дата должна быть в будущем, не позднее года')

    def notify_office(db, row, title):
        for staff_id in db.scalars(select(User.id).where(User.role == 'staff')):
            notify(db, staff_id, title, row.title, f'/app/staffmessages?id={row.id}', category='service')

    def slot_payload(slot, booking_id=None):
        return dict(id=slot.id, teacher=slot.teacher, subject=slot.subject, start_at=date_iso(slot.start_at), end_at=date_iso(slot.end_at), room=slot.room, capacity=slot.capacity, booked_count=slot.booked_count, my_booking_id=booking_id)

    def booking_payload(db, row, slots=None):
        slot = slots[row.slot_id] if slots is not None else db.get(ConsultationSlot, row.slot_id)
        return dict(id=row.id, slot_id=row.slot_id, status=row.status, created_at=date_iso(row.created_at), slot=slot_payload(slot, row.id if row.status == 'active' else None))

    def event_payload(row, registration_id=None):
        return dict(id=row.id, title=row.title, category=row.category, description=row.description, start_at=date_iso(row.start_at), end_at=date_iso(row.end_at), location=row.location, capacity=row.capacity, registered_count=row.registered_count, my_registration_id=registration_id)

    def registration_payload(db, row, events=None):
        event = events[row.event_id] if events is not None else db.get(CampusEvent, row.event_id)
        return dict(id=row.id, event_id=row.event_id, status=row.status, created_at=date_iso(row.created_at), event=event_payload(event, row.id if row.status == 'active' else None))

    def book_payload(row, loan_id=None):
        return dict(id=row.id, title=row.title, author=row.author, subject=row.subject, description=row.description, total=row.total, available=row.available, my_loan_id=loan_id)

    def loan_payload(db, row, books=None):
        book = books[row.book_id] if books is not None else db.get(LibraryBook, row.book_id)
        return dict(id=row.id, book_id=row.book_id, status=row.status, borrowed_at=date_iso(row.borrowed_at), due_date=date_iso(row.due_date), returned_at=date_iso(row.returned_at), book=book_payload(book, row.id if row.status == 'active' else None))

    def ticket_payload(db, row, detail=False, staff=False, students=None, message_limit=100, message_offset=None):
        result = dict(id=row.id, topic=row.topic, title=row.title, status=row.status, created_at=date_iso(row.created_at), updated_at=date_iso(row.updated_at))
        if staff:
            student = students[row.student_id] if students is not None else db.get(User, row.student_id)
            result.update(student_name=student.full_name, group=student.group_name)
        if detail:
            total = db.scalar(select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == row.id))
            offset = max(0, total-message_limit) if message_offset is None else message_offset
            messages = db.scalars(select(TicketMessage).where(TicketMessage.ticket_id == row.id).order_by(TicketMessage.created_at, TicketMessage.id).offset(offset).limit(message_limit)).all()
            result['messages'] = [dict(id=m.id, body=m.body, actor_role=m.actor_role, actor_name=m.actor_name, created_at=date_iso(m.created_at)) for m in messages]
            result.update(messages_total=total, messages_limit=message_limit, messages_offset=offset, messages_has_more=offset+message_limit < total)
        return result

    @router.get('/api/services/contacts')
    def contacts(q: str = Query('', max_length=100), user: User = Depends(require_student)):
        from .main import search_text
        search = search_text(q).casefold()
        return {'items': [row for row in CONTACTS if not search or search in ' '.join(str(x) for x in row.values()).casefold()], 'concept': True}

    @router.get('/api/services/knowledge')
    def knowledge(q: str = Query('', max_length=100), user: User = Depends(require_student)):
        from .main import search_text
        search = search_text(q).casefold()
        return {'items': [row for row in KNOWLEDGE if not search or search in (row['title']+' '+row['body']).casefold()], 'concept': True}

    @router.get('/api/services/consultations')
    def consultations(scope: Literal['upcoming','archive','all'] = 'upcoming', q: str = Query('', max_length=100), record_id: int | None = Query(None, ge=1), limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        conditions = scoped_catalog(ConsultationSlot, scope, record_id) + search_catalog([ConsultationSlot.subject, ConsultationSlot.teacher], q) + [consultation_scope(user)]
        query = select(ConsultationSlot).where(*conditions).order_by(ConsultationSlot.start_at, ConsultationSlot.id)
        rows, meta = page_rows(db, query, limit, offset)
        mine = {b.slot_id: b.id for b in db.scalars(select(ConsultationBooking).where(ConsultationBooking.student_id == user.id, ConsultationBooking.status == 'active', ConsultationBooking.slot_id.in_([row.id for row in rows]))).all()}
        return {'items': [slot_payload(row, mine.get(row.id)) for row in rows], **meta}

    @router.get('/api/services/bookings')
    def bookings(filter: Literal['all','active','cancelled'] = 'all', date_from: date | None = None, date_to: date | None = None, limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        conditions = [ConsultationBooking.student_id == user.id] + date_range(ConsultationSlot.start_at, date_from, date_to)
        if filter != 'all': conditions.append(ConsultationBooking.status == filter)
        rows, meta = page_rows(db, select(ConsultationBooking).join(ConsultationSlot, ConsultationSlot.id == ConsultationBooking.slot_id).where(*conditions).order_by(ConsultationBooking.created_at.desc(), ConsultationBooking.id.desc()), limit, offset)
        slots = {s.id:s for s in db.scalars(select(ConsultationSlot).where(ConsultationSlot.id.in_([row.slot_id for row in rows])))}
        return {'items': [booking_payload(db, row, slots) for row in rows], **meta}

    @router.post('/api/services/consultations/{slot_id}/book', status_code=201)
    def book_consultation(slot_id: int, body: EmptyBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        from .workspace import lock_workspace
        lock_workspace(db,user.id)
        slot = not_found(db.scalar(select(ConsultationSlot).where(ConsultationSlot.id==slot_id,consultation_scope(user))))
        receipt, replay = begin_idempotent(db, request, response, user, f'consultation-book:{slot_id}', {})
        if replay is not None: return replay
        # This UPDATE is both a capacity guard and a row lock. Duplicate checks
        # happen after it, so two workers cannot consume the same seat twice.
        changed = db.execute(update(ConsultationSlot).where(ConsultationSlot.id == slot_id, ConsultationSlot.booked_count < ConsultationSlot.capacity, ConsultationSlot.start_at > utc_now()).values(booked_count=ConsultationSlot.booked_count+1).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Запись закрыта: встреча началась или нет мест')
        duplicate = db.scalar(select(ConsultationBooking.id).where(ConsultationBooking.student_id == user.id, ConsultationBooking.slot_id == slot_id, ConsultationBooking.status == 'active'))
        if duplicate:
            db.rollback()
            raise HTTPException(409, 'Вы уже записаны на эту консультацию')
        row = ConsultationBooking(student_id=user.id, slot_id=slot_id, status='active', created_at=utc_now())
        db.add(row)
        notify(db, user.id, 'Запись на консультацию сохранена', f'{slot.subject}: {slot.teacher}.',
               f'/app/consultations?id={slot.id}', category='service')
        from .university_db import Teacher, TeachingAssignment
        from .workspace_db import TeacherConsultation, TeachingLoad
        teacher_id = db.scalar(select(Teacher.user_id).select_from(TeacherConsultation).join(TeachingLoad)
                               .join(TeachingAssignment).join(Teacher).where(TeacherConsultation.slot_id==slot_id))
        if teacher_id:
            notify(db, teacher_id, 'Новая запись на консультацию', slot.subject, '/app/teach-consultations', category='service')
        db.flush()
        db.refresh(slot)
        return commit_idempotent(db, receipt, booking_payload(db, row))

    @router.post('/api/services/bookings/{booking_id}/cancel')
    def cancel_booking(booking_id: int, body: EmptyBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        row = owned(db, ConsultationBooking, booking_id, user)
        receipt, replay = begin_idempotent(db, request, response, user, f'consultation-cancel:{booking_id}', {})
        if replay is not None: return replay
        changed = db.execute(update(ConsultationBooking).where(ConsultationBooking.id == row.id, ConsultationBooking.student_id == user.id, ConsultationBooking.status == 'active').values(status='cancelled').execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Запись уже отменена')
        db.execute(update(ConsultationSlot).where(ConsultationSlot.id == row.slot_id, ConsultationSlot.booked_count > 0).values(booked_count=ConsultationSlot.booked_count-1))
        db.flush()
        db.refresh(row)
        return commit_idempotent(db, receipt, booking_payload(db, row))

    @router.get('/api/staff/consultations')
    def staff_consultations(scope: Literal['upcoming','archive','all'] = 'upcoming', q: str = Query('', max_length=100), record_id: int | None = Query(None, ge=1), limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_staff), db: Session = Depends(get_db)):
        conditions = scoped_catalog(ConsultationSlot, scope, record_id) + search_catalog([ConsultationSlot.subject, ConsultationSlot.teacher], q)
        rows, meta = page_rows(db, select(ConsultationSlot).where(*conditions).order_by(ConsultationSlot.start_at, ConsultationSlot.id), limit, offset)
        return {'items': [slot_payload(row) for row in rows], **meta}

    @router.post('/api/staff/consultations', status_code=201)
    def add_consultation(body: SlotBody, request: Request, response: Response, user: User = Depends(require_staff), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        from .workspace import lock_workspace
        from .scheduling import aliases, teacher_is_busy
        from .university_db import Teacher
        lock_workspace(db,user.id)
        receipt, replay = begin_idempotent(db, request, response, user, 'consultation-create', body.model_dump())
        if replay is not None: return replay
        validate_future_publication(body.start_at)
        if any(body.teacher in aliases(t) and teacher_is_busy(db,t,body.start_at,body.end_at) for t in db.scalars(select(Teacher))):
            raise HTTPException(409,'В это время преподаватель уже занят')
        row = ConsultationSlot(**body.model_dump(), booked_count=0)
        db.add(row)
        db.flush()
        return commit_idempotent(db, receipt, slot_payload(row))

    @router.get('/api/services/tickets')
    def tickets(filter: Literal['all','open','closed'] = 'all', q: str = Query('', max_length=100), record_id: int | None = Query(None, ge=1), limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        conditions = [SupportTicket.student_id == user.id] + search_catalog([SupportTicket.title], q)
        if filter != 'all': conditions.append(SupportTicket.status == filter)
        if record_id is not None: conditions.append(SupportTicket.id == record_id)
        rows, meta = page_rows(db, select(SupportTicket).where(*conditions).order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()), limit, offset)
        return {'items': [ticket_payload(db, row) for row in rows], **meta}

    @router.post('/api/services/tickets', status_code=201)
    def new_ticket(body: TicketBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        receipt, replay = begin_idempotent(db, request, response, user, 'ticket-create', body.model_dump())
        if replay is not None: return replay
        now = utc_now()
        row = SupportTicket(student_id=user.id, topic=body.topic, title=body.title, status='open', created_at=now, updated_at=now)
        db.add(row)
        db.flush()
        db.add(TicketMessage(ticket_id=row.id, actor_id=user.id, actor_role='student', actor_name=user.full_name, body=body.message, created_at=now))
        notify_office(db, row, 'Новое обращение в учебный офис')
        db.flush()
        return commit_idempotent(db, receipt, ticket_payload(db, row, detail=True))

    @router.get('/api/services/tickets/{ticket_id}')
    def ticket_detail(ticket_id: int, message_limit: int = Query(100, ge=1, le=100), message_offset: int | None = Query(None, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        return ticket_payload(db, owned(db, SupportTicket, ticket_id, user), detail=True, message_limit=message_limit, message_offset=message_offset)

    def append_message(db, row, user, message, request, response):
        receipt, replay = begin_idempotent(db, request, response, user, f'ticket-message:{row.id}', {'message':message})
        if replay is not None: return replay
        # Atomic status check serializes closing and replying to a topic.
        changed = db.execute(update(SupportTicket).where(SupportTicket.id == row.id, SupportTicket.status == 'open').values(updated_at=utc_now()).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Тема закрыта. Создайте новую тему для нового вопроса')
        count = db.scalar(select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == row.id))
        if count >= 500:
            db.rollback()
            raise HTTPException(409, 'Достигнут предел переписки. Создайте новую тему')
        db.add(TicketMessage(ticket_id=row.id, actor_id=user.id, actor_role=user.role, actor_name=user.full_name, body=message, created_at=utc_now()))
        if user.role == 'staff':
            notify(db, row.student_id, 'Учебный офис ответил', row.title, f'/app/messages?id={row.id}', category='service')
        else:
            notify_office(db, row, 'Студент ответил в обращении')
        db.flush()
        db.refresh(row)
        return commit_idempotent(db, receipt, ticket_payload(db, row, detail=True, staff=user.role == 'staff'))

    def close_ticket(db, row, user, request, response):
        receipt, replay = begin_idempotent(db, request, response, user, f'ticket-close:{row.id}', {})
        if replay is not None: return replay
        changed = db.execute(update(SupportTicket).where(SupportTicket.id == row.id, SupportTicket.status == 'open').values(status='closed', updated_at=utc_now()).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Тема уже закрыта')
        if user.role == 'staff':
            notify(db, row.student_id, 'Тема закрыта учебным офисом', row.title, f'/app/messages?id={row.id}', category='service')
        db.flush()
        db.refresh(row)
        return commit_idempotent(db, receipt, ticket_payload(db, row, detail=True, staff=user.role == 'staff'))

    @router.post('/api/services/tickets/{ticket_id}/messages')
    def ticket_reply(ticket_id: int, body: MessageBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        return append_message(db, owned(db, SupportTicket, ticket_id, user), user, body.message, request, response)

    @router.post('/api/services/tickets/{ticket_id}/close')
    def ticket_close(ticket_id: int, body: EmptyBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        return close_ticket(db, owned(db, SupportTicket, ticket_id, user), user, request, response)

    @router.get('/api/staff/tickets')
    def staff_tickets(filter: Literal['all', 'open', 'closed'] = 'all', q: str = Query('', max_length=100), record_id: int | None = Query(None, ge=1), limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_staff), db: Session = Depends(get_db)):
        from .main import text_search, search_text
        search = search_text(q)
        conditions = [] if filter == 'all' else [SupportTicket.status == filter]
        if search:
            conditions.append(text_search(SupportTicket.title, search))
        if record_id is not None: conditions.append(SupportTicket.id == record_id)
        rows, meta = page_rows(db, select(SupportTicket).where(*conditions).order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()), limit, offset)
        students = {s.id:s for s in db.scalars(select(User).where(User.id.in_([row.student_id for row in rows])))}
        return {'items': [ticket_payload(db, row, staff=True, students=students) for row in rows], **meta}

    @router.get('/api/staff/tickets/{ticket_id}')
    def staff_ticket_detail(ticket_id: int, message_limit: int = Query(100, ge=1, le=100), message_offset: int | None = Query(None, ge=0, le=2147483647), user: User = Depends(require_staff), db: Session = Depends(get_db)):
        return ticket_payload(db, not_found(db.get(SupportTicket, ticket_id)), detail=True, staff=True, message_limit=message_limit, message_offset=message_offset)

    @router.post('/api/staff/tickets/{ticket_id}/messages')
    def staff_ticket_reply(ticket_id: int, body: MessageBody, request: Request, response: Response, user: User = Depends(require_staff), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        return append_message(db, not_found(db.get(SupportTicket, ticket_id)), user, body.message, request, response)

    @router.post('/api/staff/tickets/{ticket_id}/close')
    def staff_ticket_close(ticket_id: int, body: EmptyBody, request: Request, response: Response, user: User = Depends(require_staff), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        return close_ticket(db, not_found(db.get(SupportTicket, ticket_id)), user, request, response)

    @router.get('/api/services/events')
    def events(scope: Literal['upcoming','archive','all'] = 'upcoming', filter: Literal['all','available','mine'] = 'all', q: str = Query('', max_length=100), record_id: int | None = Query(None, ge=1), limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        conditions = scoped_catalog(CampusEvent, scope, record_id) + search_catalog([CampusEvent.title, CampusEvent.description, CampusEvent.category], q)
        if filter == 'available': conditions.extend([CampusEvent.start_at > utc_now(), CampusEvent.registered_count < CampusEvent.capacity])
        if filter == 'mine': conditions.append(CampusEvent.id.in_(select(EventRegistration.event_id).where(EventRegistration.student_id == user.id, EventRegistration.status == 'active')))
        rows, meta = page_rows(db, select(CampusEvent).where(*conditions).order_by(CampusEvent.start_at, CampusEvent.id), limit, offset)
        mine = {r.event_id: r.id for r in db.scalars(select(EventRegistration).where(EventRegistration.student_id == user.id, EventRegistration.status == 'active', EventRegistration.event_id.in_([row.id for row in rows]))).all()}
        return {'items': [event_payload(row, mine.get(row.id)) for row in rows], **meta}

    @router.get('/api/services/registrations')
    def registrations(filter: Literal['all','active','cancelled'] = 'all', date_from: date | None = None, date_to: date | None = None, limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        conditions = [EventRegistration.student_id == user.id] + date_range(CampusEvent.start_at, date_from, date_to)
        if filter != 'all': conditions.append(EventRegistration.status == filter)
        rows, meta = page_rows(db, select(EventRegistration).join(CampusEvent, CampusEvent.id == EventRegistration.event_id).where(*conditions).order_by(EventRegistration.created_at.desc(), EventRegistration.id.desc()), limit, offset)
        events = {s.id:s for s in db.scalars(select(CampusEvent).where(CampusEvent.id.in_([row.event_id for row in rows])))}
        return {'items': [registration_payload(db, row, events) for row in rows], **meta}

    @router.post('/api/services/events/{event_id}/register', status_code=201)
    def register_event(event_id: int, body: EmptyBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        event = not_found(db.get(CampusEvent, event_id))
        receipt, replay = begin_idempotent(db, request, response, user, f'event-register:{event_id}', {})
        if replay is not None: return replay
        changed = db.execute(update(CampusEvent).where(CampusEvent.id == event_id, CampusEvent.registered_count < CampusEvent.capacity, CampusEvent.start_at > utc_now()).values(registered_count=CampusEvent.registered_count+1).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Регистрация закрыта: событие началось или нет мест')
        if db.scalar(select(EventRegistration.id).where(EventRegistration.student_id == user.id, EventRegistration.event_id == event_id, EventRegistration.status == 'active')):
            db.rollback()
            raise HTTPException(409, 'Вы уже зарегистрированы')
        row = EventRegistration(student_id=user.id, event_id=event_id, status='active', created_at=utc_now())
        db.add(row)
        notify(db, user.id, 'Регистрация на мероприятие сохранена', event.title,
               f'/app/events?id={event.id}', category='service')
        db.flush()
        db.refresh(event)
        return commit_idempotent(db, receipt, registration_payload(db, row))

    @router.post('/api/services/registrations/{registration_id}/cancel')
    def cancel_registration(registration_id: int, body: EmptyBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        row = owned(db, EventRegistration, registration_id, user)
        receipt, replay = begin_idempotent(db, request, response, user, f'event-cancel:{registration_id}', {})
        if replay is not None: return replay
        changed = db.execute(update(EventRegistration).where(EventRegistration.id == row.id, EventRegistration.student_id == user.id, EventRegistration.status == 'active').values(status='cancelled').execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Регистрация уже отменена')
        db.execute(update(CampusEvent).where(CampusEvent.id == row.event_id, CampusEvent.registered_count > 0).values(registered_count=CampusEvent.registered_count-1))
        db.flush()
        db.refresh(row)
        return commit_idempotent(db, receipt, registration_payload(db, row))

    @router.get('/api/staff/events')
    def staff_events(scope: Literal['upcoming','archive','all'] = 'upcoming', q: str = Query('', max_length=100), record_id: int | None = Query(None, ge=1), limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_staff), db: Session = Depends(get_db)):
        conditions = scoped_catalog(CampusEvent, scope, record_id) + search_catalog([CampusEvent.title, CampusEvent.description], q)
        rows, meta = page_rows(db, select(CampusEvent).where(*conditions).order_by(CampusEvent.start_at, CampusEvent.id), limit, offset)
        return {'items': [event_payload(row) for row in rows], **meta}

    @router.post('/api/staff/events', status_code=201)
    def add_event(body: EventBody, request: Request, response: Response, user: User = Depends(require_staff), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        receipt, replay = begin_idempotent(db, request, response, user, 'event-create', body.model_dump())
        if replay is not None: return replay
        validate_future_publication(body.start_at)
        row = CampusEvent(**body.model_dump(), registered_count=0)
        db.add(row)
        db.flush()
        return commit_idempotent(db, receipt, event_payload(row))

    @router.get('/api/services/library')
    def library(q: str = Query('', max_length=100), record_id: int | None = Query(None, ge=1), limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        conditions = search_catalog([LibraryBook.title, LibraryBook.author, LibraryBook.subject], q)
        if record_id is not None: conditions.append(LibraryBook.id == record_id)
        rows, meta = page_rows(db, select(LibraryBook).where(*conditions).order_by(LibraryBook.title, LibraryBook.id), limit, offset)
        mine = {row.book_id: row.id for row in db.scalars(select(LibraryLoan).where(LibraryLoan.student_id == user.id, LibraryLoan.status == 'active', LibraryLoan.book_id.in_([row.id for row in rows]))).all()}
        return {'items': [book_payload(row, mine.get(row.id)) for row in rows], **meta}

    @router.get('/api/services/loans')
    def loans(filter: Literal['all','active','returned'] = 'all', limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        conditions = [LibraryLoan.student_id == user.id]
        if filter != 'all': conditions.append(LibraryLoan.status == filter)
        rows, meta = page_rows(db, select(LibraryLoan).where(*conditions).order_by(LibraryLoan.borrowed_at.desc(), LibraryLoan.id.desc()), limit, offset)
        books = {s.id:s for s in db.scalars(select(LibraryBook).where(LibraryBook.id.in_([row.book_id for row in rows])))}
        return {'items': [loan_payload(db, row, books) for row in rows], **meta}

    @router.post('/api/services/library/{book_id}/borrow', status_code=201)
    def borrow_book(book_id: int, body: EmptyBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        book = not_found(db.get(LibraryBook, book_id))
        receipt, replay = begin_idempotent(db, request, response, user, f'library-borrow:{book_id}', {})
        if replay is not None: return replay
        changed = db.execute(update(LibraryBook).where(LibraryBook.id == book_id, LibraryBook.available > 0).values(available=LibraryBook.available-1).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Все экземпляры выданы')
        if db.scalar(select(LibraryLoan.id).where(LibraryLoan.student_id == user.id, LibraryLoan.book_id == book_id, LibraryLoan.status == 'active')):
            db.rollback()
            raise HTTPException(409, 'Эта книга уже у вас')
        row = LibraryLoan(student_id=user.id, book_id=book_id, status='active', borrowed_at=utc_now(), due_date=campus_today()+timedelta(days=14))
        db.add(row)
        db.flush()
        db.refresh(book)
        return commit_idempotent(db, receipt, loan_payload(db, row))

    @router.post('/api/services/loans/{loan_id}/return')
    def return_book(loan_id: int, body: EmptyBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        row = owned(db, LibraryLoan, loan_id, user)
        receipt, replay = begin_idempotent(db, request, response, user, f'library-return:{loan_id}', {})
        if replay is not None: return replay
        changed = db.execute(update(LibraryLoan).where(LibraryLoan.id == row.id, LibraryLoan.student_id == user.id, LibraryLoan.status == 'active').values(status='returned', returned_at=utc_now()).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Книга уже возвращена')
        db.execute(update(LibraryBook).where(LibraryBook.id == row.book_id, LibraryBook.available < LibraryBook.total).values(available=LibraryBook.available+1))
        db.flush()
        db.refresh(row)
        return commit_idempotent(db, receipt, loan_payload(db, row))

    @router.get('/api/services/finance')
    def finance(q: str = Query('', max_length=100), limit: int = Query(300, ge=1, le=300), offset: int = Query(0, ge=0, le=2147483647), user: User = Depends(require_student), db: Session = Depends(get_db)):
        conditions = [FinanceEntry.student_id == user.id] + search_catalog([FinanceEntry.description], q)
        rows, meta = page_rows(db, select(FinanceEntry).where(*conditions).order_by(FinanceEntry.date.desc(), FinanceEntry.id.desc()), limit, offset)
        sums = db.execute(select(func.coalesce(func.sum(case((FinanceEntry.direction == 'credit', FinanceEntry.amount_kopecks), else_=0)), 0), func.coalesce(func.sum(case((FinanceEntry.direction == 'debit', FinanceEntry.amount_kopecks), else_=0)), 0)).where(FinanceEntry.student_id == user.id)).one()
        return {'items': [dict(id=row.id, date=date_iso(row.date), description=row.description, direction=row.direction, amount_kopecks=row.amount_kopecks) for row in rows], **meta, 'summary': {'credits_kopecks': sums[0], 'debits_kopecks': sums[1], 'balance_kopecks': sums[0]-sums[1], 'concept': True}, 'notice': 'Платежи и банковские сервисы не подключены.'}

    def preference_payload(row):
        return dict(email_notifications=row.email_notifications if row else False, deadline_reminders=row.deadline_reminders if row else True, compact_mode=row.compact_mode if row else False, weekly_goal=row.weekly_goal if row else 8)

    @router.get('/api/services/preferences')
    def preferences(user: User = Depends(require_user), db: Session = Depends(get_db)):
        return preference_payload(db.get(StudentPreference, user.id))

    @router.post('/api/services/preferences')
    def save_preferences(body: PreferencesBody, user: User = Depends(require_user), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
        lock_owner(db, user.id)
        values = body.model_dump(exclude_unset=True, exclude_none=True)
        row = db.get(StudentPreference, user.id)
        if row is None:
            row = StudentPreference(student_id=user.id, **values)
            db.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        db.commit()
        return preference_payload(row)

    @router.get('/api/staff/overview')
    def staff_overview(user: User = Depends(require_staff), db: Session = Depends(get_db)):
        counts = {status: count for status, count in db.execute(select(DocumentRequest.status, func.count()).group_by(DocumentRequest.status))}
        return {'requests': counts, 'requests_total': sum(counts.values()), 'open_tickets': db.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.status == 'open')), 'consultations': db.scalar(select(func.count()).select_from(ConsultationSlot).where(ConsultationSlot.start_at > utc_now())), 'events': db.scalar(select(func.count()).select_from(CampusEvent).where(CampusEvent.start_at > utc_now())), 'concept': True}

    return router
