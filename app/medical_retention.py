"""Expire private documents while keeping attendance decisions auditable."""
import asyncio
from contextlib import suppress
import logging

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from .absence_certificate_db import (AbsenceCertificate as Certificate, AbsenceCertificateAudit as Audit,
                                     AbsenceCertificateFile as File, AbsenceCertificateNote as Note,
                                     AbsenceCertificateReview as Review)
from .db import SessionLocal, utc_now


def purge_private_evidence():
    now = utc_now()
    file_present = select(File.certificate_id).where(File.certificate_id == Certificate.id).exists()
    note_present = select(Note.certificate_id).where(Note.certificate_id == Certificate.id).exists()
    pending = select(Review.id).where(Review.certificate_id == Certificate.id, Review.status == 'pending').exists()
    expired = (Certificate.expires_at <= now) & or_(file_present, note_present)
    stale = pending & or_(Certificate.expires_at <= now, ~file_present)
    stmt = select(Certificate.id).where(or_(expired, stale)).order_by(Certificate.id).limit(100)
    with SessionLocal.begin() as db:
        ids = list(db.scalars(stmt))
        if not ids:
            return 0
        from .workspace import lock_workspace

        # Use the journal lock around deletion, decisions and audited downloads.
        lock_workspace(db, 0)
        ids = list(db.scalars(stmt))
        db.execute(delete(File).where(File.certificate_id.in_(ids)))
        db.execute(delete(Note).where(Note.certificate_id.in_(ids)))
        db.execute(update(Review).where(Review.certificate_id.in_(ids), Review.status == 'pending')
                   .values(status='rejected', reviewed_at=now, expired=True))
        db.add_all(Audit(certificate_id=cert_id, action='purge_private_data', created_at=now) for cert_id in ids)
        return len(ids)


async def retention_loop():
    while True:
        try:
            while await asyncio.to_thread(purge_private_evidence) == 100:
                await asyncio.sleep(0)
        except SQLAlchemyError:
            logging.getLogger(__name__).error('Could not purge private attendance evidence; will retry')
        await asyncio.sleep(3600)


async def stop_retention(task):
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
