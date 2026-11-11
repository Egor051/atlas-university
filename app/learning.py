"""Student-owned learning API, composed with the existing authentication perimeter."""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import User, Deadline, Grade, CAMPUS_TZ, campus_today, utc_now
from .learning_db import (Course, CourseModule, AssignmentSubmission, StudyNote,
                          Flashcard, Quiz, QuizAttempt, Attendance, PersonalTask, FocusSession)
from .services import begin_idempotent, commit_idempotent
from .storage_guards import (lock_owner, update_personal, delete_personal,
                             require_record_token, identity_conditions)
from .workspace_db import GroupWork, WorkDelivery


def create_router():
    # Main has already declared its dependencies before it includes this router.
    from .main import get_db, require_student, require_same_origin, StrictBody, date_iso

    router = APIRouter(prefix='/api/learning')
    protected = [Depends(require_same_origin)]

    def owned(db, model, resource_id, user):
        row = db.scalar(select(model).where(model.id == resource_id, model.student_id == user.id))
        if row is None:
            raise HTTPException(404, 'Учебная запись не найдена')
        return row

    def room_for(db, model, user, maximum=200):
        lock_owner(db, user.id)
        if db.scalar(select(func.count()).select_from(model).where(model.student_id == user.id)) >= maximum:
            raise HTTPException(409, 'Достигнут лимит учебных записей. Удалите ненужные записи и повторите.')

    def course_payload(course, db, modules=None):
        rows = modules if modules is not None else db.scalars(select(CourseModule).where(CourseModule.course_id == course.id).order_by(CourseModule.position, CourseModule.id)).all()
        completed = sum(module.is_done for module in rows)
        return dict(id=course.id, subject=course.subject, teacher=course.teacher,
                    credits=course.credits, description=course.description, color=course.color,
                    modules=[dict(id=module.id, title=module.title, content=module.content, is_done=module.is_done) for module in rows],
                    progress=round(100 * completed / len(rows)) if rows else 0,
                    modules_done=completed, modules_total=len(rows))

    @router.get('/courses')
    def courses(user: User = Depends(require_student), db: Session = Depends(get_db)):
        rows = db.scalars(select(Course).where(Course.student_id == user.id).order_by(Course.id).limit(100)).all()
        modules = {}
        for module in db.scalars(select(CourseModule).where(CourseModule.course_id.in_([row.id for row in rows])).order_by(CourseModule.position, CourseModule.id)):
            modules.setdefault(module.course_id, []).append(module)
        items = [course_payload(row, db, modules.get(row.id, [])) for row in rows]
        return dict(items=items, summary=dict(course_count=len(items), credits_total=sum(row.credits for row in rows),
                    modules_done=sum(row['modules_done'] for row in items), modules_total=sum(row['modules_total'] for row in items)))

    @router.get('/courses/{course_id}')
    def course_detail(course_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
        return course_payload(owned(db, Course, course_id, user), db)

    class ModuleBody(StrictBody):
        is_done: StrictBool

    @router.post('/courses/{course_id}/modules/{module_id}', dependencies=protected)
    def mark_module(course_id: int, module_id: int, body: ModuleBody, user: User = Depends(require_student), db: Session = Depends(get_db)):
        course = owned(db, Course, course_id, user)
        module = db.scalar(select(CourseModule).where(CourseModule.id == module_id, CourseModule.course_id == course.id))
        if module is None:
            raise HTTPException(404, 'Модуль не найден')
        module.is_done = body.is_done
        db.commit()
        return course_payload(course, db)

    def submission_payload(row):
        if row is None:
            return None
        return dict(id=row.id, text=row.text, url=row.url, status=row.status, version=row.version,
                    submitted_at=date_iso(row.submitted_at), updated_at=date_iso(row.updated_at))

    def assignment_payload(deadline, submission, instructions, feedback):
        default_instructions = 'Подготовьте решение, опишите ход работы и проверку результата. Вставьте текст работы или добавьте HTTPS-ссылку на учебный материал. Это сдача внутри конкурсного прототипа: реальному преподавателю работа не отправляется.'
        return dict(id=deadline.id, deadline_id=deadline.id, subject=deadline.subject, title=deadline.title, due_date=date_iso(deadline.due_date), is_done=deadline.is_done,
                    instructions=instructions or default_instructions, feedback=feedback.get(submission.id,[]) if submission else [],
                    submission=submission_payload(submission), overdue=deadline.due_date < campus_today())

    def assignment_detail_payload(deadline, db, user):
        from .teaching import assignment_feedback
        submission = db.scalar(select(AssignmentSubmission).where(AssignmentSubmission.deadline_id == deadline.id,
                                                                    AssignmentSubmission.student_id == user.id))
        instructions = db.scalar(select(GroupWork.instructions).join(WorkDelivery).where(WorkDelivery.deadline_id == deadline.id))
        return assignment_payload(deadline, submission, instructions, assignment_feedback(db,[submission] if submission else []))

    @router.get('/assignments')
    def assignments(user: User = Depends(require_student), db: Session = Depends(get_db)):
        from .teaching import assignment_feedback
        query = (select(Deadline, GroupWork.instructions).outerjoin(WorkDelivery, WorkDelivery.deadline_id == Deadline.id)
                 .outerjoin(GroupWork, GroupWork.id == WorkDelivery.work_id).where(Deadline.student_id == user.id)
                 .order_by(Deadline.due_date, Deadline.id).limit(200))
        rows = db.execute(query).all()
        submissions = {row.deadline_id:row for row in db.scalars(select(AssignmentSubmission).where(
            AssignmentSubmission.student_id == user.id, AssignmentSubmission.deadline_id.in_([deadline.id for deadline,_ in rows])))}
        feedback = assignment_feedback(db, submissions.values())
        items = [assignment_payload(row, submissions.get(row.id), instructions, feedback) for row,instructions in rows]
        submitted = sum(bool(item['submission'] and item['submission']['status'] == 'submitted') for item in items)
        return dict(items=items, summary=dict(total=len(items), submitted=submitted, pending=len(items)-submitted))

    @router.get('/assignments/{deadline_id}')
    def assignment_detail(deadline_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
        return assignment_detail_payload(owned(db, Deadline, deadline_id, user), db, user)

    class SubmissionBody(StrictBody):
        text: str = Field(min_length=10, max_length=8000)
        url: str = Field(default='', max_length=500)

        @field_validator('text')
        @classmethod
        def useful_text(cls, value):
            value = value.strip()
            if len(value) < 10:
                raise ValueError('Опишите работу минимум десятью символами')
            return value

        @field_validator('url')
        @classmethod
        def https_reference(cls, value):
            value = value.strip()
            if not value:
                return ''
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not any(char.isspace() for char in value) and '\\' not in value
                _ = parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError('Допускается только полная HTTPS-ссылка без учётных данных')
            return value

    @router.post('/assignments/{deadline_id}/submit', dependencies=protected)
    def submit_assignment(deadline_id: int, body: SubmissionBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db)):
        deadline = owned(db, Deadline, deadline_id, user)
        receipt, replay = begin_idempotent(db, request, response, user, f'assignment-submit:{deadline_id}', body.model_dump())
        if replay is not None: return replay
        row = db.scalar(select(AssignmentSubmission).where(AssignmentSubmission.deadline_id == deadline.id, AssignmentSubmission.student_id == user.id))
        now = utc_now()
        if row is None:
            row = AssignmentSubmission(student_id=user.id, deadline_id=deadline.id, text=body.text, url=body.url,
                                       status='submitted', version=1, submitted_at=now, updated_at=now)
            db.add(row)
        else:
            changed = db.execute(update(AssignmentSubmission).where(AssignmentSubmission.id == row.id, AssignmentSubmission.student_id == user.id,
                       AssignmentSubmission.version == row.version).values(text=body.text, url=body.url, status='submitted', version=row.version+1, submitted_at=now, updated_at=now))
            if changed.rowcount != 1:
                db.rollback()
                raise HTTPException(409, 'Работа уже изменилась. Обновите раздел перед повторной сдачей.')
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'Работа уже сохранена другой отправкой. Обновите раздел.') from None
        from .teaching import submission_notice
        submission_notice(db, deadline)
        return commit_idempotent(db, receipt, assignment_detail_payload(deadline, db, user))

    @router.post('/assignments/{deadline_id}/withdraw', dependencies=protected)
    def withdraw_assignment(deadline_id: int, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db)):
        deadline = owned(db, Deadline, deadline_id, user)
        receipt, replay = begin_idempotent(db, request, response, user, f'assignment-withdraw:{deadline_id}', {})
        if replay is not None: return replay
        row = db.scalar(select(AssignmentSubmission).where(AssignmentSubmission.deadline_id == deadline.id, AssignmentSubmission.student_id == user.id))
        if row is None or row.status != 'submitted':
            raise HTTPException(409, 'Нет отправленной работы для отзыва')
        changed = db.execute(update(AssignmentSubmission).where(AssignmentSubmission.id == row.id, AssignmentSubmission.student_id == user.id,
                    AssignmentSubmission.version == row.version, AssignmentSubmission.status == 'submitted').values(status='withdrawn', version=row.version+1, updated_at=utc_now()))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Работа уже изменилась. Обновите раздел.')
        db.flush()
        return commit_idempotent(db, receipt, assignment_detail_payload(deadline, db, user))

    @router.get('/exams')
    def exams(user: User = Depends(require_student), db: Session = Depends(get_db)):
        grades = db.scalars(select(Grade).where(Grade.student_id == user.id).order_by(Grade.exam_date, Grade.id).limit(100)).all()
        items = [dict(id=row.id, subject=row.subject, teacher=row.teacher, kind=row.exam_kind, exam_date=date_iso(row.exam_date),
                      current=row.current, max_grade=row.max_grade, assessment=row.assessment, risk=row.current is not None and row.current < 65,
                      consultation='Запишитесь на консультацию в разделе «Консультации». Подготовьте вопросы и выполненные задания.',
                      note='Демонстрационный порог внимания — 65 баллов. Это ориентир прототипа, а не правило реального вуза.') for row in grades]
        return dict(items=items, summary=dict(total=len(items), dated=sum(bool(row.exam_date) for row in grades), risk_count=sum(item['risk'] for item in items)))

    class NoteBody(StrictBody):
        title: str = Field(min_length=1, max_length=180)
        subject: str = Field(default='', max_length=130)
        body: str = Field(min_length=1, max_length=12000)

        @field_validator('title', 'body')
        @classmethod
        def not_blank(cls, value):
            if not value.strip():
                raise ValueError('Введите текст')
            return value.strip()

        @field_validator('subject')
        @classmethod
        def trim_subject(cls, value):
            return value.strip()

    def note_payload(row):
        return dict(id=row.id, record_token=row.record_token, title=row.title, subject=row.subject, body=row.body, created_at=date_iso(row.created_at), updated_at=date_iso(row.updated_at))

    @router.get('/notes')
    def notes(q: str = Query('', max_length=100), user: User = Depends(require_student), db: Session = Depends(get_db)):
        rows = db.scalars(select(StudyNote).where(StudyNote.student_id == user.id).order_by(StudyNote.updated_at.desc(), StudyNote.id.desc())).all()
        needle = q.strip().casefold()
        return dict(items=[note_payload(row) for row in rows if not needle or needle in f'{row.title}\n{row.subject}\n{row.body}'.casefold()])

    @router.get('/notes/{note_id}')
    def note_detail(note_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
        return note_payload(owned(db, StudyNote, note_id, user))

    @router.post('/notes', status_code=201, dependencies=protected)
    def create_note(body: NoteBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db)):
        receipt, replay = begin_idempotent(db, request, response, user, 'note-create', body.model_dump())
        if replay is not None: return replay
        room_for(db, StudyNote, user)
        row = StudyNote(student_id=user.id, **body.model_dump(), created_at=utc_now(), updated_at=utc_now())
        db.add(row)
        db.flush()
        return commit_idempotent(db, receipt, note_payload(row))

    @router.post('/notes/{note_id}', dependencies=protected)
    def edit_note(note_id: int, body: NoteBody, request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
        row = owned(db, StudyNote, note_id, user)
        update_personal(db, StudyNote, row, user, {**body.model_dump(), 'updated_at': utc_now()}, request)
        db.commit()
        return note_payload(row)

    @router.post('/notes/{note_id}/delete', dependencies=protected)
    def delete_note(note_id: int, request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
        delete_personal(db, StudyNote, owned(db, StudyNote, note_id, user), user, request, 'note')
        db.commit()
        return {'ok': True}

    class CardBody(StrictBody):
        subject: str = Field(default='', max_length=130)
        front: str = Field(min_length=1, max_length=500)
        back: str = Field(min_length=1, max_length=3000)

        @field_validator('front', 'back')
        @classmethod
        def meaningful_card(cls, value):
            if not value.strip():
                raise ValueError('Введите вопрос и ответ')
            return value.strip()

        @field_validator('subject')
        @classmethod
        def trim_subject(cls, value):
            return value.strip()

    class ReviewBody(StrictBody):
        known: StrictBool

    def card_payload(row):
        return dict(id=row.id, record_token=row.record_token, subject=row.subject, front=row.front, back=row.back, due_date=date_iso(row.due_date),
                    reviews=row.reviews, known_count=row.known_count, interval_days=row.interval_days, is_due=row.due_date <= campus_today())

    @router.get('/flashcards')
    def flashcards(user: User = Depends(require_student), db: Session = Depends(get_db)):
        rows = db.scalars(select(Flashcard).where(Flashcard.student_id == user.id).order_by(Flashcard.due_date, Flashcard.id)).all()
        return dict(items=[card_payload(row) for row in rows], summary=dict(total=len(rows), due=sum(row.due_date <= campus_today() for row in rows)))

    @router.get('/flashcards/{card_id}')
    def card_detail(card_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
        return card_payload(owned(db, Flashcard, card_id, user))

    @router.post('/flashcards', status_code=201, dependencies=protected)
    def create_card(body: CardBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db)):
        receipt, replay = begin_idempotent(db, request, response, user, 'flashcard-create', body.model_dump())
        if replay is not None: return replay
        room_for(db, Flashcard, user)
        row = Flashcard(student_id=user.id, **body.model_dump(), due_date=campus_today(), reviews=0, known_count=0, interval_days=0)
        db.add(row)
        db.flush()
        return commit_idempotent(db, receipt, card_payload(row))

    @router.post('/flashcards/{card_id}/review', dependencies=protected)
    def review_card(card_id: int, body: ReviewBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db)):
        row = owned(db, Flashcard, card_id, user)
        require_record_token(request, row)
        # A pre-0006 receipt has no immutable identity. Its captured result can
        # still be replayed, but it must never be renamed onto a surviving (or
        # reused) id and must never cause another review during an upgrade.
        if request.headers.get('Idempotency-Key'):
            from .services_db import ServiceIdempotency
            legacy_operation = f'flashcard-review:{card_id}'
            legacy = db.scalar(select(ServiceIdempotency.id).where(ServiceIdempotency.user_id == user.id,
                ServiceIdempotency.operation == legacy_operation, ServiceIdempotency.key == request.headers['Idempotency-Key']))
            if legacy is not None:
                _, replay = begin_idempotent(db, request, response, user, legacy_operation, body.model_dump())
                return replay
        receipt, replay = begin_idempotent(db, request, response, user, f'flashcard-review:{card_id}:{row.record_token}', body.model_dump())
        if replay is not None: return replay
        interval = min(60, max(1, row.interval_days * 2)) if body.known else 0
        changed = db.execute(update(Flashcard).where(*identity_conditions(Flashcard, row, user), Flashcard.reviews == row.reviews).values(
                    reviews=row.reviews+1, known_count=row.known_count+int(body.known), interval_days=interval, due_date=campus_today()+timedelta(days=interval)))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Карточка уже повторена. Обновите список.')
        db.flush()
        return commit_idempotent(db, receipt, card_payload(row))

    @router.post('/flashcards/{card_id}/delete', dependencies=protected)
    def delete_card(card_id: int, request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
        delete_personal(db, Flashcard, owned(db, Flashcard, card_id, user), user, request, 'flashcard')
        db.commit()
        return {'ok': True}

    def quiz_summary(row, db, user, statistics=None):
        questions = json.loads(row.questions_json)
        attempts, best = statistics.get(row.id, (0, None)) if statistics is not None else db.execute(select(func.count(QuizAttempt.id), func.max(QuizAttempt.score)).where(QuizAttempt.student_id == user.id, QuizAttempt.quiz_id == row.id)).one()
        return dict(id=row.id, title=row.title, subject=row.subject, description=row.description, question_count=len(questions), attempts=attempts,
                    best_score=best, best_percent=round(100*best/len(questions)) if best is not None and questions else None)

    @router.get('/quizzes')
    def quizzes(user: User = Depends(require_student), db: Session = Depends(get_db)):
        rows = db.scalars(select(Quiz).where(Quiz.student_id == user.id).order_by(Quiz.id).limit(100)).all()
        statistics = {quiz_id:(count,best) for quiz_id,count,best in db.execute(select(QuizAttempt.quiz_id, func.count(QuizAttempt.id), func.max(QuizAttempt.score)).where(QuizAttempt.student_id == user.id, QuizAttempt.quiz_id.in_([row.id for row in rows])).group_by(QuizAttempt.quiz_id))}
        return dict(items=[quiz_summary(row, db, user, statistics) for row in rows])

    @router.get('/quizzes/{quiz_id}')
    def quiz_detail(quiz_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
        row = owned(db, Quiz, quiz_id, user)
        return {**quiz_summary(row, db, user), 'questions': [dict(prompt=q['prompt'], options=q['options']) for q in json.loads(row.questions_json)]}

    class AttemptBody(StrictBody):
        answers: list[StrictInt] = Field(min_length=1, max_length=50)

    def attempt_payload(attempt, quiz, include_results=False):
        payload = dict(id=attempt.id, quiz_id=attempt.quiz_id, title=quiz.title, subject=quiz.subject,
                       score=attempt.score, total=attempt.total, percent=round(100*attempt.score/attempt.total), created_at=date_iso(attempt.created_at))
        if include_results:
            answers = json.loads(attempt.answers_json)
            payload['results'] = [dict(question=q['prompt'], selected=answer, correct=q['correct'], explanation=q['explanation'],
                                selected_text=q['options'][answer], correct_text=q['options'][q['correct']]) for q, answer in zip(json.loads(quiz.questions_json), answers)]
        return payload

    @router.post('/quizzes/{quiz_id}/attempt', status_code=201, dependencies=protected)
    def attempt_quiz(quiz_id: int, body: AttemptBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db)):
        row = owned(db, Quiz, quiz_id, user)
        receipt, replay = begin_idempotent(db, request, response, user, f'quiz-attempt:{quiz_id}', body.model_dump())
        if replay is not None: return replay
        questions = json.loads(row.questions_json)
        if len(body.answers) != len(questions) or any(answer < 0 or answer >= len(question['options']) for answer, question in zip(body.answers, questions)):
            raise HTTPException(422, 'Ответьте на каждый вопрос, выбрав один из предложенных вариантов')
        room_for(db, QuizAttempt, user, 1000)
        attempt = QuizAttempt(student_id=user.id, quiz_id=row.id, answers_json=json.dumps(body.answers),
                              score=sum(answer == question['correct'] for answer, question in zip(body.answers, questions)), total=len(questions), created_at=utc_now())
        db.add(attempt)
        db.flush()
        return commit_idempotent(db, receipt, attempt_payload(attempt, row, include_results=True))

    @router.get('/quiz-attempts')
    def quiz_attempts(user: User = Depends(require_student), db: Session = Depends(get_db)):
        rows = db.execute(select(QuizAttempt, Quiz).join(Quiz, Quiz.id == QuizAttempt.quiz_id).where(QuizAttempt.student_id == user.id, Quiz.student_id == user.id).order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())).all()
        total = db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.student_id == user.id))
        return dict(items=[attempt_payload(attempt, quiz) for attempt, quiz in rows], summary=dict(total=total))

    @router.get('/quiz-attempts/{attempt_id}')
    def attempt_detail(attempt_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
        attempt = owned(db, QuizAttempt, attempt_id, user)
        return attempt_payload(attempt, owned(db, Quiz, attempt.quiz_id, user), include_results=True)

    @router.get('/attendance')
    def attendance(user: User = Depends(require_student), db: Session = Depends(get_db)):
        rows = db.scalars(select(Attendance).where(Attendance.student_id == user.id).order_by(Attendance.day.desc(), Attendance.id.desc()).limit(200)).all()
        counts = {status: sum(row.status == status for row in rows) for status in ('present', 'absent', 'excused')}
        denominator = counts['present'] + counts['absent']
        return dict(items=[dict(id=row.id, subject=row.subject, day=date_iso(row.day), status=row.status, note=row.note) for row in rows],
                    summary={**counts, 'total':len(rows), 'attendance_percent':round(100*counts['present']/denominator) if denominator else None,
                             'description':'Уважительные пропуски исключены из знаменателя. Записи вымышлены и не меняются отметками личного плана.'})

    class TaskBody(StrictBody):
        title: str = Field(min_length=1, max_length=180)
        subject: str = Field(default='', max_length=130)
        due_date: date
        priority: Literal['low', 'normal', 'high'] = 'normal'
        is_done: StrictBool = False

        @field_validator('title')
        @classmethod
        def non_blank_task(cls, value):
            if not value.strip():
                raise ValueError('Введите название задачи')
            return value.strip()

        @field_validator('subject')
        @classmethod
        def trim_subject(cls, value):
            return value.strip()

    def validate_task_date(value):
        if not campus_today()-timedelta(days=366) <= value <= campus_today()+timedelta(days=730):
            raise HTTPException(422, 'Выберите дату в пределах прошлого года или следующих двух лет')

    def task_payload(row):
        return dict(id=row.id, record_token=row.record_token, title=row.title, subject=row.subject, due_date=date_iso(row.due_date), priority=row.priority, is_done=row.is_done, created_at=date_iso(row.created_at))

    @router.get('/tasks')
    def tasks(user: User = Depends(require_student), db: Session = Depends(get_db)):
        rows = db.scalars(select(PersonalTask).where(PersonalTask.student_id == user.id).order_by(PersonalTask.is_done, PersonalTask.due_date, PersonalTask.id)).all()
        return dict(items=[task_payload(row) for row in rows], summary=dict(total=len(rows), done=sum(row.is_done for row in rows), overdue=sum(not row.is_done and row.due_date < campus_today() for row in rows)))

    @router.get('/tasks/{task_id}')
    def task_detail(task_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
        return task_payload(owned(db, PersonalTask, task_id, user))

    @router.post('/tasks', status_code=201, dependencies=protected)
    def create_task(body: TaskBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db)):
        receipt, replay = begin_idempotent(db, request, response, user, 'task-create', body.model_dump())
        if replay is not None: return replay
        validate_task_date(body.due_date)
        room_for(db, PersonalTask, user)
        row = PersonalTask(student_id=user.id, **body.model_dump(), created_at=utc_now())
        db.add(row)
        db.flush()
        return commit_idempotent(db, receipt, task_payload(row))

    @router.post('/tasks/{task_id}', dependencies=protected)
    def edit_task(task_id: int, body: TaskBody, request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
        row = owned(db, PersonalTask, task_id, user)
        if body.due_date != row.due_date:
            validate_task_date(body.due_date)
        update_personal(db, PersonalTask, row, user, body.model_dump(), request)
        db.commit()
        return task_payload(row)

    class TaskToggleBody(StrictBody):
        is_done: StrictBool

    @router.post('/tasks/{task_id}/toggle', dependencies=protected)
    def toggle_task(task_id: int, body: TaskToggleBody, request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
        row = owned(db, PersonalTask, task_id, user)
        update_personal(db, PersonalTask, row, user, {'is_done': body.is_done}, request)
        db.commit()
        return task_payload(row)

    @router.post('/tasks/{task_id}/delete', dependencies=protected)
    def delete_task(task_id: int, request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
        delete_personal(db, PersonalTask, owned(db, PersonalTask, task_id, user), user, request, 'task')
        db.commit()
        return {'ok': True}

    class FocusBody(StrictBody):
        subject: str = Field(min_length=1, max_length=130)
        minutes: StrictInt = Field(ge=1, le=180)

        @field_validator('subject')
        @classmethod
        def non_blank_subject(cls, value):
            if not value.strip():
                raise ValueError('Укажите тему занятия')
            return value.strip()

    def focus_payload(row):
        return dict(id=row.id, record_token=row.record_token, subject=row.subject, minutes=row.minutes, created_at=date_iso(row.created_at))

    @router.get('/focus-sessions')
    def focus_sessions(user: User = Depends(require_student), db: Session = Depends(get_db)):
        rows = db.scalars(select(FocusSession).where(FocusSession.student_id == user.id).order_by(FocusSession.created_at.desc(), FocusSession.id.desc())).all()
        # SQLite stores DateTime values without offsets; compare a UTC boundary
        # against the UTC timestamps written by utc_now(), as PostgreSQL also does.
        day_start = datetime.combine(campus_today(), datetime.min.time(), tzinfo=CAMPUS_TZ).astimezone(timezone.utc)
        total, minutes = db.execute(select(func.count(FocusSession.id), func.coalesce(func.sum(FocusSession.minutes), 0)).where(FocusSession.student_id == user.id)).one()
        today_minutes = db.scalar(select(func.coalesce(func.sum(FocusSession.minutes), 0)).where(FocusSession.student_id == user.id,
                                   FocusSession.created_at >= day_start, FocusSession.created_at < day_start + timedelta(days=1)))
        week_start = day_start - timedelta(days=campus_today().weekday())
        week_minutes = db.scalar(select(func.coalesce(func.sum(FocusSession.minutes), 0)).where(FocusSession.student_id == user.id,
                                  FocusSession.created_at >= week_start, FocusSession.created_at < week_start + timedelta(days=7)))
        return dict(items=[focus_payload(row) for row in rows], summary=dict(total=total, minutes=minutes, today_minutes=today_minutes,
                    week_minutes=week_minutes,
                    description='Журнал времени, записанного студентом вручную. Он не подтверждает присутствие на занятии.'))

    @router.post('/focus-sessions', status_code=201, dependencies=protected)
    def create_focus_session(body: FocusBody, request: Request, response: Response, user: User = Depends(require_student), db: Session = Depends(get_db)):
        receipt, replay = begin_idempotent(db, request, response, user, 'focus-create', body.model_dump())
        if replay is not None: return replay
        room_for(db, FocusSession, user, 1000)
        row = FocusSession(student_id=user.id, **body.model_dump(), created_at=utc_now())
        db.add(row)
        db.flush()
        return commit_idempotent(db, receipt, focus_payload(row))

    @router.post('/focus-sessions/{session_id}/delete', dependencies=protected)
    def delete_focus_session(session_id: int, request: Request, user: User = Depends(require_student), db: Session = Depends(get_db)):
        delete_personal(db, FocusSession, owned(db, FocusSession, session_id, user), user, request, 'focus')
        db.commit()
        return {'ok': True}

    return router
