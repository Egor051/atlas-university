"""Scoped workflows for the fictional student union and VUC."""
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .db import User, campus_today, utc_now
from .main import StrictBody, date_iso, get_db, require_roles, require_same_origin, require_student, require_user
from .services import begin_idempotent, commit_idempotent
from .session_security import as_utc
from .table_formats import table_bytes
from .units_db import (CenterEnrollment, CenterGroup, CenterProgram, CenterSession,
                       UnionMembership, UnitCase, UnitCaseEvent, UnitPublication)
from .workspace import lock_workspace, notify, recorded
from .workspace_db import OperationEvent

Unit = Literal['union','vuc']
RecordId = Annotated[int, Path(ge=1,le=2147483647)]
BodyId = Annotated[int, Field(strict=True,ge=1,le=2147483647)]
router = APIRouter(prefix='/api/units')
write = [Depends(require_same_origin)]
center_staff = require_roles('vuc')
CASE_NAMES = {'join':'Вступление в профсоюз','leave':'Выход из профсоюза','aid':'Материальная помощь',
              'consult':'Консультация','appeal':'Обращение','event':'Запись на мероприятие','apply':'Заявление в ВУЦ'}
STATES = {'submitted':'Подано','review':'Проверяется','needs_info':'Нужно уточнение','selection':'Рассмотрение решения',
          'accepted':'Одобрено','rejected':'Отклонено','resolved':'Ответ готов'}
UNITS = {'union':'Студенческий профсоюз','vuc':'Военный учебный центр'}
POST_KINDS = {'union':{'structure','news','benefit','event','document'},'vuc':{'structure','news','document','material'}}
UNIT_CASES = {'union':{'join','leave','aid','consult','appeal','event'},'vuc':{'apply','consult','appeal'}}
TERMINAL = {'accepted','rejected','resolved'}
CHECKLIST = {'sample_application':'Образец заявления','sample_status':'Образец подтверждения статуса студента'}


class CaseBody(StrictBody):
    kind: Literal['join','leave','aid','consult','appeal','event','apply']
    message: str = Field(default='',max_length=1200)
    confirmed: bool = Field(default=False,strict=True)
    program_id: BodyId | None = None
    publication_id: BodyId | None = None
    checklist: list[Literal['sample_application','sample_status']] = Field(default_factory=list,max_length=2)


class CaseStep(StrictBody):
    status: Literal['review','needs_info','selection','accepted','rejected','resolved']
    version: int = Field(strict=True,ge=1)
    message: str = Field(default='',max_length=1200)
    group_id: BodyId | None = None


class Followup(StrictBody):
    version: int = Field(strict=True,ge=1)
    message: str = Field(min_length=3,max_length=1200)

    @field_validator('message',mode='before')
    @classmethod
    def trim(cls,value):
        return value.strip() if isinstance(value,str) else value


class Editor(StrictBody):
    id: BodyId | None = None
    version: int = Field(default=0,strict=True,ge=0)


class PublicationBody(Editor):
    kind: Literal['structure','news','benefit','event','document','material']
    title: str = Field(min_length=4,max_length=180)
    body: str = Field(min_length=12,max_length=5000)
    published: bool = Field(default=True,strict=True)
    event_day: date | None = None
    capacity: int | None = Field(default=None,strict=True,ge=1,le=200)
    group_id: BodyId | None = None

    @field_validator('title','body',mode='before')
    @classmethod
    def trim(cls,value):
        return value.strip() if isinstance(value,str) else value


class ProgramBody(Editor):
    title: str = Field(min_length=4,max_length=180)
    description: str = Field(min_length=10,max_length=1200)
    requirements: str = Field(min_length=10,max_length=1200)
    opens: date
    closes: date
    published: bool = Field(default=True,strict=True)

    @field_validator('title','description','requirements',mode='before')
    @classmethod
    def trim(cls,value):
        return value.strip() if isinstance(value,str) else value


