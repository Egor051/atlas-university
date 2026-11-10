"""Shared session comparisons and bounded password-verification admission."""
from datetime import datetime, timezone
import re
import threading

from fastapi import HTTPException
from sqlalchemy import text


def as_utc(value: datetime) -> datetime:
    """SQLite's naive timestamps are UTC; preserve real offsets from PostgreSQL."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def validate_expected_actor(expected: str | None, user_id: int) -> None:
    """An optional client affinity check never selects or grants an owner."""
    if expected is None:
        return
    if not re.fullmatch(r'[1-9][0-9]{0,18}', expected):
        raise HTTPException(422, 'Недопустимый контекст учётной записи')
    if int(expected) != user_id:
        raise HTTPException(409, {'code': 'account_changed',
                                 'message': 'Учётная запись изменилась. Войдите снова перед продолжением.'})


_local_verifications = threading.BoundedSemaphore(2)


class PasswordAdmission:
    """Bound KDF memory across PostgreSQL workers, and locally for SQLite.

    PostgreSQL transaction locks are released automatically on every commit,
    rollback, exception or disconnected worker. They do not need lease cleanup.
    """
    def __init__(self, db, dialect: str, slots: int = 2):
        self.db = db
        self.dialect = dialect
        self.slots = slots
        self.local = False

    def __enter__(self):
        if self.dialect == 'postgresql':
            for slot in range(self.slots):
                if self.db.scalar(text('SELECT pg_try_advisory_xact_lock(:namespace, :slot)'),
                                  {'namespace': 2026111001, 'slot': slot}):
                    return self
        elif _local_verifications.acquire(blocking=False):
            self.local = True
            return self
        raise HTTPException(429, 'Сейчас выполняется много входов. Повторите через секунду.',
                            headers={'Retry-After': '1'})

    def __exit__(self, *_):
        if self.local:
            _local_verifications.release()
