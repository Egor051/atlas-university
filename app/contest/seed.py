"""Provision one synthetic semester without modifying an in-use database."""
import json
import os
from datetime import date
from hashlib import sha256

from sqlalchemy import func, inspect, select, text

from ..academic_points import AssignmentPointCorrection, ManualPointCorrection, PointAward
from ..config import settings
from ..db import (DATABASE_URL, Base, ContestDataset, Grade, Notification, SessionLocal, User,
                  database_setup, migrate_database, seed_demo_accounts, utc_now)
from ..schedule_occurrences import campus_instant
from ..session_security import as_utc
from ..units_seed import seed_unit_accounts
from ..university_seed import seed_university
from ..workspace_db import OperationEvent
from ..workspace_seed import seed_workspace_accounts


NAME = 'autumn-2026'
START = date(2026, 9, 1)
FIRST_REVIEW = date(2026, 11, 23)
LAST_REVIEW = date(2026, 11, 28)
HISTORY_THROUGH = campus_instant(date(2026, 11, 22), '12:00')


class DatasetError(RuntimeError):
    pass


def autumn(month, day, clock='12:00'):
    return campus_instant(date(2026, month, day), clock)


def token(*parts):
    return sha256(':'.join(map(str, (NAME, *parts))).encode()).hexdigest()


def json_data(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Semester:
    def __init__(self, db):
        self.db = db

    def add(self, model, **fields):
        row = model(**fields)
        self.db.add(row)
        self.db.flush()
        return row

    def notify(self, user, title, body, category, target, at, *, key, read=False, request_id=None):
        return self.add(Notification, student_id=user.id, title=title, body=body, category=category,
                        target=target, created_at=at, event_key=key, is_read=read, request_id=request_id)

    def event(self, actor, area, object_id, action, at, *, before=None, after=None):
        self.db.add(OperationEvent(actor_id=actor.id, area=area, object_id=object_id, action=action,
                                   before=json_data(before), after=json_data(after), created_at=at))


def verify_ledger(db):
    awards = {row.id: row for row in db.scalars(select(PointAward))}
    expected = {}
    for row in awards.values():
        if row.source_kind not in {'teacher', 'assignment'} or not row.created_at or not row.actor_id:
            raise DatasetError('A point award has no accountable activity.')
        expected[row.grade_id] = expected.get(row.grade_id, 0) + row.points
    for row in db.scalars(select(ManualPointCorrection)):
        grade_id = awards[row.award_id].grade_id
        expected[grade_id] += row.corrected_points - row.previous_points
    for row in db.scalars(select(AssignmentPointCorrection)):
        expected[row.grade_id] += row.corrected_points - row.previous_points
    for grade in db.scalars(select(Grade)):
        if grade.current != expected.get(grade.id, 0):
            raise DatasetError(f'Grade {grade.id} disagrees with its point history.')


def report(db, marker, status):
    rows = {table.name: db.scalar(select(func.count()).select_from(table))
            for table in sorted(Base.metadata.tables.values(), key=lambda table: table.name)}
    return dict(dataset=marker.name, status=status, history_from=START.isoformat(),
                history_through=as_utc(marker.history_through).isoformat(),
                initialized_at=as_utc(marker.initialized_at).isoformat(), rows=rows)


def install():
    if 'DATABASE_URL' not in os.environ or not settings.demo_mode:
        raise DatasetError('Set DATABASE_URL to a fresh database and set DEMO_MODE=true.')
    settings.validate(DATABASE_URL)
    if utc_now() < HISTORY_THROUGH:
        raise DatasetError('This snapshot contains history through 22 November 2026, 12:00 Moscow time.')

    with database_setup(2026110601) as connection:
        tables = set(inspect(connection).get_table_names())
        if tables:
            if ContestDataset.__tablename__ in tables:
                with SessionLocal(bind=connection) as db:
                    marker = db.get(ContestDataset, NAME)
                    if marker and as_utc(marker.history_through) == HISTORY_THROUGH:
                        return report(db, marker, 'already_initialized')
            raise DatasetError('Database already has tables. Provision a separate empty database.')

        if connection.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(2026110602)'))
        migrate_database(connection)

        from .academics import seed_academics
        from .campus import seed_campus
        from .units import seed_units

        with SessionLocal(bind=connection) as db:
            semester = Semester(db)
            students, office = seed_demo_accounts(db)
            seed_university(db, directory_only=True)
            seed_workspace_accounts(db)
            seed_unit_accounts(db)
            accounts = {row.login: row for row in db.scalars(select(User).order_by(User.id))}
            cohorts = seed_academics(semester, students, accounts)
            seed_campus(semester, cohorts, students, office)
            seed_units(semester, students, accounts)
            db.flush()
            verify_ledger(db)
            if connection.dialect.name == 'sqlite' and connection.exec_driver_sql('PRAGMA foreign_key_check').first():
                raise DatasetError('The dataset has invalid foreign keys.')
            marker = semester.add(ContestDataset, name=NAME, history_through=HISTORY_THROUGH, initialized_at=utc_now())
            return report(db, marker, 'initialized')
