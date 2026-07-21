"""Pure selection rules for retrying parts of a completed quiz session."""

from __future__ import annotations

from enum import Enum


class SessionRetryMode(str, Enum):
    INCORRECT = "incorrect"
    UNSURE = "unsure"
    REVIEW = "review"


def session_retry_question_ids(record, mode: SessionRetryMode) -> tuple[str, ...]:
    """Return stable, de-duplicated question IDs for one retry mode."""
    if mode == SessionRetryMode.INCORRECT:
        candidates = (
            answer.question_id
            for answer in getattr(record, "answers", ()) or ()
            if not getattr(answer, "skipped", False)
            and not getattr(answer, "is_correct", False)
        )
    elif mode == SessionRetryMode.UNSURE:
        candidates = (
            answer.question_id
            for answer in getattr(record, "answers", ()) or ()
            if not getattr(answer, "skipped", False)
            and getattr(answer, "confidence", "sure") == "unsure"
        )
    elif mode == SessionRetryMode.REVIEW:
        candidates = iter(
            getattr(record, "marked_review_question_ids", ()) or ()
        )
    else:
        raise ValueError(f"Unsupported session retry mode: {mode}")

    normalized = (str(item or "").strip() for item in candidates)
    return tuple(dict.fromkeys(item for item in normalized if item))
