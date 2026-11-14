"""Upgrade release 3.6 data in disposable SQLite and PostgreSQL databases."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.exc import OperationalError

from improvement_runtime import ROOT


SEED_OLD = '''
from sqlalchemy import select
from app.db import Deadline, SessionLocal, initialize_database, utc_now
from app.learning_db import AssignmentSubmission, StudyNote
from app.workspace_db import WorkDelivery, WorkFeedback

initialize_database()
with SessionLocal.begin() as db:
    deadline = db.scalar(select(Deadline).join(WorkDelivery).order_by(Deadline.id).limit(1))
    now = utc_now()
    row = AssignmentSubmission(student_id=deadline.student_id, deadline_id=deadline.id,
          text='Сохранённое решение', url='https://example.invalid/work', status='withdrawn',
          version=3, submitted_at=now, updated_at=now)
    db.add(row)
    db.flush()
    db.add(WorkFeedback(submission_id=row.id, submitted_version=2, author_id=3,
                        score=5, comment='Сохранённое замечание', created_at=now))
    db.add(StudyNote(student_id=row.student_id, title='Сохранённый конспект',
                     subject=deadline.subject, body='Сохранённый текст', created_at=now, updated_at=now))
'''


@contextmanager
def database(kind, folder):
    if kind == 'sqlite':
        yield f"sqlite:///{(folder / 'legacy.sqlite3').as_posix()}"
        return
    password = secrets.token_hex(20)
    name = 'atlas-release-migration-' + secrets.token_hex(6)
    env = {**os.environ, 'POSTGRES_PASSWORD': password}
    subprocess.run([
        'docker', 'run', '--detach', '--rm', '--name', name, '--publish', '127.0.0.1::5432',
        '--env', 'POSTGRES_PASSWORD', 'postgres:17-alpine',
    ], env=env, check=True, capture_output=True, timeout=180)
    try:
        address = subprocess.check_output(['docker', 'port', name, '5432/tcp'], text=True, timeout=10).strip()
        url = f'postgresql+psycopg://postgres:{password}@{address}/postgres'
        engine = create_engine(url)
        try:
            for _ in range(60):
                try:
                    with engine.connect() as connection:
                        assert connection.scalar(select(1)) == 1
                    break
                except OperationalError:
                    time.sleep(1)
            else:
                raise RuntimeError('Disposable PostgreSQL did not become ready')
        finally:
            engine.dispose()
        yield url
    finally:
        subprocess.run(['docker', 'stop', name], check=True, capture_output=True, timeout=30)


def execute_source(root, url, *command):
    env = {
        **os.environ, 'DATABASE_URL': url, 'APP_ENV': 'test', 'DEMO_MODE': 'true',
        'COOKIE_SECURE': 'false', 'PYTHONIOENCODING': 'utf-8',
    }
    result = subprocess.run([sys.executable, *command], cwd=root, env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.replace(url, '[database]'))


def snapshot(engine, columns=None):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    columns = columns or {table: list(data.columns.keys()) for table, data in metadata.tables.items()}
    entries = {}
    with engine.connect() as connection:
        for table, names in columns.items():
            selected = metadata.tables[table]
            rows = connection.execute(select(*(selected.c[name] for name in names)))
            encoded = sorted(json.dumps(tuple(row), ensure_ascii=False, default=str) for row in rows)
            entries[table] = {'rows': len(encoded), 'sha256': hashlib.sha256(
                '\n'.join(encoded).encode()).hexdigest()}
    return columns, entries


def verify(engine, source, url):
    execute_source(source, url, '-c', SEED_OLD)
    columns, before = snapshot(engine)
    columns.pop('schema_migrations')
    copy_columns = {
        'campus_announcements': {'title', 'body'}, 'campus_events': {'description', 'location'},
        'center_programs': {'description', 'requirements'}, 'center_sessions': {'room'},
        'document_requests': {'staff_message'}, 'finance_entries': {'description'},
        'learning_attendance': {'note'}, 'learning_course_modules': {'content'},
        'request_events': {'message'}, 'teaching_materials': {'body', 'description'},
        'unit_publications': {'title', 'body'}, 'university_faculties': {'description'},
    }
    stable = {name: [key for key in keys if key not in copy_columns.get(name, ())]
              for name, keys in columns.items()}
    _, stable_before = snapshot(engine, stable)
    execute_source(ROOT, url, '-m', 'app.db', 'migrate')
    _, projected = snapshot(engine, columns)
    changed = {name for name, value in projected.items() if before[name] != value}
    assert all(projected[name]['rows'] == before[name]['rows'] for name in projected), changed
    assert changed <= copy_columns.keys(), changed - copy_columns.keys()
    assert snapshot(engine, stable)[1] == stable_before, 'Original business fields changed during migration'
    after = snapshot(engine)[1]
    metadata = MetaData()
    metadata.reflect(bind=engine)
    attempts = metadata.tables['assignment_attempts']
    ledger = metadata.tables['academic_point_awards']
    revisions = metadata.tables['schema_migrations']
    with engine.connect() as connection:
        attempt, = connection.execute(select(attempts.c.version, attempts.c.text, attempts.c.url)).all()
        assert tuple(attempt) == (2, 'Сохранённое решение', 'https://example.invalid/work')
        awards = dict(connection.execute(select(ledger.c.grade_id, ledger.c.points)
                      .where(ledger.c.source_kind == 'opening')).all())
        grades = metadata.tables['grades']
        balances = dict(connection.execute(select(grades.c.id, grades.c.current)
                        .where(grades.c.current > 0)).all())
        assert awards and awards == balances
        versions = sorted(connection.scalars(select(revisions.c.version)))
        assert {'0013_academic_points', '0014_assignment_workflow',
                '0015_announcement_summaries', '0016_trim_bundled_copy'} <= set(versions)
    execute_source(ROOT, url, '-m', 'app.db', 'migrate')
    assert snapshot(engine)[1] == after, 'A second migration changed data'
    return {'prior_tables': len(before), 'prior_rows': sum(row['rows'] for row in before.values()),
            'updated_original_text_tables': sorted(changed), 'opening_awards': len(awards),
            'preserved_attempt_version': attempt.version, 'revisions': versions, 'repeat_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-source', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    source = args.legacy_source.resolve()
    if source == ROOT or not (source / 'app/db.py').is_file():
        parser.error('--legacy-source must point to the old application checkout')
    report = {}
    with TemporaryDirectory(prefix='atlas-release-migration-') as directory:
        for kind in ('sqlite', 'postgresql'):
            with database(kind, Path(directory)) as url:
                engine = create_engine(url)
                try:
                    report[kind] = verify(engine, source, url)
                    print(f'{kind}: {report[kind]["prior_tables"]} prior tables verified.', flush=True)
                finally:
                    engine.dispose()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
