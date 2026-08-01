"""Read-only cross-course study agenda built from existing schedulers.

The home screen historically owned one course's daily plan.  This module
provides a small aggregation boundary so a future global home view can show
what matters across courses without duplicating queue or scope rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import inf
from typing import Mapping, Sequence

from core.study_queue import StudyQueueCategory, build_daily_study_queue


@dataclass(frozen=True)
class CourseAgenda:
    """One course's actionable study summary for the current day."""

    course_id: str
    title: str
    total_question_count: int = 0
    total_actionable_count: int = 0
    today_question_count: int = 0
    current_question_count: int = 0
    plan_id: str = ""
    today_question_ids: tuple[str, ...] = ()
    remaining_question_ids: tuple[str, ...] = ()
    due_count: int = 0
    incorrect_count: int = 0
    unsure_count: int = 0
    exam_days_remaining: int | None = None
    category_counts: tuple[tuple[str, int], ...] = ()
    focus_topic_id: str = ""
    focus_topic_title: str = ""

    @property
    def has_work(self) -> bool:
        return self.total_actionable_count > 0

    @property
    def estimated_minutes(self) -> int:
        return max(0, self.today_question_count * 2)


@dataclass(frozen=True)
class GlobalStudyAgenda:
    """Stable aggregate used by home and future cross-course workflows."""

    items: tuple[CourseAgenda, ...] = ()
    current_course_id: str = ""

    @property
    def course_ids(self) -> tuple[str, ...]:
        return tuple(item.course_id for item in self.items)

    @property
    def total_question_count(self) -> int:
        return sum(item.total_question_count for item in self.items)

    @property
    def total_actionable_count(self) -> int:
        return sum(item.total_actionable_count for item in self.items)

    @property
    def total_estimated_minutes(self) -> int:
        """Estimated time for the currently scheduled question groups."""
        return sum(item.estimated_minutes for item in self.items)

    @property
    def courses_with_work(self) -> int:
        return sum(1 for item in self.items if item.has_work)

    def item_for(self, course_id: str) -> CourseAgenda | None:
        wanted = str(course_id or "").strip()
        return next(
            (item for item in self.items if item.course_id == wanted),
            None,
        )


def build_global_study_agenda(
    course_manager,
    *,
    question_bank,
    progress_records: Sequence[object] | None,
    mastery_overrides=None,
    exam_goal_store=None,
    daily_plan_store=None,
    reference_date: date | None = None,
    current_course_id: str = "",
) -> GlobalStudyAgenda:
    """Aggregate existing per-course scheduling and plan state.

    A malformed course or unavailable index is isolated to that course.  The
    caller can therefore keep the home page usable while another course is
    repaired or re-imported.  When a daily-plan store is supplied, its
    persisted pending IDs are authoritative so the aggregate cannot drift
    from the single-course home plan.
    """
    if course_manager is None or question_bank is None:
        return GlobalStudyAgenda(current_course_id=str(current_course_id or "").strip())
    try:
        courses = list(course_manager.load_all())
    except (OSError, TypeError, ValueError):
        courses = []
    today = reference_date or date.today()
    normalized_current = str(current_course_id or "").strip()
    records = tuple(progress_records or ())
    items: list[CourseAgenda] = []
    for course in courses:
        item = _build_course_agenda(
            course,
            question_bank=question_bank,
            progress_records=records,
            mastery_overrides=mastery_overrides,
            exam_goal_store=exam_goal_store,
            daily_plan_store=daily_plan_store,
            reference_date=today,
        )
        if item is not None:
            items.append(item)
    items.sort(key=lambda item: _agenda_sort_key(item, normalized_current))
    return GlobalStudyAgenda(
        items=tuple(items),
        current_course_id=normalized_current,
    )


