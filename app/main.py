"""ATLAS Campus contest concept. All student and staff data is fictional."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import FastAPI, Request, Response, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, Field, ConfigDict, StrictBool, field_validator
from sqlalchemy import select, func, update, delete, text, or_, case
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.gzip import GZipMiddleware

from .db import (SessionLocal, User, LoginSession, Lesson, LessonChange, Grade,
                 Deadline, DocumentRequest, Notification, DOC_TYPES, DOC_NAMES,
                 RequestEvent, RequestIdempotency, LoginAttempt,
                 password_hasher, initialize_database, CAMPUS_TZ, campus_today,
                 utc_now, request_due_date, engine)
from .config import settings
from .version import VERSION, build_id
from .session_security import as_utc, validate_expected_actor, PasswordAdmission

APP_DIR = Path(__file__).resolve().parent.parent
COOKIE_NAME = 'atlas_session'
COOKIE_SECURE = settings.cookie_secure
SESSION_LIFETIME = timedelta(days=7)
DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))
ALLOWED_TRANSITIONS = {
    'submitted': ['review', 'needs_info', 'rejected'],
    'review': ['processing', 'needs_info', 'ready', 'rejected'],
    'processing': ['ready', 'needs_info', 'rejected'],
    'needs_info': ['review', 'rejected'],
    'ready': [], 'rejected': [],
}
STATUS_NAMES = {'submitted': 'отправлена', 'review': 'на рассмотрении', 'processing': 'в работе', 'needs_info':'нужны уточнения', 'ready': 'готова', 'rejected': 'отклонена'}


@asynccontextmanager
async def lifespan(_app):
    initialize_database()
    yield


app = FastAPI(title='ATLAS Campus API', version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))


class BodyLimitMiddleware:
    """Bound actual ASGI bytes, including requests without Content-Length."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > 32768:
                return await JSONResponse({'detail': 'Слишком большой запрос'}, status_code=413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        return await self.app(scope, replay, send)


app.add_middleware(BodyLimitMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if 'Content-Security-Policy' not in response.headers:
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store, private'
        elif request.url.path == '/' or request.url.path.startswith('/app/'):
            # Revalidate the shell so an upgraded deployment loads its current
            # versioned assets, including the session-affinity protection.
            response.headers['Cache-Control'] = 'no-cache'
        return response


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    # Do not reflect passwords or arbitrary request payloads in validation errors.
    return JSONResponse({'detail': 'Проверьте поля формы: значение отсутствует или имеет недопустимый формат', 'errors': [{'field': '.'.join(str(x) for x in error['loc'][1:]), 'type': error['type']} for error in exc.errors()]}, status_code=422)

def get_db(request: Request):
    with SessionLocal() as db:
        if request.method == 'GET':
            # A response's rows and totals must describe one snapshot, even if
            # another worker changes statuses while the list is being read.
            if engine.dialect.name == 'postgresql':
                db.connection(execution_options={'isolation_level': 'REPEATABLE READ'})
                db.execute(text('SET TRANSACTION READ ONLY'))
            elif engine.dialect.name == 'sqlite':
                db.connection().exec_driver_sql('BEGIN')
        yield db

def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, 'Для продолжения необходимо войти')
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash))
    if not row or as_utc(row.expires_at) <= as_utc(utc_now()):
        raise HTTPException(401, 'Сессия истекла, войдите повторно')
    if not settings.demo_mode and row.user.login in {'alina.demo', 'mark.demo', 'dean.demo'}:
        raise HTTPException(401, 'Демонстрационные учётные записи отключены')
    validate_expected_actor(request.headers.get('X-ATLAS-User'), row.user_id)
    return row.user

def require_student(user: User = Depends(require_user)):
    if user.role != 'student': raise HTTPException(403, 'Только для студентов')
    return user

def require_staff(user: User = Depends(require_user)):
    if user.role != 'staff': raise HTTPException(403, 'Только для сотрудников')
    return user

def require_same_origin(request: Request):
    # Every mutating browser request must carry a non-safelisted header.
    # Cross-origin HTML forms cannot supply it; cross-origin fetch triggers a CORS preflight.
    if request.headers.get('X-Requested-With') != 'ATLAS':
        raise HTTPException(403, 'Неподтверждённый запрос')
    if request.headers.get('Sec-Fetch-Site') in {'cross-site', 'same-site'}:
        raise HTTPException(403, 'Запрос с другого сайта запрещён')
    origin = request.headers.get('Origin')
    expected = os.environ.get('PUBLIC_ORIGIN') or f'{request.url.scheme}://{request.url.netloc}'
    if origin and origin.rstrip('/') != expected.rstrip('/'):
        raise HTTPException(403, 'Недопустимый источник запроса')

def public_user(u: User):
    return dict(id=u.id,full_name=u.full_name,initials=u.initials,faculty=u.faculty,
                program=u.program,course=u.course,group=u.group_name,student_number=u.student_number,
                role=u.role,accent=u.accent)

