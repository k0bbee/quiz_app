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

    Accepts strings, enums (uses .value), or None.
    Returns a lowercase string suitable for storage and comparison.
    """
    if raw is None:
        return "general"
    if isinstance(raw, Enum):
        return raw.value
    return str(raw).strip().lower()


def topic_value(topic):
    """Return a stable storage value for a topic.

    For string topics: the lowercase string itself.
    For enum topics: the .value.
    For None: returns "general" (consistent with coerce_topic).
    """
    if topic is None:
        return "general"
    if isinstance(topic, str):
        return topic.strip().lower()
    if isinstance(topic, Enum):
        return topic.value
    return str(topic).strip().lower()


def topic_label(topic, lang="zh"):
    """Return a human-readable label for a topic.

    For generic string topics, returns the topic string itself
    (the CourseProject is expected to provide bilingual labels).
    """
    t = topic_value(topic)
    # CourseProject.topics may have labels; these are provided
    # by the caller when rendering. For bare strings without
    # label data, return the key itself.
    return t


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
