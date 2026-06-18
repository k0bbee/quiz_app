"""Maintenance helpers that keep question-bank edits consistent."""

from __future__ import annotations

from datetime import datetime, timezone

from models.question_set import SetManager


def remove_question_from_sets(set_manager: SetManager, question_id: str) -> int:
    """Remove a deleted question id from every persisted question set."""
    changed = 0
    now = datetime.now(timezone.utc).isoformat()
    for qset in set_manager.load_all():
        if question_id not in qset.questions:
            continue
        qset.questions = [qid for qid in qset.questions if qid != question_id]
        qset.estimated_minutes = max(0, len(qset.questions) * 2)
        qset.metadata["updated_at"] = now
        qset.metadata["removed_question_id"] = question_id
        qset.metadata["source"] = "question_deleted"
        set_manager.save(qset)
        changed += 1
    return changed
