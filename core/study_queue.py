"""Deterministic daily study scheduling built from existing progress data."""

from __future__ import annotations

from collections import Counter
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
_DIFFICULTY_ORDER = ("easy", "medium", "hard", "medium")


@dataclass(frozen=True)
class StudyQueueEntry:
    question_id: str
    category: StudyQueueCategory
    review_state: ReviewState
    topic_id: str = ""
    difficulty: str = "medium"


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


@dataclass
class _TopicStats:
    attempts: int = 0
    correct: int = 0
    incorrect: int = 0

    @property
    def accuracy(self) -> float:
        if self.attempts <= 0:
            return 0.0
        return self.correct / self.attempts


def build_daily_study_queue(
    candidate_question_ids,
    progress_records,
    *,
    now: datetime | None = None,
    daily_limit: int = 15,
    session_size: int = 10,
    stale_after_days: int = 14,
    topic_index=None,
    difficulty_index=None,
    exam_scope_weights=None,
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
    topics = {
        question_id: _topic_id(question_id, topic_index)
        for question_id in candidate_ids
    }
    difficulties = {
        question_id: _difficulty(question_id, difficulty_index)
        for question_id in candidate_ids
    }
    topic_stats = {
        topic_id: _TopicStats()
        for topic_id in set(topics.values())
    }
    events = _answer_events(
        progress_records,
        now,
    )
    for attempted_at, _record_index, _answer_index, answer in events:
        question_id = str(
            getattr(answer, "question_id", "") or ""
        ).strip()
        state = mutable.get(question_id)
        if state is None:
            continue
        stats = topic_stats[topics[question_id]]
        stats.attempts += 1
        state.attempts += 1
        state.last_reviewed_at = attempted_at.isoformat()
        confidence = str(getattr(answer, "confidence", "sure") or "sure")
        state.last_confidence = confidence if confidence in {"sure", "unsure"} else "sure"
        if bool(getattr(answer, "is_correct", False)):
            stats.correct += 1
            state.correct_streak += 1
            state.wrong_streak = 0
            state.interval_days = (
                1
                if state.last_confidence == "unsure"
                else min(30, 2 ** max(0, state.correct_streak - 1))
            )
        else:
            stats.incorrect += 1
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
                StudyQueueEntry(
                    state.question_id,
                    category,
                    state,
                    topic_id=topics[state.question_id],
                    difficulty=difficulties[state.question_id],
                )
            )
    for category, entries in by_category.items():
        entries.sort(key=lambda entry: _entry_sort_key(category, entry))

    selected_entries, remaining_entries = _schedule_entries(
        by_category,
        daily_limit=max(0, int(daily_limit or 0)),
        topic_stats=topic_stats,
        exam_scope_weights=exam_scope_weights,
    )
    all_entries = selected_entries + remaining_entries
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


def _schedule_entries(
    by_category: dict[StudyQueueCategory, list[StudyQueueEntry]],
    *,
    daily_limit: int,
    topic_stats: dict[str, _TopicStats],
    exam_scope_weights,
) -> tuple[tuple[StudyQueueEntry, ...], tuple[StudyQueueEntry, ...]]:
    remaining = {
        category: list(by_category[category])
        for category in _CATEGORY_ORDER
    }
    selected: list[StudyQueueEntry] = []
    selected_by_topic: Counter[str] = Counter()
    last_topic = ""
    topic_streak = 0
    weights = _normalized_topic_weights(exam_scope_weights)

    while len(selected) < daily_limit:
        primary_category = next(
            (
                category
                for category in _CATEGORY_ORDER
                if remaining[category]
            ),
            None,
        )
        if primary_category is None:
            break
        candidates = remaining[primary_category]
        chosen_category = primary_category
        if topic_streak >= 2:
            alternatives = [
                entry
                for entry in candidates
                if entry.topic_id != last_topic
            ]
            if alternatives:
                candidates = alternatives
            else:
                for category in _categories_after(primary_category):
                    alternatives = [
                        entry
                        for entry in remaining[category]
                        if entry.topic_id != last_topic
                    ]
                    if alternatives:
                        chosen_category = category
                        candidates = alternatives
                        break

        desired_difficulty = _DIFFICULTY_ORDER[
            len(selected) % len(_DIFFICULTY_ORDER)
        ]
        chosen = _choose_entry(
            candidates,
            chosen_category,
            desired_difficulty=desired_difficulty,
            topic_stats=topic_stats,
            selected_by_topic=selected_by_topic,
            topic_weights=weights,
        )
        remaining[chosen_category].remove(chosen)
        selected.append(chosen)
        selected_by_topic[chosen.topic_id] += 1
        if chosen.topic_id == last_topic:
            topic_streak += 1
        else:
            last_topic = chosen.topic_id
            topic_streak = 1

    tail = tuple(
        entry
        for category in _CATEGORY_ORDER
        for entry in remaining[category]
    )
    return tuple(selected), tail


