"""Private drafts, request follow-up and database-backed public demo quotas."""
import hashlib
import json
import re
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, field_validator, StrictStr, TypeAdapter
from sqlalchemy import select, func, delete, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from .db import SessionLocal, LoginSession, DocumentRequest, RequestEvent, User, utc_now, engine
from .improvement_db import PersonalDraft, WriteQuota, FollowupReceipt
from .config import settings
from .services import begin_idempotent, commit_idempotent
from .services_db import ServiceIdempotency
from .receipt_codec import decode_receipt
from .session_security import as_utc, validate_expected_actor
from .storage_guards import lock_owner

_path_integer = TypeAdapter(int)

def canonical_resource_path(path):
    parts = path.split('/')
    for index, part in enumerate(parts):
        try:
            number = _path_integer.validate_python(part)
        except ValueError:
            continue
        parts[index] = str(number)
    return '/'.join(parts)

def quota_limit(bucket, period):
    # Public shared fictional accounts need meaningful limits. Local development
    # permits repeat automated acceptance; the same algorithm is tested below.
    limits = {'write': (180,2000), 'create': (60,500), 'draft': (120,3000)}
    if bucket == 'direct':
        return (12, 120)[period]
    return limits[bucket][period] * (1 if settings.app_env=='production' else 20)

def reserve_write(db,user_id,bucket,now):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    insert = pg_insert if engine.dialect.name=='postgresql' else sqlite_insert
    for period,window in enumerate((now.strftime('%Y%m%d%H%M'),now.strftime('%Y%m%d'))):
        key=bucket+str(period)
        statement=insert(WriteQuota).values(user_id=user_id,bucket=key,window=window,count=1)
        statement=statement.on_conflict_do_update(index_elements=['user_id','bucket','window'],set_={'count':WriteQuota.count+1},where=WriteQuota.count<quota_limit(bucket,period)).returning(WriteQuota.count)
        if db.scalar(statement) is None:
            raise HTTPException(429,'Слишком много сохранений. Подождите и повторите отправку.',headers={'Retry-After':'60' if period==0 else '3600'})

def creates_resource(path,method):
    if method!='POST':return False
    path=canonical_resource_path(path)
    if path in {'/api/requests','/api/services/tickets','/api/staff/consultations','/api/staff/events','/api/staff/announcements',
                '/api/learning/notes','/api/learning/flashcards','/api/learning/tasks','/api/learning/focus-sessions','/api/campus/portfolio',
                '/api/materials','/api/direct/dialogs','/api/teaching/consultations','/api/scheduling/changes'}:
        return True
    return bool(re.fullmatch(r'/api/(?:services|staff)/tickets/[0-9]+/messages',path)
                or re.fullmatch(r'/api/services/(?:consultations/[0-9]+/book|events/[0-9]+/register|library/[0-9]+/borrow)',path)
                or re.fullmatch(r'/api/learning/(?:assignments/[0-9]+/submit|quizzes/[0-9]+/attempt)',path)
                or re.fullmatch(r'/api/direct/dialogs/[0-9]+/messages',path)
                or re.fullmatch(r'/api/teaching/[0-9]+/works(?:/[0-9]+/feedback/[0-9]+)?',path)
                or re.fullmatch(r'/api/units/(?:union|vuc)/cases',path))

def charge_token(token,path,method,expected_actor=None):
    # Synchronous DB work is dispatched to a worker thread by middleware so a
    # contended quota row does not block the server's async event loop.
    with SessionLocal() as db:
        now=utc_now()
        session=db.scalar(select(LoginSession).where(LoginSession.token_hash==hashlib.sha256(token.encode()).hexdigest()))
        if session and as_utc(session.expires_at)>as_utc(now):
            validate_expected_actor(expected_actor,session.user_id)
            bucket='draft' if path.startswith('/api/drafts/') else 'write'
            reserve_write(db,session.user_id,bucket,now)
            if creates_resource(path,method):reserve_write(db,session.user_id,'create',now)
            db.execute(delete(WriteQuota).where(WriteQuota.window< (now-timedelta(days=2)).strftime('%Y%m%d')))
            db.commit()