class GroupBody(Editor):
    program_id: BodyId
    code: str = Field(min_length=2,max_length=60)
    capacity: int = Field(strict=True,ge=1,le=100)

    @field_validator('code',mode='before')
    @classmethod
    def trim(cls,value):
        return value.strip() if isinstance(value,str) else value


class SessionBody(Editor):
    group_id: BodyId
    title: str = Field(min_length=4,max_length=180)
    room: str = Field(min_length=2,max_length=100)
    starts: datetime
    ends: datetime
    cancelled: bool = Field(default=False,strict=True)

    @field_validator('title','room',mode='before')
    @classmethod
    def trim(cls,value):
        return value.strip() if isinstance(value,str) else value


class ResultBody(StrictBody):
    outcome: Literal['pending','passed','revision']
    comment: str = Field(max_length=1200)
    version: int = Field(strict=True,ge=1)


def unit_access(unit,user,*,manage=False):
    if user.role==unit:
        return True
    if user.role=='student' and not manage:
        return False
    raise HTTPException(403,'Раздел недоступен вашей роли')


def case_path(unit,case_id,*,office=False):
    return f"/app/{unit}{'-office' if office else ''}/{case_id}"


def get_case(db,unit,case_id,user):
    office=unit_access(unit,user)
    query=select(UnitCase).where(UnitCase.unit==unit,UnitCase.id==case_id)
    if not office:
        query=query.where(UnitCase.student_id==user.id)
    row=db.scalar(query)
    if row is None:
        raise HTTPException(404,'Заявление не найдено')
    return row


def case_steps(row):
    if row.status in {'submitted','needs_info'}:
        return ['review']
    if row.status=='selection':
        return ['accepted','rejected','needs_info']
    if row.status=='review':
        next_status='selection' if row.kind=='apply' else 'resolved' if row.kind in {'consult','appeal'} else 'accepted'
        return [next_status,'needs_info','rejected']
    return []


def case_data(row,*,name=None):
    caption=row.program.title if row.program else row.publication.title if row.publication else ''
    return dict(id=row.id,unit=row.unit,kind=row.kind,title=CASE_NAMES[row.kind],subject=caption,status=row.status,
                status_label=STATES[row.status],response=row.response,message=row.message,program_id=row.program_id,
                publication_id=row.publication_id,checklist=json.loads(row.sample_checklist),version=row.version,
                created_at=date_iso(row.created_at),updated_at=date_iso(row.updated_at),student=name,
                allowed=case_steps(row) if name else [],can_followup=name is None and row.status=='needs_info',
                file_url=f'/api/units/{row.unit}/cases/{row.id}/file' if row.status in TERMINAL else None)


def post_data(row):
    return dict(id=row.id,kind=row.kind,title=row.title,body=row.body,group_id=row.group_id,
                event_day=date_iso(row.event_day),capacity=row.capacity,published=row.published,
                updated_at=date_iso(row.updated_at),version=row.version,
                file_url=f'/api/units/{row.unit}/publications/{row.id}/file' if row.kind in {'document','material'} else None)


def program_data(row):
    return dict(id=row.id,title=row.title,description=row.description,requirements=row.requirements,
                opens=row.opens.isoformat(),closes=row.closes.isoformat(),published=row.published,version=row.version,
                accepting=row.published and row.opens<=campus_today()<=row.closes)


def group_data(row):
    return dict(id=row.id,code=row.code,program_id=row.program_id,program=row.program.title,capacity=row.capacity,version=row.version)


def session_data(row):
    return dict(id=row.id,group_id=row.group_id,group=row.group.code,title=row.title,room=row.room,
                starts=date_iso(row.starts_at),ends=date_iso(row.ends_at),cancelled=row.cancelled,version=row.version)


def enrollment_data(row,name=None):
    return dict(id=row.id,group_id=row.group_id,group=row.group.code,program=row.program.title,case_id=row.case_id,
                outcome=row.outcome,comment=row.comment,version=row.version,student=name)


