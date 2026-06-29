"""Serializable quiz-session snapshots for full draft recovery."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from models.progress import AnswerRecord


@dataclass
class QuizSessionSnapshot:
    """Full in-progress quiz state that can be restored later."""

    snapshot_id: str
    set_id: str
    title: str
    question_order: list[str]
    current_index: int
    submitted_answers: list[AnswerRecord] = field(default_factory=list)
    draft_answers: dict[str, object] = field(default_factory=dict)
    unsure_question_ids: list[str] = field(default_factory=list)
    marked_review_question_ids: list[str] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""
    elapsed_seconds: float = 0.0
    language: str = "zh"
    mode: str = "practice"

    def to_dict(self) -> dict:
        """Serialize snapshot to JSON-compatible data."""
        return {
            "snapshot_id": self.snapshot_id,
            "set_id": self.set_id,
            "title": self.title,
            "question_order": list(self.question_order),
            "current_index": self.current_index,
            "submitted_answers": [answer.to_dict() for answer in self.submitted_answers],
            "draft_answers": dict(self.draft_answers),
            "unsure_question_ids": list(self.unsure_question_ids),
            "marked_review_question_ids": list(self.marked_review_question_ids),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "elapsed_seconds": self.elapsed_seconds,
            "language": self.language,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuizSessionSnapshot":
        """Deserialize snapshot from JSON-compatible data."""
        return cls(
            snapshot_id=data.get("snapshot_id", ""),
            set_id=data.get("set_id", ""),
            title=data.get("title", ""),
            question_order=list(data.get("question_order", [])),
            current_index=int(data.get("current_index", 0) or 0),
            submitted_answers=[
                AnswerRecord.from_dict(answer)
                for answer in data.get("submitted_answers", [])
            ],
            draft_answers=dict(data.get("draft_answers", {}) or {}),
            unsure_question_ids=list(data.get("unsure_question_ids", [])),
            marked_review_question_ids=list(data.get("marked_review_question_ids", [])),
            started_at=data.get("started_at", ""),
            updated_at=data.get("updated_at", ""),
            elapsed_seconds=float(data.get("elapsed_seconds", 0.0) or 0.0),
            language=data.get("language", "zh"),
            mode=data.get("mode", "practice"),
        )

    @classmethod
    def create_new(
        cls,
        set_id: str,
        title: str,
        question_order: list[str],
        language: str = "zh",
        mode: str = "practice",
    ) -> "QuizSessionSnapshot":
        """Create a new empty snapshot shell for a quiz session."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            snapshot_id=f"snapshot-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
            set_id=set_id,
            title=title,
            question_order=list(question_order),
            current_index=0,
            started_at=now,
            updated_at=now,
            language=language,
            mode=mode,
        )
