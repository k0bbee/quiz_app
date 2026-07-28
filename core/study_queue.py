"""Deterministic daily study scheduling built from existing progress data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from models.review_state import ReviewState


class StudyQueueCategory(str, Enum):
    DUE = "due"
    RECENT_ERROR = "recent_error"
    UNSURE = "unsure"
    STALE = "stale"
    NEW = "new"


_CATEGORY_ORDER = (
    StudyQueueCategory.DUE,
    StudyQueueCategory.RECENT_ERROR,
    StudyQueueCategory.UNSURE,
    StudyQueueCategory.STALE,
    StudyQueueCategory.NEW,
)


@dataclass(frozen=True)
class StudyQueueEntry:
    question_id: str
    category: StudyQueueCategory
    review_state: ReviewState


@dataclass(frozen=True)
class DailyStudyQueue:
    """One bounded daily plan split into the current and following session."""

    entries: tuple[StudyQueueEntry, ...]
    question_ids: tuple[str, ...]
    current_question_ids: tuple[str, ...]
    remaining_question_ids: tuple[str, ...]
    category_counts: Mapping[StudyQueueCategory, int]
    review_states: Mapping[str, ReviewState]
    estimated_minutes: int
    backlog_count: int

    @property
    def total_count(self) -> int:
        return len(self.question_ids)


@dataclass
class _MutableReviewState:
    question_id: str
    attempts: int = 0
    last_reviewed_at: str = ""
    next_due_at: str = ""
    correct_streak: int = 0
    wrong_streak: int = 0
    interval_days: int = 0
    last_confidence: str = "sure"


def build_daily_study_queue(
    candidate_question_ids,
    progress_records,
    *,
    now: datetime | None = None,
    daily_limit: int = 15,
    session_size: int = 10,
    stale_after_days: int = 14,
) -> DailyStudyQueue:
    """Build a transparent queue without persisting duplicate learning state."""
    now = _as_utc(now or datetime.now(timezone.utc))
    candidate_ids = tuple(sorted({
        str(question_id or "").strip()
        for question_id in (candidate_question_ids or ())
        if str(question_id or "").strip()
    }))
    mutable = {
        question_id: _MutableReviewState(question_id)
        for question_id in candidate_ids
    }
    for attempted_at, _record_index, _answer_index, answer in _answer_events(
        progress_records,
        now,
    ):
        state = mutable.get(str(getattr(answer, "question_id", "") or "").strip())
        if state is None:
            continue
        state.attempts += 1
        state.last_reviewed_at = attempted_at.isoformat()
        confidence = str(getattr(answer, "confidence", "sure") or "sure")
        state.last_confidence = confidence if confidence in {"sure", "unsure"} else "sure"
        if bool(getattr(answer, "is_correct", False)):
            state.correct_streak += 1
            state.wrong_streak = 0
            state.interval_days = (
                1
                if state.last_confidence == "unsure"
                else min(30, 2 ** max(0, state.correct_streak - 1))
            )
        else:
            state.correct_streak = 0
            state.wrong_streak += 1
            state.interval_days = 0
        state.next_due_at = (
            attempted_at + timedelta(days=state.interval_days)
        ).isoformat()

    review_states = {
        question_id: ReviewState(
            question_id=state.question_id,
            attempts=state.attempts,
            last_reviewed_at=state.last_reviewed_at,
            next_due_at=state.next_due_at,
            correct_streak=state.correct_streak,
            wrong_streak=state.wrong_streak,
            interval_days=state.interval_days,
            last_confidence=state.last_confidence,
        )
        for question_id, state in mutable.items()
    }
    by_category = {category: [] for category in _CATEGORY_ORDER}
    for state in review_states.values():
        category = _category_for_state(
            state,
            now,
            stale_after_days=max(1, int(stale_after_days or 14)),
        )
        if category is not None:
            by_category[category].append(
                StudyQueueEntry(state.question_id, category, state)
            )
    for category, entries in by_category.items():
        entries.sort(key=lambda entry: _entry_sort_key(category, entry))

    all_entries = tuple(
        entry
        for category in _CATEGORY_ORDER
        for entry in by_category[category]
    )
    selected_entries = all_entries[:max(0, int(daily_limit or 0))]
    question_ids = tuple(entry.question_id for entry in selected_entries)
    selected_category_counts = {
        category: sum(
            1 for entry in selected_entries if entry.category is category
        )
        for category in _CATEGORY_ORDER
    }
    current_count = min(
        len(question_ids),
        max(1, int(session_size or 1)),
    )
    current_question_ids = question_ids[:current_count]
    remaining_question_ids = question_ids[current_count:]
    estimated_minutes = max(5, len(question_ids) * 2) if question_ids else 0
    return DailyStudyQueue(
        entries=all_entries,
        question_ids=question_ids,
        current_question_ids=current_question_ids,
        remaining_question_ids=remaining_question_ids,
        category_counts=MappingProxyType(selected_category_counts),
        review_states=MappingProxyType(review_states),
        estimated_minutes=estimated_minutes,
        backlog_count=len(all_entries),
    )


def _answer_events(progress_records, now: datetime):
    events = []
    for record_index, record in enumerate(progress_records or ()):
        if str(getattr(record, "status", "") or "") != "completed":
            continue
        record_time = _parse_timestamp(
            getattr(record, "completed_at", "")
            or getattr(record, "started_at", ""),
            now,
        )
        for answer_index, answer in enumerate(getattr(record, "answers", ()) or ()):
            if bool(getattr(answer, "skipped", False)):
                continue
            attempted_at = _parse_timestamp(
                getattr(answer, "attempted_at", ""),
                record_time,
            )
            events.append((attempted_at, record_index, answer_index, answer))
    events.sort(key=lambda row: (row[0], row[1], row[2]))
    return events


def _category_for_state(
    state: ReviewState,
    now: datetime,
    *,
    stale_after_days: int,
) -> StudyQueueCategory | None:
    if state.attempts <= 0:
        return StudyQueueCategory.NEW
    if state.wrong_streak > 0:
        return StudyQueueCategory.RECENT_ERROR
    if state.last_confidence == "unsure":
        return StudyQueueCategory.UNSURE
    due_at = _parse_timestamp(state.next_due_at, datetime.max.replace(tzinfo=timezone.utc))
    if due_at <= now:
        return StudyQueueCategory.DUE
    last_reviewed = _parse_timestamp(
        state.last_reviewed_at,
        datetime.max.replace(tzinfo=timezone.utc),
    )
    if now - last_reviewed >= timedelta(days=stale_after_days):
        return StudyQueueCategory.STALE
    return None


def _entry_sort_key(
    category: StudyQueueCategory,
    entry: StudyQueueEntry,
):
    state = entry.review_state
    if category is StudyQueueCategory.RECENT_ERROR:
        return (
            -state.wrong_streak,
            state.last_reviewed_at,
            entry.question_id,
        )
    if category is StudyQueueCategory.NEW:
        return (entry.question_id,)
    timestamp = (
        state.next_due_at
        if category is StudyQueueCategory.DUE
        else state.last_reviewed_at
    )
    return (timestamp, entry.question_id)


def _parse_timestamp(value: str, fallback: datetime) -> datetime:
    if not value:
        return _as_utc(fallback)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return _as_utc(fallback)
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
