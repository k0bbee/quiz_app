"""Deterministic state for the zero-to-first-practice experience."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ai.exam_plan import ExamGenerationPlan


class FirstRunStage(str, Enum):
    AI_SETUP = "ai_setup"
    MATERIALS = "materials"
    IMPORTING = "importing"
    GENERATE = "generate"
    GENERATING = "generating"
    REVIEW_PENDING = "review_pending"
    READY = "ready"


@dataclass(frozen=True)
class FirstRunState:
    stage: FirstRunStage
    ai_error: str = ""
    error: str = ""
    progress_text: str = ""
    progress_current: int = 0
    progress_total: int = 0
    question_count: int = 0
    draft_question_count: int = 0


def build_first_run_exam_plan(course_project) -> ExamGenerationPlan:
    """Build the single low-decision plan used before a user's first practice."""
    exam_topics = getattr(course_project, "exam_topics", None)
    topics = exam_topics() if callable(exam_topics) else getattr(
        course_project,
        "topics",
        [],
    )
    topic_ids = tuple(
        str(getattr(topic, "topic_id", "") or "").strip()
        for topic in topics
        if str(getattr(topic, "topic_id", "") or "").strip()
    )
    if not topic_ids:
        raise ValueError("The course has no available topics for generation.")
    return ExamGenerationPlan(
        question_count=10,
        difficulty="mixed",
        template="quick_review",
        selected_topics=topic_ids,
    )


def resolve_first_run_state(
    *,
    ai_error: str,
    has_course: bool,
    question_count: int,
    operation: str = "",
    error: str = "",
    progress_text: str = "",
    progress_current: int = 0,
    progress_total: int = 0,
    draft_question_count: int = 0,
) -> FirstRunState:
    """Resolve one visible stage from durable resources plus transient work."""
    normalized_operation = str(operation or "").strip().lower()
    if normalized_operation == "importing":
        stage = FirstRunStage.IMPORTING
    elif normalized_operation == "generating":
        stage = FirstRunStage.GENERATING
    elif has_course and int(question_count or 0) > 0:
        stage = FirstRunStage.READY
    elif has_course and int(draft_question_count or 0) > 0:
        stage = FirstRunStage.REVIEW_PENDING
    elif str(ai_error or "").strip():
        stage = FirstRunStage.AI_SETUP
    elif not has_course:
        stage = FirstRunStage.MATERIALS
    elif int(question_count or 0) <= 0:
        stage = FirstRunStage.GENERATE
    else:  # Defensive fallback for future resource states.
        stage = FirstRunStage.MATERIALS
    return FirstRunState(
        stage=stage,
        ai_error=str(ai_error or "").strip(),
        error=str(error or "").strip(),
        progress_text=str(progress_text or "").strip(),
        progress_current=max(0, int(progress_current or 0)),
        progress_total=max(0, int(progress_total or 0)),
        question_count=max(0, int(question_count or 0)),
        draft_question_count=max(0, int(draft_question_count or 0)),
    )
