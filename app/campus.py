"""Portfolio, cross-campus search and session controls. No external services."""
import hashlib
from datetime import date
from typing import Literal
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import Field, field_validator
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from .db import LoginSession, DocumentRequest, Deadline, Notification, Grade, request_kind, utc_now
from .campus_db import PortfolioItem
from .services import begin_idempotent, commit_idempotent
from .storage_guards import lock_owner, update_personal, delete_personal


def create_router():
    from .main import (get_db, require_student, require_user, require_same_origin,
                       StrictBody, date_iso, COOKIE_NAME, text_search, search_text)
    router = APIRouter()

    class PortfolioBody(StrictBody):
        title: str = Field(min_length=3, max_length=180)
        kind: Literal['project', 'award', 'course', 'practice'] = 'project'
        description: str = Field(default='', max_length=6000)
        url: str = Field(default='', max_length=500)
        day: date

        @field_validator('title')
        @classmethod
        def title_content(cls, value):
            if len(value.strip()) < 3:
                raise ValueError('Название слишком короткое')
            return value.strip()

        @field_validator('url')
        @classmethod
        def safe_url(cls, value):
            value = value.strip()
            if value:
                parsed = urlsplit(value)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or '\\' in value or any(c.isspace() for c in value):
                    raise ValueError('Укажите HTTPS-ссылку без логина и пароля')
            return value

    def payload(item):
        return dict(id=item.id, record_token=item.record_token, title=item.title, kind=item.kind, description=item.description,
                    url=item.url, day=date_iso(item.day), updated_at=date_iso(item.updated_at))

    def owned(db, user, item_id):
        row = db.scalar(select(PortfolioItem).where(PortfolioItem.id == item_id, PortfolioItem.student_id == user.id))
        if not row:
            raise HTTPException(404, 'Запись портфолио не найдена')
        return row

    @router.get('/api/campus/portfolio')
    def portfolio(user=Depends(require_student), db: Session = Depends(get_db)):
        rows = db.scalars(select(PortfolioItem).where(PortfolioItem.student_id == user.id).order_by(PortfolioItem.day.desc(), PortfolioItem.id.desc())).all()
        return {'items': [payload(row) for row in rows]}

    @router.post('/api/campus/portfolio', status_code=201)
    def add_portfolio(body: PortfolioBody, request: Request, response: Response, user=Depends(require_student), db: Session = Depends(get_db), _=Depends(require_same_origin)):
        receipt, replay = begin_idempotent(db, request, response, user, 'portfolio-create', body.model_dump())
        if replay is not None:
            return replay
        lock_owner(db, user.id)
        if db.scalar(select(func.count()).select_from(PortfolioItem).where(PortfolioItem.student_id == user.id)) >= 200:
            raise HTTPException(409, 'В портфолио можно сохранить до 200 записей')
        row = PortfolioItem(student_id=user.id, **body.model_dump(), updated_at=utc_now())
        db.add(row)
        db.flush()
        return commit_idempotent(db, receipt, payload(row))

    @router.post('/api/campus/portfolio/{item_id}')
    def edit_portfolio(item_id: int, body: PortfolioBody, request: Request, user=Depends(require_student), db: Session = Depends(get_db), _=Depends(require_same_origin)):
        row = owned(db, user, item_id)
        update_personal(db, PortfolioItem, row, user, {**body.model_dump(), 'updated_at': utc_now()}, request)
        db.commit()
        return payload(row)

    @router.post('/api/campus/portfolio/{item_id}/delete')
    def delete_portfolio(item_id: int, request: Request, user=Depends(require_student), db: Session = Depends(get_db), _=Depends(require_same_origin)):
        delete_personal(db, PortfolioItem, owned(db, user, item_id), user, request, 'portfolio')
        db.commit()
        return {'ok': True}

    @router.get('/api/campus/portfolio/export')
    def export_portfolio(user=Depends(require_student), db: Session = Depends(get_db)):
        import html
        esc = html.escape
        rows = db.scalars(select(PortfolioItem).where(PortfolioItem.student_id == user.id).order_by(PortfolioItem.day.desc(), PortfolioItem.id.desc())).all()
        sections = ''.join(f'<article><h2>{esc(row.title)}</h2><p>{row.day:%d.%m.%Y} · {esc(row.kind)}</p><p class="text">{esc(row.description)}</p>{"<p>" + esc(row.url) + "</p>" if row.url else ""}</article>' for row in rows)
        doc = f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>АТЛАС · портфолио</title><body><main><h1>Портфолио: {esc(user.full_name)}</h1><p>{esc(user.program)} · {esc(user.group_name)}</p>{sections or "<p>Записей пока нет.</p>"}<footer>Портфолио составлено пользователем. Оно не подтверждает квалификацию.</footer></main></body></html>'
        return HTMLResponse(doc, headers={'Content-Disposition': 'attachment; filename="atlas-portfolio.html"', 'Content-Security-Policy': "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"})

    @router.get('/api/campus/search')
    def campus_search(q: str = Query('', max_length=100), user=Depends(require_student), db: Session = Depends(get_db)):
        term = search_text(q.strip())
        if len(term) < 2:
            return {'items': []}
        from .assignment_workflow import visible_deadline
        from .learning_db import StudyNote
        results = []
        specifications = [
            (DocumentRequest, DocumentRequest.type, 'requests', 'Заявка', DocumentRequest.comment),
            (Deadline, Deadline.title, 'plan', 'Задание', Deadline.subject),
            (Notification, Notification.title, 'notifications', 'Уведомление', Notification.body),
            (Grade, Grade.subject, 'grades', 'Дисциплина', Grade.teacher),
            (PortfolioItem, PortfolioItem.title, 'portfolio', 'Портфолио', PortfolioItem.description),
            (StudyNote, StudyNote.title, 'notes', 'Конспект', StudyNote.body),
        ]
        for model, title, target, category, content in specifications:
            condition = text_search(title, term) | text_search(content, term)
            if model is Deadline:
                condition = condition & visible_deadline()
            rows = db.scalars(select(model).where(model.student_id == user.id, condition).order_by(model.id.desc()).limit(8)).all()
            for row in rows:
                certificate = model is DocumentRequest and request_kind(row.type) == 'certificate'
                results.append({'id': row.id, 'title': getattr(row, title.key), 'snippet': str(getattr(row, content.key) or '')[:160],
                                'target': 'certificates' if certificate else target, 'category': 'Справка' if certificate else category})
        return {'items': results}

    @router.get('/api/account/sessions')
    def sessions(request: Request, user=Depends(require_user), db: Session = Depends(get_db)):
        current = hashlib.sha256(request.cookies.get(COOKIE_NAME, '').encode()).hexdigest()
        rows = db.scalars(select(LoginSession).where(LoginSession.user_id == user.id, LoginSession.expires_at > utc_now()).order_by(LoginSession.id.desc())).all()
        return {'items': [{'id': row.id, 'is_current': row.token_hash == current, 'expires_at': date_iso(row.expires_at)} for row in rows]}

    @router.post('/api/account/sessions/revoke-others')
    def revoke_others(request: Request, user=Depends(require_user), db: Session = Depends(get_db), _=Depends(require_same_origin)):
        current = hashlib.sha256(request.cookies.get(COOKIE_NAME, '').encode()).hexdigest()
        result = db.execute(delete(LoginSession).where(LoginSession.user_id == user.id, LoginSession.token_hash != current))
        db.commit()
        return {'ok': True, 'revoked': result.rowcount}

    return router
