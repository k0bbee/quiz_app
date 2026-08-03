"""Pure selection rules for retrying parts of a completed quiz session."""

from __future__ import annotations

def session_retry_question_ids(record) -> tuple[str, ...]:
    """Return stable, de-duplicated IDs for the wrong-answer review queue."""
    candidates = (
        answer.question_id
        for answer in getattr(record, "answers", ()) or ()
        if not getattr(answer, "skipped", False)
        and not getattr(answer, "is_correct", False)
    )

    normalized = (str(item or "").strip() for item in candidates)
    return tuple(dict.fromkeys(item for item in normalized if item))
