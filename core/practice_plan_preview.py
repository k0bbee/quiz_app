"""Lightweight, deterministic summary data for a planned practice session."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


MINUTES_PER_QUESTION = 2


@dataclass(frozen=True)
class PracticePlanPreview:
    """The session facts a learner needs before deciding to begin."""

    requested_count: int
    ready_count: int
    missing_count: int
    ready_minutes: int
    target_minutes: int
    topic_counts: tuple[tuple[str, int], ...]
    difficulty_counts: tuple[tuple[str, int], ...]


def build_practice_plan_preview(
    scheduling_index: Mapping[str, tuple[str, str, str]],
    *,
    question_ids: Sequence[str],
    requested_count: int,
) -> PracticePlanPreview:
    """Summarize only the valid, unique questions selected for this session."""
    requested_count = max(0, int(requested_count or 0))
    seen_ids: set[str] = set()
    selected_rows: list[tuple[str, str, str]] = []
    for value in question_ids or ():
        question_id = str(value or "").strip()
        if not question_id or question_id in seen_ids:
            continue
        seen_ids.add(question_id)
        row = scheduling_index.get(question_id)
        if not isinstance(row, tuple) or len(row) != 3:
            continue
        topic_id, topic_title, difficulty = row
        topic_id = str(topic_id or "").strip()
        if not topic_id:
            continue
        selected_rows.append((
            topic_id,
            str(topic_title or topic_id).strip() or topic_id,
            str(difficulty or "").strip().lower(),
        ))

    topic_counts = Counter(topic_title for _, topic_title, _ in selected_rows)
    difficulty_counts = Counter(
        difficulty for _, _, difficulty in selected_rows if difficulty
    )
    ready_count = len(selected_rows)
    return PracticePlanPreview(
        requested_count=requested_count,
        ready_count=ready_count,
        missing_count=max(0, requested_count - ready_count),
        ready_minutes=ready_count * MINUTES_PER_QUESTION,
        target_minutes=requested_count * MINUTES_PER_QUESTION,
        topic_counts=tuple(topic_counts.items()),
        difficulty_counts=tuple(difficulty_counts.items()),
    )
