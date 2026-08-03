"""Read-only learning diagnostics for the home workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core.today_learning_plan import build_topic_learning


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
    topics = build_topic_learning(topic_index, records)
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