def add_history(db,actor,row,action,message):
    db.add(UnitCaseEvent(case_id=row.id,actor_id=actor.id,status=row.status,action=action,message=message,created_at=utc_now()))


def notify_operators(db,unit,row,title):
    for uid in db.scalars(select(User.id).where(User.role==unit)):
        notify(db,uid,title,f'{CASE_NAMES[row.kind]} №{row.id}',case_path(unit,row.id,office=True))


def membership(db,uid):
    return db.get(UnionMembership,uid)


def visible_posts(unit,user,office):
    query=select(UnitPublication).where(UnitPublication.unit==unit)
    if not office:
        groups=select(CenterEnrollment.group_id).where(CenterEnrollment.student_id==user.id)
        query=query.where(UnitPublication.published.is_(True),
                          or_(UnitPublication.group_id.is_(None),UnitPublication.group_id.in_(groups)))
    return query


@router.get('/{unit}')
def overview(unit:Unit,user=Depends(require_user),db:Session=Depends(get_db)):
    office=unit_access(unit,user)
    counts_query=select(UnitCase.status,func.count()).where(UnitCase.unit==unit)
    if not office:
        counts_query=counts_query.where(UnitCase.student_id==user.id)
    counts=dict(db.execute(counts_query.group_by(UnitCase.status)).all())
    posts=db.scalars(visible_posts(unit,user,office).order_by(UnitPublication.id.desc()).limit(80)).all()
    result=dict(title=UNITS[unit],unit=unit,office=office,counts=counts,publications=[post_data(row) for row in posts])
    if unit=='union' and not office:
        member=membership(db,user.id)
        result['member']={'active':bool(member and member.active),'updated_at':date_iso(member.updated_at) if member else None}
    if unit=='vuc':
        query=select(CenterProgram)
        if not office:
            query=query.where(CenterProgram.published.is_(True))
        result.update(programs=[program_data(row) for row in db.scalars(query.order_by(CenterProgram.id))],checklist=CHECKLIST)
    return result


@router.get('/{unit}/cases')
def cases(unit:Unit,offset:int=Query(0,ge=0,le=2147483647),status:str=Query('',max_length=20),
          user=Depends(require_user),db:Session=Depends(get_db)):
    office=unit_access(unit,user)
    query=(select(UnitCase,User.full_name).join(User,User.id==UnitCase.student_id)
           .options(joinedload(UnitCase.program),joinedload(UnitCase.publication)).where(UnitCase.unit==unit))
    if not office:
        query=query.where(UnitCase.student_id==user.id)
    if status:
        if status not in STATES:
            raise HTTPException(422,'Неизвестный статус')
        query=query.where(UnitCase.status==status)
    rows=db.execute(query.order_by(UnitCase.updated_at.desc(),UnitCase.id.desc()).offset(offset).limit(31)).all()
    return dict(items=[case_data(row,name=name if office else None) for row,name in rows[:30]],more=len(rows)>30,offset=offset)


@router.get('/{unit}/cases/{case_id}')
def case_detail(unit:Unit,case_id:RecordId,before:int|None=Query(None,ge=1,le=2147483647),user=Depends(require_user),db:Session=Depends(get_db)):
    row=get_case(db,unit,case_id,user)
    name=db.get(User,row.student_id).full_name if user.role==unit else None
    query=select(UnitCaseEvent,User.full_name).join(User,User.id==UnitCaseEvent.actor_id).where(UnitCaseEvent.case_id==row.id)
    if before:
        query=query.where(UnitCaseEvent.id<before)
    rows=db.execute(query.order_by(UnitCaseEvent.id.desc()).limit(51)).all()
    groups=[]
    if user.role=='vuc' and row.kind=='apply' and row.status=='selection':
        groups=[group_data(item) for item in db.scalars(select(CenterGroup).where(CenterGroup.program_id==row.program_id))]
    can_followup=name is None and row.status=='needs_info' and before is None and (not rows or rows[0][0].action!='followup')
    return {**case_data(row,name=name),'can_followup':can_followup,'groups':groups,'older_before':rows[49][0].id if len(rows)>50 else None,
            'history':[dict(id=event.id,author=author,action=event.action,status=STATES[event.status],message=event.message,
                            created_at=date_iso(event.created_at)) for event,author in reversed(rows[:50])]}


