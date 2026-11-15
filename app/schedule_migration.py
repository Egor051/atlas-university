"""Add calendar and occurrence metadata, retaining old IDs and audit history."""
from datetime import date
import json

from sqlalchemy import func, inspect, select

from .db import User
from .schedule_calendar import DEMO_WINDOW
from .workspace_db import AcademicDayRule, Classroom, GroupMember, OperationEvent, ScheduledClass


def upgrade_calendar(connection):
    additions = {
        'academic_group_members': {'subgroup_id': 'INTEGER REFERENCES academic_subgroups(id)'},
        'academic_classes': {
            'subgroup_id': 'INTEGER REFERENCES academic_subgroups(id)',
            'student_id': 'INTEGER REFERENCES users(id)',
            'title': "VARCHAR(180) NOT NULL DEFAULT ''",
            'calendar_exception': "VARCHAR(300) NOT NULL DEFAULT ''",
            'change_action': "VARCHAR(20) NOT NULL DEFAULT ''",
            'previous': 'JSON',
            'previous_day': 'DATE',
        },
    }
    for table, fields in additions.items():
        columns = {column['name'] for column in inspect(connection).get_columns(table)}
        for name, kind in fields.items():
            if name not in columns:
                connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
    for index in ScheduledClass.__table__.indexes:
        index.create(connection, checkfirst=True)
    events = ScheduledClass.__table__
    audit = OperationEvent.__table__
    for payload in connection.scalars(select(audit.c.after).where(audit.c.area == 'schedule', audit.c.action == 'publish')
                                      .order_by(audit.c.id)):
        log = json.loads(payload)
        effects = log.get('effects') or {}
        previous = effects.get('previous')
        for published in effects.get('published', ()):
            # Later rows or non-workflow edits must keep their newer version.
            connection.execute(events.update().where(events.c.id == published['id'], events.c.version == published['version'])
                               .values(previous=previous, previous_day=date.fromisoformat(previous['day']) if previous else None,
                                       change_action=log['action']))
    rooms = Classroom.__table__
    if connection.scalar(select(rooms.c.id).where(func.lower(rooms.c.code) == 'онлайн').limit(1)) is None:
        connection.execute(rooms.insert().values(code='Онлайн', building='Дистанционный формат', capacity=500,
                                                  kind='online', equipment='', accessible=True, available=True, version=1))


def seed_published_demo_window(db):
    # README's release note records this November demonstration interval. It is
    # only an existing weekly template window, without inferred term limits.
    groups = db.scalars(select(GroupMember.group_id).join(User).where(
        User.login.in_(['alina.demo', 'mark.demo']), User.role == 'student')).all()
    for group_id in set(groups):
        if db.scalar(select(AcademicDayRule.id).where(AcademicDayRule.group_id == group_id,
                                                      AcademicDayRule.kind == 'legacy')) is None:
            db.add(AcademicDayRule(group_id=group_id, starts_on=DEMO_WINDOW[0], ends_on=DEMO_WINDOW[1],
                                   kind='legacy', source='Демонстрационный календарь ATLAS 3.2 от 9 ноября 2026'))
