"""Helpers for replacing a question set with regenerated questions."""

from __future__ import annotations

from datetime import datetime, timezone

from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, topic_value


def apply_regenerated_questions(
    question_set: QuestionSet,
    questions: list[Question],
    difficulty: Difficulty | None = None,
    course_project=None,
) -> QuestionSet:
    """Replace a question set's question references with regenerated questions."""
    now = datetime.now(timezone.utc).isoformat()
    question_set.questions = [q.question_id for q in questions]
    question_set.topics = sorted({topic_value(q.topic) for q in questions})
    if difficulty is not None:
        question_set.difficulty = difficulty
    question_set.estimated_minutes = max(4, len(questions) * 2)
    question_set.metadata["updated_at"] = now
    question_set.metadata["regenerated_at"] = now
    question_set.metadata["source"] = "ai_regenerated"
    if course_project is not None:
        question_set.metadata["course_id"] = getattr(course_project, "course_id", "")
        question_set.metadata["course_title"] = getattr(course_project, "title", "")
        question_set.metadata["course_updated_at"] = getattr(course_project, "updated_at", "")
    return question_set