def verify_submission(db,unit,user,body):
    kind=body.kind
    if kind not in UNIT_CASES[unit]:
        raise HTTPException(422,'Выберите услугу этого подразделения')
    if kind in {'join','leave','event','apply'} and not body.confirmed:
        raise HTTPException(422,'Подтвердите демонстрационное действие')
    if kind in {'aid','consult','appeal'} and len(body.message.strip())<5:
        raise HTTPException(422,'Опишите вымышленную ситуацию или вопрос')
    if kind!='apply' and (body.program_id is not None or body.checklist):
        raise HTTPException(422,'Программа и чек-лист относятся к заявлению в ВУЦ')
    if kind!='event' and body.publication_id is not None:
        raise HTTPException(422,'Укажите мероприятие только при записи на событие')
    if kind in {'join','leave','aid'}:
        member=membership(db,user.id)
        active=bool(member and member.active)
        if kind=='join' and active:
            raise HTTPException(409,'Членство уже действует')
        if kind in {'leave','aid'} and not active:
            raise HTTPException(409,'Действие доступно члену профсоюза')
    if kind=='apply':
        if body.message or set(body.checklist)!=set(CHECKLIST) or len(body.checklist)!=len(CHECKLIST):
            raise HTTPException(422,'Отметьте два демонстрационных образца')
        program=db.get(CenterProgram,body.program_id) if body.program_id else None
        if program is None or not program.published:
            raise HTTPException(404,'Программа не найдена')
        if not program.opens<=campus_today()<=program.closes:
            raise HTTPException(409,'Приём заявлений закрыт')
        if db.scalar(select(CenterEnrollment.id).where(CenterEnrollment.student_id==user.id,
                                                       CenterEnrollment.program_id==program.id)) is not None:
            raise HTTPException(409,'Учебная группа уже назначена')
    if kind=='event':
        item=db.scalar(select(UnitPublication).where(UnitPublication.id==body.publication_id,UnitPublication.unit=='union',
                                                      UnitPublication.kind=='event',UnitPublication.published.is_(True)))
        if item is None or item.event_day<campus_today():
            raise HTTPException(404,'Мероприятие недоступно')
    duplicate = select(UnitCase.id).where(UnitCase.unit==unit,UnitCase.student_id==user.id,UnitCase.kind==kind,
                                         UnitCase.status.not_in(TERMINAL-{'accepted'} if kind=='event' else TERMINAL))
    if kind=='apply':
        duplicate=duplicate.where(UnitCase.program_id==body.program_id)
    if kind=='event':
        duplicate=duplicate.where(UnitCase.publication_id==body.publication_id)
    if kind in {'join','leave','event','apply'} and db.scalar(duplicate.limit(1)) is not None:
        raise HTTPException(409,'Действующая заявка уже есть в истории')
    if db.scalar(select(func.count()).select_from(UnitCase).where(UnitCase.unit==unit,UnitCase.student_id==user.id,
                                                                  UnitCase.status.not_in(TERMINAL))) >= 20:
        raise HTTPException(429,'Достигнут предел открытых обращений')


@router.post('/{unit}/cases',status_code=201,dependencies=write)
def submit(unit:Unit,body:CaseBody,request:Request,response:Response,user=Depends(require_student),db:Session=Depends(get_db)):
    lock_workspace(db,user.id)
    receipt,prior=begin_idempotent(db,request,response,user,f'unit-case:{unit}',body.model_dump())
    if prior is not None:
        return prior
    verify_submission(db,unit,user,body)
    now=utc_now()
    row=UnitCase(unit=unit,student_id=user.id,kind=body.kind,status='submitted',message=body.message.strip(),
                 program_id=body.program_id,publication_id=body.publication_id,sample_checklist=json.dumps(body.checklist),
                 created_at=now,updated_at=now)
    db.add(row);db.flush()
    add_history(db,user,row,'submitted','Демонстрационная заявка подана.')
    notify_operators(db,unit,row,'Новое заявление')
    return commit_idempotent(db,receipt,case_data(row))


