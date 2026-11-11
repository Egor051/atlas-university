"""Authenticated directory and digital teaching library."""
from html import escape
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, defer, joinedload

from .db import User, utc_now
from .services import begin_idempotent, commit_idempotent
from .university_db import Department, Discipline, Faculty, Teacher, TeachingAssignment, TeachingMaterial, TeachingSlot

MaterialKind = Literal['lecture', 'guide', 'slides', 'practice', 'lab', 'extra']
Slug = Annotated[str, Path(min_length=1, max_length=60, pattern=r'^[a-z0-9-]+$')]
KIND_LABELS = {
    'lecture': 'Лекция', 'guide': 'Методические указания', 'slides': 'Презентация',
    'practice': 'Практическое задание', 'lab': 'Лабораторная работа', 'extra': 'Дополнительный материал',
}


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


def directory_path(*slugs):
    return '/app/university/' + '/'.join(slugs)


def faculty_card(row):
    return dict(kind='faculty', slug=row.slug, title=row.name, description=row.description,
                directions=row.directions, href=directory_path(row.slug), parents=[])


def department_card(row):
    faculty = row.faculty
    return dict(kind='department', slug=row.slug, title=row.name, description=row.description,
                directions=row.directions, href=directory_path(faculty.slug, row.slug),
                parents=[dict(title=faculty.name, href=directory_path(faculty.slug))])


def teacher_card(row):
    department = row.department
    parent = department_card(department)
    return dict(kind='teacher', id=row.id, title=row.user.full_name, position=row.position,
                department=department.name, description=row.academic, recipient_id=row.user_id,
                href=directory_path(department.faculty.slug, department.slug, row.slug),
                parents=[*parent['parents'], dict(title=department.name, href=parent['href'])])


def discipline_card(row):
    return dict(id=row.id, title=row.title, description=row.description)


def teachers_query():
    return select(Teacher).options(joinedload(Teacher.user),
                                   joinedload(Teacher.department).joinedload(Department.faculty))


def materials_query():
    teacher = joinedload(TeachingMaterial.assignment).joinedload(TeachingAssignment.teacher)
    return (select(TeachingMaterial)
            .options(teacher.joinedload(Teacher.user), teacher.joinedload(Teacher.department).joinedload(Department.faculty),
                     joinedload(TeachingMaterial.assignment).joinedload(TeachingAssignment.discipline)))


