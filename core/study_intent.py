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
    set_id: str = ""
    topic_ids: tuple[str, ...] = ()
    question_ids: tuple[str, ...] = ()
    remaining_question_ids: tuple[str, ...] = ()
    question_count: int = 10
    submission_mode: str = "practice"
    source: str = "manual"
    plan_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "course_id", str(self.course_id or "").strip())
        object.__setattr__(self, "action", StudyAction(self.action))
        object.__setattr__(self, "set_id", str(self.set_id or "").strip())
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
        submission_mode = str(self.submission_mode or "").strip().lower()
        object.__setattr__(
            self,
            "submission_mode",
            submission_mode if submission_mode in {"practice", "exam"} else "practice",
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

    def to_dict(self) -> dict[str, object]:
        return {
            "course_id": self.course_id,
            "action": self.action.value,
            "set_id": self.set_id,
            "topic_ids": list(self.topic_ids),
            "question_ids": list(self.question_ids),
            "remaining_question_ids": list(self.remaining_question_ids),
            "question_count": self.question_count,
            "submission_mode": self.submission_mode,
            "source": self.source,
            "plan_id": self.plan_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StudyIntent":
        if not isinstance(data, dict):
            raise TypeError("study intent must be an object")
        return cls(
            course_id=data.get("course_id", ""),
            action=data.get("action", StudyAction.CUSTOM_PRACTICE.value),
            set_id=data.get("set_id", ""),
            topic_ids=data.get("topic_ids", ()),
            question_ids=data.get("question_ids", ()),
            remaining_question_ids=data.get("remaining_question_ids", ()),
            question_count=data.get("question_count", 0),
            submission_mode=data.get("submission_mode", "practice"),
            source=data.get("source", "manual"),
            plan_id=data.get("plan_id", ""),
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
        set_id=intent.set_id,
        topic_ids=intent.topic_ids,
        question_ids=current,
        remaining_question_ids=following,
        question_count=len(current),
        submission_mode=intent.submission_mode,
        source=intent.source,
        plan_id=intent.plan_id,
    )


def _normalized_ids(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        text
        for value in (values or ())
        if (text := str(value or "").strip())
    ))
