"""Persistent snapshot of one course's bounded daily study plan."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DailyStudyPlan:
    """Stable plan state shared by the home, quiz, and results flows."""

    plan_id: str
    date: str
    course_id: str
    planned_ids: tuple[str, ...]
    completed_ids: tuple[str, ...]
    pending_ids: tuple[str, ...]
    remediation_ids: tuple[str, ...]
    deferred_ids: tuple[str, ...]
    category_by_question: tuple[tuple[str, str], ...] = ()
    backlog_count: int = 0
    updated_at: str = ""
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", str(self.plan_id or "").strip())
        object.__setattr__(self, "date", str(self.date or "").strip())
        object.__setattr__(self, "course_id", str(self.course_id or "").strip())
        for field_name in (
            "planned_ids",
            "completed_ids",
            "pending_ids",
            "remediation_ids",
            "deferred_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalized_ids(getattr(self, field_name)),
            )
        pending = set(self.pending_ids)
        object.__setattr__(
            self,
            "remediation_ids",
            tuple(
                question_id
                for question_id in self.remediation_ids
                if question_id in pending
            ),
        )
        object.__setattr__(
            self,
            "category_by_question",
            _normalized_categories(self.category_by_question),
        )
        object.__setattr__(
            self,
            "backlog_count",
            max(len(self.planned_ids), int(self.backlog_count or 0)),
        )
        object.__setattr__(
            self,
            "schema_version",
            max(1, int(self.schema_version or _SCHEMA_VERSION)),
        )
        object.__setattr__(self, "updated_at", str(self.updated_at or "").strip())

    @property
    def is_complete(self) -> bool:
        return not self.pending_ids

    @property
    def remediation_count(self) -> int:
        return len(self.remediation_ids)

    @property
    def category_counts(self) -> tuple[tuple[str, int], ...]:
        """Return initial plan composition, excluding the remediation tail."""
        planned = set(self.planned_ids)
        counts = Counter(
            category
            for question_id, category in self.category_by_question
            if question_id in planned and category
        )
        return tuple(sorted(counts.items()))

    def next_session(
        self,
        session_size: int = 10,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        size = max(1, int(session_size or 1))
        return self.pending_ids[:size], self.pending_ids[size:]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "date": self.date,
            "course_id": self.course_id,
            "planned_ids": list(self.planned_ids),
            "completed_ids": list(self.completed_ids),
            "pending_ids": list(self.pending_ids),
            "remediation_ids": list(self.remediation_ids),
            "deferred_ids": list(self.deferred_ids),
            "category_by_question": {
                question_id: category
                for question_id, category in self.category_by_question
            },
            "backlog_count": self.backlog_count,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DailyStudyPlan":
        if not isinstance(data, dict):
            raise TypeError("daily study plan must be an object")
        categories = data.get("category_by_question", {})
        if isinstance(categories, dict):
            categories = tuple(categories.items())
        return cls(
            plan_id=data.get("plan_id", ""),
            date=data.get("date", ""),
            course_id=data.get("course_id", ""),
            planned_ids=data.get("planned_ids", ()),
            completed_ids=data.get("completed_ids", ()),
            pending_ids=data.get("pending_ids", ()),
            remediation_ids=data.get("remediation_ids", ()),
            deferred_ids=data.get("deferred_ids", ()),
            category_by_question=categories,
            backlog_count=data.get("backlog_count", 0),
            updated_at=data.get("updated_at", ""),
            schema_version=data.get("schema_version", _SCHEMA_VERSION),
        )


def _normalized_ids(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        text
        for value in (values or ())
        if (text := str(value or "").strip())
    ))


def _normalized_categories(values) -> tuple[tuple[str, str], ...]:
    normalized: dict[str, str] = {}
    for row in values or ():
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            continue
        question_id = str(row[0] or "").strip()
        category = str(row[1] or "").strip()
        if question_id and category:
            normalized[question_id] = category
    return tuple(normalized.items())
