"""Database models and deterministic, fictional demo fixture data."""
from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone, date
from sqlalchemy import create_engine, ForeignKey, Integer, String, DateTime, Date, Boolean, Text, UniqueConstraint, event, inspect, select, text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from argon2 import PasswordHasher
from .config import DEMO_LOGINS, settings
from .session_security import as_utc
from .storage_guards import lock_owner

# `python -m app.db` must share this metadata with extension imports of
# `app.db`; otherwise Python would create two independent model registries.
if __name__ == '__main__':
    sys.modules.setdefault('app.db', sys.modules[__name__])

CAMPUS_TZ = timezone(timedelta(hours=3), 'Europe/Moscow')


def campus_today():
    return datetime.now(CAMPUS_TZ).date()


def utc_now():
    return datetime.now(timezone.utc)

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///./atlas.db')
connect_args = {'check_same_thread': False, 'timeout': 15} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

if DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def sqlite_foreign_keys(connection, _):
        connection.create_function('casefold', 1, lambda value: (value or '').casefold(), deterministic=True)
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=15000')
        cursor.close()

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(180))
    initials: Mapped[str] = mapped_column(String(8))
    faculty: Mapped[str] = mapped_column(String(180))
    program: Mapped[str] = mapped_column(String(180))
    course: Mapped[int] = mapped_column(Integer)
    group_name: Mapped[str] = mapped_column(String(80))
    student_number: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20), default='student')
    accent: Mapped[str] = mapped_column(String(20), default='purple')

class LoginSession(Base):
    __tablename__ = 'login_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user: Mapped[User] = relationship()

class Lesson(Base):
    __tablename__ = 'lessons'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    weekday: Mapped[int] = mapped_column(Integer)  # Monday=0
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    title: Mapped[str] = mapped_column(String(130))
    kind: Mapped[str] = mapped_column(String(80))
    room: Mapped[str] = mapped_column(String(80))
    teacher: Mapped[str] = mapped_column(String(120))
    color: Mapped[str] = mapped_column(String(20))

class LessonChange(Base):
    __tablename__ = 'lesson_changes'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey('lessons.id'))
    day: Mapped[date] = mapped_column(Date)
    new_room: Mapped[str | None] = mapped_column(String(80), nullable=True)
    new_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    note: Mapped[str] = mapped_column(String(180))

class Grade(Base):
    __tablename__ = 'grades'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    subject: Mapped[str] = mapped_column(String(130))
    kind: Mapped[str] = mapped_column(String(30))
    current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_grade: Mapped[int] = mapped_column(Integer, default=100)
    exam_kind: Mapped[str] = mapped_column(String(80))
    assessment: Mapped[str] = mapped_column(String(80))
    teacher: Mapped[str] = mapped_column(String(120))
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    trend: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default='1')

class Deadline(Base):
    __tablename__ = 'deadlines'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    subject: Mapped[str] = mapped_column(String(130))
    title: Mapped[str] = mapped_column(String(180))
    due_date: Mapped[date] = mapped_column(Date)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)

class DocumentRequest(Base):
    __tablename__ = 'document_requests'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    type: Mapped[str] = mapped_column(String(100))
    comment: Mapped[str] = mapped_column(Text, default='')
    details: Mapped[str] = mapped_column(Text, default='{}', server_default='{}')
    status: Mapped[str] = mapped_column(String(30), default='submitted')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    staff_message: Mapped[str] = mapped_column(Text, default='', server_default='')
    version: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    due_at: Mapped[date | None] = mapped_column(Date, nullable=True)

class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    target: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey('document_requests.id'), nullable=True)


