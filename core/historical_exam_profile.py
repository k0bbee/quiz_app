"""Build an ephemeral structure profile from imported historical questions.

The profile is intentionally a small, read-only input to the existing mock-exam
controls.  It never becomes another persisted course or prediction state.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from config import DEFAULT_DIFFICULTY_WEIGHTS, DEFAULT_QUESTION_TYPE_WEIGHTS
from utils.constants import topic_value


@dataclass(frozen=True)
class HistoricalExamProfile:
    """Normalized distributions observed in accepted historical imports."""

    sample_count: int
    topic_weights: dict[str, int]
    question_type_weights: dict[str, int]
    difficulty_weights: dict[str, int]
    source_files: tuple[str, ...] = ()


_IGNORED_TOPIC_MATCH_STATUSES = {"unmatched", "ambiguous", "unavailable"}


def build_historical_exam_profile(
    questions,
    *,
    allowed_topic_ids=(),
    course_id: str = "",
) -> HistoricalExamProfile | None:
    """Summarize imported questions that are safe for one course/scope.

    Only questions explicitly marked as historical imports are considered.  A
    requested course ID requires an exact metadata match, preventing another
    course's imported exam from influencing this mock exam.  Unmatched or
    ambiguous topic assignments are excluded from the structure signal rather
    than silently guessing their ownership.
    """
    requested_course = str(course_id or "").strip()
    allowed = tuple(
        dict.fromkeys(
            value
            for value in (topic_value(topic) for topic in (allowed_topic_ids or ()))
            if value and value != "general"
        )
    )
    allowed_set = set(allowed)
    topic_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    difficulty_counts: dict[str, int] = {}
    source_files: list[str] = []
    sample_count = 0

    for question in questions or ():
        metadata = getattr(question, "metadata", {}) or {}
        source = str(metadata.get("source", "") or "").strip().lower()
        if not bool(metadata.get("historical_import")) and source != "historical_import":
            continue
        if requested_course and str(metadata.get("course_id", "") or "").strip() != requested_course:
            continue
        if str(metadata.get("topic_match_status", "") or "").strip().lower() in _IGNORED_TOPIC_MATCH_STATUSES:
            continue

        question_topic = topic_value(getattr(question, "topic", "general"))
        if allowed_set and question_topic not in allowed_set:
            continue
        if question_topic == "general" and allowed_set:
            continue

        sample_count += 1
        if question_topic != "general":
            topic_counts[question_topic] = topic_counts.get(question_topic, 0) + 1

        type_key = _enum_value(getattr(question, "type", ""))
        if type_key in DEFAULT_QUESTION_TYPE_WEIGHTS:
            type_counts[type_key] = type_counts.get(type_key, 0) + 1
        difficulty_key = _enum_value(getattr(question, "difficulty", ""))
        if difficulty_key in DEFAULT_DIFFICULTY_WEIGHTS:
            difficulty_counts[difficulty_key] = difficulty_counts.get(difficulty_key, 0) + 1

        for source_ref in metadata.get("source_refs", ()) or ():
            if not isinstance(source_ref, dict):
                continue
            source_file = str(source_ref.get("source_file", "") or "").strip()
            if source_file and source_file not in source_files:
                source_files.append(source_file)

    if sample_count <= 0:
        return None

    topic_keys = allowed or tuple(topic_counts)
    return HistoricalExamProfile(
        sample_count=sample_count,
        topic_weights=_normalize(topic_counts, topic_keys),
        question_type_weights=_normalize(
            type_counts,
            tuple(DEFAULT_QUESTION_TYPE_WEIGHTS),
        ),
        difficulty_weights=_normalize(
            difficulty_counts,
            tuple(DEFAULT_DIFFICULTY_WEIGHTS),
        ),
        source_files=tuple(source_files),
    )


def _enum_value(value) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _normalize(counts: dict[str, int], keys) -> dict[str, int]:
    ordered_keys = tuple(dict.fromkeys(str(key) for key in keys if str(key)))
    if not ordered_keys:
        return {}
    # Add one observation to every bucket so a small import does not make an
    # unseen type/topic impossible; observed buckets still dominate.
    source = {key: max(0, int(counts.get(key, 0))) + 1 for key in ordered_keys}
    total = sum(source.values())
    raw = {key: source[key] * 100 / total for key in ordered_keys}
    normalized = {key: floor(raw[key]) for key in ordered_keys}
    remainder = 100 - sum(normalized.values())
    ranked = sorted(
        ordered_keys,
        key=lambda key: (-(raw[key] - normalized[key]), ordered_keys.index(key)),
    )
    for key in ranked[:remainder]:
        normalized[key] += 1
    return normalized
