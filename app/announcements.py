"""Read scoped announcements and manage their editorial workflow in the study office."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import Field, StrictBool, field_validator, model_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from .announcements_db import Announcement
from .db import User, utc_now
from .main import StrictBody, date_iso, get_db, require_same_origin, require_staff, require_user, text_search
from .services import begin_idempotent, commit_idempotent
from .workspace import event_payload, notify, recorded
from .workspace_db import AcademicGroup, GroupMember, OperationEvent

router = APIRouter(prefix='/api')
write = [Depends(require_same_origin)]
Category = Literal['announcement', 'deadline', 'academic', 'campus']
Priority = Literal['normal', 'important', 'critical']
Audience = Literal['all', 'students', 'employees', 'group']
Status = Literal['draft', 'published', 'archived']
Sort = Literal['featured', 'newest', 'oldest']


class AnnouncementBody(StrictBody):
    title: str = Field(min_length=5, max_length=180)
    body: str = Field(min_length=10, max_length=4000)
    category: Category = 'announcement'
    priority: Priority = 'normal'
    audience: Audience = 'students'
    group_id: int | None = Field(default=None, strict=True, ge=1, le=2147483647)
    pinned: StrictBool = False
    status: Status = 'published'

    @field_validator('title', 'body', mode='before')
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode='after')
    def group_matches_audience(self):
        if (self.audience == 'group') != (self.group_id is not None):
            raise ValueError('Группа указывается только для публикаций учебной группы')
        return self


class AnnouncementEdit(AnnouncementBody):
    version: int = Field(strict=True, ge=1, le=2147483647)


def audience_scope(user):
    if user.role != 'student':
        return Announcement.audience.in_(('all', 'employees'))
    member = select(GroupMember.student_id).where(GroupMember.student_id == user.id,
                                                  GroupMember.group_id == Announcement.group_id).exists()
    return or_(Announcement.audience.in_(('all', 'students')),
               (Announcement.audience == 'group') & member)


def payload(row, *, excerpt=False):
    result = dict(id=row.id, title=row.title, category=row.category, priority=row.priority,
                  audience=row.audience, group_id=row.group_id, group=row.group.code if row.group else None,
                  status=row.status, pinned=row.pinned, author=row.author.full_name, unit='Учебный офис',
                  created_at=date_iso(row.created_at), updated_at=date_iso(row.updated_at),
                  published_at=date_iso(row.published_at), version=row.version)
    if excerpt:
        shortened = row.body[:220].rstrip()
        result['excerpt'] = shortened + ('…' if len(row.body) > 220 else '')
    else:
        result['body'] = row.body
    return result


def find_announcement(db, record_id, *conditions):
    row = db.scalar(select(Announcement).where(Announcement.id == record_id, *conditions)
                    .options(joinedload(Announcement.author), joinedload(Announcement.group)))
    if row is None:
        raise HTTPException(404, 'Объявление не найдено')
    return row


def listing(db, conditions, *, category, priority, q, sort, offset, limit, staff=False):
    if category:
        conditions.append(Announcement.category == category)
    if priority:
        conditions.append(Announcement.priority == priority)
    if q.strip():
        conditions.append(or_(text_search(Announcement.title, q.strip()), text_search(Announcement.body, q.strip())))
    date = func.coalesce(Announcement.published_at, Announcement.created_at) if staff else Announcement.published_at
    order = (date.asc(), Announcement.id.asc()) if sort == 'oldest' else (date.desc(), Announcement.id.desc())
    if sort == 'featured':
        order = (Announcement.pinned.desc(), *order)
    rows = db.scalars(select(Announcement).where(*conditions)
                      .options(joinedload(Announcement.author), joinedload(Announcement.group))
                      .order_by(*order).offset(offset).limit(limit + 1)).all()
    return dict(items=[payload(row, excerpt=True) for row in rows[:limit]],
                offset=offset, limit=limit, more=len(rows) > limit)


def validate_group(db, group_id):
    if group_id is not None and db.get(AcademicGroup, group_id) is None:
        raise HTTPException(422, 'Учебная группа не найдена')


def deliver(db, announcement, *, legacy=False):
    recipients = select(User.id, User.role)
    if announcement.audience == 'employees':
        recipients = recipients.where(User.role != 'student')
    elif announcement.audience == 'students':
        recipients = recipients.where(User.role == 'student')
    elif announcement.audience == 'group':
        recipients = recipients.join(GroupMember, GroupMember.student_id == User.id).where(
            User.role == 'student', GroupMember.group_id == announcement.group_id)
    rows = db.execute(recipients.order_by(User.id)).all()
    category = 'deadline' if legacy and announcement.category == 'deadline' else 'announcement'
    notice = announcement.body if legacy else 'Учебный офис опубликовал объявление.'
    for user_id, role in rows:
        notify(db, user_id, announcement.title, notice, f'/app/announcements/{announcement.id}',
               student=role == 'student', category=category)
    return len(rows)


@router.get('/announcements')
def announcements(user: User = Depends(require_user), db: Session = Depends(get_db),
                  status: Literal['published', 'archived'] = 'published', category: Category | None = None,
                  priority: Priority | None = None, q: str = Query('', max_length=100), sort: Sort = 'featured',
                  offset: int = Query(0, ge=0, le=2147483647), limit: int = Query(24, ge=1, le=50)):
    conditions = [Announcement.status == status, Announcement.published_at.is_not(None), audience_scope(user)]
    return listing(db, conditions, category=category, priority=priority, q=q, sort=sort, offset=offset, limit=limit)


@router.get('/announcements/{record_id}')
def announcement_detail(record_id: int = Path(ge=1, le=2147483647),
                        user: User = Depends(require_user), db: Session = Depends(get_db)):
    return payload(find_announcement(db, record_id, Announcement.status.in_(('published', 'archived')),
                                     Announcement.published_at.is_not(None), audience_scope(user)))


@router.get('/staff/announcements')
def editor_list(_user: User = Depends(require_staff), db: Session = Depends(get_db), status: Status | None = None,
                category: Category | None = None, priority: Priority | None = None,
                q: str = Query('', max_length=100), sort: Sort = 'newest',
                offset: int = Query(0, ge=0, le=2147483647), limit: int = Query(24, ge=1, le=50)):
    return listing(db, [Announcement.status == status] if status else [], category=category, priority=priority,
                   q=q, sort=sort, offset=offset, limit=limit, staff=True)


@router.get('/staff/announcements/groups')
def audience_groups(_user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return dict(items=[dict(id=group.id, name=group.code) for group in
                       db.scalars(select(AcademicGroup).order_by(AcademicGroup.code))])


@router.get('/staff/announcements/{record_id}')
def editor_detail(record_id: int = Path(ge=1, le=2147483647), history_offset: int = Query(0, ge=0, le=2147483647),
                  _user: User = Depends(require_staff), db: Session = Depends(get_db)):
    row = find_announcement(db, record_id)
    events = db.execute(select(OperationEvent, User.full_name).join(User, User.id == OperationEvent.actor_id)
                        .where(OperationEvent.area == 'announcement', OperationEvent.object_id == row.id)
                        .order_by(OperationEvent.id.desc()).offset(history_offset).limit(21)).all()
    return dict(**payload(row), revisions=[event_payload(event, author, date_iso) for event, author in events[:20]],
                revision_offset=history_offset, more_revisions=len(events) > 20)


@router.post('/staff/announcements', status_code=201, dependencies=write)
def create_announcement(body: AnnouncementBody, request: Request, response: Response,
                        user: User = Depends(require_staff), db: Session = Depends(get_db)):
    values = body.model_dump()
    legacy_fields = {'title', 'body', 'category'}
    legacy = body.model_fields_set <= legacy_fields
    receipt_body = {key: values[key] for key in legacy_fields} if legacy else values
    receipt, replay = begin_idempotent(db, request, response, user, 'announcement-create', receipt_body)
    if replay is not None:
        return replay
    if body.status == 'archived':
        raise HTTPException(422, 'Создайте черновик или опубликуйте объявление')
    validate_group(db, body.group_id)
    now = utc_now()
    published = body.status == 'published'
    row = Announcement(**values, author_id=user.id, created_at=now, updated_at=now,
                       published_at=now if published else None)
    db.add(row)
    db.flush()
    result = payload(row)
    recorded(db, user, 'announcement', row.id, 'published' if published else 'created', after=result)
    sent = deliver(db, row, legacy=legacy) if published else 0
    return commit_idempotent(db, receipt, dict(**result, sent=sent, concept=True))


@router.patch('/staff/announcements/{record_id}', dependencies=write)
def edit_announcement(body: AnnouncementEdit, request: Request, response: Response,
                      record_id: int = Path(ge=1, le=2147483647),
                      user: User = Depends(require_staff), db: Session = Depends(get_db)):
    receipt, replay = begin_idempotent(db, request, response, user, f'announcement-edit-{record_id}', body.model_dump())
    if replay is not None:
        return replay
    row = find_announcement(db, record_id)
    if row.version != body.version:
        raise HTTPException(409, 'Объявление изменилось. Обновите страницу перед сохранением')
    if row.status == 'archived':
        raise HTTPException(409, 'Архивное объявление доступно только для чтения')
    if row.published_at and (row.audience, row.group_id) != (body.audience, body.group_id):
        raise HTTPException(409, 'Для другой аудитории создайте новое объявление')
    validate_group(db, body.group_id)
    before = payload(row)
    now = utc_now()
    first_publish = body.status == 'published' and row.published_at is None
    action = 'edited' if body.status == row.status else {'published': 'published', 'archived': 'archived', 'draft': 'withdrawn'}[body.status]
    fields = body.model_dump(exclude={'version'})
    if not any(before[key] != value for key, value in fields.items()):
        return commit_idempotent(db, receipt, dict(**before, sent=0))
    changed = db.execute(update(Announcement).where(Announcement.id == row.id, Announcement.version == body.version)
                         .values(**fields, version=body.version + 1, updated_at=now,
                                 published_at=now if first_publish else row.published_at)
                         .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, 'Объявление изменилось. Обновите страницу перед сохранением')
    # Reload relationships as well as scalar fields if the draft's audience changed.
    db.expire(row)
    result = payload(row)
    recorded(db, user, 'announcement', row.id, action, before, result)
    sent = deliver(db, row) if first_publish else 0
    return commit_idempotent(db, receipt, dict(**result, sent=sent))