def accept(db,row,group_id):
    if row.kind in {'join','leave'}:
        item=membership(db,row.student_id)
        active=row.kind=='join'
        if active==bool(item and item.active):
            raise HTTPException(409,'Статус членства уже изменён')
        if item is None:
            item=UnionMembership(student_id=row.student_id,active=active,case_id=row.id,updated_at=utc_now())
            db.add(item)
        else:
            item.active,item.case_id,item.updated_at=active,row.id,utc_now()
    if row.kind=='aid':
        item=membership(db,row.student_id)
        if not item or not item.active:
            raise HTTPException(409,'Членство уже завершено')
    if row.kind=='apply':
        group=db.get(CenterGroup,group_id) if group_id else None
        if group is None or group.program_id!=row.program_id:
            raise HTTPException(422,'Выберите учебную группу выбранной программы')
        if db.scalar(select(CenterEnrollment.id).where(CenterEnrollment.student_id==row.student_id,
                                                       CenterEnrollment.program_id==row.program_id)) is not None:
            raise HTTPException(409,'Студент уже записан на программу')
        count=db.scalar(select(func.count()).select_from(CenterEnrollment).where(CenterEnrollment.group_id==group.id))
        if count>=group.capacity:
            raise HTTPException(409,'В учебной группе нет мест')
        db.add(CenterEnrollment(student_id=row.student_id,program_id=row.program_id,group_id=group.id,case_id=row.id))
    if row.kind=='event':
        item=row.publication
        if item is None or not item.published or item.event_day<campus_today():
            raise HTTPException(409,'Запись на мероприятие закрыта')
        count=db.scalar(select(func.count()).select_from(UnitCase).where(UnitCase.publication_id==item.id,UnitCase.status=='accepted'))
        if count>=item.capacity:
            raise HTTPException(409,'На мероприятии нет мест')


@router.post('/{unit}/cases/{case_id}/step',dependencies=write)
def advance(unit:Unit,case_id:RecordId,body:CaseStep,user=Depends(require_user),db:Session=Depends(get_db)):
    unit_access(unit,user,manage=True)
    lock_workspace(db,user.id)
    row=get_case(db,unit,case_id,user)
    if body.version!=row.version or body.status not in case_steps(row):
        raise HTTPException(409,'Состояние изменилось или переход недоступен')
    if body.status in TERMINAL|{'needs_info'} and len(body.message.strip())<4:
        raise HTTPException(422,'Добавьте текст ответа')
    if body.group_id and (row.kind!='apply' or body.status!='accepted'):
        raise HTTPException(422,'Группа назначается при одобрении заявления в ВУЦ')
    if body.status=='accepted':
        accept(db,row,body.group_id)
    row.status,row.updated_at,row.version=body.status,utc_now(),row.version+1
    if body.message.strip():
        row.response=body.message.strip()
    add_history(db,user,row,'status',body.message.strip())
    notify(db,row.student_id,'Статус заявления обновлён',CASE_NAMES[row.kind]+' · '+STATES[row.status],
           case_path(unit,row.id),student=True,category=unit)
    db.commit()
    return case_data(row,name=db.get(User,row.student_id).full_name)


@router.post('/{unit}/cases/{case_id}/followup',dependencies=write)
def clarify(unit:Unit,case_id:RecordId,body:Followup,user=Depends(require_student),db:Session=Depends(get_db)):
    lock_workspace(db,user.id)
    row=get_case(db,unit,case_id,user)
    if row.status!='needs_info' or row.version!=body.version:
        raise HTTPException(409,'Уточнение уже обработано или состояние изменилось')
    previous=db.scalar(select(UnitCaseEvent.action).where(UnitCaseEvent.case_id==row.id).order_by(UnitCaseEvent.id.desc()).limit(1))
    if previous=='followup':
        raise HTTPException(409,'Уточнение уже отправлено. Дождитесь ответа.')
    row.version,row.updated_at=row.version+1,utc_now()
    add_history(db,user,row,'followup',body.message)
    notify_operators(db,unit,row,'Добавлено уточнение')
    db.commit()
    return case_data(row)


