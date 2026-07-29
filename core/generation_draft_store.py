"""Durable AI question drafts waiting for review and final save."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ai.exam_plan import ExamGenerationPlan
from models.question import Question
from utils.json_io import read_json, write_json


_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GenerationDraft:
    """One course-scoped generation result that has not become a question set."""

    course_id: str
    questions: tuple[Question, ...]
    question_set_title: str
    exam_plan: ExamGenerationPlan
    review_warnings_only: bool = False
    source: str = "manual"
    task_id: str = ""
    stage: str = "review_pending"
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "course_id": self.course_id,
            "stage": self.stage,
            "questions": [question.to_dict() for question in self.questions],
            "question_set_title": self.question_set_title,
            "exam_plan": self.exam_plan.to_dict(),
            "review_warnings_only": self.review_warnings_only,
            "source": self.source,
            "task_id": self.task_id,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationDraft":
        if not isinstance(data, dict):
            raise TypeError("generation draft must be an object")
        course_id = str(data.get("course_id", "") or "").strip()
        if not course_id:
            raise ValueError("generation draft course_id is required")
        stage = str(data.get("stage", "") or "").strip()
        if stage != "review_pending":
            raise ValueError(f"unsupported generation draft stage: {stage}")
        question_rows = data.get("questions")
        if not isinstance(question_rows, list) or not question_rows:
            raise ValueError("generation draft questions must be a non-empty array")
        questions = tuple(
            Question.from_dict(row)
            for row in question_rows
            if isinstance(row, dict)
        )
        if not questions or any(not question.question_id for question in questions):
            raise ValueError("generation draft contains invalid questions")
        plan_data = data.get("exam_plan")
        if not isinstance(plan_data, dict):
            raise ValueError("generation draft exam_plan must be an object")
        exam_plan = ExamGenerationPlan(
            question_count=plan_data.get("question_count", len(questions)),
            difficulty=plan_data.get("difficulty", "medium"),
            template=plan_data.get("template", "quick_review"),
            selected_topics=plan_data.get("selected_topics", ()),
            question_type_weights=plan_data.get("question_type_weights", {}),
            difficulty_weights=plan_data.get("difficulty_weights", {}),
            topic_weights=plan_data.get("topic_weights", {}),
        )
        return cls(
            course_id=course_id,
            questions=questions,
            question_set_title=str(
                data.get("question_set_title", "") or ""
            ).strip(),
            exam_plan=exam_plan,
            review_warnings_only=bool(data.get("review_warnings_only", False)),
            source=str(data.get("source", "manual") or "manual").strip()
            or "manual",
            task_id=str(data.get("task_id", "") or "").strip(),
            stage=stage,
            updated_at=str(data.get("updated_at", "") or "").strip(),
        )


class GenerationDraftStore:
    """Persist one review-pending generation draft per course."""

    def __init__(
        self,
        filepath: str | Path,
        *,
        clock: Callable[[], str] | None = None,
    ):
        self._path = str(filepath)
        self._clock = clock or _utc_now

    def get(self, course_id: str) -> GenerationDraft | None:
        course_id = str(course_id or "").strip()
        if not course_id:
            return None
        data = self._load_payload()["drafts"].get(course_id)
        if not isinstance(data, dict):
            return None
        try:
            draft = GenerationDraft.from_dict(data)
        except (TypeError, ValueError):
            return None
        return draft if draft.course_id == course_id else None

    def save(
        self,
        *,
        course_id: str,
        questions,
        question_set_title: str,
        exam_plan: ExamGenerationPlan,
        review_warnings_only: bool = False,
        source: str = "manual",
        task_id: str = "",
    ) -> GenerationDraft | None:
        course_id = str(course_id or "").strip()
        if not course_id:
            raise ValueError("course_id is required")
        if not isinstance(exam_plan, ExamGenerationPlan):
            raise TypeError("exam_plan must be an ExamGenerationPlan")
        questions = tuple(
            question
            for question in (questions or ())
            if isinstance(question, Question) and question.question_id
        )
        if not questions:
            self.delete(course_id)
            return None
        draft = GenerationDraft(
            course_id=course_id,
            questions=questions,
            question_set_title=str(question_set_title or "").strip(),
            exam_plan=exam_plan,
            review_warnings_only=bool(review_warnings_only),
            source=str(source or "manual").strip() or "manual",
            task_id=str(task_id or "").strip(),
            updated_at=self._clock(),
        )
        payload = self._load_payload()
        payload["drafts"][course_id] = draft.to_dict()
        if not write_json(self._path, payload):
            raise OSError("failed to persist generation draft")
        return draft

    def delete(self, course_id: str) -> bool:
        course_id = str(course_id or "").strip()
        if not course_id:
            return True
        payload = self._load_payload()
        if course_id not in payload["drafts"]:
            return True
        payload["drafts"].pop(course_id, None)
        if not write_json(self._path, payload):
            raise OSError("failed to delete generation draft")
        return True

    def _load_payload(self) -> dict:
        payload = read_json(self._path) or {}
        if not isinstance(payload, dict):
            payload = {}
        drafts = payload.get("drafts")
        if not isinstance(drafts, dict):
            drafts = {}
        return {
            "schema_version": _SCHEMA_VERSION,
            "drafts": drafts,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