def _build_course_agenda(
    course,
    *,
    question_bank,
    progress_records,
    mastery_overrides,
    exam_goal_store,
    daily_plan_store,
    reference_date: date,
) -> CourseAgenda | None:
    course_id = str(getattr(course, "course_id", "") or "").strip()
    if not course_id:
        return None
    title = str(getattr(course, "title", "") or "").strip() or course_id
    try:
        question_ids = {
            str(question_id or "").strip()
            for question_id in question_bank.question_ids(course_id=course_id)
            if str(question_id or "").strip()
        }
        scheduling = question_bank.scheduling_index(course_id=course_id)
    except (OSError, TypeError, ValueError):
        return CourseAgenda(course_id=course_id, title=title)

    normalized_rows = _normalized_scheduling_rows(scheduling, question_ids)
    scoped_ids = _scope_question_ids(course, normalized_rows)
    mastered = _mastered_topics(mastery_overrides, course_id)
    candidate_ids = {
        question_id
        for question_id in scoped_ids
        if normalized_rows[question_id][0] not in mastered
    }
    topic_index = {
        question_id: (row[0], row[1])
        for question_id, row in normalized_rows.items()
        if question_id in candidate_ids
    }
    difficulty_index = {
        question_id: row[2]
        for question_id, row in normalized_rows.items()
        if question_id in candidate_ids
    }
    profile = getattr(course, "generation_profile", {}) or {}
    exam_weights = (
        profile.get("topic_weights", {})
        if isinstance(profile, Mapping)
        else {}
    )
    try:
        queue = build_daily_study_queue(
            candidate_ids,
            progress_records,
            topic_index=topic_index,
            difficulty_index=difficulty_index,
            exam_scope_weights=exam_weights,
        )
    except (OSError, TypeError, ValueError):
        queue = None
    if queue is None:
        return CourseAgenda(
            course_id=course_id,
            title=title,
            total_question_count=len(candidate_ids),
        )
    category_counts = tuple(
        sorted(
            (
                _category_value(category),
                max(0, int(count or 0)),
            )
            for category, count in (queue.category_counts or {}).items()
            if _category_value(category)
        )
    )
    signals = _topic_signals(candidate_ids, topic_index, progress_records)
    focus_topic_id, focus_topic_title, incorrect_count, unsure_count = _focus_topic(
        signals
    )
    exam_days = _exam_days_remaining(
        exam_goal_store,
        course_id,
        reference_date,
    )
    plan_id, today_ids, remaining_ids, actionable_count = _daily_plan_state(
        daily_plan_store,
        course_id=course_id,
        reference_date=reference_date,
        queue=queue,
        candidate_ids=candidate_ids,
    )
    return CourseAgenda(
        course_id=course_id,
        title=title,
        total_question_count=len(candidate_ids),
        total_actionable_count=actionable_count,
        today_question_count=len(today_ids),
        current_question_count=len(today_ids),
        plan_id=plan_id,
        today_question_ids=today_ids,
        remaining_question_ids=remaining_ids,
        due_count=_category_count(category_counts, StudyQueueCategory.DUE.value),
        incorrect_count=incorrect_count,
        unsure_count=unsure_count,
        exam_days_remaining=exam_days,
        category_counts=category_counts,
        focus_topic_id=focus_topic_id,
        focus_topic_title=focus_topic_title,
    )


def _daily_plan_state(
    daily_plan_store,
    *,
    course_id: str,
    reference_date: date,
    queue,
    candidate_ids: set[str],
) -> tuple[str, tuple[str, ...], tuple[str, ...], int]:
    """Return pending state from storage, with a deterministic queue fallback."""
    current_ids = tuple(getattr(queue, "current_question_ids", ()) or ())
    remaining_ids = tuple(getattr(queue, "remaining_question_ids", ()) or ())
    fallback = (
        "",
        current_ids,
        remaining_ids,
        max(0, int(getattr(queue, "backlog_count", 0) or 0)),
    )
    if daily_plan_store is None:
        return fallback
    plan_id = f"{reference_date.isoformat()}:{course_id}"
    getter = getattr(daily_plan_store, "get_or_create", None)
    if not callable(getter):
        return fallback
    try:
        plan = getter(
            plan_id=plan_id,
            plan_date=reference_date.isoformat(),
            course_id=course_id,
            queue=queue,
            valid_question_ids=set(candidate_ids),
        )
        if plan is None:
            return fallback
        next_session = getattr(plan, "next_session", None)
        if not callable(next_session):
            return fallback
        plan_current, plan_remaining = next_session()
        pending = tuple(
            str(question_id or "").strip()
            for question_id in (getattr(plan, "pending_ids", ()) or ())
            if str(question_id or "").strip()
        )
        return (
            str(getattr(plan, "plan_id", "") or plan_id).strip() or plan_id,
            tuple(plan_current or ()),
            tuple(plan_remaining or ()),
            len(pending),
        )
    except (OSError, TypeError, ValueError):
        return fallback