def date_iso(v):
    if isinstance(v, datetime):
        v = as_utc(v)
    return v.isoformat() if v else None

def request_payload(r: DocumentRequest):
    return dict(id=r.id,type=r.type,comment=r.comment,details=json.loads(r.details or '{}'),status=r.status,
                created_at=date_iso(r.created_at),updated_at=date_iso(r.updated_at),
                version=r.version, staff_message=r.staff_message,
                due_at=date_iso(r.due_at), document_url=f'/api/requests/{r.id}/document' if r.status == 'ready' else None)


def request_with_history(r: DocumentRequest, db: Session, *, history_limit=100, history_offset=None, history_cutoff=None):
    conditions = [RequestEvent.request_id == r.id]
    if history_cutoff is not None:
        conditions.append(RequestEvent.id <= history_cutoff)
    total = db.scalar(select(func.count()).select_from(RequestEvent).where(*conditions))
    limit = min(200, max(1, history_limit))
    offset = max(0, (total - 1) // limit * limit) if history_offset is None else history_offset
    history = db.scalars(select(RequestEvent).where(*conditions).order_by(RequestEvent.created_at, RequestEvent.id).offset(offset).limit(limit)).all()
    return {**request_payload(r), 'history': [dict(id=e.id,status=e.status,message=e.message,actor_role=e.actor_role,actor_name=e.actor_name,created_at=date_iso(e.created_at)) for e in history],
            'history_total': total, 'history_limit': limit, 'history_offset': offset,
            'history_has_more': offset + len(history) < total}

def notification_payload(n: Notification):
    return dict(id=n.id,title=n.title,body=n.body,category=n.category,
                created_at=date_iso(n.created_at),is_read=n.is_read,
                target=n.target, request_id=n.request_id)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*')
    @classmethod
    def reject_non_text_characters(cls, value):
        if isinstance(value, str) and re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]', value):
            raise ValueError('Недопустимые управляющие символы')
        return value


class LoginBody(StrictBody):
    login: str = Field(min_length=2,max_length=100)
    password: str = Field(min_length=1,max_length=200)

@app.get('/api/health')
def health(): return {'ok': True, 'service':'ATLAS Campus', 'version': VERSION, 'build':build_id()}


@app.get('/api/ready')
def ready():
    try:
        with SessionLocal() as db:
            db.execute(text('SELECT 1'))
    except SQLAlchemyError:
        return JSONResponse({'ok': False, 'service': 'ATLAS Campus'}, status_code=503)
    return {'ok': True, 'database': 'ready'}


@app.get('/api/config')
def public_config():
    return {'demo_mode': settings.demo_mode, 'concept': True, 'timezone': 'Europe/Moscow', 'version': VERSION, 'build':build_id()}

@app.post('/api/login')
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
    ip = request.client.host if request.client else 'unknown'
    login_name = body.login.lower().strip()
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()
    account_hash = hashlib.sha256(login_name.encode()).hexdigest()
    # Serialize the check and reservation across workers, not just one process.
    if engine.dialect.name == 'sqlite':
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    elif engine.dialect.name == 'postgresql':
        lock_key = int.from_bytes(bytes.fromhex(ip_hash[:16]), byteorder='big', signed=True)
        db.execute(text('SELECT pg_advisory_xact_lock(:lock_key)'), {'lock_key': lock_key})
    now = utc_now()
    cutoff = now - timedelta(minutes=15)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    ip_attempts = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.ip_hash == ip_hash, LoginAttempt.created_at >= cutoff))
    pair_attempts = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.ip_hash == ip_hash, LoginAttempt.account_hash == account_hash, LoginAttempt.created_at >= cutoff))
    if ip_attempts >= 40 or pair_attempts >= 12:
        db.commit()
        raise HTTPException(429,'Слишком много попыток. Повторите через 15 минут.', headers={'Retry-After': '900'})
    u=db.scalar(select(User).where(User.login == login_name))
    with PasswordAdmission(db, engine.dialect.name):
        try:
            valid = password_hasher.verify(u.password_hash if u else DUMMY_PASSWORD_HASH,body.password) and u is not None
        except (VerifyMismatchError,VerificationError): valid=False
    if not settings.demo_mode and login_name in {'alina.demo', 'mark.demo', 'dean.demo'}:
        valid = False
    if not valid:
        db.add(LoginAttempt(ip_hash=ip_hash, account_hash=account_hash, created_at=now))
        db.commit()
        raise HTTPException(401,'Неверный логин или пароль')
    db.execute(delete(LoginAttempt).where(LoginAttempt.ip_hash == ip_hash, LoginAttempt.account_hash == account_hash))
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    # Different source IPs must still serialize the account's session cap.
    if engine.dialect.name == 'postgresql':
        db.scalar(select(User.id).where(User.id == u.id).with_for_update())
    old_sessions = db.scalars(select(LoginSession.id).where(LoginSession.user_id == u.id).order_by(LoginSession.expires_at.desc()).offset(19)).all()
    if old_sessions:
        db.execute(delete(LoginSession).where(LoginSession.id.in_(old_sessions)))
    # Multiple review sessions can coexist for shared *fictional* accounts.
    token=secrets.token_urlsafe(40)
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                        user_id=u.id,expires_at=now+SESSION_LIFETIME))
    db.commit()
    response.set_cookie(COOKIE_NAME,token,max_age=int(SESSION_LIFETIME.total_seconds()),
                        httponly=True,secure=COOKIE_SECURE,samesite='lax',path='/')
    return {'user':public_user(u)}

