"""Upgrade the existing task/submission graph without replacing its records."""
from sqlalchemy import inspect


def upgrade_assignment_workflow(connection):
    timestamp = 'TIMESTAMP WITH TIME ZONE' if connection.dialect.name == 'postgresql' else 'DATETIME'
    for table, fields in (
        ('academic_group_work', (
            ('state', "VARCHAR(20) NOT NULL DEFAULT 'published'"),
            ('policy_json', "TEXT NOT NULL DEFAULT '{}'"),
            ('publish_at', timestamp),
            ('due_at', timestamp),
        )),
        ('academic_work_deliveries', (
            ('extended_until', timestamp), ('active', 'BOOLEAN NOT NULL DEFAULT TRUE'),
        )),
        ('academic_work_feedback', (
            ('action', "VARCHAR(20) NOT NULL DEFAULT 'comment'"), ('extended_until', timestamp),
        )),
        ('learning_submissions', (('attempt_version', 'INTEGER NOT NULL DEFAULT 1'),)),
    ):
        existing = {column['name'] for column in inspect(connection).get_columns(table)}
        for name, kind in fields:
            if name not in existing:
                connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
    # A legacy withdrawal advanced the record revision without writing new
    # content. Older overwritten content is unavailable and is not fabricated.
    connection.exec_driver_sql("""
        UPDATE learning_submissions SET attempt_version =
        CASE WHEN status = 'withdrawn' AND version > 1 THEN version - 1 ELSE version END
        WHERE status != 'in_progress'
        AND NOT EXISTS (
            SELECT 1 FROM assignment_attempts a WHERE a.submission_id = learning_submissions.id
        )
    """)
    connection.exec_driver_sql("""
        INSERT INTO assignment_attempts
        (submission_id, actor_id, version, number, text, url, completed, late, submitted_at)
        SELECT s.id, s.student_id, s.attempt_version, 1, s.text, s.url, FALSE, FALSE, s.submitted_at
        FROM learning_submissions s
        WHERE s.attempt_version > 0
        AND NOT EXISTS (SELECT 1 FROM assignment_attempts a WHERE a.submission_id = s.id)
    """)