def install_quota(app):
    from .main import COOKIE_NAME, require_same_origin
    from fastapi.responses import JSONResponse
    @app.middleware('http')
    async def guard(request,call_next):
        if request.method not in {'POST','PUT','PATCH','DELETE'} or not request.url.path.startswith('/api/') or request.url.path in {'/api/login','/api/logout'}:
            return await call_next(request)
        token=request.cookies.get(COOKIE_NAME)
        if token:
            try:
                require_same_origin(request)
                await run_in_threadpool(charge_token,token,request.url.path,request.method,request.headers.get('X-ATLAS-User'))
            except HTTPException as error:
                return JSONResponse({'detail':error.detail},status_code=error.status_code,headers=error.headers)
        return await call_next(request)

def create_router():
    from .main import StrictBody, require_user, require_student, get_db, require_same_origin, request_with_history
    router=APIRouter()
    class DraftBody(StrictBody):
        values: dict[str,StrictStr] = Field(max_length=24)
        @field_validator('values')
        @classmethod
        def safe_values(cls,values):
            if sum(len(v) for v in values.values())>16000 or any(len(v)>12000 for v in values.values()):
                raise ValueError('Черновик слишком длинный')
            if any(not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',k) or any(word in k.lower() for word in ('password','secret','token')) for k in values):
                raise ValueError('Недопустимое поле черновика')
            if any(re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]',v) for v in values.values()):
                raise ValueError('Недопустимые символы')
            return values
    def valid_name(name):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',name):
            raise HTTPException(422,'Недопустимое имя черновика')

    def bound_name(name,user,db):
        match=re.fullmatch(r'(note|task|portfolio|flashcard|focus):([0-9]+):([a-f0-9]{32})',name)
        if not match:return
        record_id=int(match[2])
        if not 1<=record_id<=2147483647:
            raise HTTPException(422,'Недопустимый номер записи для черновика')
        from .learning_db import StudyNote,PersonalTask,Flashcard,FocusSession
        from .campus_db import PortfolioItem
        model={'note':StudyNote,'task':PersonalTask,'portfolio':PortfolioItem,'flashcard':Flashcard,'focus':FocusSession}[match[1]]
        row=db.scalar(select(model).where(model.id==record_id,model.student_id==user.id))
        if not row:raise HTTPException(404,'Запись для черновика не найдена')
        if row.record_token!=match[3]:raise HTTPException(409,{'code':'record_changed','message':'Запись заменена. Откройте её заново.'})

    @router.get('/api/drafts/export')
    def export_drafts(user=Depends(require_user),db=Depends(get_db)):
        rows=db.scalars(select(PersonalDraft).where(PersonalDraft.user_id==user.id).order_by(PersonalDraft.id)).all()
        items=[{'name':row.name,'values':json.loads(row.values_json),'updated_at':row.updated_at.isoformat(),
                'requires_manual_recovery':bool(re.fullmatch(r'(note|task|portfolio|flashcard|focus):[0-9]+',row.name))} for row in rows]
        return {'items':items,'legacy_recovery_count':sum(item['requires_manual_recovery'] for item in items)}

    @router.get('/api/drafts/{name}')
    def get_draft(name:str,user=Depends(require_user),db=Depends(get_db)):
        valid_name(name)
        bound_name(name,user,db)
        row=db.scalar(select(PersonalDraft).where(PersonalDraft.user_id==user.id,PersonalDraft.name==name,PersonalDraft.updated_at>=utc_now()-timedelta(days=14)))
        return {'values':json.loads(row.values_json) if row else {},'updated_at':row.updated_at.isoformat() if row else None,'retention_days':14}
    @router.put('/api/drafts/{name}')
    def put_draft(name:str,body:DraftBody,user=Depends(require_user),db=Depends(get_db),_=Depends(require_same_origin)):
        valid_name(name)
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        now=utc_now()
        # Serialize the cap check for one owner on PostgreSQL. On SQLite the
        # following DELETE starts the write transaction and supplies its lock.
        lock_owner(db,user.id)
        bound_name(name,user,db)
        db.execute(delete(PersonalDraft).where(PersonalDraft.updated_at<now-timedelta(days=14)))
        row=db.scalar(select(PersonalDraft.id).where(PersonalDraft.user_id==user.id,PersonalDraft.name==name))
        if not row and db.scalar(select(func.count()).select_from(PersonalDraft).where(PersonalDraft.user_id==user.id))>=40:
            raise HTTPException(409,'Сохранено 40 черновиков. Завершите одну из форм.')
        insert=pg_insert if engine.dialect.name=='postgresql' else sqlite_insert
        values=json.dumps(body.values,ensure_ascii=False)
        stmt=insert(PersonalDraft).values(user_id=user.id,name=name,values_json=values,updated_at=now)
        db.execute(stmt.on_conflict_do_update(index_elements=['user_id','name'],set_={'values_json':values,'updated_at':now}))
        db.commit()
        return {'saved':True,'retention_days':14,'updated_at':now.isoformat()}
    @router.delete('/api/drafts/{name}')
    def delete_draft(name:str,user=Depends(require_user),db=Depends(get_db),_=Depends(require_same_origin)):
        valid_name(name)
        db.execute(delete(PersonalDraft).where(PersonalDraft.user_id==user.id,PersonalDraft.name==name));db.commit()
        return {'ok':True}
    class FollowupBody(StrictBody):
        message: str = Field(min_length=10,max_length=1200)
        expected_version: int = Field(strict=True,ge=1,le=2147483647)
        kind: str = Field(default='clarification',pattern='^(clarification|withdrawal)$')
    @router.post('/api/requests/{request_id}/followup')
    def followup(request_id:int,body:FollowupBody,request:Request,response:Response,user=Depends(require_student),db=Depends(get_db),_=Depends(require_same_origin)):
        row=db.scalar(select(DocumentRequest).where(DocumentRequest.id==request_id,DocumentRequest.student_id==user.id))
        if not row: raise HTTPException(404,'Заявка не найдена')
        key=request.headers.get('Idempotency-Key','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key): raise HTTPException(422,'Нужен ключ безопасной отправки')
        message=body.message.strip()
        if len(message)<10: raise HTTPException(422,'Добавьте пояснение от 10 символов')
        fingerprint=hashlib.sha256(json.dumps(body.model_dump(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        previous=db.scalar(select(FollowupReceipt).where(FollowupReceipt.user_id==user.id,FollowupReceipt.request_id==request_id,FollowupReceipt.key==key))
        if previous:
            if previous.fingerprint!=fingerprint: raise HTTPException(409,'Ключ уже использован для другого уточнения')
            saved=db.scalar(select(ServiceIdempotency).where(ServiceIdempotency.user_id==user.id,ServiceIdempotency.operation==f'request-followup:{request_id}',ServiceIdempotency.key==key))
            if saved and saved.response_json:return decode_receipt(db,saved.response_json)
            return request_with_history(row,db)
        receipt,replay=begin_idempotent(db,request,response,user,f'request-followup:{request_id}',body.model_dump())
        if replay is not None:return replay
        if row.status in {'ready','rejected'}: raise HTTPException(409,'Заявка завершена. Создайте новое обращение.')
        if body.expected_version!=row.version:raise HTTPException(409,'Заявка изменилась. Откройте её заново.')
        result=db.execute(update(DocumentRequest).where(DocumentRequest.id==row.id,DocumentRequest.student_id==user.id,
                          DocumentRequest.version==row.version,DocumentRequest.version==body.expected_version,
                          DocumentRequest.status==row.status,DocumentRequest.status.not_in(['ready','rejected']))
                          .values(version=DocumentRequest.version+1,updated_at=utc_now()).execution_options(synchronize_session=False))
        if result.rowcount!=1: raise HTTPException(409,'Заявка изменилась. Откройте её заново.')
        prefix='Просьба об отзыве' if body.kind=='withdrawal' else 'Уточнение студента'
        db.add(RequestEvent(request_id=row.id,status=row.status,message=prefix+': '+message,actor_role='student',actor_name=user.full_name,created_at=utc_now()))
        db.add(FollowupReceipt(user_id=user.id,request_id=row.id,key=key,fingerprint=fingerprint))
        try:
            db.flush()
            db.refresh(row)
            return commit_idempotent(db,receipt,request_with_history(row,db))
        except IntegrityError:
            db.rollback()
            previous=db.scalar(select(FollowupReceipt).where(FollowupReceipt.user_id==user.id,FollowupReceipt.request_id==request_id,FollowupReceipt.key==key))
            if not previous or previous.fingerprint!=fingerprint: raise HTTPException(409,'Уточнение уже изменилось')
        db.refresh(row)
        return request_with_history(row,db)
    return router