@app.post('/api/logout')
def logout(request: Request,response:Response, db:Session=Depends(get_db), _:None=Depends(require_same_origin)):
    token=request.cookies.get(COOKIE_NAME)
    if token:
        row = db.scalar(select(LoginSession).where(LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        if row:
            validate_expected_actor(request.headers.get('X-ATLAS-User'), row.user_id)
        db.query(LoginSession).filter(LoginSession.token_hash==hashlib.sha256(token.encode()).hexdigest()).delete()
        db.commit()
    response.delete_cookie(COOKIE_NAME,path='/',secure=COOKIE_SECURE,samesite='lax',httponly=True)
    return {'ok': True}

@app.get('/api/me')
def me(user:User=Depends(require_user)):
    return public_user(user)

def get_week_schedule(db: Session, user: User, week_start: date):
    end=week_start+timedelta(days=7)
    lessons=db.scalars(select(Lesson).where(Lesson.student_id==user.id).order_by(Lesson.weekday,Lesson.start_time)).all()
    changes=db.scalars(select(LessonChange).where(LessonChange.student_id==user.id,LessonChange.day>=week_start,LessonChange.day<end)).all()
    by_key={(c.lesson_id,c.day):c for c in changes}
    days=[]
    for offset in range(7):
        day=week_start+timedelta(days=offset)
        daily=[]
        for l in lessons:
            if l.weekday != day.weekday():continue
            change=by_key.get((l.id,day))
            start = change.new_start if change and change.new_start else l.start_time
            end = l.end_time
            if change and change.new_start:
                original_start = datetime.strptime(l.start_time, '%H:%M')
                original_end = datetime.strptime(l.end_time, '%H:%M')
                duration = original_end - original_start
                end = (datetime.strptime(start, '%H:%M') + duration).strftime('%H:%M')
            daily.append(dict(id=l.id,date=str(day),start=change.new_start if change and change.new_start else l.start_time,
                              end=end,title=l.title,kind=l.kind,room=change.new_room if change and change.new_room else l.room,
                              teacher=l.teacher,color=l.color,changed=bool(change),note=change.note if change else None,
                              original_room=l.room,original_start=l.start_time,original_end=l.end_time))
        daily.sort(key=lambda x:x['start'])
        days.append({'date':str(day),'items':daily})
    return days

@app.get('/api/schedule')
def schedule(week:date|None=None,user:User=Depends(require_student),db:Session=Depends(get_db)):
    target=week or campus_today()
    if abs((target-campus_today()).days)>370: raise HTTPException(422,'Недопустимый период')
    monday=target-timedelta(days=target.weekday())
    return {'week_start':str(monday),'days':get_week_schedule(db,user,monday), 'timezone': 'Europe/Moscow'}


def ics_text(value):
    return str(value).replace('\\', '\\\\').replace('\r', '').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold_ics(line):
    result = []
    current = ''
    for character in line:
        if len((current + character).encode('utf-8')) > 75:
            result.append(current)
            current = ' '
        current += character
    result.append(current)
    return '\r\n'.join(result)


@app.get('/api/schedule/export')
def export_schedule(week: date | None = None, user: User = Depends(require_student), db: Session = Depends(get_db)):
    data = schedule(week, user, db)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ATLAS Campus//Contest concept//RU', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:АТЛАС — вымышленное расписание', 'X-WR-TIMEZONE:Europe/Moscow', 'BEGIN:VTIMEZONE', 'TZID:Europe/Moscow', 'BEGIN:STANDARD', 'DTSTART:19700101T000000', 'TZOFFSETFROM:+0300', 'TZOFFSETTO:+0300', 'TZNAME:MSK', 'END:STANDARD', 'END:VTIMEZONE']
    stamp = utc_now().strftime('%Y%m%dT%H%M%SZ')
    for day in data['days']:
        for lesson in day['items']:
            start = day['date'].replace('-', '') + 'T' + lesson['start'].replace(':', '') + '00'
            end = day['date'].replace('-', '') + 'T' + lesson['end'].replace(':', '') + '00'
            description = f"{lesson['kind']} · {lesson['teacher']}\nКонкурсный прототип. Все данные вымышлены."
            if lesson['note']:
                description += '\n' + lesson['note']
            lines.extend(['BEGIN:VEVENT', f"UID:lesson-{user.id}-{lesson['id']}-{day['date']}@atlas-concept.local", f'DTSTAMP:{stamp}', f'DTSTART;TZID=Europe/Moscow:{start}', f'DTEND;TZID=Europe/Moscow:{end}', 'SUMMARY:' + ics_text(lesson['title']), 'LOCATION:' + ics_text(lesson['room']), 'DESCRIPTION:' + ics_text(description), 'STATUS:CONFIRMED', 'END:VEVENT'])
    lines.append('END:VCALENDAR')
    return Response('\r\n'.join(fold_ics(line) for line in lines) + '\r\n', media_type='text/calendar; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="atlas-week-{data["week_start"]}.ics"'})

@app.get('/api/grades')
def grades(user:User=Depends(require_student),db:Session=Depends(get_db)):
    rows=db.scalars(select(Grade).where(Grade.student_id==user.id).order_by(Grade.id)).all()
    items=[dict(id=g.id,subject=g.subject,score=g.current,max=g.max_grade,trend=g.trend,
                exam_kind=g.exam_kind,assessment=g.assessment,teacher=g.teacher,
                exam_date=date_iso(g.exam_date),color=g.color) for g in rows]
    avg=round(sum(g.current for g in rows if g.current is not None)/max(1,len([g for g in rows if g.current is not None]))) if rows else 0
    return {'items':items,'average':avg,'credits_passed':len([g for g in rows if g.exam_kind=='Зачёт' and g.current is not None and g.current>=65]),
            'credits_total':len([g for g in rows if g.exam_kind=='Зачёт']),
            'risk_count':len([g for g in rows if g.current is not None and g.current<65])}

@app.get('/api/deadlines')
def deadlines(user:User=Depends(require_student),db:Session=Depends(get_db)):
    rows=db.scalars(select(Deadline).where(Deadline.student_id==user.id).order_by(Deadline.due_date, Deadline.id).limit(200)).all()
    return [deadline_payload(d) for d in rows]


def deadline_payload(d):
    return {'id':d.id,'subject':d.subject,'title':d.title,'due_date':str(d.due_date),'is_done':d.is_done}


RequestFilter = Literal['all', 'active', 'overdue', 'submitted', 'review', 'processing', 'needs_info', 'ready', 'rejected']
NotificationFilter = Literal['all', 'unread', 'schedule', 'deadline', 'request', 'announcement']


def text_search(column, value):
    # SQLite lower()/LIKE does not case-fold Cyrillic. Its connection function
    # mirrors Python casefold; PostgreSQL uses its native case-insensitive LIKE.
    if engine.dialect.name == 'sqlite':
        return func.casefold(column).contains(value.casefold(), autoescape=True)
    escaped = value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return column.ilike('%' + escaped + '%', escape='\\')


def search_text(value):
    value = value.strip()
    if re.search(r'[\x00-\x1f\ud800-\udfff]', value):
        raise HTTPException(422, 'Недопустимые символы поискового запроса')
    return value


def request_counts(db, scope):
    active = DocumentRequest.status.in_(['submitted', 'review', 'processing', 'needs_info'])
    expressions = {
        'active': active,
        **{value: DocumentRequest.status == value for value in STATUS_NAMES},
        'overdue': active & (DocumentRequest.due_at < campus_today()),
    }
    row = db.execute(select(func.count(DocumentRequest.id).label('all'), *[func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name) for name, condition in expressions.items()]).where(*scope)).mappings().one()
    return {name: int(value) for name, value in row.items()}


