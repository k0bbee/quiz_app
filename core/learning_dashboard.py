"""Read-only learning diagnostics for the home workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil

from core.exam_goal_store import ExamGoal
from core.today_learning_plan import TodayLearningPlan, build_topic_learning


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
class PlanProgress:
    """User-facing progress through the bounded plan for one day."""

    completed_count: int = 0
    total_count: int = 0
    current_group_count: int = 0
    remaining_after_current_group: int = 0

    @property
    def remaining_count(self) -> int:
        return max(0, self.total_count - self.completed_count)

    @property
    def completion_rate(self) -> float:
        return (
            self.completed_count / self.total_count
            if self.total_count
            else 0.0
        )


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
class ExamStatus:
    """A transparent one-round coverage estimate for a configured exam goal."""

    configured: bool = False
    days_remaining: int | None = None
    predicted_study_days: int = 0
    coverage_question_count: int = 0
    on_track: bool = True
    message: str = ""


@dataclass(frozen=True)
class NextDayPreview:
    """Conservative preview derived from backlog without changing scheduling."""

    question_count: int = 0


@dataclass(frozen=True)
class LearningDashboardViewModel:
    """One read-only model shared by the home and learning-analysis views."""

    daily_plan: TodayLearningPlan | None = None
    plan_progress: PlanProgress = PlanProgress()
    estimated_minutes: int = 0
    focus_topics: tuple[TopicFocus, ...] = ()
    weekly_summary: WeeklySummary = WeeklySummary()
    exam_status: ExamStatus = ExamStatus()
    next_day_preview: NextDayPreview = NextDayPreview()

    @property
    def focus_topic_ids(self) -> tuple[str, ...]:
        return tuple(topic.topic_id for topic in self.focus_topics)


# Compatibility name retained while view imports migrate to the explicit model.
LearningDashboard = LearningDashboardViewModel


def build_learning_dashboard(
    topic_index,
    *,
    records,
    daily_plan: TodayLearningPlan | None = None,
    exam_goal: ExamGoal | None = None,
    reference_date: date | None = None,
    max_focus_topics: int = 2,
) -> LearningDashboardViewModel:
    """Build a complete presentation model without changing scheduling."""
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
    plan_progress = _plan_progress(daily_plan)
    return LearningDashboardViewModel(
        daily_plan=daily_plan,
        plan_progress=plan_progress,
        estimated_minutes=max(
            0,
            int(getattr(daily_plan, "estimated_minutes", 0) or 0),
        ),
        focus_topics=tuple(ordered[:max(0, int(max_focus_topics or 0))]),
        weekly_summary=_weekly_summary(
            records,
            visible_question_ids=set(normalized_index),
            reference_date=current_date,
        ),
        exam_status=_exam_status(
            exam_goal,
            daily_plan=daily_plan,
            reference_date=current_date,
        ),
        next_day_preview=_next_day_preview(daily_plan),
    )


def _plan_progress(plan: TodayLearningPlan | None) -> PlanProgress:
    if plan is None:
        return PlanProgress()
    total = max(0, int(getattr(plan, "plan_total_count", 0) or 0))
    completed = min(
        total,
        max(0, int(getattr(plan, "completed_count", 0) or 0)),
    )
    remaining = max(0, total - completed)
    current = min(
        remaining,
        max(0, int(getattr(plan, "target_question_count", 0) or 0)),
    )
    return PlanProgress(
        completed_count=completed,
        total_count=total,
        current_group_count=current,
        remaining_after_current_group=max(0, remaining - current),
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


def _next_day_preview(plan: TodayLearningPlan | None) -> NextDayPreview:
    if plan is None:
        return NextDayPreview()
    total = max(0, int(getattr(plan, "plan_total_count", 0) or 0))
    backlog = max(0, int(getattr(plan, "backlog_count", 0) or 0))
    deferred = max(0, int(getattr(plan, "deferred_count", 0) or 0))
    future_count = max(deferred, backlog - total)
    return NextDayPreview(question_count=min(15, future_count))


def _exam_status(
    goal: ExamGoal | None,
    *,
    daily_plan: TodayLearningPlan | None,
    reference_date: date,
) -> ExamStatus:
    if goal is None:
        return ExamStatus()
    days_remaining = goal.days_remaining(reference_date)
    backlog = max(
        0,
        int(getattr(daily_plan, "backlog_count", 0) or 0),
    )
    predicted_days = (
        ceil(backlog * 2 / goal.daily_minutes)
        if backlog
        else 0
    )
    return ExamStatus(
        configured=True,
        days_remaining=days_remaining,
        predicted_study_days=predicted_days,
        coverage_question_count=backlog,
        on_track=predicted_days <= days_remaining,
    )
