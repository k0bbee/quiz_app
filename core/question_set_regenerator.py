"""Helpers for replacing a question set with regenerated questions."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, topic_value
from core.question_bank_maintenance import delete_unreferenced_ai_questions


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


def persist_regenerated_question_set(
    question_bank,
    set_manager,
    progress_manager,
    question_set: QuestionSet,
    questions: list[Question],
    difficulty: Difficulty | None = None,
    course_project=None,
) -> tuple[QuestionSet, int, list[str]]:
    """Persist a complete regeneration, rolling back incomplete new-question saves."""
    if not questions:
        raise RuntimeError("Regeneration produced no questions to save.")

    collisions = [q.question_id for q in questions if question_bank.get(q.question_id) is not None]
    if collisions:
        raise RuntimeError(
            "Regeneration produced question ID collision(s): " + ", ".join(collisions)
        )

    saved_ids = []
    for question in questions:
        if not question_bank.save(question):
            for question_id in saved_ids:
                question_bank.delete(question_id)
            raise RuntimeError(
                f"Only {len(saved_ids)} of {len(questions)} regenerated questions could be saved; "
                "the new batch was rolled back."
            )
        saved_ids.append(question.question_id)

    old_ids = list(question_set.questions)
    updated = copy.deepcopy(question_set)
    apply_regenerated_questions(
        updated,
        questions,
        difficulty=difficulty,
        course_project=course_project,
    )
    if not set_manager.save(updated):
        for question_id in saved_ids:
            question_bank.delete(question_id)
        raise RuntimeError(
            "The regenerated question set could not be saved; the new batch was rolled back."
        )

    obsolete_ids = [question_id for question_id in old_ids if question_id not in updated.questions]
    deleted = delete_unreferenced_ai_questions(
        question_bank,
        set_manager,
        obsolete_ids,
        progress_manager=progress_manager,
    )
    return updated, len(saved_ids), deleted