def request_list_conditions(scope, filter_name, search, staff=False):
    conditions = list(scope)
    if filter_name == 'active':
        conditions.append(DocumentRequest.status.in_(['submitted', 'review', 'processing', 'needs_info']))
    elif filter_name == 'overdue':
        conditions.extend([DocumentRequest.status.in_(['submitted', 'review', 'processing', 'needs_info']), DocumentRequest.due_at < campus_today()])
    elif filter_name != 'all':
        conditions.append(DocumentRequest.status == filter_name)
    search = search_text(search)
    if search:
        columns = [DocumentRequest.type, DocumentRequest.comment]
        if staff:
            columns.extend([User.full_name, User.group_name])
        options = [text_search(column, search) for column in columns]
        id_text = search.lstrip('#№ ')
        if id_text.isascii() and id_text.isdecimal() and len(id_text) <= 10:
            options.append(DocumentRequest.id == int(id_text))
        conditions.append(or_(*options))
    return conditions


def list_response(items, total, offset, limit, counts, paginated, response, unread_count=None):
    response.headers['X-Total-Count'] = str(total)
    if unread_count is not None:
        response.headers['X-Unread-Count'] = str(unread_count)
    if not paginated:
        return items
    result = {'items': items, 'total': total, 'offset': offset, 'limit': limit, 'has_more': offset + len(items) < total, 'counts': counts}
    if unread_count is not None:
        result['unread_count'] = unread_count
    return result

class DeadlineToggleBody(StrictBody):
    is_done: StrictBool


