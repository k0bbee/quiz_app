"""Typed intent passed through the user-facing study workflow."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class StudyAction(str, Enum):
    """Supported reasons for entering the study workflow."""

    RESUME_SESSION = "resume_session"
    DAILY_QUEUE = "daily_queue"
    REVIEW_QUESTIONS = "review_questions"
    PRACTICE_TOPIC = "practice_topic"
    CUSTOM_PRACTICE = "custom_practice"
    GENERATE_MISSING = "generate_missing"
    IMPORT_COURSE = "import_course"


@dataclass(frozen=True)
class StudyIntent:
    """Immutable course, scope, and quantity context for one study request."""

    course_id: str
    action: StudyAction
    topic_ids: tuple[str, ...] = ()
    question_ids: tuple[str, ...] = ()
    remaining_question_ids: tuple[str, ...] = ()
    question_count: int = 10
    source: str = "manual"
    plan_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "course_id", str(self.course_id or "").strip())
        object.__setattr__(self, "action", StudyAction(self.action))
        object.__setattr__(self, "topic_ids", _normalized_ids(self.topic_ids))
        object.__setattr__(
            self,
            "question_ids",
            _normalized_ids(self.question_ids),
        )
        object.__setattr__(
            self,
            "remaining_question_ids",
            _normalized_ids(self.remaining_question_ids),
        )
        object.__setattr__(
            self,
            "question_count",
            max(0, int(self.question_count or 0)),
        )
        object.__setattr__(
            self,
            "source",
            str(self.source or "manual").strip() or "manual",
        )
        object.__setattr__(
            self,
            "plan_id",
            str(self.plan_id or "").strip(),
        )


def continue_daily_queue_intent(
    intent: StudyIntent,
    *,
    session_size: int = 10,
) -> StudyIntent | None:
    """Advance one daily queue without repeating the completed question IDs."""
    if not isinstance(intent, StudyIntent) or intent.action is not StudyAction.DAILY_QUEUE:
        return None
    remaining = intent.remaining_question_ids
    if not remaining:
        return None
    size = max(1, int(session_size or 1))
    current = remaining[:size]
    following = remaining[size:]
    return StudyIntent(
        course_id=intent.course_id,
        action=StudyAction.DAILY_QUEUE,
        topic_ids=intent.topic_ids,
        question_ids=current,
        remaining_question_ids=following,
        question_count=len(current),
        source=intent.source,
        plan_id=intent.plan_id,
    )


def _normalized_ids(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        text
        for value in (values or ())
        if (text := str(value or "").strip())
    ))