def html_file(title,body,filename):
    html=('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>{escape(title)}</title><main><p>АТЛАС Campus · конкурсный образец · все данные вымышлены</p>'
          f'<h1>{escape(title)}</h1>'+''.join(f'<p>{escape(line)}</p>' for line in body.splitlines() if line.strip())+'</main></html>')
    return HTMLResponse(html,headers={'Content-Disposition':f'attachment; filename="{filename}.html"',
                                      'Content-Security-Policy':"sandbox; default-src 'none'; frame-ancestors 'none'; base-uri 'none'"})


@router.get('/{unit}/cases/{case_id}/file')
def case_file(unit:Unit,case_id:RecordId,user=Depends(require_user),db:Session=Depends(get_db)):
    row=get_case(db,unit,case_id,user)
    if row.status not in TERMINAL:
        raise HTTPException(409,'Решение ещё не оформлено')
    return html_file(CASE_NAMES[row.kind],f'Заявление №{row.id}\nРезультат: {STATES[row.status]}\n{row.response}',f'atlas-{unit}-case-{row.id}')


@router.get('/{unit}/publications/{post_id}/file')
def publication_file(unit:Unit,post_id:RecordId,user=Depends(require_user),db:Session=Depends(get_db)):
    office=unit_access(unit,user)
    row=db.scalar(visible_posts(unit,user,office).where(UnitPublication.id==post_id,UnitPublication.kind.in_(['document','material'])))
    if row is None:
        raise HTTPException(404,'Документ не найден')
    return html_file(row.title,row.body,f'atlas-{unit}-publication-{row.id}')


def edit_row(db,model,body,condition=None):
    row=None
    if body.id is not None:
        query=select(model).where(model.id==body.id)
        if condition is not None:
            query=query.where(condition)
        row=db.scalar(query)
        if row is None:
            raise HTTPException(404,'Запись не найдена')
    if (row.version if row else 0)!=body.version:
        raise HTTPException(409,'Запись уже изменена')
    return row


def persist(db,actor,unit,area,model,row,fields,serialize):
    before=serialize(row) if row else None
    if row:
        for key,value in fields.items():
            setattr(row,key,value)
        row.version+=1
    else:
        row=model(**fields)
        db.add(row)
    db.flush()
    after=serialize(row)
    recorded(db,actor,unit,row.id,area+'_edit' if before else area+'_add',before,after)
    return after


@router.put('/{unit}/publications',dependencies=write)
def save_publication(unit:Unit,body:PublicationBody,user=Depends(require_user),db:Session=Depends(get_db)):
    unit_access(unit,user,manage=True)
    lock_workspace(db,user.id)
    row=edit_row(db,UnitPublication,body,UnitPublication.unit==unit)
    if body.kind not in POST_KINDS[unit] or (row and body.kind!=row.kind):
        raise HTTPException(422,'Тип публикации недоступен')
    if body.kind=='event':
        if body.event_day is None or body.capacity is None:
            raise HTTPException(422,'Укажите дату и число мест')
        if row and db.scalar(select(func.count()).select_from(UnitCase).where(
                UnitCase.publication_id==row.id,UnitCase.status=='accepted'))>body.capacity:
            raise HTTPException(409,'Уже принято больше участников')
    elif body.event_day is not None or body.capacity is not None:
        raise HTTPException(422,'Дата события и места относятся к мероприятию')
    if body.group_id and (unit!='vuc' or body.kind not in {'material','document','news'} or db.get(CenterGroup,body.group_id) is None):
        raise HTTPException(422,'Выберите учебную группу для публикации ВУЦ')
    result=persist(db,user,unit,'publication',UnitPublication,row,
                   {**body.model_dump(exclude={'id','version'}),'unit':unit,'author_id':user.id,'updated_at':utc_now()},post_data)
    db.commit()
    return result


