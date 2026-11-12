"""Preserve earlier workspace notices in the unified inbox."""
from sqlalchemy import String, case, cast, literal, select

from .db import Notification
from .workspace_db import WorkspaceNotice


def upgrade_notifications(connection):
    legacy = WorkspaceNotice.__table__
    inbox = Notification.__table__
    key = literal('workspace:') + cast(legacy.c.id, String)
    category = case(
        (legacy.c.target.startswith('/app/schedule'), 'schedule'),
        (legacy.c.target.startswith('/app/teach-schedule'), 'schedule'),
        (legacy.c.target.startswith('/app/union-office'), 'union'),
        (legacy.c.target.startswith('/app/vuc-office'), 'vuc'),
        else_='academic',
    )
    old_notices = select(legacy.c.user_id, legacy.c.title, legacy.c.body, category, legacy.c.created_at,
                         legacy.c.is_read, legacy.c.target, key).where(
        ~select(inbox.c.id).where(inbox.c.event_key == key).exists()
    )
    connection.execute(inbox.insert().from_select(
        ['student_id', 'title', 'body', 'category', 'created_at', 'is_read', 'target', 'event_key'], old_notices
    ))
