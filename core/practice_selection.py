"""Deterministic question selection for user-configured practice sessions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def select_practice_question_ids(
    scheduling_index: Mapping[str, tuple[str, str, str]],
    *,
    topic_ids: Sequence[str] = (),
    difficulty: str = "",
    limit: int = 10,
) -> list[str]:
    """Select a bounded, topic-rotated session from lightweight metadata."""
    limit = max(0, int(limit or 0))
    if not limit:
        return []

    wanted_topics = tuple(dict.fromkeys(
        topic_id
        for value in (topic_ids or ())
        if (topic_id := str(value or "").strip())
    ))
    allowed_topics = set(wanted_topics)
    difficulty = str(difficulty or "").strip().lower()
    grouped: dict[str, list[str]] = {}
    for question_id, row in scheduling_index.items():
        try:
            topic_id, _topic_title, question_difficulty = row
        except (TypeError, ValueError):
            continue
        question_id = str(question_id or "").strip()
        topic_id = str(topic_id or "").strip()
        if not question_id or not topic_id:
            continue
        if allowed_topics and topic_id not in allowed_topics:
            continue
        if difficulty and str(question_difficulty or "").strip().lower() != difficulty:
            continue
        grouped.setdefault(topic_id, []).append(question_id)

    topic_order = (
        [topic_id for topic_id in wanted_topics if topic_id in grouped]
        if wanted_topics
        else sorted(grouped)
    )
    for question_ids in grouped.values():
        question_ids.sort()

    selected: list[str] = []
    offset = 0
    while len(selected) < limit:
        added = False
        for topic_id in topic_order:
            question_ids = grouped[topic_id]
            if offset >= len(question_ids):
                continue
            selected.append(question_ids[offset])
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
        offset += 1
    return selected
