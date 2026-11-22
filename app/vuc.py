"""Verified admission campaigns and private applicant tracking for the VUC."""
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .db import User, campus_today, utc_now
from .main import StrictBody, date_iso, get_db, require_same_origin, require_student, require_user
from .services import begin_idempotent, commit_idempotent
from .units import edit_row, persist, require_vuc_operator
from .vuc_db import VucApplication, VucApplicationEvent, VucCampaign, VucProgram, program_data
from .vuc_policy import (CATEGORIES, FEDERAL_REQUIREMENTS, LAW_URL, ORDER_URL, STAGES,
                         ProgramCategory, StageKind, can_manage_vuc, private_account)
from .workspace import lock_workspace, notify

router = APIRouter(prefix='/api/units/vuc/admission')
write = [Depends(require_same_origin)]
BodyId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
RecordId = Annotated[int, Path(ge=1, le=2147483647)]
DocumentName = Annotated[str, Field(min_length=2, max_length=240)]

STATUSES = {
    'inquiry': 'Обращение создано',
    'inquiry_closed': 'Обращение закрыто',
    'documents_received': 'Документы зарегистрированы',
    'needs_documents': 'Нужно дополнить документы',
    'preliminary': 'Предварительный отбор',
    'admitted': 'Допущен к конкурсному отбору',
    'not_admitted': 'Не допущен к конкурсному отбору',
    'selection_complete': 'Конкурсные мероприятия завершены',
    'recommended': 'Рекомендован комиссией',
    'not_selected': 'Комиссия не рекомендовала',
    'enrolled': 'Допущен к обучению приказом',
    'not_enrolled': 'Допуск к обучению не оформлен',
}
TRANSITIONS = {
    'inquiry': ('documents_received', 'inquiry_closed'),
    'documents_received': ('needs_documents', 'preliminary'),
    'needs_documents': ('documents_received',),
    'preliminary': ('admitted', 'not_admitted'),
    'admitted': ('selection_complete',),
    'selection_complete': ('recommended', 'not_selected'),
    'recommended': ('enrolled', 'not_enrolled'),
}
BASIS_LABELS = {
    'documents_received': 'Регистрационный номер принятого комплекта',
    'admitted': 'Реквизиты подтверждения допуска к конкурсу',
    'not_admitted': 'Реквизиты решения о недопуске',
    'selection_complete': 'Реквизиты подтверждения завершения конкурсных мероприятий',
    'recommended': 'Реквизиты протокола конкурсной комиссии',
    'not_selected': 'Реквизиты протокола конкурсной комиссии',
    'enrolled': 'Реквизиты приказа ректора о допуске к обучению',
    'not_enrolled': 'Реквизиты документа о завершении оформления',
}


class VucBody(StrictBody):
    model_config = ConfigDict(str_strip_whitespace=True)


class SourceEditor(VucBody):
    id: BodyId | None = None
    version: int = Field(default=0, strict=True, ge=0)
    source_title: str = Field(default='', max_length=240)
    source_url: str = Field(default='', max_length=1000)
    verified_on: date | None = None

    @field_validator('source_url')
    @classmethod
    def public_https_url(cls, value):
        if not value:
            return value
        link = urlsplit(value)
        if (link.scheme != 'https' or not link.hostname or link.username is not None
                or '\\' in value or any(char.isspace() for char in value)):
            raise ValueError('Укажите HTTPS-ссылку на официальный источник')
        return value


class ProgramBody(SourceEditor):
    title: str = Field(min_length=4, max_length=180)
    category: ProgramCategory
    outcome: str = Field(default='', max_length=1200)
    duration_months: int | None = Field(default=None, strict=True, ge=1, le=120)
    academic_link: str = Field(default='', max_length=1800)
    requirements: str = Field(default='', max_length=2400)
    selection: str = Field(default='', max_length=2400)
    state: Literal['draft', 'active', 'inactive'] = 'draft'


