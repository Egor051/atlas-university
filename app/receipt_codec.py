"""Linear-size operation receipts over immutable, separately stored history.

Version 1 stores one base snapshot, a child-id cutoff and one page position.
It never stores growing child-id arrays or repeats historical message bodies.
Legacy JSON responses remain readable.
"""
import json
from datetime import datetime
from sqlalchemy import select, func
from .session_security import as_utc

MARKER = '__atlas_receipt_v1__'


def _source(kind):
    if kind == 'request':
        from .db import RequestEvent
        return RequestEvent, RequestEvent.request_id, 'history', 'history', 100
    from .services_db import TicketMessage
    return TicketMessage, TicketMessage.ticket_id, 'messages', 'messages', 100


def encode_receipt(db, payload, *, verify_legacy=False):
    if not isinstance(payload, dict) or MARKER in payload:
        return payload
    kind = 'request' if isinstance(payload.get('history'), list) else 'ticket' if isinstance(payload.get('messages'), list) else None
    if kind is None or not isinstance(payload.get('id'), int):
        return payload
    model, parent, key, prefix, default_limit = _source(kind)
    children = payload[key]
    if verify_legacy:
        # Do not discard the only surviving copy of a deleted/changed child.
        ids = [child.get('id') for child in children]
        if not ids or any(not isinstance(i, int) for i in ids):
            return payload
        existing = {row.id: row for row in db.scalars(select(model).where(parent == payload['id'], model.id.in_(ids)))}
        if any(i not in existing or _child_payload(existing[i], kind) != child for i, child in zip(ids, children)):
            return payload
        cutoff = max(ids)
    else:
        cutoff = db.scalar(select(func.max(model.id)).where(parent == payload['id'])) or 0
    total = db.scalar(select(func.count()).select_from(model).where(parent == payload['id'], model.id <= cutoff))
    historical_total = payload.get(prefix + '_total')
    if verify_legacy and historical_total is not None and total != historical_total:
        return payload
    # Keep the exact captured page, including old unbounded request responses.
    # The receipt remains constant-size: only these two integers are stored.
    # Newly produced responses already carry their endpoint's bounded page.
    limit = max(1, int(payload.get(prefix + '_limit', len(children) or default_limit)))
    offset = payload.get(prefix + '_offset')
    if offset is None:
        offset = max(0, total-len(children)) if kind == 'ticket' else 0
    if verify_legacy:
        page = db.scalars(select(model).where(parent == payload['id'], model.id <= cutoff)
                          .order_by(model.created_at, model.id).offset(offset).limit(limit)).all()
        if [_child_payload(row, kind) for row in page] != children:
            return payload
    base = {k: v for k, v in payload.items() if k != key}
    return {MARKER: True, 'kind': kind, 'resource_id': payload['id'],
            'cutoff': cutoff, 'limit': limit, 'offset': offset, 'base': base}


def _child_payload(row, kind):
    def date_iso(value):
        if isinstance(value, datetime):
            value = as_utc(value)
        return value.isoformat() if value else None
    if kind == 'request':
        return dict(id=row.id, status=row.status, message=row.message,
                    actor_role=row.actor_role, actor_name=row.actor_name,
                    created_at=date_iso(row.created_at))
    return dict(id=row.id, body=row.body, actor_role=row.actor_role,
                actor_name=row.actor_name, created_at=date_iso(row.created_at))


def decode_receipt(db, value):
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict) or payload.get(MARKER) is not True:
        return payload
    model, parent, key, _, _ = _source(payload['kind'])
    rows = db.scalars(select(model).where(parent == payload['resource_id'], model.id <= payload['cutoff'])
                      .order_by(model.created_at, model.id).offset(payload['offset']).limit(payload['limit'])).all()
    return {**payload['base'], key: [_child_payload(row, payload['kind']) for row in rows]}
