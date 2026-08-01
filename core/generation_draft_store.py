"""Durable AI question drafts waiting for review and final save."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from typing import Callable
from uuid import uuid4

from ai.exam_plan import ExamGenerationPlan
from models.question import Question
from utils.json_io import read_json, write_json


_SCHEMA_VERSION = 2
_PUBLISH_DESTINATIONS = {"library", "practice_now"}
_REVIEW_STATES = {"accepted", "rejected", "pending"}
_STORE_LOCKS: dict[str, RLock] = {}
_STORE_LOCKS_GUARD = Lock()


def _lock_for_path(path: str) -> RLock:
    """Share a re-entrant lock between store instances for one JSON file."""
    key = str(Path(path).expanduser().resolve(strict=False))
    with _STORE_LOCKS_GUARD:
        lock = _STORE_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _STORE_LOCKS[key] = lock
        return lock


def _normalize_publish_destination(value: object) -> str:
    destination = str(value or "library").strip()
    return destination if destination in _PUBLISH_DESTINATIONS else "library"


def _normalize_review_state(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    state: dict[str, str] = {}
    for question_id, decision in value.items():
        clean_id = str(question_id or "").strip()
        clean_decision = str(decision or "").strip()
        if clean_id and clean_decision in _REVIEW_STATES:
            state[clean_id] = clean_decision
    return state


@dataclass(frozen=True)
class GenerationDraft:
    """One course-scoped generation result that has not become a question set."""

    draft_id: str
    course_id: str
    questions: tuple[Question, ...]
    question_set_title: str
    exam_plan: ExamGenerationPlan
    review_warnings_only: bool = False
    publish_destination: str = "library"
    review_state: dict[str, str] | None = None
    source: str = "manual"
    task_id: str = ""
    stage: str = "review_pending"
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "draft_id": self.draft_id,
            "course_id": self.course_id,
            "stage": self.stage,
            "questions": [question.to_dict() for question in self.questions],
            "question_set_title": self.question_set_title,
            "exam_plan": self.exam_plan.to_dict(),
            "review_warnings_only": self.review_warnings_only,
            "publish_destination": self.publish_destination,
            "review_state": dict(self.review_state or {}),
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
        draft_id = str(data.get("draft_id", "") or "").strip()
        if not draft_id:
            draft_id = f"legacy-{course_id}"
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
            draft_id=draft_id,
            course_id=course_id,
            questions=questions,
            question_set_title=str(
                data.get("question_set_title", "") or ""
            ).strip(),
            exam_plan=exam_plan,
            review_warnings_only=bool(data.get("review_warnings_only", False)),
            publish_destination=_normalize_publish_destination(
                data.get("publish_destination", "library")
            ),
            review_state=_normalize_review_state(data.get("review_state", {})),
            source=str(data.get("source", "manual") or "manual").strip()
            or "manual",
            task_id=str(data.get("task_id", "") or "").strip(),
            stage=stage,
            updated_at=str(data.get("updated_at", "") or "").strip(),
        )


class GenerationDraftStore:
    """Persist review-pending generation drafts by stable draft ID.

    ``get(course_id)`` remains a compatibility API and returns the newest
    draft. New callers can keep multiple sessions for the same course by
    supplying ``draft_id`` to :meth:`save`.
    """

    def __init__(
        self,
        filepath: str | Path,
        *,
        clock: Callable[[], str] | None = None,
    ):
        self._path = str(filepath)
        self._clock = clock or _utc_now
        self._lock = _lock_for_path(self._path)

    def get(self, course_id: str) -> GenerationDraft | None:
        course_id = str(course_id or "").strip()
        if not course_id:
            return None
        drafts = self.list_for_course(course_id)
        return drafts[0] if drafts else None

    def get_by_id(self, draft_id: str) -> GenerationDraft | None:
        draft_id = str(draft_id or "").strip()
        if not draft_id:
            return None
        with self._lock:
            data = self._load_payload()["drafts"].get(draft_id)
            if not isinstance(data, dict):
                return None
            try:
                draft = GenerationDraft.from_dict(data)
            except (TypeError, ValueError):
                return None
            return draft if draft.draft_id == draft_id else None

    def list_for_course(self, course_id: str) -> tuple[GenerationDraft, ...]:
        course_id = str(course_id or "").strip()
        if not course_id:
            return ()
        return tuple(
            draft
            for draft in self.list_all()
            if draft.course_id == course_id
        )

    def list_all(self) -> tuple[GenerationDraft, ...]:
        """Return every valid draft newest first without exposing storage rows."""
        with self._lock:
            drafts: list[GenerationDraft] = []
            for draft_id, data in self._load_payload()["drafts"].items():
                if not isinstance(data, dict):
                    continue
                try:
                    draft = GenerationDraft.from_dict(data)
                except (TypeError, ValueError):
                    continue
                if draft.draft_id == str(draft_id or "").strip():
                    drafts.append(draft)
            return tuple(
                sorted(
                    drafts,
                    key=lambda draft: (draft.updated_at, draft.course_id),
                    reverse=True,
                )
            )

    def save(
        self,
        *,
        course_id: str,
        draft_id: str = "",
        questions,
        question_set_title: str,
        exam_plan: ExamGenerationPlan,
        review_warnings_only: bool = False,
        publish_destination: str = "library",
        review_state: Mapping[str, str] | None = None,
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
        with self._lock:
            draft_id = str(draft_id or "").strip()
            if not draft_id:
                existing = self.get(course_id)
                draft_id = existing.draft_id if existing is not None else self.new_draft_id()
            if not questions:
                self.delete(course_id, draft_id=draft_id)
                return None
            draft = GenerationDraft(
                draft_id=draft_id,
                course_id=course_id,
                questions=questions,
                question_set_title=str(question_set_title or "").strip(),
                exam_plan=exam_plan,
                review_warnings_only=bool(review_warnings_only),
                publish_destination=_normalize_publish_destination(publish_destination),
                review_state=_normalize_review_state(review_state),
                source=str(source or "manual").strip() or "manual",
                task_id=str(task_id or "").strip(),
                updated_at=self._clock(),
            )
            payload = self._load_payload()
            existing = payload["drafts"].get(draft_id)
            if isinstance(existing, dict):
                existing_course_id = str(
                    existing.get("course_id", "") or ""
                ).strip()
                if existing_course_id and existing_course_id != course_id:
                    raise ValueError("draft_id already belongs to another course")
            payload["drafts"][draft_id] = draft.to_dict()
            if not write_json(self._path, payload):
                raise OSError("failed to persist generation draft")
            return draft

    def save_draft(
        self,
        draft: GenerationDraft,
        *,
        allow_course_change: bool = False,
    ) -> GenerationDraft:
        """Restore an already validated draft without changing its timestamp.

        Lifecycle rollback uses this path so a failed course removal can put
        the exact pending generation task back instead of silently creating a
        new session or losing its review metadata.
        """
        if not isinstance(draft, GenerationDraft):
            raise TypeError("draft must be a GenerationDraft")
        if not draft.course_id or not draft.draft_id:
            raise ValueError("draft course_id and draft_id are required")
        with self._lock:
            payload = self._load_payload()
            existing = payload["drafts"].get(draft.draft_id)
            if isinstance(existing, dict):
                existing_course_id = str(
                    existing.get("course_id", "") or ""
                ).strip()
                if (
                    existing_course_id
                    and existing_course_id != draft.course_id
                    and not allow_course_change
                ):
                    raise ValueError("draft_id already belongs to another course")
            payload["drafts"][draft.draft_id] = draft.to_dict()
            if not write_json(self._path, payload):
                raise OSError("failed to persist generation draft")
            return draft

    def delete(self, course_id: str = "", *, draft_id: str = "") -> bool:
        course_id = str(course_id or "").strip()
        draft_id = str(draft_id or "").strip()
        if not course_id and not draft_id:
            return True
        with self._lock:
            payload = self._load_payload()
            if draft_id:
                data = payload["drafts"].get(draft_id)
                if not isinstance(data, dict):
                    return True
                stored_course_id = str(data.get("course_id", "") or "").strip()
                if course_id and stored_course_id != course_id:
                    return False
                payload["drafts"].pop(draft_id, None)
            else:
                matching = [
                    key
                    for key, data in payload["drafts"].items()
                    if isinstance(data, dict)
                    and str(data.get("course_id", "") or "").strip() == course_id
                ]
                if not matching:
                    return True
                for key in matching:
                    payload["drafts"].pop(key, None)
            if not write_json(self._path, payload):
                raise OSError("failed to delete generation draft")
            return True

    @staticmethod
    def new_draft_id() -> str:
        return f"draft-{uuid4().hex}"

    def _load_payload(self) -> dict:
        payload = read_json(self._path) or {}
        if not isinstance(payload, dict):
            payload = {}
        raw_drafts = payload.get("drafts")
        if not isinstance(raw_drafts, dict):
            raw_drafts = {}
        drafts: dict[str, dict] = {}
        for storage_key, raw_data in raw_drafts.items():
            if not isinstance(raw_data, dict):
                continue
            data = dict(raw_data)
            course_id = str(data.get("course_id", "") or "").strip()
            draft_id = str(data.get("draft_id", "") or "").strip()
            if not draft_id:
                draft_id = str(storage_key or "").strip()
            if not draft_id or draft_id == course_id:
                draft_id = f"legacy-{course_id}" if course_id else ""
            if not draft_id:
                continue
            data["draft_id"] = draft_id
            drafts[draft_id] = data
        return {
            "schema_version": _SCHEMA_VERSION,
            "drafts": drafts,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
