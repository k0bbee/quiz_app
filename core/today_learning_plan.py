"""Deterministic daily learning-plan recommendations for the home screen."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LearningPlanAction(str, Enum):
    IMPORT_COURSE = "import_course"
    RESUME_DRAFT = "resume_draft"
    START_DAILY_QUEUE = "start_daily_queue"
    DAILY_COMPLETE = "daily_complete"
    REVIEW_INCORRECT = "review_incorrect"
    START_PRACTICE = "start_practice"
    GENERATE_QUESTIONS = "generate_questions"


@dataclass(frozen=True)
class DraftLearningState:
    title: str
    remaining_count: int
    mode: str = "practice"


@dataclass(frozen=True)
class TodayLearningPlan:
    action: LearningPlanAction
    target_question_count: int = 0
    review_question_count: int = 0
    estimated_minutes: int = 0
    draft_title: str = ""
    draft_mode: str = ""
    weak_topic_id: str = ""
    weak_topic_title: str = ""
    question_ids: tuple[str, ...] = ()
    remaining_question_ids: tuple[str, ...] = ()
    queue_counts: tuple[tuple[str, int], ...] = ()
    plan_id: str = ""
    plan_total_count: int = 0
    backlog_count: int = 0
    completed_count: int = 0
    remediation_count: int = 0
    deferred_count: int = 0


def build_today_learning_plan(
    *,
    total_questions: int,
    incorrect_question_ids,
    topic_index: dict[str, tuple[str, str]],
    progress_records,
    draft: DraftLearningState | None = None,
    has_course: bool = True,
    daily_queue=None,
    daily_plan=None,
    plan_id: str = "",
) -> TodayLearningPlan:
    """Build a transparent plan: draft, review, practice, then generation."""
    total_questions = max(0, int(total_questions or 0))
    incorrect_ids = tuple(dict.fromkeys(
        str(question_id)
        for question_id in (incorrect_question_ids or [])
        if str(question_id)
    ))

    if draft is not None and draft.remaining_count > 0:
        target = max(1, int(draft.remaining_count))
        return TodayLearningPlan(
            action=LearningPlanAction.RESUME_DRAFT,
            target_question_count=target,
            estimated_minutes=_estimated_minutes(target),
            draft_title=str(draft.title or "").strip(),
            draft_mode=draft.mode if draft.mode in {"exam", "practice"} else "practice",
        )

    if daily_plan is not None and total_questions > 0:
        current_ids, remaining_ids = daily_plan.next_session()
        counts = tuple(getattr(daily_plan, "category_counts", ()) or ())
        common = {
            "queue_counts": counts,
            "plan_id": str(getattr(daily_plan, "plan_id", "") or "").strip(),
            "plan_total_count": len(
                getattr(daily_plan, "planned_ids", ()) or ()
            ),
            "backlog_count": int(
                getattr(daily_plan, "backlog_count", 0) or 0
            ),
            "completed_count": len(
                getattr(daily_plan, "completed_ids", ()) or ()
            ),
            "remediation_count": len(
                getattr(daily_plan, "remediation_ids", ()) or ()
            ),
            "deferred_count": len(
                getattr(daily_plan, "deferred_ids", ()) or ()
            ),
        }
        if current_ids:
            pending_count = len(current_ids) + len(remaining_ids)
            return TodayLearningPlan(
                action=LearningPlanAction.START_DAILY_QUEUE,
                target_question_count=len(current_ids),
                estimated_minutes=_estimated_minutes(pending_count),
                question_ids=current_ids,
                remaining_question_ids=remaining_ids,
                **common,
            )
        return TodayLearningPlan(
            action=LearningPlanAction.DAILY_COMPLETE,
            **common,
        )

    if daily_queue is not None and total_questions > 0:
        current_ids = tuple(
            getattr(daily_queue, "current_question_ids", ()) or ()
        )
        remaining_ids = tuple(
            getattr(daily_queue, "remaining_question_ids", ()) or ()
        )
        counts = tuple(
            (str(getattr(category, "value", category)), int(count or 0))
            for category, count in (
                getattr(daily_queue, "category_counts", {}) or {}
            ).items()
        )
        if current_ids:
            return TodayLearningPlan(
                action=LearningPlanAction.START_DAILY_QUEUE,
                target_question_count=len(current_ids),
                estimated_minutes=int(
                    getattr(daily_queue, "estimated_minutes", 0) or 0
                ),
                question_ids=current_ids,
                remaining_question_ids=remaining_ids,
                queue_counts=counts,
                plan_id=str(plan_id or "").strip(),
                plan_total_count=len(current_ids) + len(remaining_ids),
                backlog_count=int(
                    getattr(daily_queue, "backlog_count", 0) or 0
                ),
            )
        return TodayLearningPlan(
            action=LearningPlanAction.DAILY_COMPLETE,
            queue_counts=counts,
            plan_id=str(plan_id or "").strip(),
            backlog_count=int(
                getattr(daily_queue, "backlog_count", 0) or 0
            ),
        )

    if incorrect_ids:
        target = min(10, len(incorrect_ids))
        return TodayLearningPlan(
            action=LearningPlanAction.REVIEW_INCORRECT,
            target_question_count=target,
            review_question_count=len(incorrect_ids),
            estimated_minutes=_estimated_minutes(target),
            question_ids=incorrect_ids[:target],
        )

    if total_questions > 0:
        weak_topic_id, weak_topic_title = _weak_topic(topic_index, progress_records)
        target = min(10, total_questions)
        return TodayLearningPlan(
            action=LearningPlanAction.START_PRACTICE,
            target_question_count=target,
            estimated_minutes=_estimated_minutes(target),
            weak_topic_id=weak_topic_id,
            weak_topic_title=weak_topic_title,
        )

    return TodayLearningPlan(
        action=(
            LearningPlanAction.GENERATE_QUESTIONS
            if has_course
            else LearningPlanAction.IMPORT_COURSE
        )
    )


def _weak_topic(topic_index, progress_records) -> tuple[str, str]:
    topics: dict[str, dict] = {}
    for question_id, topic_row in (topic_index or {}).items():
        if not isinstance(topic_row, (tuple, list)) or len(topic_row) < 2:
            continue
        topic_id = str(topic_row[0] or "").strip()
        if not topic_id:
            continue
        title = str(topic_row[1] or topic_id).strip() or topic_id
        row = topics.setdefault(topic_id, {
            "title": title,
            "questions": 0,
            "attempts": 0,
            "correct": 0,
        })
        row["questions"] += 1

    for record in progress_records or []:
        if getattr(record, "status", "") != "completed":
            continue
        for answer in getattr(record, "answers", []) or []:
            if getattr(answer, "skipped", False):
                continue
            topic_row = topic_index.get(getattr(answer, "question_id", ""))
            if not topic_row:
                continue
            topic_id = str(topic_row[0] or "").strip()
            if topic_id not in topics:
                continue
            topics[topic_id]["attempts"] += 1
            if getattr(answer, "is_correct", False):
                topics[topic_id]["correct"] += 1

    attempted = [
        (topic_id, row)
        for topic_id, row in topics.items()
        if row["attempts"] > 0
    ]
    if attempted:
        topic_id, row = min(
            attempted,
            key=lambda item: (
                item[1]["correct"] / item[1]["attempts"],
                item[1]["attempts"],
                item[1]["title"].casefold(),
                item[0],
            ),
        )
        return topic_id, row["title"]

    if topics:
        topic_id, row = min(
            topics.items(),
            key=lambda item: (
                -item[1]["questions"],
                item[1]["title"].casefold(),
                item[0],
            ),
        )
        return topic_id, row["title"]
    return "", ""


def _estimated_minutes(question_count: int) -> int:
    return max(5, question_count * 2) if question_count > 0 else 0