@router.put('/vuc/learning/programs',dependencies=write)
def save_program(body:ProgramBody,user=Depends(center_staff),db:Session=Depends(get_db)):
    lock_workspace(db,user.id)
    row=edit_row(db,CenterProgram,body)
    if body.closes<body.opens:
        raise HTTPException(422,'Срок приёма должен быть позже даты открытия')
    if db.scalar(select(CenterProgram.id).where(CenterProgram.title==body.title,CenterProgram.id!=(body.id or 0))) is not None:
        raise HTTPException(409,'Название программы уже используется')
    result=persist(db,user,'vuc','program',CenterProgram,row,body.model_dump(exclude={'id','version'}),program_data)
    db.commit()
    return result


@router.put('/vuc/learning/groups',dependencies=write)
def save_group(body:GroupBody,user=Depends(center_staff),db:Session=Depends(get_db)):
    lock_workspace(db,user.id)
    row=edit_row(db,CenterGroup,body)
    program=db.get(CenterProgram,body.program_id)
    if program is None or (row and row.program_id!=program.id):
        raise HTTPException(422,'Выберите программу новой группы')
    if db.scalar(select(CenterGroup.id).where(CenterGroup.code==body.code,CenterGroup.id!=(body.id or 0))) is not None:
        raise HTTPException(409,'Код группы уже используется')
    if row and db.scalar(select(func.count()).select_from(CenterEnrollment).where(CenterEnrollment.group_id==row.id))>body.capacity:
        raise HTTPException(409,'В группе уже больше участников')
    result=persist(db,user,'vuc','group',CenterGroup,row,{'program':program,'code':body.code,'capacity':body.capacity},group_data)
    db.commit()
    return result


@router.put('/vuc/learning/sessions',dependencies=write)
def save_session(body:SessionBody,user=Depends(center_staff),db:Session=Depends(get_db)):
    lock_workspace(db,user.id)
    row=edit_row(db,CenterSession,body)
    group=db.get(CenterGroup,body.group_id)
    if group is None or body.starts.tzinfo is None or body.ends.tzinfo is None:
        raise HTTPException(422,'Укажите группу и время с часовым поясом')
    try:
        start,end=body.starts.astimezone(timezone.utc),body.ends.astimezone(timezone.utc)
    except (OverflowError,ValueError):
        raise HTTPException(422,'Дата выходит за поддерживаемый диапазон') from None
    if not timedelta(minutes=15)<=end-start<=timedelta(hours=6) or start>utc_now()+timedelta(days=370) or (start<=utc_now() and not body.cancelled):
        raise HTTPException(422,'Укажите будущее занятие продолжительностью от 15 минут до 6 часов')
    if body.cancelled and row is None:
        raise HTTPException(422,'Отмените существующее занятие')
    overlap=select(CenterSession.id).where(CenterSession.id!=(body.id or 0),CenterSession.cancelled.is_(False),
        CenterSession.starts_at<end,CenterSession.ends_at>start,or_(CenterSession.group_id==group.id,CenterSession.room==body.room))
    if not body.cancelled and db.scalar(overlap.limit(1)) is not None:
        raise HTTPException(409,'Группа или помещение уже заняты')
    affected={row.group_id,group.id} if row else {group.id}
    fields=dict(group=group,title=body.title,room=body.room,starts_at=start,ends_at=end,cancelled=body.cancelled)
    result=persist(db,user,'vuc','session',CenterSession,row,fields,session_data)
    for uid in set(db.scalars(select(CenterEnrollment.student_id).where(CenterEnrollment.group_id.in_(affected)))):
        notify(db,uid,'Расписание ВУЦ изменилось',body.title,'/app/vuc?tab=learning',student=True,category='vuc')
    db.commit()
    return result


