"""Authenticated university directory and teacher profiles."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .db import User
from .university_db import Department, Discipline, Faculty, Teacher, TeachingAssignment, TeachingSlot

Slug = Annotated[str, Path(min_length=1, max_length=60, pattern=r'^[a-z0-9-]+$')]


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


def create_router():
    from .main import get_db, require_user, search_text

    router = APIRouter(prefix='/api')

    def lookup(db, query, label):
        row = db.scalar(query)
        if row is None:
            raise HTTPException(404, label)
        return row

    def teacher_profile(db, row, user):
        assignments = db.scalars(select(TeachingAssignment).where(TeachingAssignment.teacher_id == row.id)
                                 .options(joinedload(TeachingAssignment.discipline)).order_by(TeachingAssignment.id)).all()
        ids = [assignment.id for assignment in assignments]
        slots = db.scalars(select(TeachingSlot).where(TeachingSlot.assignment_id.in_(ids))
                          .options(joinedload(TeachingSlot.assignment).joinedload(TeachingAssignment.discipline))
                          .order_by(TeachingSlot.weekday, TeachingSlot.starts, TeachingSlot.id)).all()
        from .materials import teacher_materials
        materials = teacher_materials(db, user, row.id)
        return {**teacher_card(row), 'disciplines': [discipline_card(x.discipline) for x in assignments],
                'schedule': [dict(kind=x.kind, weekday=x.weekday, starts=x.starts, ends=x.ends, room=x.room,
                                  discipline=x.assignment.discipline.title) for x in slots],
                'materials': materials,
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

    return router
