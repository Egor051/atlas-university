"""Additive 0006 migration: preserve ids/data and bind mutable record identity."""
import json
from sqlalchemy import inspect, select, update, text
from sqlalchemy.orm import Session
from .storage_guards import new_record_token


def upgrade_integrity(connection):
    from .learning_db import StudyNote, PersonalTask, Flashcard, FocusSession
    from .campus_db import PortfolioItem
    from .services_db import ServiceIdempotency
    from .receipt_codec import encode_receipt, MARKER
    models = {'note': StudyNote, 'task': PersonalTask, 'flashcard': Flashcard,
              'focus': FocusSession, 'portfolio': PortfolioItem}
    for model in models.values():
        table = model.__table__
        columns = {column['name'] for column in inspect(connection).get_columns(table.name)}
        if 'record_token' not in columns:
            connection.exec_driver_sql(f"ALTER TABLE {table.name} ADD COLUMN record_token VARCHAR(32) DEFAULT ''")
        missing = connection.execute(select(table.c.id).where((table.c.record_token.is_(None)) | (table.c.record_token == ''))).scalars().all()
        for row_id in missing:
            connection.execute(update(table).where(table.c.id == row_id).values(record_token=new_record_token()))
        for index in table.indexes:
            index.create(connection, checkfirst=True)
        if connection.dialect.name == 'sqlite':
            connection.exec_driver_sql(f'''CREATE TRIGGER IF NOT EXISTS atlas_identity_{table.name}
                AFTER INSERT ON {table.name}
                WHEN NEW.record_token IS NULL OR NEW.record_token = ''
                BEGIN UPDATE {table.name} SET record_token=lower(hex(randomblob(16))) WHERE id=NEW.id; END''')
        elif connection.dialect.name == 'postgresql':
            connection.exec_driver_sql(f"ALTER TABLE {table.name} ALTER COLUMN record_token SET DEFAULT replace(gen_random_uuid()::text,'-','')")
    with Session(bind=connection) as db:
        from .db import DocumentRequest, CAMPUS_TZ, as_utc, request_due_date
        for row in db.scalars(select(DocumentRequest)):
            instant=as_utc(row.created_at)
            old_due=request_due_date(row.type,instant.date())
            correct_due=request_due_date(row.type,instant.astimezone(CAMPUS_TZ).date())
            if row.due_at==old_due and old_due!=correct_due:
                row.due_at=correct_due
        # Old names contain only an integer, which SQLite may already have
        # reused before this upgrade. Even the same owner/id cannot establish
        # that a draft belongs to the surviving logical record. Preserve every
        # old draft verbatim for explicit owner-only export/recovery; only new
        # token-bound names may be restored automatically by the client.
        db.flush()
        for receipt in db.scalars(select(ServiceIdempotency).execution_options(yield_per=20)):
            try:
                payload = json.loads(receipt.response_json)
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict) and MARKER not in payload:
                encoded = encode_receipt(db, payload, verify_legacy=True)
                if encoded is not payload:
                    receipt.response_json = json.dumps(encoded, ensure_ascii=False, sort_keys=True, default=str)
        db.flush()
