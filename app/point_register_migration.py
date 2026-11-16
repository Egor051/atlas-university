"""Preserve original ledger rows while adding metadata for new awards."""
from sqlalchemy import inspect


def upgrade_point_register(connection):
    columns = {column['name'] for column in inspect(connection).get_columns('academic_point_awards')}
    for name, definition in (
        ('title', "VARCHAR(180) NOT NULL DEFAULT ''"),
        ('kind', "VARCHAR(20) NOT NULL DEFAULT ''"),
        ('custom_kind', "VARCHAR(80) NOT NULL DEFAULT ''"),
        ('max_points', 'INTEGER'),
        ('review_id', 'INTEGER REFERENCES academic_work_feedback(id)'),
    ):
        if name not in columns:
            connection.exec_driver_sql(f'ALTER TABLE academic_point_awards ADD COLUMN {name} {definition}')
