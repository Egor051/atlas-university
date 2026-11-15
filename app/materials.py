"""One publication and attachment store for courses, the directory and teaching workflows."""
from html import escape
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, defer, joinedload

from .assignment_workflow import validate_https
from .db import User, utc_now
from .main import StrictBody, date_iso, get_db, require_roles, require_same_origin, require_user, search_text, text_search
from .material_policy import MATERIAL_MANAGERS, PUBLISHED_ACCESS, managed_assignments, visible_materials
from .material_upload import (FILE_FORMATS, FILE_POLICY, MAX_ASSIGNMENT_FILE_BYTES, MAX_MATERIAL_BYTES,
                              MaterialUpload, decode_upload, download_upload)
from .services import begin_idempotent, commit_idempotent
from .university import discipline_card, teacher_card, teachers_query
from .university_db import Department, Discipline, MaterialDelegation, Teacher, TeachingAssignment, TeachingMaterial
from .workspace import lock_workspace, notify, recorded
from .workspace_db import GroupMember, OperationEvent, TeachingLoad

MaterialKind = Literal['lecture', 'guide', 'slides', 'practice', 'lab', 'extra']
Access = Literal['campus', 'group', 'hidden', 'archived']
RecordId = Annotated[int, Path(ge=1, le=2147483647)]
Version = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
KIND_LABELS = {
    'lecture': 'Лекция', 'guide': 'Методические указания', 'slides': 'Презентация',
    'practice': 'Практическое задание', 'lab': 'Лабораторная работа', 'extra': 'Дополнительный материал',
}
ACCESS_LABELS = {'campus': 'Весь кампус', 'group': 'Мои учебные группы', 'hidden': 'Скрыт', 'archived': 'В архиве'}

router = APIRouter(prefix='/api/materials')
publisher = require_roles(*MATERIAL_MANAGERS)
administrator = require_roles('admin')
write = [Depends(require_same_origin)]


def material_sections(body):
    sections = []
    heading, lines = '', []
    for line in body.splitlines():
        if line.startswith('## '):
            if heading or any(lines):
                sections.append({'heading': heading, 'paragraphs': split_paragraphs(lines)})
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    if heading or any(lines):
        sections.append({'heading': heading, 'paragraphs': split_paragraphs(lines)})
    return sections


def split_paragraphs(lines):
    return [part.strip() for part in re.split(r'\n[ \t]*\n', '\n'.join(lines)) if part.strip()]