def _normalized_scheduling_rows(scheduling, question_ids: set[str]):
    rows: dict[str, tuple[str, str, str]] = {}
    for question_id in question_ids:
        raw = scheduling.get(question_id) if isinstance(scheduling, Mapping) else None
        if isinstance(raw, (tuple, list)) and len(raw) >= 3:
            topic_id = str(raw[0] or "").strip()
            title = str(raw[1] or topic_id).strip() or topic_id
            difficulty = str(raw[2] or "medium").strip() or "medium"
        else:
            topic_id, title, difficulty = "", "", "medium"
        rows[question_id] = (topic_id, title, difficulty)
    return rows


def _scope_question_ids(course, rows: Mapping[str, tuple[str, str, str]]) -> set[str]:
    allowed_topics: set[str] | None = None
    if str(getattr(course, "exam_scope_mode", "all") or "all") == "selected":
        exam_topics = getattr(course, "exam_topics", None)
        topics = exam_topics() if callable(exam_topics) else getattr(course, "topics", ())
        allowed_topics = {
            str(getattr(topic, "topic_id", topic) or "").strip()
            for topic in (topics or ())
            if str(getattr(topic, "topic_id", topic) or "").strip()
        }
    return {
        question_id
        for question_id, (topic_id, _title, _difficulty) in rows.items()
        if allowed_topics is None or topic_id in allowed_topics
    }


def _mastered_topics(mastery_overrides, course_id: str) -> set[str]:
    if mastery_overrides is None:
        return set()
    getter = getattr(mastery_overrides, "mastered_topics", None)
    if not callable(getter):
        return set()
    try:
        return {
            str(topic_id or "").strip()
            for topic_id in getter(course_id)
            if str(topic_id or "").strip()
        }
    except (OSError, TypeError, ValueError):
        return set()


def _topic_signals(candidate_ids, topic_index, records):
    signals: dict[str, dict[str, int | str]] = {}
    for question_id, row in topic_index.items():
        if question_id not in candidate_ids:
            continue
        topic_id = str(row[0] or "").strip()
        if not topic_id:
            continue
        signals.setdefault(topic_id, {
            "title": str(row[1] or topic_id).strip() or topic_id,
            "incorrect": 0,
            "unsure": 0,
        })
    for record in records:
        if getattr(record, "status", "") != "completed":
            continue
        for answer in getattr(record, "answers", ()) or ():
            question_id = str(getattr(answer, "question_id", "") or "").strip()
            row = topic_index.get(question_id)
            if not row:
                continue
            topic_id = str(row[0] or "").strip()
            signal = signals.get(topic_id)
            if signal is None or getattr(answer, "skipped", False):
                continue
            if not getattr(answer, "is_correct", False):
                signal["incorrect"] = int(signal["incorrect"]) + 1
            if str(getattr(answer, "confidence", "sure") or "sure") == "unsure":
                signal["unsure"] = int(signal["unsure"]) + 1
    return signals


def _focus_topic(signals):
    if not signals:
        return "", "", 0, 0
    topic_id, signal = min(
        signals.items(),
        key=lambda item: (
            -(int(item[1]["incorrect"]) * 2 + int(item[1]["unsure"])),
            str(item[1]["title"]).casefold(),
            item[0],
        ),
    )
    incorrect = int(signal["incorrect"])
    unsure = int(signal["unsure"])
    if incorrect == 0 and unsure == 0:
        return "", "", 0, 0
    return topic_id, str(signal["title"]), incorrect, unsure


def _exam_days_remaining(exam_goal_store, course_id: str, reference_date: date):
    if exam_goal_store is None:
        return None
    getter = getattr(exam_goal_store, "get", None)
    if not callable(getter):
        return None
    try:
        goal = getter(course_id)
        if goal is None:
            return None
        days = getattr(goal, "days_remaining", None)
        if not callable(days):
            return None
        try:
            return max(0, int(days(reference_date)))
        except TypeError:
            return max(0, int(days()))
    except (OSError, TypeError, ValueError):
        return None


def _category_value(category) -> str:
    return str(getattr(category, "value", category) or "").strip()


def _category_count(category_counts, category: str) -> int:
    return next(
        (count for value, count in category_counts if value == category),
        0,
    )


def _agenda_sort_key(item: CourseAgenda, current_course_id: str):
    return (
        0 if item.exam_days_remaining is not None else 1,
        item.exam_days_remaining if item.exam_days_remaining is not None else inf,
        0 if item.has_work else 1,
        -item.due_count,
        -item.incorrect_count,
        0 if item.course_id == current_course_id else 1,
        item.title.casefold(),
        item.course_id,
    )
