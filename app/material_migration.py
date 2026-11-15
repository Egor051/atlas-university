"""Preserve publication identities and link unambiguous legacy student courses."""
from sqlalchemy import func, inspect, select, update

from .learning_db import Course
from .university_db import Discipline


def discipline_matches(title):
    return (select(func.min(Discipline.id)).where(Discipline.title == title)
            .having(func.count(Discipline.id) == 1))


def upgrade_materials(connection):
    byte_type = 'BYTEA' if connection.dialect.name == 'postgresql' else 'BLOB'
    changes = {
        'teaching_materials': {
            'access': "VARCHAR(12) NOT NULL DEFAULT 'campus'",
            'external_url': "VARCHAR(1000) NOT NULL DEFAULT ''",
            'file_name': 'VARCHAR(180)', 'file_size': 'INTEGER',
            'file_digest': 'VARCHAR(64)', 'file_content': byte_type,
        },
        'learning_courses': {'discipline_id': 'INTEGER REFERENCES university_disciplines(id)'},
        'campus_announcements': {'discipline_id': 'INTEGER REFERENCES university_disciplines(id)'},
    }
    for table, columns in changes.items():
        existing = {column['name'] for column in inspect(connection).get_columns(table)}
        for name, sql_type in columns.items():
            if name not in existing:
                connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {sql_type}')

    connection.execute(update(Course).where(Course.discipline_id.is_(None))
                       .values(discipline_id=discipline_matches(Course.subject).scalar_subquery()))