def material_html(row, sections):
    title = escape(row['title'])
    deck = row['kind'] == 'slides'
    articles = []
    for i, section in enumerate(sections, 1):
        heading = '<h2>' + escape(section['heading']) + '</h2>' if section['heading'] else ''
        paragraphs = ''.join('<p>' + escape(paragraph) + '</p>' for paragraph in section['paragraphs'])
        links = ''
        if deck:
            previous = f'<a href="#slide-{i - 1}">Предыдущий слайд</a>' if i > 1 else ''
            following = f'<a href="#slide-{i + 1}">Следующий слайд</a>' if i < len(sections) else ''
            links = f'<nav aria-label="Переход по слайдам">{previous}<span>{i} / {len(sections)}</span>{following}</nav>'
        articles.append(f'<section id="slide-{i}">{heading}{paragraphs}{links}</section>')
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'">
<title>{title}</title><style>
body{{margin:0;background:#f5f6fa;color:#202439;font:1rem/1.65 system-ui,sans-serif;overflow-wrap:anywhere}}
main{{max-width:48rem;margin:auto;padding:1.5rem}}h1,h2{{line-height:1.2}}p{{white-space:pre-wrap}}
header{{padding-bottom:1rem;border-bottom:2px solid #6556df}}a{{color:#514199}}nav{{display:flex;flex-wrap:wrap;gap:1rem}}
.deck section{{margin:1.5rem 0;min-height:48vh;padding:1.5rem;background:white;border:1px solid #e1dceb;border-radius:1rem}}
@media print{{body{{background:white}}.deck section{{break-before:page}}nav{{display:none}}}}
</style></head><body><main class="{'deck' if deck else 'handout'}"><header>
<small>АТЛАС Campus</small><h1>{title}</h1>
<p>{escape(row['kind_label'])} · {escape(row['discipline']['title'])} · {escape(row['author']['title'])} · {row['created_at'][:10]}</p>
<p>{escape(row['description'])}</p></header>{''.join(articles)}</main></body></html>'''


class MaterialBody(StrictBody):
    assignment_id: Version
    kind: MaterialKind
    title: str = Field(min_length=4, max_length=180)
    description: str = Field(min_length=10, max_length=600)
    body: str = Field(default='', max_length=6000)
    url: str = Field(default='', max_length=1000)
    file: MaterialUpload | None = None
    source: Literal['text', 'link', 'file'] | None = None
    access: Access | None = None

    @field_validator('title', 'description', 'body', 'url', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('url')
    @classmethod
    def secure_link(cls, value):
        return validate_https(value)

    @property
    def content_source(self):
        return self.source or ('file' if self.file else 'link' if self.url else 'text')

    @model_validator(mode='after')
    def valid_content(self):
        source = self.content_source
        if self.file and source != 'file' or bool(self.url) != (source == 'link'):
            raise ValueError('Укажите файл или HTTPS-ссылку для выбранного источника')
        if source == 'text':
            sections = material_sections(self.body)
            if len(self.body) < 20 or not any(section['paragraphs'] for section in sections):
                raise ValueError('Добавьте текст материала')
            if self.kind == 'slides' and (len(sections) < 2 or any(not s['heading'] or not s['paragraphs'] for s in sections)):
                raise ValueError('Для текстовой презентации нужны минимум два слайда с заголовками ## и текстом')
        return self


class MaterialEdit(MaterialBody):
    version: Version


def materials_query():
    teacher = joinedload(TeachingMaterial.assignment).joinedload(TeachingAssignment.teacher)
    return (select(TeachingMaterial).join(TeachingAssignment)
            .options(teacher.joinedload(Teacher.user),
                     teacher.joinedload(Teacher.department).joinedload(Department.faculty),
                     joinedload(TeachingMaterial.assignment).joinedload(TeachingAssignment.discipline)))


def material_card(row, *, can_edit=False):
    source = 'file' if row.file_name else 'link' if row.external_url else 'text'
    return dict(id=row.id, title=row.title, description=row.description, kind=row.kind,
                kind_label=KIND_LABELS[row.kind], discipline=discipline_card(row.assignment.discipline),
                author=teacher_card(row.assignment.teacher), assignment_id=row.assignment_id,
                created_at=date_iso(row.created_at), updated_at=date_iso(row.updated_at), version=row.version,
                access=row.access, source=source, url=row.external_url, can_edit=can_edit,
                file={'name': row.file_name, 'size': row.file_size} if row.file_name else None,
                file_url=f'/api/materials/{row.id}/file' if source != 'link' else None,
                href=f'/app/courses/materials/{row.id}')


def editable_ids(db, user, assignment_ids):
    return set(db.scalars(select(TeachingAssignment.id).where(TeachingAssignment.id.in_(assignment_ids),
                                                             managed_assignments(user))))


def material_cards(db, user, rows):
    editable = editable_ids(db, user, {row.assignment_id for row in rows})
    return [material_card(row, can_edit=row.assignment_id in editable) for row in rows]


def teacher_materials(db, user, teacher_id):
    rows = db.scalars(materials_query().where(TeachingAssignment.teacher_id == teacher_id,
                      TeachingMaterial.access.in_(PUBLISHED_ACCESS), visible_materials(user))
                      .options(defer(TeachingMaterial.body))
                      .order_by(TeachingMaterial.updated_at.desc(), TeachingMaterial.id.desc()).limit(6)).all()
    return material_cards(db, user, rows)


def find_material(db, material_id, *conditions):
    row = db.scalar(materials_query().where(TeachingMaterial.id == material_id, *conditions))
    if row is None:
        raise HTTPException(404, 'Материал недоступен или не найден')
    return row


def checked_assignment(db, assignment_id, user):
    row = db.get(TeachingAssignment, assignment_id)
    if row is None:
        raise HTTPException(404, 'Учебное назначение не найдено')
    if assignment_id not in editable_ids(db, user, [assignment_id]):
        raise HTTPException(403, 'Материал можно изменить только в пределах вашего учебного назначения')
    return row


def material_values(body, row=None):
    values = body.model_dump(include={'kind', 'title', 'description', 'body'})
    values['external_url'] = body.url
    if body.file:
        values.update(decode_upload(body.file))
    elif body.content_source != 'file':
        values.update(file_name=None, file_size=None, file_digest=None, file_content=None)
    elif row is None or not row.file_name:
        raise HTTPException(422, 'Добавьте файл материала')
    return values


def require_file_capacity(db, assignment_id, material_id, size):
    if not size:
        return
    total = db.scalar(select(func.coalesce(func.sum(TeachingMaterial.file_size), 0)).where(
        TeachingMaterial.assignment_id == assignment_id, TeachingMaterial.id != material_id))
    if total + size > MAX_ASSIGNMENT_FILE_BYTES:
        raise HTTPException(409, 'Достигнут лимит вложений для этого учебного назначения')


def snapshot(row):
    return {field: getattr(row, field) for field in ('assignment_id', 'kind', 'title', 'description', 'body',
            'access', 'external_url', 'file_name', 'file_size', 'file_digest', 'version')}


def notify_students(db, row):
    recipients = db.scalars(select(GroupMember.student_id).join(TeachingLoad, TeachingLoad.group_id == GroupMember.group_id)
                            .where(TeachingLoad.assignment_id == row.assignment_id).distinct())
    for student_id in recipients:
        notify(db, student_id, 'Опубликован учебный материал', row.title,
               f'/app/courses/materials/{row.id}', category='material')


@router.get('')
def materials(q: str = Query('', max_length=100), kind: MaterialKind | None = None,
              discipline: int | None = Query(None, ge=1, le=2147483647),
              teacher: int | None = Query(None, ge=1, le=2147483647),
              sort: Literal['newest', 'updated', 'oldest', 'title'] = 'newest',
              access: Access | None = None, mine: bool = False,
              offset: int = Query(0, ge=0, le=2147483647), limit: int = Query(18, ge=1, le=50),
              user=Depends(require_user), db: Session = Depends(get_db)):
    query = materials_query().join(Teacher).join(User, Teacher.user_id == User.id).join(Discipline)
    if mine:
        if user.role not in MATERIAL_MANAGERS:
            raise HTTPException(403, 'Доступно только уполномоченным сотрудникам')
        query = query.where(managed_assignments(user))
        disciplines = select(Discipline).where(Discipline.id.in_(
            select(TeachingAssignment.discipline_id).where(managed_assignments(user))))
    else:
        query = query.where(visible_materials(user), TeachingMaterial.access.in_(PUBLISHED_ACCESS))
        disciplines = select(Discipline)
    if discipline:
        query = query.where(Discipline.id == discipline)
    if teacher:
        query = query.where(Teacher.id == teacher)
    if kind:
        query = query.where(TeachingMaterial.kind == kind)
    if access:
        query = query.where(TeachingMaterial.access == access)
    q = search_text(q)
    if q:
        query = query.where(or_(*(text_search(column, q) for column in
                                  (TeachingMaterial.title, TeachingMaterial.description, TeachingMaterial.body,
                                   TeachingMaterial.file_name, Discipline.title, User.full_name))))
    order = {'newest': TeachingMaterial.created_at.desc(), 'updated': TeachingMaterial.updated_at.desc(),
             'oldest': TeachingMaterial.created_at.asc(), 'title': TeachingMaterial.title.asc()}[sort]
    total = db.scalar(select(func.count()).select_from(query.with_only_columns(TeachingMaterial.id).subquery()))
    rows = db.scalars(query.options(defer(TeachingMaterial.body))
                      .order_by(order, TeachingMaterial.id.desc()).offset(offset).limit(limit)).all()
    author = db.scalar(teachers_query().where(Teacher.id == teacher)) if teacher else None
    return dict(items=material_cards(db, user, rows), total=total, offset=offset, limit=limit,
                kinds=KIND_LABELS, access_labels=ACCESS_LABELS, teacher=teacher_card(author) if author else None,
                disciplines=[discipline_card(row) for row in db.scalars(disciplines.order_by(Discipline.title))])


@router.get('/assignments')
def publication_assignments(user=Depends(publisher), db: Session = Depends(get_db)):
    query = (select(TeachingAssignment).where(managed_assignments(user))
             .options(joinedload(TeachingAssignment.discipline), joinedload(TeachingAssignment.teacher).joinedload(Teacher.user))
             .order_by(TeachingAssignment.id))
    return dict(items=[dict(id=row.id, discipline=row.discipline.title, discipline_id=row.discipline_id,
                            author=row.teacher.user.full_name) for row in db.scalars(query)],
                kinds=KIND_LABELS, access_labels=ACCESS_LABELS, formats=FILE_FORMATS, max_file_bytes=MAX_MATERIAL_BYTES)


class DelegationBody(StrictBody):
    user_id: Version
    scope: Literal['course', 'department']
    scope_id: Version


def delegation_scope(scope):
    return ('coordinator', Discipline, 'discipline_id') if scope == 'course' else ('department', Department, 'department_id')


def delegation_payload(row):
    return dict(id=row.id, user_id=row.user_id, discipline_id=row.discipline_id, department_id=row.department_id)


@router.get('/delegations')
def delegations(_admin=Depends(administrator), db: Session = Depends(get_db)):
    actors = db.execute(select(User.id, User.full_name, User.role)
                        .where(User.role.in_(('coordinator', 'department'))).order_by(User.full_name)).all()
    disciplines = dict(db.execute(select(Discipline.id, Discipline.title).order_by(Discipline.title)).all())
    departments = dict(db.execute(select(Department.id, Department.name).order_by(Department.name)).all())
    names = {key: name for key, name, _role in actors}
    rows = db.scalars(select(MaterialDelegation).order_by(MaterialDelegation.id))
    return dict(items=[{**delegation_payload(row), 'name': names.get(row.user_id, f'Учётная запись №{row.user_id}'),
                       'label': disciplines.get(row.discipline_id) or departments.get(row.department_id)} for row in rows],
                actors=[dict(id=key, name=name, role=role) for key, name, role in actors],
                disciplines=[dict(id=key, title=title) for key, title in disciplines.items()],
                departments=[dict(id=key, title=title) for key, title in departments.items()])


@router.post('/delegations', status_code=201, dependencies=write)
def grant_delegation(body: DelegationBody, user=Depends(administrator), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    role, model, column = delegation_scope(body.scope)
    if db.scalar(select(User.id).where(User.id == body.user_id, User.role == role)) is None or db.get(model, body.scope_id) is None:
        raise HTTPException(404, 'Учётная запись с этой ролью или область доступа не найдена')
    row = db.scalar(select(MaterialDelegation).where(MaterialDelegation.user_id == body.user_id,
                                                     getattr(MaterialDelegation, column) == body.scope_id))
    if row is None:
        row = MaterialDelegation(user_id=body.user_id, **{column: body.scope_id})
        db.add(row)
        db.flush()
        recorded(db, user, 'material_delegation', row.id, 'granted', after=delegation_payload(row))
        db.commit()
    return delegation_payload(row)


@router.delete('/delegations/{grant_id}', dependencies=write)
def revoke_delegation(grant_id: RecordId, user=Depends(administrator), db: Session = Depends(get_db)):
    lock_workspace(db, user.id)
    row = db.get(MaterialDelegation, grant_id)
    if row is None:
        raise HTTPException(404, 'Полномочие не найдено')
    recorded(db, user, 'material_delegation', row.id, 'revoked', before=delegation_payload(row))
    db.delete(row)
    db.commit()
    return {'ok': True}


@router.get('/{material_id}')
def material(material_id: RecordId, user=Depends(require_user), db: Session = Depends(get_db)):
    row = find_material(db, material_id, visible_materials(user))
    return {**material_cards(db, user, [row])[0], 'body': row.body, 'sections': material_sections(row.body)}


@router.get('/{material_id}/history')
def material_history(material_id: RecordId, offset: int = Query(0, ge=0, le=2147483647),
                     user=Depends(publisher), db: Session = Depends(get_db)):
    query = select(TeachingAssignment.id).where(managed_assignments(user))
    find_material(db, material_id, TeachingMaterial.assignment_id.in_(query))
    events = db.execute(select(OperationEvent, User.full_name).join(User, User.id == OperationEvent.actor_id)
                        .where(OperationEvent.area == 'material', OperationEvent.object_id == material_id)
                        .order_by(OperationEvent.id.desc()).offset(offset).limit(51)).all()
    return dict(items=[dict(id=row.id, action=row.action, author=name, created_at=date_iso(row.created_at))
                       for row, name in events[:50]], has_more=len(events) > 50, offset=offset)


@router.get('/{material_id}/file')
def material_file(material_id: RecordId, user=Depends(require_user), db: Session = Depends(get_db)):
    row = find_material(db, material_id, visible_materials(user))
    if row.file_name:
        return download_upload(row.file_name, row.file_content)
    if row.external_url:
        raise HTTPException(404, 'У материала нет вложения')
    return HTMLResponse(material_html(material_card(row), material_sections(row.body)), headers={
        'Content-Disposition': f'attachment; filename="atlas-material-{row.id}.html"',
        'Content-Security-Policy': FILE_POLICY,
    })


@router.post('', status_code=201, dependencies=write)
def publish_material(body: MaterialBody, request: Request, response: Response,
                     user=Depends(publisher), db: Session = Depends(get_db)):
    values = material_values(body)
    access = body.access or 'campus'
    if access == 'archived':
        raise HTTPException(422, 'Сначала добавьте материал')
    lock_workspace(db, user.id)
    assignment = checked_assignment(db, body.assignment_id, user)
    legacy_fields = {'assignment_id', 'kind', 'title', 'description', 'body'}
    fingerprint = (body.model_dump(include=legacy_fields) if body.model_fields_set <= legacy_fields else
                   {**{name: value for name, value in values.items() if name != 'file_content'},
                    'assignment_id': assignment.id, 'access': access})
    receipt, prior = begin_idempotent(db, request, response, user, 'publish-material', fingerprint)
    if prior is not None:
        return prior
    require_file_capacity(db, assignment.id, None, values.get('file_size'))
    now = utc_now()
    row = TeachingMaterial(**values, access=access, assignment=assignment, publisher_id=user.id, created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    recorded(db, user, 'material', row.id, 'created', after=snapshot(row))
    if access in PUBLISHED_ACCESS:
        notify_students(db, row)
    return commit_idempotent(db, receipt, material_card(row, can_edit=True))


def owned_revision(db, user, material_id, version):
    lock_workspace(db, user.id)
    row = find_material(db, material_id)
    checked_assignment(db, row.assignment_id, user)
    if row.version != version:
        raise HTTPException(409, 'Материал изменился. Откройте его заново.')
    return row


@router.patch('/{material_id}', dependencies=write)
def edit_material(material_id: RecordId, body: MaterialEdit, user=Depends(publisher), db: Session = Depends(get_db)):
    row = owned_revision(db, user, material_id, body.version)
    assignment = checked_assignment(db, body.assignment_id, user)
    before = snapshot(row)
    values = material_values(body, row)
    require_file_capacity(db, assignment.id, row.id, values.get('file_size', row.file_size))
    for key, value in values.items():
        setattr(row, key, value)
    row.assignment = assignment
    row.access = body.access or row.access
    row.version += 1
    row.updated_at = utc_now()
    db.flush()
    action = 'edited' if before['access'] == row.access else 'archived' if row.access == 'archived' else 'access_changed'
    recorded(db, user, 'material', row.id, action, before=before, after=snapshot(row))
    if row.access in PUBLISHED_ACCESS and (before['access'] not in PUBLISHED_ACCESS or before['assignment_id'] != row.assignment_id):
        notify_students(db, row)
    result = material_card(row, can_edit=True)
    db.commit()
    return result


@router.delete('/{material_id}', dependencies=write)
def archive_material(material_id: RecordId, version: int = Query(..., ge=1, le=2147483647),
                     user=Depends(publisher), db: Session = Depends(get_db)):
    row = owned_revision(db, user, material_id, version)
    if row.access != 'archived':
        before = snapshot(row)
        row.access = 'archived'
        row.version += 1
        row.updated_at = utc_now()
        recorded(db, user, 'material', row.id, 'archived', before=before, after=snapshot(row))
        db.commit()
    return {'ok': True}
