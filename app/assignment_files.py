"""Source and review files scoped to their assignment or submitted version."""
from collections import defaultdict
from urllib.parse import quote

from fastapi import HTTPException, Response
from sqlalchemy import delete, select

from .assignment_db import WorkFeedbackFile, WorkSourceFile
from .workspace_db import WorkFeedback


def file_metadata(row):
    return dict(id=row.id, name=row.name, size=row.size)


def source_files(db, work_id):
    rows = db.execute(select(WorkSourceFile.id, WorkSourceFile.name, WorkSourceFile.size)
                      .where(WorkSourceFile.work_id == work_id).order_by(WorkSourceFile.id))
    return [file_metadata(row) for row in rows]


def replace_source_files(db, work_id, uploads, remove_ids, *, max_bytes):
    existing = source_files(db, work_id)
    to_remove = set(remove_ids)
    if not to_remove.issubset({file['id'] for file in existing}):
        raise HTTPException(404, 'Исходный файл не найден в задании')
    kept = [file for file in existing if file['id'] not in to_remove]
    if len(kept) + len(uploads) > 3:
        raise HTTPException(422, 'В задании можно оставить не более трёх исходных файлов')
    if sum(file['size'] for file in kept) + sum(len(content) for _, content in uploads) > max_bytes:
        raise HTTPException(422, 'Общий размер исходных файлов задания превышает 1 МиБ')
    if to_remove:
        db.execute(delete(WorkSourceFile).where(WorkSourceFile.work_id == work_id, WorkSourceFile.id.in_(to_remove)))
    files = [WorkSourceFile(work_id=work_id, name=name, size=len(content), content=content)
             for name, content in uploads]
    db.add_all(files)
    db.flush()
    return kept + [file_metadata(file) for file in files]


def feedback_files(db, submission_id):
    rows = db.execute(select(WorkFeedbackFile.id, WorkFeedbackFile.feedback_id, WorkFeedbackFile.name, WorkFeedbackFile.size)
                      .join(WorkFeedback).where(WorkFeedback.submission_id == submission_id).order_by(WorkFeedbackFile.id))
    by_review = defaultdict(list)
    for row in rows:
        by_review[row.feedback_id].append(file_metadata(row))
    return by_review


def save_feedback_files(db, feedback_id, uploads):
    if not uploads:
        return []
    files = [WorkFeedbackFile(feedback_id=feedback_id, name=name, size=len(content), content=content)
             for name, content in uploads]
    db.add_all(files)
    db.flush()
    return [file_metadata(file) for file in files]


def download_file(row):
    if row is None:
        raise HTTPException(404, 'Вложение не найдено')
    return Response(row.content, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row.name, safe=''),
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
    })


def download_source_file(db, work_id, file_id):
    return download_file(db.scalar(select(WorkSourceFile).where(WorkSourceFile.work_id == work_id,
                                                                 WorkSourceFile.id == file_id)))


def download_feedback_file(db, submission_id, file_id):
    return download_file(db.scalar(select(WorkFeedbackFile).join(WorkFeedback).where(
        WorkFeedback.submission_id == submission_id, WorkFeedbackFile.id == file_id)))