def _choose_entry(
    candidates: list[StudyQueueEntry],
    category: StudyQueueCategory,
    *,
    desired_difficulty: str,
    topic_stats: dict[str, _TopicStats],
    selected_by_topic: Counter[str],
    topic_weights: dict[str, float],
) -> StudyQueueEntry:
    topics = {entry.topic_id for entry in candidates}

    def topic_key(topic_id: str):
        stats = topic_stats.get(topic_id, _TopicStats())
        weakness = (
            (
                0 if stats.attempts <= 0 else 1,
                stats.attempts,
                stats.accuracy,
            )
            if category is StudyQueueCategory.NEW
            else (
                stats.accuracy,
                -stats.incorrect,
                stats.attempts,
            )
        )
        weight = topic_weights.get(topic_id, 1.0)
        projected_share = (selected_by_topic[topic_id] + 1) / weight
        has_desired_difficulty = any(
            entry.topic_id == topic_id
            and entry.difficulty == desired_difficulty
            for entry in candidates
        )
        return (
            *weakness,
            projected_share,
            0 if has_desired_difficulty else 1,
            topic_id,
        )

    chosen_topic = min(topics, key=topic_key)
    topic_entries = [
        entry for entry in candidates if entry.topic_id == chosen_topic
    ]
    return min(
        topic_entries,
        key=lambda entry: (
            _difficulty_distance(entry.difficulty, desired_difficulty),
            _entry_sort_key(category, entry),
        ),
    )


def _categories_after(
    category: StudyQueueCategory,
) -> tuple[StudyQueueCategory, ...]:
    index = _CATEGORY_ORDER.index(category)
    return _CATEGORY_ORDER[index + 1:]


def _normalized_topic_weights(values) -> dict[str, float]:
    if not isinstance(values, Mapping):
        return {}
    normalized = {}
    for topic, weight in values.items():
        topic_id = str(topic or "").strip()
        try:
            numeric = float(weight)
        except (TypeError, ValueError):
            continue
        if topic_id and numeric > 0:
            normalized[topic_id] = numeric
    return normalized


def _topic_id(question_id: str, topic_index) -> str:
    row = (
        topic_index.get(question_id)
        if isinstance(topic_index, Mapping)
        else None
    )
    value = row[0] if isinstance(row, (tuple, list)) and row else row
    return str(value or question_id).strip() or question_id


def _difficulty(question_id: str, difficulty_index) -> str:
    value = (
        difficulty_index.get(question_id)
        if isinstance(difficulty_index, Mapping)
        else None
    )
    normalized = str(
        getattr(value, "value", value) or "medium"
    ).strip().lower()
    return normalized if normalized in {"easy", "medium", "hard"} else "medium"


def _difficulty_distance(actual: str, desired: str) -> int:
    levels = {"easy": 0, "medium": 1, "hard": 2}
    return abs(levels.get(actual, 1) - levels.get(desired, 1))


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