class StageBody(VucBody):
    starts_on: date | None = None
    ends_on: date | None = None
    details: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def check_dates(self):
        check_range(self.starts_on, self.ends_on)
        return self


class CampaignBody(SourceEditor):
    program_id: BodyId
    academic_year: int = Field(strict=True, ge=2000, le=2199)
    title: str = Field(min_length=4, max_length=180)
    state: Literal['draft', 'published', 'archived'] = 'draft'
    opens_on: date | None = None
    closes_on: date | None = None
    intake_enabled: bool = Field(default=True, strict=True)
    seats: int | None = Field(default=None, strict=True, ge=1, le=100000)
    documents: list[DocumentName] = Field(default_factory=list, max_length=24)
    procedure: str = Field(default='', max_length=2400)
    requirements: str = Field(default='', max_length=2400)
    stages: dict[StageKind, StageBody] = Field(default_factory=dict)

    @field_validator('documents')
    @classmethod
    def clean_documents(cls, values):
        return [cls.reject_non_text_characters(value) for value in values]

    @model_validator(mode='after')
    def check_dates(self):
        check_range(self.opens_on, self.closes_on)
        return self


class InquiryBody(VucBody):
    campaign_id: BodyId
    confirmed: bool = Field(strict=True)

    @field_validator('confirmed')
    @classmethod
    def confirm_procedure(cls, value):
        if not value:
            raise ValueError('Подтвердите, что порядок подачи документов понятен')
        return value


ApplicationStatus = Literal[
    'inquiry_closed', 'documents_received', 'needs_documents', 'preliminary', 'admitted',
    'not_admitted', 'selection_complete', 'recommended', 'not_selected', 'enrolled', 'not_enrolled',
]


class ApplicantNotice(VucBody):
    version: int = Field(strict=True, ge=1)
    message: str = Field(min_length=4, max_length=1200)


class StepBody(ApplicantNotice):
    status: ApplicationStatus
    basis_ref: str = Field(default='', max_length=160)
    basis_on: date | None = None
    contract_ref: str = Field(default='', max_length=160)


def check_range(first, last):
    if first and last and first > last:
        raise ValueError('Дата окончания должна быть не раньше даты начала')


def require_source(body):
    if not (body.source_title and body.source_url and body.verified_on):
        raise HTTPException(422, 'Укажите официальный источник, ссылку и дату его проверки')
    if body.verified_on > campus_today():
        raise HTTPException(422, 'Дата проверки источника ещё не наступила')


def campaign_status(row, today):
    if row.state != 'published':
        return row.state
    if row.program.state != 'active':
        return 'program_inactive'
    if not row.intake_enabled:
        return 'not_accepting'
    if not (row.opens_on and row.closes_on):
        return 'awaiting_dates'
    if today < row.opens_on:
        return 'upcoming'
    if today <= row.closes_on:
        return 'open'
    final_date = row.stages.get('formalities', {}).get('ends_on')
    return 'completed' if final_date and today > date.fromisoformat(final_date) else 'documents_closed'


def campaign_data(row, today):
    return dict(
        id=row.id, title=row.title, program_id=row.program_id, program=row.program_snapshot or program_data(row.program),
        academic_year=row.academic_year, state=row.state, status=campaign_status(row, today),
        opens_on=date_iso(row.opens_on), closes_on=date_iso(row.closes_on), intake_enabled=row.intake_enabled,
        seats=row.seats, documents=row.documents, procedure=row.procedure, requirements=row.requirements,
        stages=row.stages, source_title=row.source_title, source_url=row.source_url,
        verified_on=date_iso(row.verified_on), version=row.version,
    )


def admission_scope(user):
    if user.role not in {'student', 'vuc'}:
        raise HTTPException(403, 'Раздел недоступен вашей роли')
    return can_manage_vuc(user)


