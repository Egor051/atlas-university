"""Campus-wide editorial publications, independent from personal notifications."""
from datetime import datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, inspect, select, text, update
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
    summary: Mapped[str] = mapped_column(Text, server_default='')
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


ORIGINAL_PUBLICATIONS = {
    'support': ('Консультации преподавателей',
                'В разделе «Консультации» можно посмотреть свободные часы и записаться на встречу с преподавателем. '
                'Если нужно обсудить задание или результаты аттестации, подготовьте вопросы заранее.'),
    'deadlines': ('Ближайшие сроки сдачи работ',
                  'Проверьте раздел «Задания». В нём собраны сроки, условия сдачи и комментарии преподавателей. '
                  'Если требуется уточнение по работе, свяжитесь с преподавателем по дисциплине.'),
    'documents': ('Справки в личном кабинете',
                  'Документы можно заказать в разделе «Справки». Там указаны сроки подготовки, '
                  'ответственные и перечень необходимых сведений.'),
}
PUBLICATIONS = {
    'support': (
        'Как записаться на консультацию перед аттестацией', 'academic', 'normal',
        'В разделе «Консультации» можно посмотреть свободные часы преподавателей по дисциплинам. Запишитесь заранее '
        'и подготовьте конкретные вопросы по темам, результатам или возвращённым на доработку заданиям.',
        'Консультация помогает разобрать сложную тему или уточнить требования к работе. В карточке записи указаны '
        'преподаватель, дисциплина, время и аудитория. Выберите удобный свободный слот и откройте календарь, чтобы '
        'проверить пересечения с занятиями.\n\n'
        '## Что взять на встречу\n\n'
        'Подготовьте список из двух-трёх вопросов. Если разбираете работу, откройте инструкцию к заданию, предыдущую '
        'попытку и комментарий преподавателя. Покажите, на каком шаге остановились и что уже успели проверить.\n\n'
        'Освободите слот, если планы изменились. Для вопросов о порядке аттестации и заявлениях можно обратиться '
        'в учебный офис через переписку в кабинете.',
    ),
    'deadlines': (
        'Подготовка к сессии: проверьте сроки и вернувшиеся работы', 'deadline', 'important',
        'В «Сдаче работ» видны сроки, способы отправки и замечания преподавателей. Сначала проверьте задания с ближайшим '
        'дедлайном и работы, которые нужно исправить. Даты аттестации смотрите в разделе «Сессия и зачёты».',
        'Начните с заданий, от которых зависит подготовка к аттестации. Откройте работу в «Сдаче работ»: в карточке '
        'есть инструкция, разрешённые способы отправки и условия поздней сдачи. Проверьте дату и время дедлайна по МСК.\n\n'
        '## Если работу вернули на доработку\n\n'
        'Прочитайте замечания к последней отправке и проверьте срок повторной сдачи. После исправлений отправьте новую '
        'версию из карточки задания. Преподаватель увидит её вместе с предыдущими попытками и комментариями.\n\n'
        '## Куда смотреть после проверки\n\n'
        'Проверьте принятые работы и начисленные баллы в разделе «Успеваемость и посещаемость». Если нужна помощь '
        'с заданием, запишитесь на консультацию по дисциплине или напишите преподавателю. Подготовьте название работы '
        'и конкретный вопрос, чтобы преподавателю было проще найти её в журнале.',
    ),
    'documents': (
        'Какие сведения нужны для заказа справки в кабинете', 'announcement', 'normal',
        'Откройте «Справки», выберите нужный документ и проверьте список полей перед отправкой. Номер заказа, '
        'срок подготовки и ответ учебного офиса сохраняются в истории.',
        'В каталоге справок есть карточки с назначением каждого документа и ориентиром по сроку подготовки. '
        'Перед отправкой проверьте выбранный тип, нужный период и количество экземпляров, если форма их запрашивает.\n\n'
        'Статус и ответ сотрудника можно посмотреть в «Моих справках». Если учебный офис запросил сведения, '
        'откройте историю заказа и добавьте уточнение к тому же обращению. Когда подготовка завершится, в карточке '
        'появится действие для просмотра документа.',
    ),
    'conference': (
        'Научная конференция: подготовьте тезисы для студенческой секции', 'campus', 'normal',
        'Студенческая секция принимает темы по разработке, анализу данных и проектированию. Для обсуждения темы '
        'подготовьте короткие тезисы и опишите свой вклад в работу.',
        'Для выступления подойдёт исследование, курсовая работа или проект с результатом, который можно объяснить '
        'аудитории другой специальности. В заявке кратко сформулируйте вопрос, метод и результат.\n\n'
        '## Как подготовить материал\n\n'
        'Вынесите главный вывод в начало тезисов. Для прикладного проекта опишите сценарий, который вы проверили. '
        'Для исследования отметьте, какие данные использовали и какие ограничения есть у результата. '
        'В командном проекте перечислите участников и укажите, кто представит работу.\n\n'
        'Обсудите тезисы с преподавателем: он поможет выбрать объём выступления и подготовить ответы на вопросы. '
        'За новостями секции и университетскими встречами следите в разделе «Вне учёбы».',
    ),
    'electives': (
        'Как выбрать факультатив и проверить пересечения в расписании', 'academic', 'normal',
        'Перед выбором факультатива сравните содержание программы с текущим расписанием. Проверьте, сколько '
        'времени потребуется на занятия и самостоятельную работу.',
        'Начните с цели: хотите закрыть пробел по дисциплине, попробовать смежную область или подготовить проект. '
        'Сверьте темы занятий с опубликованными материалами и уточните у преподавателя, нужна ли предварительная подготовка.\n\n'
        'Если выбранный курс пересекается с парой или практикой, уточните возможные варианты учебной группы '
        'через учебный офис. После согласования проверьте расписание и внесите сроки работ в личный план.',
    ),
    'schedule': (
        'Где проверить перенос пары и номер аудитории', 'academic', 'important',
        'Расписание занятий может меняться по неделям. Перед выходом на занятия откройте нужную дату и проверьте '
        'время, корпус и аудиторию.',
        'В карточке занятия видны название дисциплины, преподаватель и место проведения. Переключатель недели '
        'поможет сверить расписание на нужную дату. Если рядом с занятием появилось сообщение о переносе, проверьте '
        'новое время и корпус даже при знакомом номере аудитории.\n\n'
        'Если уточнение требуется для нескольких студентов, учебный офис разместит информацию в расписании или '
        'в объявлении для группы. В личном кабинете отдельно проверьте уведомления о своей учебной неделе.',
    ),
}


