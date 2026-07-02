"""Maintenance helpers that keep question-bank edits consistent."""

from __future__ import annotations

from datetime import datetime, timezone

from core.course_index import enrich_course_source_refs
from models.question_set import SetManager


def backfill_source_refs_from_course(question_bank, course_project) -> int:
    """Enrich stored question source_refs from a course project's source index."""
    course_id = str(getattr(course_project, "course_id", "") or "").strip()
    changed = 0
    for question in question_bank.load_all():
        metadata = dict(question.metadata or {})
        question_course_id = str(metadata.get("course_id", "") or "").strip()
        if question_course_id and course_id and question_course_id != course_id:
            continue
        source_refs = metadata.get("source_refs", [])
        enriched = enrich_course_source_refs(course_project, source_refs)
        if enriched == source_refs:
            continue
        metadata["source_refs"] = enriched
        question.metadata = metadata
        if question_bank.save(question):
            changed += 1
    return changed


def remove_question_from_sets(set_manager: SetManager, question_id: str, delete_empty: bool = False) -> int:
    """Remove a deleted question id from every persisted question set.

    When ``delete_empty`` is true, sets whose last question was removed are
    deleted instead of being kept as unusable empty shells.
    """
    changed = 0
    now = datetime.now(timezone.utc).isoformat()
    for qset in set_manager.load_all():
        if question_id not in qset.questions:
            continue
        qset.questions = [qid for qid in qset.questions if qid != question_id]
        if delete_empty and not qset.questions:
            set_manager.delete(qset.set_id)
            changed += 1
            continue
        qset.estimated_minutes = max(0, len(qset.questions) * 2)
        qset.metadata["updated_at"] = now
        qset.metadata["removed_question_id"] = question_id
        qset.metadata["source"] = "question_deleted"
        set_manager.save(qset)
        changed += 1
    return changed


def delete_unreferenced_ai_questions(
    question_bank,
    set_manager: SetManager,
    candidate_ids: list[str],
    progress_manager=None,
) -> list[str]:
    """Delete obsolete AI questions only when no live data still references them."""
    referenced = {
        question_id
        for question_set in set_manager.load_all()
        for question_id in question_set.questions
    }
    historical = set()
    if progress_manager is not None:
        for record in progress_manager.load_all():
            historical.update(answer.question_id for answer in record.answers)

    deleted = []
    for question_id in dict.fromkeys(candidate_ids):
        if question_id in referenced or question_id in historical:
            continue
        question = question_bank.get(question_id)
        if question is None:
            continue
        source = str((question.metadata or {}).get("source", ""))
        if source not in {"ai_generated", "ai_regenerated"}:
            continue
        if question_bank.delete(question_id):
            deleted.append(question_id)
    return deleted
