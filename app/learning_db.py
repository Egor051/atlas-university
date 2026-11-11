"""Additive study workspace models. Every person and academic record is fictional."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, User, Grade, campus_today, utc_now
from .storage_guards import new_record_token


class LearningSeed(Base):
    __tablename__ = 'learning_seeds'
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    version: Mapped[str] = mapped_column(String(30), default='0004_learning')


class Course(Base):
    __tablename__ = 'learning_courses'
    __table_args__ = (UniqueConstraint('student_id', 'grade_id', name='uq_learning_course_student_grade'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey('grades.id'))
    subject: Mapped[str] = mapped_column(String(130))
    teacher: Mapped[str] = mapped_column(String(120))
    credits: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(20))


class CourseModule(Base):
    __tablename__ = 'learning_course_modules'
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey('learning_courses.id', ondelete='CASCADE'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(180))
    content: Mapped[str] = mapped_column(Text)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)


class AssignmentSubmission(Base):
    __tablename__ = 'learning_submissions'
    __table_args__ = (UniqueConstraint('student_id', 'deadline_id', name='uq_learning_submission_student_deadline'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    deadline_id: Mapped[int] = mapped_column(ForeignKey('deadlines.id'))
    text: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(500), default='')
    status: Mapped[str] = mapped_column(String(30), default='submitted')
    version: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StudyNote(Base):
    __tablename__ = 'learning_notes'
    id: Mapped[int] = mapped_column(primary_key=True)
    record_token: Mapped[str] = mapped_column(String(32), default=new_record_token, server_default='', unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(180))
    subject: Mapped[str] = mapped_column(String(130), default='')
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Flashcard(Base):
    __tablename__ = 'learning_flashcards'
    id: Mapped[int] = mapped_column(primary_key=True)
    record_token: Mapped[str] = mapped_column(String(32), default=new_record_token, server_default='', unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    subject: Mapped[str] = mapped_column(String(130))
    front: Mapped[str] = mapped_column(String(500))
    back: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date)
    reviews: Mapped[int] = mapped_column(Integer, default=0)
    known_count: Mapped[int] = mapped_column(Integer, default=0)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)


class Quiz(Base):
    __tablename__ = 'learning_quizzes'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(180))
    subject: Mapped[str] = mapped_column(String(130))
    description: Mapped[str] = mapped_column(Text)
    # Server-only key and explanations. Never return this field in GET payloads.
    questions_json: Mapped[str] = mapped_column(Text)


class QuizAttempt(Base):
    __tablename__ = 'learning_quiz_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey('learning_quizzes.id'))
    answers_json: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Attendance(Base):
    __tablename__ = 'learning_attendance'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    subject: Mapped[str] = mapped_column(String(130))
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(300), default='')
    version: Mapped[int] = mapped_column(Integer, default=1, server_default='1')


class PersonalTask(Base):
    __tablename__ = 'learning_tasks'
    id: Mapped[int] = mapped_column(primary_key=True)
    record_token: Mapped[str] = mapped_column(String(32), default=new_record_token, server_default='', unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(180))
    subject: Mapped[str] = mapped_column(String(130), default='')
    due_date: Mapped[date] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(20), default='normal')
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FocusSession(Base):
    __tablename__ = 'learning_focus_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    record_token: Mapped[str] = mapped_column(String(32), default=new_record_token, server_default='', unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    subject: Mapped[str] = mapped_column(String(130))
    minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Original, concise teaching material, authored for this fictional prototype.
COURSE_CONTENT = {
    'Алгоритмы и структуры данных': [
        ('Сложность алгоритмов', 'O(n) описывает рост числа операций при увеличении входа. Для последовательного поиска нужно проверить до n элементов; двоичный поиск работает за O(log n), но требует упорядоченного массива. Сравнивайте время и дополнительную память отдельно.'),
        ('Массивы, списки и хеш-таблицы', 'Массив даёт доступ по индексу за O(1), а вставка в середину требует сдвига. Связный список хранит ссылки на соседние элементы. Хеш-таблица сопоставляет ключ корзине; коллизии требуют отдельной обработки.'),
        ('Графы и обходы', 'Граф состоит из вершин и рёбер. BFS использует очередь и находит кратчайший путь по числу рёбер в невзвешенном графе. DFS использует стек или рекурсию и полезен для поиска компонент и циклов.'),
        ('Практика и проверка решения', 'Начните с контрпримеров: пустой вход, один элемент, повторяющиеся значения и предельный размер. Сформулируйте инвариант цикла, затем объясните завершение алгоритма и его сложность.'),
    ],
    'Проектирование интерфейсов': [
        ('Пользовательская задача', 'Опишите пользователя, ситуацию и результат, который ему нужен. Сценарий «получить справку с телефона» полезнее перечня экранов. Гипотезу проверяют наблюдением и добровольным интервью, а не придуманной цитатой.'),
        ('Структура и навигация', 'Группируйте разделы по задачам, используйте знакомые названия и показывайте текущее местоположение. Важные действия должны быть доступны с клавиатуры и иметь понятный фокус.'),
        ('Компоненты и состояния', 'Для формы предусмотрите подпись поля, помощь, ошибку и подтверждение. Для списка нужны загрузка, пустой результат, ошибка и восстановление. Цвет не должен быть единственным носителем смысла.'),
        ('Проверка прототипа', 'Попросите участника выполнить конкретную задачу без подсказок. Запишите затруднения без персональных данных. Проверьте 360 px, увеличение текста и последовательность фокуса.'),
    ],
    'Теория вероятностей': [
        ('События и вероятность', 'Вероятность лежит от 0 до 1. Для несовместных событий P(A∪B)=P(A)+P(B). В общем случае нужно вычесть P(A∩B), чтобы не посчитать пересечение дважды.'),
        ('Условная вероятность', 'P(A|B)=P(A∩B)/P(B), если P(B)>0. Независимость означает P(A∩B)=P(A)P(B). Несовместность и независимость — разные свойства.'),
        ('Случайные величины', 'Математическое ожидание дискретной величины — сумма x·P(X=x). Дисперсия E[(X−E[X])²] измеряет разброс. При независимости дисперсии суммы складываются.'),
        ('Решение задач', 'Сначала задайте пространство исходов и допущения. Для комбинаторной задачи уточните, учитываются ли порядок и повторения. Проверяйте, что итоговая вероятность находится в [0,1].'),
    ],
    'Базы данных': [
        ('Модель данных', 'Сущности имеют ключи, связи и ограничения. Внешний ключ связывает записи и защищает ссылочную целостность. NOT NULL и UNIQUE выражают правила, которые должны соблюдаться независимо от интерфейса.'),
        ('SELECT и соединения', 'WHERE фильтрует строки, JOIN связывает таблицы, GROUP BY объединяет строки для агрегатов. Условия доступа по владельцу применяют в запросе до ограничения количества результатов.'),
        ('Транзакции', 'Транзакция объединяет связанные изменения: либо сохраняются все, либо ни одно. Уровень изоляции определяет видимость параллельных изменений. Уникальное ограничение защищает от дубликатов при гонке.'),
        ('Индексы и запросы', 'Индекс ускоряет подходящие чтения ценой памяти и дополнительных операций записи. Проверяйте план запроса, а не добавляйте индексы к каждому полю. Параметризуйте пользовательские значения.'),
    ],
    'Английский язык': [
        ('Чтение учебного текста', 'Перед чтением просмотрите заголовки и сформулируйте вопрос. Сначала найдите основную мысль, затем уточните термины по контексту. Запишите краткое резюме своими словами.'),
        ('Академическая лексика', 'Собирайте слова вместе с примером употребления. Compare — сравнивать; evidence — доказательства; approach — подход. Повторяйте карточки с увеличивающимися интервалами.'),
        ('Письмо преподавателю', 'Укажите понятную тему, представьтесь и задайте один конкретный вопрос. Вежливая формулировка: Could you clarify the submission deadline? Закончите благодарностью и подписью.'),
        ('Краткое выступление', 'Начните с темы и плана, изложите два-три тезиса и завершите выводом. Проговорите выступление вслух и проверьте время. Не читайте весь текст со слайда.'),
    ],
    'Инженерия ПО': [
        ('Требования и критерии приёмки', 'Опишите наблюдаемое поведение системы и ограничения. Критерий приёмки связывает вход, действие и результат. Нефункциональные требования включают доступность, безопасность и скорость.'),
        ('Архитектура и границы', 'Разделяйте ответственность модулей и фиксируйте их контракты. Изменение одного модуля не должно требовать знания внутреннего устройства всех остальных. Проверяйте источник идентификатора владельца.'),
        ('Тестирование', 'Проверяйте важные пользовательские пути, границы, отказы и права доступа. Регрессионный тест воспроизводит найденную ошибку и сохраняет ожидаемое поведение после исправления.'),
        ('Код-ревью и выпуск', 'Проверяйте корректность, понятность и угрозы. Небольшие изменения проще оценить. Перед выпуском подтвердите сохранение данных, работу миграций и возможность восстановления.'),
    ],
    'Компьютерные сети': [
        ('Уровни и протоколы', 'Канальный уровень передаёт кадры в локальной сети, сетевой маршрутизирует пакеты, транспортный связывает приложения. TCP предоставляет упорядоченный поток, UDP — отдельные датаграммы.'),
        ('IP-адреса и подсети', 'Префикс /24 оставляет восемь бит для адресов внутри IPv4-подсети. Маска определяет сетевую часть адреса. Для связи за пределами подсети используется шлюз.'),
        ('DNS и HTTPS', 'DNS сопоставляет имя адресам и другим записям. TLS шифрует обмен и подтверждает сервер сертификатом. Наличие HTTPS не заменяет проверку прав доступа в приложении.'),
        ('Диагностика', 'Проверяйте последовательно: интерфейс, адрес и маршрут, разрешение имени, доступность порта и ответ приложения. Таймаут и отказ соединения указывают на разные классы причин.'),
    ],
    'Анализ данных': [
        ('Постановка вопроса', 'Сформулируйте измеримый вопрос до выбора модели. Разделите признаки и целевую переменную, проверьте единицы измерения, пропуски и дубликаты.'),
        ('Описательная статистика', 'Среднее чувствительно к выбросам, медиана устойчивее. Показывайте разброс и размер выборки. Корреляция описывает связь, но сама по себе не доказывает причину.'),
        ('Обучение и проверка', 'Разделяйте обучающую и тестовую выборки до подготовки признаков. Утечка целевой информации завышает метрики. Для временных данных соблюдайте порядок наблюдений.'),
        ('Метрики и интерпретация', 'Для несбалансированных классов одной accuracy мало. Precision отражает долю верных положительных ответов, recall — долю найденных положительных объектов. Выбор зависит от цены ошибки.'),
    ],
    'Управление проектами': [
        ('Цель и результат', 'Опишите результат проекта, границы и критерий завершения. Разделите обязательные требования и пожелания. У задачи должен быть ответственный и проверяемый результат.'),
        ('План и зависимости', 'Разбейте работу на обозримые шаги. Зависимости показывают, что нельзя начать раньше завершения другого шага. Буфер помогает учесть неопределённость, но не заменяет оценку.'),
        ('Риски', 'Для риска зафиксируйте событие, вероятность, влияние и действие при наступлении. Следите за ранними признаками. Проблема уже произошла, риск ещё может произойти.'),
        ('Обратная связь', 'Показывайте промежуточный результат и проверяйте ожидания. На ретроспективе выберите конкретное улучшение процесса и способ проверить его эффект.'),
    ],
    'Право в цифровой среде': [
        ('Источники и контекст', 'Отличайте нормативный акт, договор и мнение автора. Для учебного разбора фиксируйте дату и юрисдикцию источника. Материал прототипа не является юридической консультацией.'),
        ('Данные и доступ', 'Для учебного кейса определите, какие данные собираются, зачем, кто имеет доступ и когда данные удаляются. В этом прототипе используются только вымышленные записи.'),
        ('Авторские материалы', 'Проверяйте условия лицензии до использования кода, шрифта или изображения. Открытый доступ к файлу не означает разрешение на любое использование. Фиксируйте источник и условия.'),
        ('Разбор ситуации', 'Разделите факты, предположения и вопросы. Определите заинтересованные стороны и требуемые доказательства. Для практического решения обращаются к актуальным первичным источникам.'),
    ],
}


QUIZ_CONTENT = {
    'Алгоритмы и структуры данных': [
        {'prompt': 'Какова сложность двоичного поиска в отсортированном массиве?', 'options': ['O(n²)', 'O(log n)', 'O(n)'], 'correct': 1, 'explanation': 'На каждом шаге область поиска уменьшается примерно вдвое.'},
        {'prompt': 'Какая структура нужна для классического BFS?', 'options': ['Очередь', 'Стек', 'Множество без порядка'], 'correct': 0, 'explanation': 'Очередь обеспечивает обработку вершин по расстоянию от начальной.'},
        {'prompt': 'Что обязательно проверить при тестировании сортировки?', 'options': ['Только случайный массив', 'Только положительные числа', 'Пустой массив и повторяющиеся значения'], 'correct': 2, 'explanation': 'Пустой вход и дубликаты часто выявляют ошибки границ и сравнения.'},
    ],
    'Теория вероятностей': [
        {'prompt': 'Если A и B независимы, чему равна P(A∩B)?', 'options': ['P(A)+P(B)', 'P(A)P(B)', '0 всегда'], 'correct': 1, 'explanation': 'Для независимых событий вероятность пересечения равна произведению вероятностей.'},
        {'prompt': 'Какое значение может быть вероятностью?', 'options': ['−0,2', '1,2', '0,7'], 'correct': 2, 'explanation': 'Вероятность неотрицательна и не превышает единицу.'},
        {'prompt': 'Как вычисляют P(A|B), если P(B)>0?', 'options': ['P(A∩B)/P(B)', 'P(A)/P(A∩B)', 'P(A)+P(B)'], 'correct': 0, 'explanation': 'Условная вероятность ограничивает пространство исходов событием B.'},
    ],
    'Инженерия ПО': [
        {'prompt': 'Что делает критерий приёмки полезным?', 'options': ['Описание наблюдаемого результата', 'Число использованных библиотек', 'Длина технического текста'], 'correct': 0, 'explanation': 'Критерий должен позволять проверить, выполнено ли ожидаемое поведение.'},
        {'prompt': 'Зачем нужен регрессионный тест?', 'options': ['Ускорить любую программу', 'Не допустить возврата найденной ошибки', 'Заменить проверку прав доступа'], 'correct': 1, 'explanation': 'Тест воспроизводит исправленную ошибку и проверяет ожидаемый результат.'},
        {'prompt': 'Откуда сервер должен брать владельца личной записи?', 'options': ['Из параметра student_id браузера', 'Из названия группы', 'Из подтверждённой сессии'], 'correct': 2, 'explanation': 'Браузер может подменить любой переданный идентификатор; источник владельца — серверная сессия.'},
    ],
    'Анализ данных': [
        {'prompt': 'Когда нужно отделять тестовую выборку?', 'options': ['До подготовки признаков', 'После подбора всех параметров', 'Только после публикации модели'], 'correct': 0, 'explanation': 'Раннее разделение уменьшает риск утечки информации из тестовых данных.'},
        {'prompt': 'Что само по себе доказывает наличие причинной связи?', 'options': ['Высокая корреляция', 'Совпадение трендов', 'Ни один из этих признаков'], 'correct': 2, 'explanation': 'Корреляция может возникать из-за третьих факторов или случайности.'},
        {'prompt': 'Что измеряет recall?', 'options': ['Долю верных среди предсказанных положительных', 'Долю найденных среди всех положительных', 'Среднюю абсолютную ошибку'], 'correct': 1, 'explanation': 'Recall = TP/(TP+FN), доля обнаруженных положительных объектов.'},
    ],
}


def seed_learning(db):
    """One-time additive demo expansion; edits/deletions survive later restarts."""
    students = db.scalars(select(User).where(User.role == 'student', User.login.in_(['alina.demo', 'mark.demo']))).all()
    for student in students:
        if db.get(LearningSeed, student.id):
            continue
        grades = db.scalars(select(Grade).where(Grade.student_id == student.id).order_by(Grade.id)).all()
        if not grades:
            continue
        now, day = utc_now(), campus_today()
        for index, grade in enumerate(grades):
            course = db.scalar(select(Course).where(Course.student_id == student.id, Course.grade_id == grade.id))
            if course is None:
                course = Course(student_id=student.id, grade_id=grade.id, subject=grade.subject,
                                teacher=grade.teacher, credits=6 if grade.kind == 'exam' else 3,
                                description=f'Учебная траектория: {grade.subject.lower()}. Четыре коротких модуля, самостоятельная практика и подготовка к аттестации.', color=grade.color)
                db.add(course)
                db.flush()
                modules = COURSE_CONTENT.get(grade.subject, [('Введение', 'Изучите основные термины дисциплины.'), ('Практика', 'Решите учебное задание.'), ('Разбор', 'Проверьте решение.'), ('Повторение', 'Составьте план повторения.')])
                for position, (title, content) in enumerate(modules, 1):
                    db.add(CourseModule(course_id=course.id, position=position, title=title, content=content, is_done=position == 1 and index == 0))
            for previous in range(1, 4):
                status = 'absent' if index == 2 and previous == 2 else 'excused' if index == 1 and previous == 3 else 'present'
                db.add(Attendance(student_id=student.id, subject=grade.subject, day=day - timedelta(days=previous * 7 + index), status=status,
                                  note='Вымышленная отметка посещаемости.' if status != 'excused' else 'Учебный пример уважительной причины.'))
        for grade in (grades[0], grades[2] if len(grades) > 2 else grades[-1]):
            questions = QUIZ_CONTENT.get(grade.subject)
            if questions:
                db.add(Quiz(student_id=student.id, title=f'{grade.subject}: самопроверка', subject=grade.subject,
                            description='Три учебных вопроса с объяснениями. Результат не изменяет официальную успеваемость прототипа.', questions_json=json.dumps(questions, ensure_ascii=False)))
        db.add(StudyNote(student_id=student.id, title='План подготовки к сессии', subject=grades[0].subject,
                         body='1. Повторить определения и основные методы.\n2. Решить три задачи без подсказок.\n3. Разобрать ошибки и записаться на консультацию.\n4. Проверить дату экзамена в разделе «Сессия».', created_at=now, updated_at=now))
        front, back = ('Сложность двоичного поиска?', 'O(log n), если массив отсортирован.') if student.login == 'alina.demo' else ('Что такое критерий приёмки?', 'Проверяемое описание ожидаемого поведения системы.')
        db.add(Flashcard(student_id=student.id, subject=grades[0].subject, front=front, back=back, due_date=day, reviews=0, known_count=0, interval_days=0))
        db.add(Flashcard(student_id=student.id, subject=grades[2].subject, front='Как закрепить сложную тему?', back='Объяснить своими словами, решить задачу и повторить с интервалом.', due_date=day, reviews=0, known_count=0, interval_days=0))
        db.add(PersonalTask(student_id=student.id, title='Подготовить вопросы к консультации', subject=grades[2].subject, due_date=day + timedelta(days=2), priority='high', is_done=False, created_at=now))
        db.add(PersonalTask(student_id=student.id, title='Повторить первый модуль', subject=grades[0].subject, due_date=day + timedelta(days=4), priority='normal', is_done=False, created_at=now))
        db.add(FocusSession(student_id=student.id, subject=grades[0].subject, minutes=25 if student.login == 'alina.demo' else 45, created_at=now - timedelta(days=1)))
        db.add(LearningSeed(student_id=student.id, version='0004_learning'))
    db.flush()
