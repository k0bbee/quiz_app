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


def build_today_learning_plan(
    *,
    total_questions: int,
    incorrect_question_ids,
    topic_index: dict[str, tuple[str, str]],
    progress_records,
    draft: DraftLearningState | None = None,
    has_course: bool = True,
    daily_queue=None,
) -> TodayLearningPlan:
    """Build a transparent recommendation from the current in-memory state."""
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

    if daily_queue is not None and total_questions > 0:
        current_ids = tuple(
            getattr(daily_queue, "current_question_ids", ()) or ()
        )
        remaining_ids = tuple(
            getattr(daily_queue, "remaining_question_ids", ()) or ()
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
            )
        return TodayLearningPlan(
            action=LearningPlanAction.DAILY_COMPLETE,
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
    topics = build_topic_learning(topic_index, progress_records)

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
                -item[1]["question_count"],
                item[1]["title"].casefold(),
                item[0],
            ),
        )
        return topic_id, row["title"]
    return "", ""


def build_topic_learning(topic_index, progress_records) -> dict[str, dict]:
    """Aggregate question and answer performance by topic.

    This is the shared read-only index used by the daily plan, home learning
    diagnosis, and course hub.  Keeping the mapping here prevents each view
    from applying subtly different skipped/unknown-question rules.
    """
    topics: dict[str, dict] = {}
    question_to_topic: dict[str, str] = {}
    for question_id, topic_row in (topic_index or {}).items():
        if not isinstance(topic_row, (tuple, list)) or len(topic_row) < 2:
            continue
        normalized_question_id = str(question_id or "").strip()
        topic_id = str(topic_row[0] or "").strip()
        if not normalized_question_id or not topic_id:
            continue
        title = str(topic_row[1] or topic_id).strip() or topic_id
        question_to_topic[normalized_question_id] = topic_id
        row = topics.setdefault(topic_id, {
            "title": title,
            "question_count": 0,
            "attempts": 0,
            "correct": 0,
            "incorrect": 0,
            "unsure": 0,
            "error_reasons": {},
            "recent": "",
        })
        row["question_count"] += 1

    for record in progress_records or ():
        if getattr(record, "status", "") != "completed":
            continue
        recent = str(
            getattr(record, "completed_at", "")
            or getattr(record, "started_at", "")
            or ""
        )[:10]
        for answer in getattr(record, "answers", ()) or ():
            if getattr(answer, "skipped", False):
                continue
            topic_id = question_to_topic.get(
                str(getattr(answer, "question_id", "") or "").strip()
            )
            if not topic_id:
                continue
            row = topics[topic_id]
            row["attempts"] += 1
            if getattr(answer, "is_correct", False):
                row["correct"] += 1
            else:
                row["incorrect"] += 1
                reason = str(getattr(answer, "error_reason", "") or "").strip()
                if reason:
                    row["error_reasons"][reason] = (
                        row["error_reasons"].get(reason, 0) + 1
                    )
            if str(getattr(answer, "confidence", "sure") or "sure") == "unsure":
                row["unsure"] += 1
            row["recent"] = max(row["recent"], recent)
    return topics


def _estimated_minutes(question_count: int) -> int:
    return max(5, question_count * 2) if question_count > 0 else 0