def may_publish(user, teacher):
    return user.role == 'staff' or (user.role == 'teacher' and teacher.user_id == user.id)


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
<small>АТЛАС Campus · конкурсный концепт · все данные вымышлены</small><h1>{title}</h1>
<p>{escape(row['kind_label'])} · {escape(row['discipline']['title'])} · {escape(row['author']['title'])} · {row['created_at'][:10]}</p>
<p>{escape(row['description'])}</p></header>{''.join(articles)}</main></body></html>'''


def create_router():
    from .main import StrictBody, date_iso, get_db, require_same_origin, require_user, search_text, text_search

    router = APIRouter(prefix='/api')
    write = [Depends(require_same_origin)]

    class MaterialBody(StrictBody):
        assignment_id: int = Field(strict=True, ge=1, le=2147483647)
        kind: MaterialKind
        title: str = Field(min_length=4, max_length=180)
        description: str = Field(min_length=10, max_length=600)
        body: str = Field(min_length=20, max_length=6000)

        @field_validator('title', 'description', 'body', mode='before')
        @classmethod
        def trim(cls, value):
            return value.strip() if isinstance(value, str) else value

        @model_validator(mode='after')
        def validate_sections(self):
            sections = material_sections(self.body)
            if not any(section['paragraphs'] for section in sections):
                raise ValueError('Добавьте текст материала')
            if self.kind == 'slides' and (len(sections) < 2 or any(not s['heading'] or not s['paragraphs'] for s in sections)):
                raise ValueError('Для презентации нужны минимум два слайда с заголовками ## и текстом')
            return self

    class MaterialEdit(MaterialBody):
        version: int = Field(strict=True, ge=1, le=2147483647)

    def publisher(user=Depends(require_user)):
        if user.role not in {'teacher', 'staff'}:
            raise HTTPException(403, 'Публиковать материалы могут уполномоченные сотрудники')
        return user

    def lookup(db, query, label):
        row = db.scalar(query)
        if row is None:
            raise HTTPException(404, label)
        return row

    def find_material(db, material_id):
        return lookup(db, materials_query().where(TeachingMaterial.id == material_id), 'Материал не найден')

    def checked_assignment(db, assignment_id, user):
        row = lookup(db, select(TeachingAssignment).options(joinedload(TeachingAssignment.teacher))
                     .where(TeachingAssignment.id == assignment_id), 'Дисциплина не найдена')
        if not may_publish(user, row.teacher):
            raise HTTPException(403, 'Материал можно публиковать только по назначенной дисциплине')
        return row

    def material_card(row, user):
        return dict(id=row.id, title=row.title, description=row.description, kind=row.kind,
                    kind_label=KIND_LABELS[row.kind], discipline=discipline_card(row.assignment.discipline),
                    author=teacher_card(row.assignment.teacher), assignment_id=row.assignment_id,
                    created_at=date_iso(row.created_at), updated_at=date_iso(row.updated_at), version=row.version,
                    can_edit=may_publish(user, row.assignment.teacher), file_url=f'/api/materials/{row.id}/file')

    def teacher_profile(db, row, user):
        assignments = db.scalars(select(TeachingAssignment).where(TeachingAssignment.teacher_id == row.id)
                                 .options(joinedload(TeachingAssignment.discipline)).order_by(TeachingAssignment.id)).all()
        ids = [assignment.id for assignment in assignments]
        slots = db.scalars(select(TeachingSlot).where(TeachingSlot.assignment_id.in_(ids))
                          .options(joinedload(TeachingSlot.assignment).joinedload(TeachingAssignment.discipline))
                          .order_by(TeachingSlot.weekday, TeachingSlot.starts, TeachingSlot.id)).all()
        material_filter = TeachingMaterial.assignment_id.in_(ids)
        materials = db.scalars(materials_query().where(material_filter).options(defer(TeachingMaterial.body))
                               .order_by(TeachingMaterial.created_at.desc(), TeachingMaterial.id.desc()).limit(6)).all()
        return {**teacher_card(row), 'disciplines': [discipline_card(x.discipline) for x in assignments],
                'schedule': [dict(kind=x.kind, weekday=x.weekday, starts=x.starts, ends=x.ends, room=x.room,
                                  discipline=x.assignment.discipline.title) for x in slots],
                'materials': [material_card(x, user) for x in materials],
                'can_message': user.role == 'student' and row.user.role == 'teacher'}

    @router.get('/university')
    def directory(q: str = Query('', max_length=100), faculty: str = Query('', max_length=60),
                  kind: Literal['all', 'faculty', 'department', 'teacher'] = 'all',
                  _user=Depends(require_user), db: Session = Depends(get_db)):
        q = search_text(q).casefold()
        faculties = db.scalars(select(Faculty).order_by(Faculty.name)).all()
        rows = [faculty_card(row) for row in faculties if not faculty or row.slug == faculty]
        if q or faculty or kind != 'all':
            departments = db.scalars(select(Department).options(joinedload(Department.faculty)).order_by(Department.name)).all()
            rows += [department_card(row) for row in departments if not faculty or row.faculty.slug == faculty]
            teachers = db.scalars(teachers_query().join(User, Teacher.user_id == User.id).order_by(User.full_name)).all()
            subjects = {}
            for teacher_id, title in db.execute(select(TeachingAssignment.teacher_id, Discipline.title).join(Discipline)):
                subjects.setdefault(teacher_id, []).append(title)
            rows += [{**teacher_card(row), 'subjects': subjects.get(row.id, [])}
                     for row in teachers if not faculty or row.department.faculty.slug == faculty]
            rows = [row for row in rows if (kind == 'all' or row['kind'] == kind)
                    and q in ' '.join([row['title'], row['description'], row.get('directions', ''),
                                      row.get('department', ''), *row.get('subjects', [])]).casefold()]
        return {'kind': 'directory', 'title': 'Университет', 'items': rows,
                'faculties': [{'slug': row.slug, 'title': row.name} for row in faculties]}

    @router.get('/university/me')
    def my_teaching(user=Depends(require_user), db: Session = Depends(get_db)):
        if user.role != 'teacher':
            raise HTTPException(403, 'Только для преподавателей')
        return teacher_profile(db, lookup(db, teachers_query().where(Teacher.user_id == user.id),
                                          'Профиль преподавателя не найден'), user)

    @router.get('/university/{faculty}')
    def faculty_detail(faculty: Slug, _user=Depends(require_user), db: Session = Depends(get_db)):
        row = lookup(db, select(Faculty).where(Faculty.slug == faculty), 'Подразделение не найдено')
        departments = db.scalars(select(Department).where(Department.faculty_id == row.id).order_by(Department.name)).all()
        disciplines = db.scalars(select(Discipline).join(Department).where(Department.faculty_id == row.id)
                                .order_by(Discipline.title)).all()
        return {**faculty_card(row), 'items': [department_card(x) for x in departments],
                'disciplines': [discipline_card(x) for x in disciplines]}

    @router.get('/university/{faculty}/{department}')
    def department_detail(faculty: Slug, department: Slug, _user=Depends(require_user), db: Session = Depends(get_db)):
        row = lookup(db, select(Department).join(Faculty).where(Faculty.slug == faculty, Department.slug == department),
                     'Кафедра не найдена')
        teachers = db.scalars(teachers_query().where(Teacher.department_id == row.id).order_by(Teacher.id)).all()
        disciplines = db.scalars(select(Discipline).where(Discipline.department_id == row.id).order_by(Discipline.title)).all()
        return {**department_card(row), 'items': [teacher_card(x) for x in teachers],
                'disciplines': [discipline_card(x) for x in disciplines]}

    @router.get('/university/{faculty}/{department}/{teacher}')
    def teacher_detail(faculty: Slug, department: Slug, teacher: Slug, user=Depends(require_user), db: Session = Depends(get_db)):
        row = lookup(db, teachers_query().join(Department).join(Faculty)
                     .where(Faculty.slug == faculty, Department.slug == department, Teacher.slug == teacher),
                     'Преподаватель не найден')
        return teacher_profile(db, row, user)

    @router.get('/materials')
    def materials(q: str = Query('', max_length=100), kind: MaterialKind | None = None,
                  discipline: int | None = Query(None, ge=1, le=2147483647), teacher: int | None = Query(None, ge=1, le=2147483647),
                  mine: bool = False, offset: int = Query(0, ge=0, le=2147483647), limit: int = Query(18, ge=1, le=50),
                  user=Depends(require_user), db: Session = Depends(get_db)):
        query = materials_query().join(TeachingAssignment).join(Teacher).join(User, Teacher.user_id == User.id).join(Discipline)
        q = search_text(q)
        if q:
            query = query.where(or_(*(text_search(column, q) for column in
                                      (TeachingMaterial.title, TeachingMaterial.description, Discipline.title, User.full_name))))
        if kind:
            query = query.where(TeachingMaterial.kind == kind)
        if discipline:
            query = query.where(Discipline.id == discipline)
        if teacher:
            query = query.where(Teacher.id == teacher)
        if mine:
            if user.role not in {'teacher', 'staff'}:
                raise HTTPException(403, 'Доступно только сотрудникам')
            if user.role == 'teacher':
                query = query.where(Teacher.user_id == user.id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.options(defer(TeachingMaterial.body))
                          .order_by(TeachingMaterial.created_at.desc(), TeachingMaterial.id.desc()).offset(offset).limit(limit)).all()
        return dict(items=[material_card(row, user) for row in rows], total=total, offset=offset, limit=limit,
                    kinds=KIND_LABELS, disciplines=[discipline_card(row) for row in
                                                    db.scalars(select(Discipline).order_by(Discipline.title)).all()])

    @router.get('/materials/assignments')
    def publication_assignments(user=Depends(publisher), db: Session = Depends(get_db)):
        query = (select(TeachingAssignment).join(Teacher)
                 .options(joinedload(TeachingAssignment.discipline), joinedload(TeachingAssignment.teacher).joinedload(Teacher.user))
                 .order_by(TeachingAssignment.id))
        if user.role == 'teacher':
            query = query.where(Teacher.user_id == user.id)
        return {'items': [dict(id=row.id, discipline=row.discipline.title, author=row.teacher.user.full_name)
                          for row in db.scalars(query).all()], 'kinds': KIND_LABELS}

    @router.get('/materials/{material_id}')
    def material(material_id: int, user=Depends(require_user), db: Session = Depends(get_db)):
        row = find_material(db, material_id)
        return {**material_card(row, user), 'body': row.body, 'sections': material_sections(row.body)}

    @router.get('/materials/{material_id}/file')
    def material_file(material_id: int, user=Depends(require_user), db: Session = Depends(get_db)):
        row = find_material(db, material_id)
        return HTMLResponse(material_html(material_card(row, user), material_sections(row.body)), headers={
            'Content-Disposition': f'attachment; filename="atlas-material-{row.id}.html"',
            'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
        })

    @router.post('/materials', status_code=201, dependencies=write)
    def publish_material(body: MaterialBody, request: Request, response: Response,
                         user=Depends(publisher), db: Session = Depends(get_db)):
        assignment = checked_assignment(db, body.assignment_id, user)
        values = body.model_dump()
        receipt, prior = begin_idempotent(db, request, response, user, 'publish-material', values)
        if prior is not None:
            return prior
        now = utc_now()
        row = TeachingMaterial(**body.model_dump(exclude={'assignment_id'}), assignment=assignment,
                               publisher_id=user.id, created_at=now, updated_at=now)
        db.add(row)
        db.flush()
        result = material_card(row, user)
        return commit_idempotent(db, receipt, result)

    @router.patch('/materials/{material_id}', dependencies=write)
    def edit_material(material_id: int, body: MaterialEdit, user=Depends(publisher), db: Session = Depends(get_db)):
        row = find_material(db, material_id)
        if not may_publish(user, row.assignment.teacher):
            raise HTTPException(403, 'Этот материал закреплён за другим преподавателем')
        if row.version != body.version:
            raise HTTPException(409, 'Материал изменился. Откройте его заново.')
        checked_assignment(db, body.assignment_id, user)
        values = body.model_dump(exclude={'version'})
        changed = db.execute(update(TeachingMaterial).where(TeachingMaterial.id == material_id, TeachingMaterial.version == body.version)
                             .values(**values, version=body.version + 1, updated_at=utc_now()))
        if changed.rowcount != 1:
            raise HTTPException(409, 'Материал изменился. Откройте его заново.')
        db.expire(row)
        result = material_card(row, user)
        db.commit()
        return result

    @router.delete('/materials/{material_id}', dependencies=write)
    def remove_material(material_id: int, version: int = Query(..., ge=1, le=2147483647),
                        user=Depends(publisher), db: Session = Depends(get_db)):
        row = find_material(db, material_id)
        if not may_publish(user, row.assignment.teacher):
            raise HTTPException(403, 'Этот материал закреплён за другим преподавателем')
        if row.version != version:
            raise HTTPException(409, 'Материал изменился. Откройте его заново.')
        changed = db.execute(delete(TeachingMaterial).where(TeachingMaterial.id == material_id, TeachingMaterial.version == version))
        if changed.rowcount != 1:
            raise HTTPException(409, 'Материал изменился. Откройте его заново.')
        db.commit()
        return {'ok': True}

    return router
