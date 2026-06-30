"""Enums and constants for the quiz application."""

from enum import Enum


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    MATCHING = "matching"
    ORDERING = "ordering"
    SCENARIO_CHOICE = "scenario_choice"
    FILL_IN_BLANK = "fill_in_blank"
    SHORT_ANSWER = "short_answer"


class QuizState(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    ANSWERED = "answered"
    SHOWING_FEEDBACK = "showing_feedback"
    COMPLETED = "completed"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# ── Dynamic topic system ──────────────────────────────────────
# Topics are NO LONGER hardcoded. They come from imported
# CourseProject objects. The old Topic enum is removed.
#
# The functions below handle both "known" enum-style topics
# and free-form string topics from any course.

def coerce_topic(raw):
    """Normalize a topic value to a stable string.

    Accepts strings, enums (uses .value), course-topic-like objects, or None.
    Returns a lowercase string suitable for storage and comparison.
    """
    if raw is None:
        return "general"
    if isinstance(raw, Enum):
        return raw.value
    topic_id = _object_text_attr(raw, "topic_id")
    if topic_id:
        return topic_id.strip().lower()
    title = _object_text_attr(raw, "title")
    if title:
        return title.strip().lower()
    return str(raw).strip().lower()


def topic_value(topic):
    """Return a stable storage value for a topic.

    For string topics: the lowercase string itself.
    For enum topics: the .value.
    For course-topic-like objects: the normalized topic_id, falling back to title.
    For None: returns "general" (consistent with coerce_topic).
    """
    if topic is None:
        return "general"
    if isinstance(topic, str):
        return topic.strip().lower()
    if isinstance(topic, Enum):
        return topic.value
    topic_id = _object_text_attr(topic, "topic_id")
    if topic_id:
        return topic_id.strip().lower()
    title = _object_text_attr(topic, "title")
    if title:
        return title.strip().lower()
    return str(topic).strip().lower()


def topic_label(topic, lang="zh"):
    """Return a human-readable label for a topic.

    For CourseProject topics, returns the inferred human-readable title.
    For generic string topics, returns the normalized topic string itself.
    """
    title = _object_text_attr(topic, "title")
    if title:
        return title.strip()
    t = topic_value(topic)
    return t


def topic_alias_values(topic) -> set[str]:
    """Return normalized identity and legacy aliases that may refer to a topic."""
    values = {topic_value(topic)}
    title = _object_text_attr(topic, "title")
    if title:
        values.add(title.strip().lower())
    aliases = getattr(topic, "aliases", []) or []
    if isinstance(aliases, (list, tuple, set)):
        for alias in aliases:
            alias_text = str(alias or "").strip().lower()
            if alias_text:
                values.add(alias_text)
    return {value for value in values if value}


def topic_matches(candidate, selected) -> bool:
    """Return whether candidate and selected refer to the same topic.

    This supports new topic_id-based storage while preserving old question files
    that stored the mutable topic title as their only topic value.
    """
    return bool(topic_alias_values(candidate) & topic_alias_values(selected))


def _object_text_attr(obj, name: str) -> str:
    value = getattr(obj, name, "")
    if callable(value):
        return ""
    return str(value or "")


# ── Auto-gradeable and manual-review question types ───────────
AUTO_GRADEABLE_TYPES = {
    QuestionType.MULTIPLE_CHOICE,
    QuestionType.TRUE_FALSE,
    QuestionType.SCENARIO_CHOICE,
    QuestionType.MATCHING,
    QuestionType.ORDERING,
    QuestionType.FILL_IN_BLANK,
}

MANUAL_REVIEW_TYPES = {
    QuestionType.SHORT_ANSWER,
}
