"""Read-only learning diagnostics for the home workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core.today_learning_plan import build_topic_learning


_FOCUS_WINDOW_SIZE = 5


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
    error_reason_counts: tuple[tuple[str, int], ...] = ()

    @property
    def accuracy(self) -> float:
        return self.correct_count / self.attempts if self.attempts else 0.0


@dataclass(frozen=True)
class WeeklySummary:
    """A compact summary of completed work in the current calendar week."""

    study_days: int = 0
    completed_questions: int = 0
    correct_questions: int = 0

    @property
    def accuracy(self) -> float:
        return (
            self.correct_questions / self.completed_questions
            if self.completed_questions
            else 0.0
        )


@dataclass(frozen=True)
class LearningDashboardViewModel:
    """One read-only model shared by the home and learning-analysis views."""

    focus_topics: tuple[TopicFocus, ...] = ()
    weekly_summary: WeeklySummary = WeeklySummary()

    @property
    def focus_topic_ids(self) -> tuple[str, ...]:
        return tuple(topic.topic_id for topic in self.focus_topics)


# Compatibility name retained while view imports migrate to the explicit model.
LearningDashboard = LearningDashboardViewModel


def build_learning_dashboard(
    topic_index,
    *,
    records,
    reference_date: date | None = None,
    max_focus_topics: int = 2,
) -> LearningDashboardViewModel:
    """Build read-only topic and weekly metrics without owning scheduling."""
    all_topics = build_topic_learning(topic_index, ())
    topics = _recent_topic_learning(
        all_topics,
        topic_index=topic_index,
        records=records,
        limit=_FOCUS_WINDOW_SIZE,
    )
    normalized_index = {
        str(question_id or "").strip()
        for question_id in (topic_index or {})
        if str(question_id or "").strip()
    }

    focus_topics = tuple(
        TopicFocus(
            topic_id=topic_id,
            title=str(values["title"]),
            question_count=int(values["question_count"]),
            attempts=int(values["attempts"]),
            correct_count=int(values["correct"]),
            incorrect_count=int(values["incorrect"]),
            unsure_count=int(values["unsure"]),
            error_reason_counts=tuple(
                sorted(
                    (
                        (str(reason), int(count))
                        for reason, count in (values.get("error_reasons", {}) or {}).items()
                        if str(reason).strip() and int(count) > 0
                    ),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
        )
        for topic_id, values in topics.items()
        if (
            int(values["attempts"]) > 0
            and (
                int(values["incorrect"]) > 0
                or int(values["unsure"]) > 0
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
    current_date = reference_date or date.today()
    return LearningDashboardViewModel(
        focus_topics=tuple(ordered[:max(0, int(max_focus_topics or 0))]),
        weekly_summary=_weekly_summary(
            records,
            visible_question_ids=set(normalized_index),
            reference_date=current_date,
        ),
    )


def _recent_topic_learning(
    topic_templates: dict[str, dict],
    *,
    topic_index,
    records,
    limit: int,
) -> dict[str, dict]:
    question_to_topic = {
        str(question_id or "").strip(): str(topic_row[0] or "").strip()
        for question_id, topic_row in (topic_index or {}).items()
        if (
            str(question_id or "").strip()
            and isinstance(topic_row, (tuple, list))
            and len(topic_row) >= 2
            and str(topic_row[0] or "").strip()
        )
    }
    recent_answers: dict[str, list[tuple[str, int, int, object]]] = {
        topic_id: [] for topic_id in topic_templates
    }
    for record_index, record in enumerate(records or ()):
        if getattr(record, "status", "") != "completed":
            continue
        record_time = _record_timestamp(record)
        for answer_index, answer in enumerate(
            getattr(record, "answers", ()) or ()
        ):
            if getattr(answer, "skipped", False):
                continue
            topic_id = question_to_topic.get(
                str(getattr(answer, "question_id", "") or "").strip()
            )
            if topic_id in recent_answers:
                recent_answers[topic_id].append(
                    (record_time, -record_index, answer_index, answer)
                )

    topics: dict[str, dict] = {}
    for topic_id, template in topic_templates.items():
        rows = sorted(
            recent_answers.get(topic_id, ()),
            key=lambda row: (row[0], row[1], row[2]),
            reverse=True,
        )[:max(0, int(limit or 0))]
        values = dict(template)
        values.update({
            "attempts": len(rows),
            "correct": 0,
            "incorrect": 0,
            "unsure": 0,
            "error_reasons": {},
        })
        for _timestamp, _record_order, _answer_order, answer in rows:
            if getattr(answer, "is_correct", False):
                values["correct"] += 1
            else:
                values["incorrect"] += 1
                reason = str(
                    getattr(answer, "error_reason", "") or ""
                ).strip()
                if reason:
                    values["error_reasons"][reason] = (
                        values["error_reasons"].get(reason, 0) + 1
                    )
            if str(
                getattr(answer, "confidence", "sure") or "sure"
            ) == "unsure":
                values["unsure"] += 1
        topics[topic_id] = values
    return topics


def _record_timestamp(record) -> str:
    return (
        str(getattr(record, "completed_at", "") or "").strip()
        or str(getattr(record, "started_at", "") or "").strip()
    )


def _weekly_summary(
    records,
    *,
    visible_question_ids: set[str],
    reference_date: date,
) -> WeeklySummary:
    week_start = reference_date - timedelta(days=reference_date.weekday())
    study_dates: set[date] = set()
    answered = 0
    correct = 0
    for record in records or ():
        if getattr(record, "status", "") != "completed":
            continue
        record_date = _record_date(record)
        if record_date is None or not week_start <= record_date <= reference_date:
            continue
        scoped_answers = [
            answer
            for answer in (getattr(record, "answers", ()) or ())
            if (
                not getattr(answer, "skipped", False)
                and str(getattr(answer, "question_id", "") or "").strip()
                in visible_question_ids
            )
        ]
        if not scoped_answers:
            continue
        study_dates.add(record_date)
        answered += len(scoped_answers)
        correct += sum(
            1 for answer in scoped_answers
            if getattr(answer, "is_correct", False)
        )
    return WeeklySummary(
        study_days=len(study_dates),
        completed_questions=answered,
        correct_questions=correct,
    )


def _record_date(record) -> date | None:
    value = (
        str(getattr(record, "completed_at", "") or "").strip()
        or str(getattr(record, "started_at", "") or "").strip()
    )
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