class RequestEvent(Base):
    __tablename__ = 'request_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey('document_requests.id', ondelete='CASCADE'), index=True)
    status: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text, default='')
    actor_role: Mapped[str] = mapped_column(String(20))
    actor_name: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RequestIdempotency(Base):
    __tablename__ = 'request_idempotency'
    __table_args__ = (UniqueConstraint('student_id', 'key', name='uq_request_idempotency_student_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[int] = mapped_column(ForeignKey('document_requests.id'))


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    account_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SchemaMigration(Base):
    __tablename__ = 'schema_migrations'
    version: Mapped[str] = mapped_column(String(30), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index('ix_requests_student_created', DocumentRequest.student_id, DocumentRequest.created_at)
Index('ix_requests_status_created', DocumentRequest.status, DocumentRequest.created_at, DocumentRequest.id)
Index('ix_requests_due_status', DocumentRequest.due_at, DocumentRequest.status)
Index('ix_notifications_student_created', Notification.student_id, Notification.created_at)
Index('ix_notifications_student_read_created', Notification.student_id, Notification.is_read, Notification.created_at)

DOC_TYPES = [
    {'id':'study','name':'Справка об обучении','eta':'1–2 рабочих дня', 'description':'Подтверждение обучения для вымышленного сценария.', 'category':'documents'},
    {'id':'transcript','name':'Выписка об успеваемости','eta':'до 3 рабочих дней', 'description':'Текущие оценки и зачёты по вашим дисциплинам.', 'category':'documents'},
    {'id':'scholarship','name':'Справка о стипендии','eta':'1–2 рабочих дня', 'description':'Демонстрационный ответ о стипендиальном обеспечении.', 'category':'finance'},
    {'id':'statement','name':'Обращение в деканат','eta':'до 5 рабочих дней', 'description':'Вопрос или заявление в свободной форме.', 'category':'other'},
    {'id':'academic_leave','name':'Академический отпуск','eta':'до 5 рабочих дней', 'description':'Заявление на отпуск: укажите причину и желаемый период.', 'category':'academic','requires_comment':True},
    {'id':'resume','name':'Выход из академического отпуска','eta':'до 5 рабочих дней', 'description':'Обращение о возобновлении обучения и индивидуальном плане.', 'category':'academic','requires_comment':True},
    {'id':'individual_plan','name':'Индивидуальный учебный план','eta':'до 5 рабочих дней', 'description':'Согласование графика, дисциплин и сроков обучения.', 'category':'academic','requires_comment':True},
    {'id':'retake','name':'Запись на пересдачу','eta':'до 5 рабочих дней', 'description':'Укажите дисциплину и удобный период пересдачи.', 'category':'academic','requires_comment':True},
    {'id':'appeal','name':'Апелляция по аттестации','eta':'до 5 рабочих дней', 'description':'Укажите дисциплину, дату и основание обращения.', 'category':'academic','requires_comment':True},
    {'id':'transfer','name':'Перевод на другую программу','eta':'до 5 рабочих дней', 'description':'Запрос консультации об учебной разнице и переводе.', 'category':'academic','requires_comment':True},
    {'id':'elective','name':'Выбор факультатива','eta':'до 5 рабочих дней', 'description':'Заявление на дополнительную дисциплину.', 'category':'academic','requires_comment':True},
    {'id':'practice','name':'Направление на практику','eta':'до 5 рабочих дней', 'description':'Согласуйте место, программу и сроки практики.', 'category':'academic','requires_comment':True},
    {'id':'dormitory','name':'Место в общежитии','eta':'до 5 рабочих дней', 'description':'Заявление на заселение или продление проживания.', 'category':'campus','requires_comment':True},
    {'id':'social_support','name':'Материальная поддержка','eta':'до 5 рабочих дней', 'description':'Вымышленное обращение о помощи и сопровождении.', 'category':'finance','requires_comment':True},
    {'id':'tuition','name':'Вопрос об оплате обучения','eta':'до 5 рабочих дней', 'description':'Уточнение демонстрационной финансовой ленты.', 'category':'finance','requires_comment':True},
    {'id':'tax','name':'Справка об оплате обучения','eta':'до 3 рабочих дней', 'description':'Образец ответа по расходам. Не для налоговой подачи.', 'category':'documents'},
    {'id':'student_card','name':'Восстановление студенческого','eta':'до 5 рабочих дней', 'description':'Сообщите об утрате вымышленного пропуска.', 'category':'documents','requires_comment':True},
    {'id':'name_change','name':'Исправление сведений профиля','eta':'до 5 рабочих дней', 'description':'Передайте сотруднику запрос на уточнение данных.', 'category':'other','requires_comment':True},
    {'id':'accessibility','name':'Особые условия обучения','eta':'до 5 рабочих дней', 'description':'Запрос доступного формата или индивидуального сопровождения. Без медицинских данных.', 'category':'campus','requires_comment':True},
    {'id':'mobility','name':'Академическая мобильность','eta':'до 5 рабочих дней', 'description':'Консультация по обмену и перезачёту дисциплин.', 'category':'academic','requires_comment':True},
    {'id':'graduation','name':'Выпуск и итоговая аттестация','eta':'до 5 рабочих дней', 'description':'Вопрос по ВКР, итоговому экзамену и выпускным документам.', 'category':'academic','requires_comment':True},
    {'id':'military','name':'Справка для воинского учёта','eta':'до 3 рабочих дней', 'description':'Конкурсный образец без реквизитов официального документа.', 'category':'documents'},
]
DOC_NAMES = {x['id']:x['name'] for x in DOC_TYPES}


def add_business_days(start: date, count: int) -> date:
    result = start
    while count:
        result += timedelta(days=1)
        if result.weekday() < 5:
            count -= 1
    return result


def request_due_date(type_name: str, start: date) -> date:
    short = {'study', 'scholarship'}
    regular = {'transcript', 'tax', 'military'}
    key = next((key for key, name in DOC_NAMES.items() if name == type_name), 'statement')
    count = 2 if key in short else 3 if key in regular else 5
    return add_business_days(start, count)


def migrate_database():
    """Additive, versioned upgrade of v1 databases, preserving every existing row.

    Startup holds a database lock, so concurrent workers cannot race the DDL.
    All identifiers below are fixed by source, never provided by a client.
    """
    # Register additive extension tables before metadata creation. These imports
    # do not create a connection, run DDL or seed data by themselves.
    from . import learning_db, services_db, campus_db, improvement_db, university_db, workspace_db, units_db  # noqa: F401
    with engine.begin() as connection:
        if engine.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(2026110601)'))
        elif engine.dialect.name == 'sqlite':
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection)
        columns = {column['name'] for column in inspect(connection).get_columns('document_requests')}
        for name, sql_type in [
            ('staff_message', "TEXT NOT NULL DEFAULT ''"),
            ('version', 'INTEGER NOT NULL DEFAULT 1'),
            ('due_at', 'DATE'),
            ('details', "TEXT NOT NULL DEFAULT '{}'"),
        ]:
            if name not in columns:
                connection.exec_driver_sql(f'ALTER TABLE document_requests ADD COLUMN {name} {sql_type}')
        columns = {column['name'] for column in inspect(connection).get_columns('notifications')}
        for name, sql_type in [('target', 'VARCHAR(100)'), ('request_id', 'INTEGER REFERENCES document_requests(id)')]:
            if name not in columns:
                connection.exec_driver_sql(f'ALTER TABLE notifications ADD COLUMN {name} {sql_type}')
        for model in (DocumentRequest, Notification, LoginSession):
            for index in model.__table__.indexes:
                index.create(connection, checkfirst=True)
        versions = set(connection.execute(select(SchemaMigration.version)).scalars())
        if '0002_workflow' not in versions:
            with SessionLocal(bind=connection) as db:
                for row in db.scalars(select(DocumentRequest)).all():
                    row.due_at = request_due_date(row.type, as_utc(row.created_at).astimezone(CAMPUS_TZ).date())
                    if row.status == 'ready' and not row.staff_message:
                        row.staff_message = 'Демонстрационный документ подготовлен. Все данные вымышлены.'
                    db.add(RequestEvent(request_id=row.id, status=row.status, message='Заявка сохранена в предыдущей версии прототипа; ранние этапы не восстанавливались.', actor_role='system', actor_name='Система', created_at=row.updated_at))
                for notification in db.scalars(select(Notification)).all():
                    notification.target = {'schedule': '/app/schedule', 'deadline': '/app/plan', 'request': '/app/requests'}.get(notification.category)
                db.add(SchemaMigration(version='0002_workflow', applied_at=utc_now()))
                db.flush()
        if '0003_listing_indexes' not in versions:
            connection.execute(SchemaMigration.__table__.insert().values(version='0003_listing_indexes', applied_at=utc_now()))
        if '0004_full_campus' not in versions:
            connection.execute(SchemaMigration.__table__.insert().values(version='0004_full_campus', applied_at=utc_now()))
        if '0005_contest_hardening' not in versions:
            connection.execute(SchemaMigration.__table__.insert().values(version='0005_contest_hardening', applied_at=utc_now()))
        if '0006_audit_integrity' not in versions:
            from .audit_migration import upgrade_integrity
            upgrade_integrity(connection)
            connection.execute(SchemaMigration.__table__.insert().values(version='0006_audit_integrity', applied_at=utc_now()))
        if '0007_university_library_direct' not in versions:
            connection.execute(SchemaMigration.__table__.insert().values(version='0007_university_library_direct', applied_at=utc_now()))
        if '0008_academic_workspace' not in versions:
            for name in ('grades', 'learning_attendance'):
                if 'version' not in {column['name'] for column in inspect(connection).get_columns(name)}:
                    connection.exec_driver_sql(f'ALTER TABLE {name} ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
            connection.execute(SchemaMigration.__table__.insert().values(version='0008_academic_workspace', applied_at=utc_now()))
        if '0009_student_units' not in versions:
            connection.execute(SchemaMigration.__table__.insert().values(version='0009_student_units', applied_at=utc_now()))


def seed_demo(session=None):
    """Insert fictional fixtures only when the users table is completely empty."""
    with (nullcontext(session) if session is not None else SessionLocal()) as db:
        if db.query(User).first(): return
        students = [
            User(login='alina.demo', password_hash=password_hasher.hash('AtlasDemo!2026-A'), full_name='Алина Ветрова', initials='АВ', faculty='Институт цифровых технологий', program='Информационные системы и технологии', course=2, group_name='ИТ-24-03', student_number='AT-2024-001', accent='purple'),
            User(login='mark.demo', password_hash=password_hasher.hash('AtlasDemo!2026-M'), full_name='Марк Северин', initials='МС', faculty='Факультет прикладных наук', program='Прикладная информатика', course=3, group_name='ПИ-23-02', student_number='AT-2023-002', accent='orange'),
        ]
        staff = User(login='dean.demo', password_hash=password_hasher.hash('AtlasStaff!2026-D'), full_name='Кира Миронова', initials='КМ', faculty='Студенческий офис', program='Сопровождение студентов', course=0, group_name='Сотрудник', student_number='AT-STAFF-001', role='staff', accent='blue')
        db.add_all([*students, staff]); db.flush()
        subjects = [
            [('Алгоритмы и структуры данных','М. Орлов',86,6,'exam', 'Экзамен','violet'),('Проектирование интерфейсов','Н. Ласточкина',93,3,'credit','Зачёт','blue'),('Теория вероятностей','Р. Соловьёв',58,-4,'exam','Экзамен','orange'),('Базы данных','Е. Рябинина',79,8,'exam','Экзамен','teal'),('Английский язык','Л. Голубева',100,0,'credit','Зачёт','pink')],
            [('Инженерия ПО','А. Громов',95,6,'exam','Экзамен','violet'),('Компьютерные сети','С. Белова',72,1,'exam','Экзамен','blue'),('Анализ данных','Д. Зорин',64,-3,'exam','Экзамен','orange'),('Управление проектами','В. Весенняя',88,4,'credit','Зачёт','teal'),('Право в цифровой среде','Т. Ларина',80,0,'credit','Зачёт','pink')],
        ]
        times=[('09:00','10:30'),('10:45','12:15'),('13:05','14:35'),('14:50','16:20')]
        for index,stu in enumerate(students):
            grads=subjects[index]
            for j,(sub,teacher,score,trend,kind,assessment,color) in enumerate(grads):
                db.add(Grade(student_id=stu.id,subject=sub,teacher=teacher,current=score,trend=trend,kind=kind,exam_kind=assessment,assessment='Зачтено' if kind=='credit' and score>=65 else ('Не зачтено' if kind=='credit' else 'Допуск'),exam_date=date(2026,12,14)+timedelta(days=j*2) if kind=='exam' else None,color=color))
            # Different timetable for each account; stable across all weeks.
            rotations = [[0,1,2],[3,4],[2,0,3],[1,4,0],[3,2]] if index==0 else [[1,3],[0,2,4],[2,1],[4,0,3],[1,2]]
            for weekday,selected in enumerate(rotations):
                for slot,k in enumerate(selected):
                    sub,teacher,_,_,kind,_,color=grads[k]
                    start,end=times[slot + (1 if weekday==4 else 0)]
                    db.add(Lesson(student_id=stu.id, weekday=weekday,start_time=start,end_time=end,title=sub,kind=['Лекция','Практика','Семинар'][(slot+weekday)%3], room=['А-301','Б-208','Онлайн','В-412','Б-115'][(slot+weekday+index)%5],teacher=teacher,color=color))
            db.flush()
            week_monday = campus_today() - timedelta(days=campus_today().weekday())
            lesson = db.query(Lesson).filter_by(student_id=stu.id,weekday=3).first()
            for w in range(12):
                change_date = week_monday + timedelta(days=w*7+3)
                db.add(LessonChange(student_id=stu.id, lesson_id=lesson.id, day=change_date,
                                    new_room='В-404' if index==0 else 'А-509', new_start=None,
                                    note='Аудитория изменена преподавателем'))
            if index==0:
                move = db.query(Lesson).filter_by(student_id=stu.id,weekday=2).first()
                db.add(LessonChange(student_id=stu.id, lesson_id=move.id,
                                    day=week_monday+timedelta(days=9),new_room='Онлайн',
                                    new_start='11:00',note='Пара перенесена на 11:00, формат — онлайн'))
            d0 = campus_today()
            due=[(grads[0][0], 'Лабораторная работа №4',3),
                 (grads[2][0],'Домашняя работа: вариант 7',7),
                 (grads[3][0],'Практическое задание',12),
                 (grads[1][0],'Проектная работа',24),
                 (grads[0][0],'Итоговая работа',34)] if index==0 else [
                 (grads[1][0],'Схема корпоративной сети',5),
                 (grads[2][0],'Мини-проект: классификация',8),
                 (grads[0][0],'Код-ревью проекта',13),
                 (grads[3][0],'Доклад по проекту',25),
                 (grads[4][0],'Контрольная работа',36)]
            for sub,title,days in due:
                db.add(Deadline(student_id=stu.id,subject=sub,title=title,
                                due_date=d0+timedelta(days=days)))
            now=utc_now()
            demo_reqs = [(DOC_NAMES['study'],'ready',now-timedelta(days=8)),(DOC_NAMES['transcript'],'review',now-timedelta(days=2))] if index==0 else [(DOC_NAMES['scholarship'],'processing',now-timedelta(days=1))]
            for title,status,dt in demo_reqs:
                row = DocumentRequest(student_id=stu.id,type=title,comment='',status=status,created_at=dt,updated_at=dt+timedelta(hours=3), due_at=request_due_date(title,dt.astimezone(CAMPUS_TZ).date()),staff_message='Демонстрационный документ подготовлен. Все данные вымышлены.' if status=='ready' else '')
                db.add(row); db.flush()
                db.add(RequestEvent(request_id=row.id,status=status,message='Вымышленная заявка для демонстрации сценария.',actor_role='system',actor_name='Система',created_at=row.updated_at))
            news=[('Изменение в расписании','Проверьте аудиторию: для одной из пар внесён перенос.','schedule',0),('Скоро дедлайн','До ближайшего задания осталось несколько дней.','deadline',1),('Началась запись на консультации','График консультаций по дисциплинам опубликован в учебном офисе.','announcement',3),('Окно заявок открыто','Теперь справки можно заказать прямо в кабинете.','request',5)]
            for title,body,cat,daysago in news: db.add(Notification(student_id=stu.id,title=title,body=body,category=cat,created_at=now-timedelta(days=daysago),is_read=daysago>=3,target={'schedule':'/app/schedule','deadline':'/app/plan','request':'/app/requests'}.get(cat)))
        if session is None:
            db.commit()
        else:
            db.flush()


def initialize_database():
    settings.validate(DATABASE_URL)
    migrate_database()
    if settings.demo_mode:
        # Fixtures are initialized once, including in deployments with >1 worker.
        with engine.begin() as connection:
            if engine.dialect.name == 'postgresql':
                connection.execute(text('SELECT pg_advisory_xact_lock(2026110602)'))
            elif engine.dialect.name == 'sqlite':
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            with SessionLocal(bind=connection) as db:
                if db.scalar(select(User.id).limit(1)) is None:
                    seed_demo(db)
                from .learning_db import seed_learning
                from .services_db import seed_services
                from .university_seed import seed_university
                from .workspace_seed import seed_workspace
                from .units_seed import seed_units
                seed_learning(db)
                seed_services(db)
                seed_university(db)
                seed_workspace(db)
                seed_units(db)
                db.flush()
    elif settings.app_env == 'production':
        with SessionLocal() as db:
            if db.scalar(select(User.id).where(User.login.in_(DEMO_LOGINS)).limit(1)):
                raise RuntimeError('DEMO_MODE=false cannot run a production database containing public demo accounts')


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else 'migrate'
    if command == 'migrate':
        settings.validate(DATABASE_URL)
        migrate_database()
        print('Database migrations applied; existing records preserved.')
    elif command == 'seed':
        if not settings.demo_mode:
            raise SystemExit('Seeding requires DEMO_MODE=true')
        initialize_database()
        print('Fictional demo fixtures initialized (existing users were preserved).')
    else:
        raise SystemExit('Usage: python -m app.db [migrate|seed]')
