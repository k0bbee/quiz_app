"""Read-only learning diagnostics for the home workspace."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicFocus:
    """One attempted topic whose result needs a learner's attention."""

    topic_id: str
    title: str
    question_count: int
    attempts: int
    correct_count: int
    incorrect_count: int
    unsure_count: int

    @property
    def accuracy(self) -> float:
        return self.correct_count / self.attempts if self.attempts else 0.0


@dataclass(frozen=True)
class LearningDashboard:
    """A compact diagnostic that leaves scheduling decisions unchanged."""

    focus_topics: tuple[TopicFocus, ...] = ()

    @property
    def focus_topic_ids(self) -> tuple[str, ...]:
        return tuple(topic.topic_id for topic in self.focus_topics)


def build_learning_dashboard(
    topic_index,
    *,
    records,
    max_focus_topics: int = 2,
) -> LearningDashboard:
    """Find attempted topics with the most actionable weakness signals."""
    topics: dict[str, dict[str, int | str]] = {}
    normalized_index: dict[str, str] = {}
    for question_id, row in (topic_index or {}).items():
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            continue
        topic_id = str(row[0] or "").strip()
        if not topic_id:
            continue
        title = str(row[1] or topic_id).strip() or topic_id
        normalized_index[str(question_id or "").strip()] = topic_id
        values = topics.setdefault(topic_id, {
            "title": title,
            "question_count": 0,
            "attempts": 0,
            "correct_count": 0,
            "incorrect_count": 0,
            "unsure_count": 0,
        })
        values["question_count"] = int(values["question_count"]) + 1

    for record in records or ():
        if getattr(record, "status", "") != "completed":
            continue
        for answer in getattr(record, "answers", ()) or ():
            if getattr(answer, "skipped", False):
                continue
            topic_id = normalized_index.get(
                str(getattr(answer, "question_id", "") or "").strip()
            )
            if not topic_id:
                continue
            values = topics[topic_id]
            values["attempts"] = int(values["attempts"]) + 1
            if getattr(answer, "is_correct", False):
                values["correct_count"] = int(values["correct_count"]) + 1
            else:
                values["incorrect_count"] = int(values["incorrect_count"]) + 1
            if str(getattr(answer, "confidence", "sure") or "sure") == "unsure":
                values["unsure_count"] = int(values["unsure_count"]) + 1

    focus_topics = tuple(
        TopicFocus(
            topic_id=topic_id,
            title=str(values["title"]),
            question_count=int(values["question_count"]),
            attempts=int(values["attempts"]),
            correct_count=int(values["correct_count"]),
            incorrect_count=int(values["incorrect_count"]),
            unsure_count=int(values["unsure_count"]),
        )
        for topic_id, values in topics.items()
        if (
            int(values["attempts"]) > 0
            and (
                int(values["incorrect_count"]) > 0
                or int(values["unsure_count"]) > 0
            )
        )
    )
    ordered = sorted(
        focus_topics,
        key=lambda topic: (
            -(topic.incorrect_count * 2 + topic.unsure_count),
            topic.accuracy,
            -topic.attempts,
            topic.title.casefold(),
            topic.topic_id,
        ),
    )
    return LearningDashboard(
        focus_topics=tuple(ordered[:max(0, int(max_focus_topics or 0))])
    )
