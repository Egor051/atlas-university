"""Official marks are the latest results published for a submitted work."""
from sqlalchemy import select

from .workspace_db import WorkFeedback


GRADE_ACTIONS = ('accept', 'grade', 'correct_score')


def score_from_history(feedback):
    return next((note['score'] for note in feedback
                 if note['action'] in GRADE_ACTIONS and note['score'] is not None), None)


def official_score_query(submission_id):
    return (select(WorkFeedback.score).where(WorkFeedback.submission_id == submission_id,
            WorkFeedback.action.in_(GRADE_ACTIONS), WorkFeedback.score.is_not(None))
            .order_by(WorkFeedback.id.desc()).limit(1))