@router.get('/vuc/learning')
def learning(user=Depends(require_user),db:Session=Depends(get_db)):
    office=unit_access('vuc',user)
    query=(select(CenterEnrollment,User.full_name).join(User,User.id==CenterEnrollment.student_id)
           .options(joinedload(CenterEnrollment.group),joinedload(CenterEnrollment.program)))
    if not office:
        query=query.where(CenterEnrollment.student_id==user.id)
    enrollment=db.execute(query.order_by(CenterEnrollment.id)).all()
    groups=select(CenterGroup).options(joinedload(CenterGroup.program)).order_by(CenterGroup.code)
    sessions=select(CenterSession).options(joinedload(CenterSession.group))
    if not office:
        ids=[row.group_id for row,_ in enrollment]
        groups=groups.where(CenterGroup.id.in_(ids))
        sessions=sessions.where(CenterSession.group_id.in_(ids))
    return dict(groups=[group_data(row) for row in db.scalars(groups)],
                sessions=[session_data(row) for row in db.scalars(sessions.order_by(CenterSession.starts_at.desc()).limit(100))],
                enrollments=[enrollment_data(row,name if office else None) for row,name in enrollment])


@router.put('/vuc/learning/results/{enrollment_id}',dependencies=write)
def save_result(enrollment_id:RecordId,body:ResultBody,user=Depends(center_staff),db:Session=Depends(get_db)):
    lock_workspace(db,user.id)
    row=db.get(CenterEnrollment,enrollment_id)
    if row is None:
        raise HTTPException(404,'Учебная запись не найдена')
    if row.version!=body.version:
        raise HTTPException(409,'Результат уже изменён')
    if body.outcome!='pending' and len(body.comment.strip())<4:
        raise HTTPException(422,'Добавьте пояснение к результату')
    before=enrollment_data(row)
    row.outcome,row.comment,row.version=body.outcome,body.comment.strip(),row.version+1
    after=enrollment_data(row)
    recorded(db,user,'vuc',row.id,'result',before,after)
    notify(db,row.student_id,'Результат ВУЦ обновлён',row.program.title,'/app/vuc?tab=learning',student=True,category='vuc')
    db.commit()
    return after


@router.get('/{unit}/report')
def report(unit:Unit,format:Literal['json','csv','xlsx']='json',user=Depends(require_user),db:Session=Depends(get_db)):
    unit_access(unit,user,manage=True)
    rows=[dict(section='Заявления',status=STATES[status],count=count) for status,count in
          db.execute(select(UnitCase.status,func.count()).where(UnitCase.unit==unit).group_by(UnitCase.status))]
    if unit=='union':
        rows.append(dict(section='Членство',status='Действующее',count=db.scalar(
            select(func.count()).select_from(UnionMembership).where(UnionMembership.active.is_(True)))))
    else:
        labels={'pending':'Ожидает результата','passed':'Зачтено','revision':'Нужна доработка'}
        rows.extend(dict(section='Учебные результаты',status=labels[outcome],count=count) for outcome,count in
                    db.execute(select(CenterEnrollment.outcome,func.count()).group_by(CenterEnrollment.outcome)))
    if format=='json':
        return {'items':rows}
    data,mime=table_bytes(format,['section','status','count'],rows)
    return Response(data,media_type=mime,headers={'Content-Disposition':f'attachment; filename="atlas-{unit}-report.{format}"'})


@router.get('/{unit}/history')
def history(unit:Unit,user=Depends(require_user),db:Session=Depends(get_db)):
    unit_access(unit,user,manage=True)
    rows=db.execute(select(OperationEvent,User.full_name).join(User,User.id==OperationEvent.actor_id)
                    .where(OperationEvent.area==unit).order_by(OperationEvent.id.desc()).limit(60))
    return {'items':[dict(action=row.action,object_id=row.object_id,author=author,created_at=date_iso(row.created_at))
                    for row,author in rows]}