@router.get('')
def catalog(user=Depends(require_user), db: Session = Depends(get_db)):
    office = admission_scope(user)
    student = user.role == 'student'
    today = campus_today()
    programs = select(VucProgram).order_by(VucProgram.id)
    campaigns = (select(VucCampaign).options(joinedload(VucCampaign.program))
                 .order_by(VucCampaign.academic_year.desc(), VucCampaign.opens_on.desc().nulls_last(), VucCampaign.id.desc()))
    if not office:
        programs = programs.where(VucProgram.state != 'draft')
        campaigns = campaigns.where(VucCampaign.state != 'draft')
    owned = dict(db.execute(select(VucApplication.campaign_id, VucApplication.id)
                           .where(VucApplication.student_id == user.id)).all()) if student else {}
    return dict(
        can_manage=office, can_apply=student and private_account(user),
        programs=[program_data(row) for row in db.scalars(programs)],
        campaigns=[{**campaign_data(row, today), 'application_id': owned.get(row.id)} for row in db.scalars(campaigns)],
        categories=CATEGORIES, stages=STAGES, federal_requirements=FEDERAL_REQUIREMENTS,
        law_url=LAW_URL, order_url=ORDER_URL, statuses=STATUSES,
    )


@router.put('/programs', dependencies=write)
def save_program(body: ProgramBody, user=Depends(require_vuc_operator), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    row = edit_row(db, VucProgram, body)
    if body.state == 'draft' and row and row.state != 'draft':
        raise HTTPException(409, 'Опубликованную программу можно перевести в неактуальные')
    if body.state != 'draft':
        require_source(body)
        if not body.outcome:
            raise HTTPException(422, 'Укажите результат обучения')
    if db.scalar(select(VucProgram.id).where(VucProgram.title == body.title, VucProgram.id != (body.id or 0))):
        raise HTTPException(409, 'Программа с таким названием уже существует')
    result = persist(db, user, 'vuc', 'program', VucProgram, row,
                     body.model_dump(exclude={'id', 'version'}), program_data)
    db.commit()
    return result


@router.put('/campaigns', dependencies=write)
def save_campaign(body: CampaignBody, user=Depends(require_vuc_operator), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    row = edit_row(db, VucCampaign, body)
    program = db.get(VucProgram, body.program_id)
    today = campus_today()
    if program is None:
        raise HTTPException(404, 'Программа не найдена')
    if row and row.state == 'archived':
        raise HTTPException(409, 'Архивная кампания доступна для чтения')
    published = row is not None and row.state == 'published'
    if published and (body.state == 'draft' or (body.program_id, body.academic_year) != (row.program_id, row.academic_year)):
        raise HTTPException(409, 'Программа и учебный год опубликованной кампании закреплены')
    if body.state == 'archived':
        if not published or campaign_status(row, today) in {'open', 'upcoming'}:
            raise HTTPException(409, 'Архивировать можно опубликованный набор после завершения или приостановки приёма')
    if body.state == 'published':
        require_source(body)
        if not published and program.state != 'active':
            raise HTTPException(409, 'Для публикации нужна актуальная программа')
        if body.opens_on and body.closes_on and body.intake_enabled and not (body.documents and body.procedure):
            raise HTTPException(422, 'Заполните перечень документов и порядок их подачи')
    if db.scalar(select(VucCampaign.id).where(
        VucCampaign.program_id == program.id, VucCampaign.academic_year == body.academic_year,
        VucCampaign.title == body.title, VucCampaign.id != (body.id or 0),
    )):
        raise HTTPException(409, 'В этом учебном году уже есть набор с таким названием для программы')
    if body.state == 'archived':
        fields = {'state': 'archived'}
    else:
        fields = body.model_dump(exclude={'id', 'version', 'program_id', 'stages'})
        fields.update(program=program, stages=body.model_dump(mode='json')['stages'])
        if body.state == 'published' and not published:
            fields['program_snapshot'] = program_data(program)
    result = persist(db, user, 'vuc', 'campaign', VucCampaign, row, fields, lambda item: campaign_data(item, today))
    db.commit()
    return result


def application_path(application_id, office=False):
    return f"/app/vuc{'-office' if office else ''}/admission/{application_id}"


def application_data(row, *, name=None):
    return dict(
        id=row.id, campaign_id=row.campaign_id, campaign=row.campaign.title, academic_year=row.campaign.academic_year,
        program=row.campaign.program_snapshot['title'], student=name,
        status=row.status, status_label=STATUSES[row.status], next_action=row.next_action,
        allowed=TRANSITIONS.get(row.status, ()) if name is not None else (),
        created_at=date_iso(row.created_at), updated_at=date_iso(row.updated_at), version=row.version,
    )


def application_scope(user):
    office = admission_scope(user)
    if user.role == 'vuc' and not office:
        raise HTTPException(403, 'Работа с кандидатами доступна в служебной учётной записи ВУЦ')
    query = select(VucApplication).options(joinedload(VucApplication.campaign))
    return query if office else query.where(VucApplication.student_id == user.id)


@router.get('/applications')
def applications(
    campaign_id: int | None = Query(None, ge=1, le=2147483647),
    status: str = Query('', max_length=24), offset: int = Query(0, ge=0, le=2147483647),
    user=Depends(require_user), db: Session = Depends(get_db),
):
    query = application_scope(user)
    office = can_manage_vuc(user)
    if status:
        if status not in STATUSES:
            raise HTTPException(422, 'Неизвестный статус обращения')
        query = query.where(VucApplication.status == status)
    if campaign_id:
        query = query.where(VucApplication.campaign_id == campaign_id)
    query = query.join(User, User.id == VucApplication.student_id).add_columns(User.full_name)
    rows = db.execute(query.order_by(VucApplication.updated_at.desc(), VucApplication.id.desc()).offset(offset).limit(31)).all()
    return dict(items=[application_data(row, name=name if office else None) for row, name in rows[:30]],
                offset=offset, more=len(rows) > 30)


def get_application(db, user, application_id):
    row = db.scalar(application_scope(user).where(VucApplication.id == application_id))
    if row is None:
        raise HTTPException(404, 'Обращение не найдено')
    return row


@router.get('/applications/{application_id}')
def detail(
    application_id: RecordId, before: int | None = Query(None, ge=1, le=2147483647),
    user=Depends(require_user), db: Session = Depends(get_db),
):
    row = get_application(db, user, application_id)
    office = can_manage_vuc(user)
    name = db.get(User, row.student_id).full_name if office else None
    query = (select(VucApplicationEvent, User.full_name).join(User, User.id == VucApplicationEvent.actor_id)
             .where(VucApplicationEvent.application_id == row.id))
    if before:
        query = query.where(VucApplicationEvent.id < before)
    events = db.execute(query.order_by(VucApplicationEvent.id.desc()).limit(51)).all()
    return dict(
        **application_data(row, name=name), basis_labels=BASIS_LABELS if office else {},
        older_before=events[49][0].id if len(events) > 50 else None,
        history=[dict(
            id=event.id, action=event.action, status=STATUSES[event.status], author=author,
            message=event.message, basis_ref=event.basis_ref, basis_on=date_iso(event.basis_on),
            contract_ref=event.contract_ref, created_at=date_iso(event.created_at),
        ) for event, author in reversed(events[:50])],
    )


@router.post('/applications', status_code=201, dependencies=write)
def submit_inquiry(
    body: InquiryBody, request: Request, response: Response,
    user=Depends(require_student), db: Session = Depends(get_db),
):
    if not private_account(user):
        raise HTTPException(403, 'Для регистрации обращения нужна личная учётная запись студента')
    lock_workspace(db, user.id)
    receipt, prior = begin_idempotent(db, request, response, user, 'vuc-admission', body.model_dump())
    if prior is not None:
        return prior
    campaign = db.get(VucCampaign, body.campaign_id)
    if campaign is None or campaign.state == 'draft':
        raise HTTPException(404, 'Кампания не найдена')
    if campaign_status(campaign, campus_today()) != 'open':
        raise HTTPException(409, 'Регистрация обращений по этой кампании закрыта')
    if db.scalar(select(VucApplication.id).where(
        VucApplication.student_id == user.id, VucApplication.campaign_id == campaign.id,
    )):
        raise HTTPException(409, 'Обращение по этой кампании уже есть в личном кабинете')
    now = utc_now()
    row = VucApplication(
        student_id=user.id, campaign=campaign, status='inquiry',
        next_action='Подайте документы в порядке, указанном в кампании. Отметку о приёме внесёт сотрудник ВУЦ.',
        created_at=now, updated_at=now,
    )
    db.add(row)
    db.flush()
    db.add(VucApplicationEvent(application_id=row.id, actor_id=user.id, status=row.status,
                               action='submitted', message=row.next_action, created_at=now))
    for operator in db.scalars(select(User).where(User.role == 'vuc')):
        if can_manage_vuc(operator):
            notify(db, operator.id, 'Новое обращение по приёму в ВУЦ', f'Обращение №{row.id}',
                   application_path(row.id, office=True), category='vuc')
    return commit_idempotent(db, receipt, application_data(row))


def verify_step(db, row, body):
    if body.status not in TRANSITIONS.get(row.status, ()):
        raise HTTPException(409, 'Переход недоступен на текущем этапе')
    today = campus_today()
    if body.status in BASIS_LABELS:
        if not body.basis_ref or not body.basis_on or body.basis_on > today:
            raise HTTPException(422, 'Укажите реквизиты и дату существующего документа')
        previous = db.scalar(select(VucApplicationEvent.basis_on).where(
            VucApplicationEvent.application_id == row.id, VucApplicationEvent.basis_on.is_not(None),
        ).order_by(VucApplicationEvent.id.desc()).limit(1))
        if previous and body.basis_on < previous:
            raise HTTPException(422, 'Документ датирован раньше предыдущего подтверждённого этапа')
    elif body.basis_ref or body.basis_on:
        raise HTTPException(422, 'Для этого перехода реквизиты не заполняются')
    if (body.status == 'enrolled') != bool(body.contract_ref):
        raise HTTPException(422, 'При допуске к обучению нужны реквизиты подписанного договора')


def save_applicant_event(db, user, application_id, body, step=None):
    lock_workspace(db, user.id)
    row = get_application(db, user, application_id)
    if row.version != body.version:
        raise HTTPException(409, 'Обращение изменилось. Откройте его снова')
    fields = {}
    if step:
        verify_step(db, row, step)
        row.status = step.status
        fields = step.model_dump(include={'basis_ref', 'basis_on', 'contract_ref'})
    row.next_action, row.updated_at, row.version = body.message, utc_now(), row.version + 1
    db.add(VucApplicationEvent(
        application_id=row.id, actor_id=user.id, status=row.status, action='status' if step else 'notice',
        message=body.message, created_at=row.updated_at, **fields,
    ))
    notify(db, row.student_id, 'Статус обращения ВУЦ обновлён' if step else 'Сообщение ВУЦ',
           f'Обращение №{row.id} · {STATUSES[row.status]}' if step else f'Обращение №{row.id} · Откройте сообщение',
           application_path(row.id), student=True, category='vuc')
    result = application_data(row, name=db.get(User, row.student_id).full_name)
    db.commit()
    return result


@router.post('/applications/{application_id}/step', dependencies=write)
def advance(
    application_id: RecordId, body: StepBody,
    user=Depends(require_vuc_operator), db: Session = Depends(get_db),
):
    return save_applicant_event(db, user, application_id, body, step=body)


@router.post('/applications/{application_id}/notice', dependencies=write)
def send_notice(
    application_id: RecordId, body: ApplicantNotice,
    user=Depends(require_vuc_operator), db: Session = Depends(get_db),
):
    return save_applicant_event(db, user, application_id, body)