@app.post('/api/deadlines/{deadline_id}/toggle')
def toggle_deadline(deadline_id: int, body: DeadlineToggleBody, user: User = Depends(require_student), db: Session = Depends(get_db), _: None = Depends(require_same_origin)):
    row = db.scalar(select(Deadline).where(Deadline.id == deadline_id, Deadline.student_id == user.id))
    if not row:
        raise HTTPException(404, 'Задание не найдено')
    row.is_done = body.is_done
    db.commit()
    return deadline_payload(row)

@app.get('/api/requests/types')
def request_types(user:User=Depends(require_student)):
    return DOC_TYPES

@app.get('/api/requests')
def requests_list(response: Response, paginated: bool = False, offset: int = Query(0, ge=0, le=2147483647), limit: int = Query(200, ge=1, le=200), filter: RequestFilter = 'all', q: str = Query('', max_length=100), user:User=Depends(require_student),db:Session=Depends(get_db)):
    scope = [DocumentRequest.student_id == user.id]
    conditions = request_list_conditions(scope, filter, q)
    total = db.scalar(select(func.count()).select_from(DocumentRequest).where(*conditions))
    counts = request_counts(db, scope)
    rows=db.scalars(select(DocumentRequest).where(*conditions).order_by(DocumentRequest.created_at.desc(),DocumentRequest.id.desc()).offset(offset).limit(limit)).all()
    return list_response([request_payload(r) for r in rows], total, offset, limit, counts, paginated, response)

@app.get('/api/requests/{request_id}')
def request_details(request_id:int,history_limit:int=Query(100,ge=1,le=200),history_offset:int|None=Query(None,ge=0,le=2147483647),user:User=Depends(require_student),db:Session=Depends(get_db)):
    # Ownership check belongs in SQL query, not in the UI or an after-the-fact check.
    row=db.scalar(select(DocumentRequest).where(DocumentRequest.id==request_id,DocumentRequest.student_id==user.id))
    if not row: raise HTTPException(404,'Заявка не найдена')
    return request_with_history(row, db, history_limit=history_limit, history_offset=history_offset)

class NewRequestBody(StrictBody):
    type: str = Field(min_length=1, max_length=40)
    comment: str = Field(default='',max_length=1200)
    details: dict[str,str] = Field(default_factory=dict,max_length=4)

    @field_validator('type')
    @classmethod
    def known_type(cls, value):
        if value not in DOC_NAMES:
            raise ValueError('Неизвестная услуга')
        return value

SERVICE_FIELDS = {
    'study': {'purpose':('Для чего нужна справка',120),'copies':('Количество экземпляров',1)},
    'transcript': {'period':('Учебный период',80),'format':('Формат результата',40)},
    'retake': {'subject':('Дисциплина',130),'preferred_date':('Желаемая дата',10)},
}

def validate_service_details(service,details,user,db,*,validate_time=True):
    fields=SERVICE_FIELDS.get(service,{})
    for key,value in details.items():
        if key not in fields or not value.strip() or len(value)>fields[key][1] or re.search(r'[\x00-\x1f\ud800-\udfff]',value):
            raise HTTPException(422,{'message':'Проверьте сведения услуги','field':'details.'+key})
    if 'copies' in details and details['copies'] not in {'1','2','3'}: raise HTTPException(422,{'message':'Выберите от 1 до 3 экземпляров','field':'copies'})
    if 'format' in details and details['format'] not in {'HTML','PDF через печать'}: raise HTTPException(422,'Недопустимый формат')
    if 'preferred_date' in details:
        try: target=date.fromisoformat(details['preferred_date'])
        except ValueError: raise HTTPException(422,'Укажите корректную желаемую дату')
        if validate_time and not campus_today()<=target<=campus_today()+timedelta(days=180): raise HTTPException(422,'Выберите дату в ближайшие 180 дней')
    if 'subject' in details and not db.scalar(select(Grade.id).where(Grade.student_id==user.id,Grade.subject==details['subject'])):
        raise HTTPException(422,'Выберите дисциплину из собственной успеваемости')
    return {k:v.strip() for k,v in details.items()}