def upgrade_summaries(connection):
    if 'summary' not in {column['name'] for column in inspect(connection).get_columns(Announcement.__tablename__)}:
        connection.execute(text("ALTER TABLE campus_announcements ADD COLUMN summary TEXT NOT NULL DEFAULT ''"))
    table = Announcement.__table__
    for key, (old_title, old_body) in ORIGINAL_PUBLICATIONS.items():
        title, _category, _priority, summary, body = PUBLICATIONS[key]
        connection.execute(update(table).where(table.c.fixture_key == key, table.c.version == 1,
                           table.c.title == old_title, table.c.body == old_body, table.c.summary == '')
                           .values(title=title, summary=summary, body=body))


def seed_announcements(db):
    """Insert the bundled campus publications once per database."""
    author_id = db.scalar(select(User.id).where(User.login == 'dean.demo', User.role == 'staff'))
    if author_id is None:
        return
    existing = set(db.scalars(select(Announcement.fixture_key).where(Announcement.fixture_key.is_not(None))))
    now = utc_now()
    for age, (key, (title, category, priority, summary, body)) in enumerate(PUBLICATIONS.items()):
        if key in existing:
            continue
        published = now - timedelta(days=age)
        db.add(Announcement(author_id=author_id, title=title, summary=summary, body=body, category=category,
                            priority=priority, audience='all', status='published', pinned=key == 'documents',
                            created_at=published, updated_at=published, published_at=published, fixture_key=key))