@app.post('/api/requests',status_code=201)
def new_request(body:NewRequestBody,request:Request,response:Response,user:User=Depends(require_student),db:Session=Depends(get_db),_:None=Depends(require_same_origin)):
    comment=body.comment.strip()
    details=validate_service_details(body.type,body.details,user,db,validate_time=False)
    service = next(t for t in DOC_TYPES if t['id'] == body.type)
    if (body.type == 'statement' or service.get('requires_comment')) and len(comment)<10:
        raise HTTPException(422,'Опишите вопрос хотя бы в 10 символах')
    key = request.headers.get('Idempotency-Key')
    if key is not None and not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', key):
        raise HTTPException(422, 'Недопустимый ключ отправки')
    submission={'type': body.type, 'comment':comment}
    if details: submission['details']=details
    payload_hash = hashlib.sha256(json.dumps(submission, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if key:
        previous = db.scalar(select(RequestIdempotency).where(RequestIdempotency.student_id == user.id, RequestIdempotency.key == key))
        if previous:
            if previous.payload_hash != payload_hash:
                raise HTTPException(409, 'Эта отправка уже использована для другой заявки')
            response.status_code = 200
            return request_payload(db.get(DocumentRequest, previous.request_id))
    # A completed retry is valid even when its originally chosen date has passed.
    validate_service_details(body.type,details,user,db)
    now=utc_now()
    row=DocumentRequest(student_id=user.id,type=DOC_NAMES[body.type],comment=comment,details=json.dumps(details,ensure_ascii=False),
                        status='submitted',created_at=now,updated_at=now,
                        due_at=request_due_date(DOC_NAMES[body.type], campus_today()), staff_message='', version=1)
    db.add(row)
    db.flush()
    db.add(RequestEvent(request_id=row.id, status='submitted',message='Заявка принята и передана в учебный офис.',actor_role='student',actor_name=user.full_name,created_at=now))
    db.add(Notification(student_id=user.id,title='Заявка отправлена',body=f'{DOC_NAMES[body.type]} — заявка №{row.id} принята. Статус можно отслеживать в разделе «Заявки».',category='request',created_at=now,is_read=False,target='/app/requests',request_id=row.id))
    if key:
        db.add(RequestIdempotency(student_id=user.id, key=key, payload_hash=payload_hash, request_id=row.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(select(RequestIdempotency).where(RequestIdempotency.student_id == user.id, RequestIdempotency.key == key)) if key else None
        if previous and previous.payload_hash == payload_hash:
            response.status_code = 200
            return request_payload(db.get(DocumentRequest, previous.request_id))
        raise HTTPException(409, 'Заявка была отправлена в другом окне; обновите список')
    db.refresh(row)
    return request_payload(row)


@app.get('/api/requests/{request_id}/document')
def request_document(request_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
    row = db.scalar(select(DocumentRequest).where(DocumentRequest.id == request_id, DocumentRequest.student_id == user.id))
    if not row:
        raise HTTPException(404, 'Заявка не найдена')
    if row.status != 'ready':
        raise HTTPException(409, 'Документ станет доступен после готовности заявки')
    esc = html.escape
    nonce = secrets.token_urlsafe(18)
    if row.type == DOC_NAMES['study']:
        content = f'<p>В рамках вымышленного сценария подтверждается, что <strong>{esc(user.full_name)}</strong> обучается на {user.course} курсе по направлению «{esc(user.program)}», группа {esc(user.group_name)}.</p>'
    elif row.type == DOC_NAMES['transcript']:
        rows = db.scalars(select(Grade).where(Grade.student_id == user.id).order_by(Grade.id)).all()
        content = '<table><thead><tr><th>Дисциплина</th><th>Баллы</th><th>Аттестация</th></tr></thead><tbody>' + ''.join(f'<tr><td>{esc(g.subject)}</td><td>{g.current if g.current is not None else "—"}/{g.max_grade}</td><td>{esc(g.assessment)}</td></tr>' for g in rows) + '</tbody></table>'
    elif row.type == DOC_NAMES['scholarship']:
        content = '<p>Демонстрационная справка о стипендии. Суммы вымышленной финансовой ленты не подтверждают реальное начисление или выплату. Образец не имеет юридической силы.</p>'
    else:
        content = f'<h2>Обращение</h2><p class="multiline">{esc(row.comment)}</p>'
    if row.details and row.details!='{}':
        labels={'purpose':'Назначение','copies':'Экземпляры','period':'Учебный период','format':'Формат','subject':'Дисциплина','preferred_date':'Желаемая дата'}
        content+='<h2>Сведения заявки</h2><dl>'+''.join('<dt>'+esc(labels.get(k,k))+'</dt><dd>'+esc(v)+'</dd>' for k,v in json.loads(row.details).items())+'</dl>'
    document = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>АТЛАС · образец №{row.id}</title><style nonce="{nonce}">body{{margin:0;background:#f2f3f8;color:#202338;font:16px/1.65 system-ui,sans-serif}}main{{max-width:760px;margin:40px auto;padding:40px;background:white;border:1px solid #dce0eb}}.warning{{padding:16px;border:2px solid #ad4024;color:#8d301a;font-weight:700}}small{{color:#596174}}h1{{font-size:28px}}h2{{font-size:19px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #dce0eb}}.multiline{{white-space:pre-wrap;overflow-wrap:anywhere}}footer{{margin-top:40px;padding-top:20px;border-top:1px solid #dce0eb}}@media(max-width:600px){{main{{margin:0;padding:20px}}th,td{{font-size:13px;padding:6px}}}}@page{{size:A4;margin:16mm}}td,th,dd{{overflow-wrap:anywhere}}tr,footer{{break-inside:avoid}}@media print{{body{{background:white}}main{{margin:0;border:0;padding:0}}}}</style></head><body><main><div class="warning">КОНКУРСНЫЙ ОБРАЗЕЦ · ВСЕ ДАННЫЕ ВЫМЫШЛЕНЫ</div><p><strong>АТЛАС / цифровой кампус</strong><br><small>Неофициальный концепт. Не является документом образовательной организации.</small></p><h1>{esc(row.type)}</h1><p>Заявка №{row.id} · подготовлена {row.updated_at.astimezone(CAMPUS_TZ).strftime('%d.%m.%Y') if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc).astimezone(CAMPUS_TZ).strftime('%d.%m.%Y')}</p><p><strong>{esc(user.full_name)}</strong><br>{esc(user.faculty)}<br>{esc(user.program)} · {esc(user.group_name)}<br>Вымышленный номер: {esc(user.student_number)}</p>{content}<h2>Ответ учебного офиса</h2><p class="multiline">{esc(row.staff_message)}</p><footer>Этот образец показывает полный путь заявки в прототипе. Юридической силы не имеет. Реальная подпись, печать и интеграция с вузом отсутствуют.<br><small>Можно сохранить в PDF через печать браузера.</small></footer></main></body></html>'''
    return HTMLResponse(document, headers={'Content-Disposition': f'attachment; filename="atlas-document-{row.id}.html"', 'Content-Security-Policy': f"default-src 'none'; script-src 'none'; style-src 'nonce-{nonce}'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"})

@app.get('/api/notifications')
def notifications(response: Response, paginated: bool = False, offset: int = Query(0, ge=0, le=2147483647), limit: int = Query(200, ge=1, le=200), filter: NotificationFilter = 'all', q: str = Query('', max_length=100), user:User=Depends(require_student),db:Session=Depends(get_db)):
    scope = [Notification.student_id == user.id]
    expressions = {'unread': Notification.is_read.is_(False), **{category: Notification.category == category for category in ['schedule', 'deadline', 'request', 'announcement']}}
    values = db.execute(select(func.count(Notification.id).label('all'), *[func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name) for name, condition in expressions.items()]).where(*scope)).mappings().one()
    counts = {name: int(value) for name, value in values.items()}
    conditions = list(scope)
    if filter != 'all':
        conditions.append(expressions[filter])
    search = search_text(q)
    if search:
        conditions.append(or_(text_search(Notification.title, search), text_search(Notification.body, search)))
    total = db.scalar(select(func.count()).select_from(Notification).where(*conditions))
    rows=db.scalars(select(Notification).where(*conditions).order_by(Notification.created_at.desc(),Notification.id.desc()).offset(offset).limit(limit)).all()
    return list_response([notification_payload(n) for n in rows], total, offset, limit, counts, paginated, response, counts['unread'])

@app.post('/api/notifications/{notification_id}/read')
def read_notification(notification_id:int,user:User=Depends(require_student),db:Session=Depends(get_db),_:None=Depends(require_same_origin)):
    row=db.scalar(select(Notification).where(Notification.id==notification_id,Notification.student_id==user.id))
    if not row: raise HTTPException(404,'Уведомление не найдено')
    row.is_read=True;db.commit()
    return {'ok':True}

@app.post('/api/notifications/read-all')
def read_all_notifications(user:User=Depends(require_student),db:Session=Depends(get_db),_:None=Depends(require_same_origin)):
    db.query(Notification).filter(Notification.student_id==user.id).update({'is_read':True})
    db.commit();return {'ok':True}

@app.get('/api/dashboard')
def dashboard(user:User=Depends(require_student),db:Session=Depends(get_db)):
    now = datetime.now(CAMPUS_TZ)
    today = now.date()
    monday=today-timedelta(days=today.weekday())
    days=get_week_schedule(db,user,monday)
    incoming=db.scalars(select(Deadline).where(Deadline.student_id==user.id,Deadline.is_done==False).order_by(Deadline.due_date, Deadline.id).limit(3)).all()
    grade_data=grades(user,db)
    recent=db.scalars(select(Notification).where(Notification.student_id==user.id).order_by(Notification.created_at.desc()).limit(3)).all()
    open_requests=db.scalar(select(func.count()).select_from(DocumentRequest).where(DocumentRequest.student_id==user.id,DocumentRequest.status.not_in(['ready', 'rejected'])))
    unread=db.scalar(select(func.count()).select_from(Notification).where(Notification.student_id==user.id,Notification.is_read==False))
    upcoming_days = days + get_week_schedule(db, user, monday + timedelta(days=7))
    next_lesson = next((lesson for day in upcoming_days for lesson in day['items'] if day['date'] > str(today) or (day['date'] == str(today) and lesson['end'] > now.strftime('%H:%M'))), None)
    return {'profile':public_user(user),'today':next((d['items'] for d in days if d['date']==str(today)),[]),
            'week_classes':sum(len(d['items']) for d in days),'grades':grade_data,
            'deadlines':[deadline_payload(d) for d in incoming],
            'notifications':[notification_payload(n) for n in recent],
            'open_requests':open_requests,'unread_count':unread,
            'next_lesson': next_lesson, 'timezone': 'Europe/Moscow', 'server_now': now.isoformat()}

@app.get('/api/staff/requests')
def staff_requests(response: Response, paginated: bool = False, offset: int = Query(0, ge=0, le=2147483647), limit: int = Query(200, ge=1, le=200), filter: RequestFilter = 'all', q: str = Query('', max_length=100), user:User=Depends(require_staff),db:Session=Depends(get_db)):
    conditions = request_list_conditions([], filter, q, staff=True)
    total = db.scalar(select(func.count()).select_from(DocumentRequest).join(User, DocumentRequest.student_id == User.id).where(*conditions))
    counts = request_counts(db, [])
    rows=db.execute(select(DocumentRequest,User).join(User,DocumentRequest.student_id==User.id).where(*conditions).order_by(DocumentRequest.created_at.desc(),DocumentRequest.id.desc()).offset(offset).limit(limit)).all()
    items = [{**request_payload(r),'student_name':u.full_name,'group':u.group_name} for r,u in rows]
    return list_response(items, total, offset, limit, counts, paginated, response)


@app.get('/api/staff/requests/{request_id}')
def staff_request_details(request_id: int, history_limit:int=Query(100,ge=1,le=200), history_offset:int|None=Query(None,ge=0,le=2147483647), user: User = Depends(require_staff), db: Session = Depends(get_db)):
    row = db.get(DocumentRequest, request_id)
    if not row:
        raise HTTPException(404, 'Заявка не найдена')
    student = db.get(User, row.student_id)
    return {**request_with_history(row, db, history_limit=history_limit, history_offset=history_offset), 'student_name': student.full_name, 'group': student.group_name}


class StaffStatusBody(StrictBody):
    status: Literal['submitted','review','processing','needs_info','ready','rejected']
    message: str = Field(default='', max_length=2000)
    expected_version: int | None = Field(default=None, ge=1)

@app.post('/api/staff/requests/{request_id}/status')
def staff_update(request_id:int,body:StaffStatusBody,user:User=Depends(require_staff),db:Session=Depends(get_db),_:None=Depends(require_same_origin)):
    row=db.get(DocumentRequest,request_id)
    if not row: raise HTTPException(404,'Заявка не найдена')
    if body.expected_version is not None and body.expected_version != row.version:
        raise HTTPException(409, 'Заявка изменена в другом окне. Обновите данные.')
    if body.status not in ALLOWED_TRANSITIONS[row.status]: raise HTTPException(409,'Этот переход статуса недопустим')
    message = body.message.strip()
    if body.status in {'needs_info','ready', 'rejected'} and len(message) < 10:
        raise HTTPException(422, 'Добавьте ответ или причину отклонения: не менее 10 символов')
    now = utc_now()
    result = db.execute(update(DocumentRequest).where(DocumentRequest.id == row.id, DocumentRequest.version == row.version, DocumentRequest.status == row.status).values(status=body.status,staff_message=message or row.staff_message,updated_at=now,version=row.version+1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'Заявка уже изменена другим сотрудником. Обновите данные.')
    db.add(RequestEvent(request_id=row.id,status=body.status,message=message or f'Статус: {STATUS_NAMES[body.status]}.',actor_role='staff',actor_name=user.full_name,created_at=now))
    db.add(Notification(student_id=row.student_id,title='Статус заявки изменился',body=f'{row.type}, №{row.id}: {STATUS_NAMES[body.status]}. {message}',category='request',created_at=now,is_read=False,target='/app/requests',request_id=row.id))
    db.commit()
    db.refresh(row)
    return request_with_history(row, db)

@app.get('/')
def index(): return FileResponse(APP_DIR/'static'/'index.html')

@app.get('/app/{path:path}')
def app_routes(path:str): return FileResponse(APP_DIR/'static'/'index.html')

@app.get('/static/{filename:path}')
def static_files(filename:str):
    allowed={'app.js':'text/javascript','campus.js':'text/javascript','improvements.js':'text/javascript','campus.css':'text/css','style.css':'text/css','usability.css':'text/css','favicon.svg':'image/svg+xml'}
    if filename not in allowed: raise HTTPException(404)
    return FileResponse(APP_DIR/'static'/filename,media_type=allowed[filename])


# Router factories receive the same authentication, ownership and CSRF
# dependencies as the original core; importing modules does not touch the DB.
from .learning import create_router as learning_router
from .services import create_router as services_router
from .campus import create_router as campus_router
app.include_router(learning_router())
app.include_router(services_router())
app.include_router(campus_router())
from .improvements import create_router as improvements_router, install_quota
app.include_router(improvements_router())
install_quota(app)
# Install last so headers also cover early quota, CSRF and actor-affinity
# rejections. Starlette wraps newly added middleware around the existing stack.
app.add_middleware(SecurityHeaders)
