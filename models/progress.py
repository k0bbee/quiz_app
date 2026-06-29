"""Progress tracking data models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class AnswerRecord:
    """A single answer given during a quiz session."""

    question_id: str
    index_in_session: int
    user_answer: object  # str for choice, list for matching/ordering, etc.
    is_correct: bool
    skipped: bool = False
    confidence: str = "sure"  # "sure" or "unsure"
    time_spent_seconds: float = 0.0
    attempted_at: str = ""

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "index_in_session": self.index_in_session,
            "user_answer": self.user_answer,
            "is_correct": self.is_correct,
            "skipped": self.skipped,
            "confidence": self.confidence,
            "time_spent_seconds": self.time_spent_seconds,
            "attempted_at": self.attempted_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AnswerRecord:
        return cls(
            question_id=data.get("question_id", ""),
            index_in_session=data.get("index_in_session", 0),
            user_answer=data.get("user_answer"),
            is_correct=data.get("is_correct", False),
            skipped=data.get("skipped", False),
            confidence=data.get("confidence", "sure"),
            time_spent_seconds=data.get("time_spent_seconds", 0.0),
            attempted_at=data.get("attempted_at", ""),
        )


@dataclass
class SessionSummary:
    """Aggregated stats for a completed session."""

    total_questions: int
    answered: int
    correct: int
    incorrect: int = 0
    score_percentage: float = 0.0
    total_time_seconds: float = 0.0
    average_time_per_question: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_questions": self.total_questions,
            "answered": self.answered,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "score_percentage": round(self.score_percentage, 1),
            "total_time_seconds": round(self.total_time_seconds, 1),
            "average_time_per_question": round(self.average_time_per_question, 1),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionSummary:
        return cls(
            total_questions=data.get("total_questions", 0),
            answered=data.get("answered", 0),
            correct=data.get("correct", 0),
            incorrect=data.get("incorrect", 0),
            score_percentage=data.get("score_percentage", 0.0),
            total_time_seconds=data.get("total_time_seconds", 0.0),
            average_time_per_question=data.get("average_time_per_question", 0.0),
        )

    @classmethod
    def compute(cls, answers: list[AnswerRecord], total_questions: int, total_time: float) -> SessionSummary:
        """Compute summary from a list of answers."""
        answered = len(answers)
        correct = sum(1 for a in answers if a.is_correct)
        incorrect = answered - correct
        score = (correct / total_questions * 100) if total_questions > 0 else 0.0
        avg_time = (total_time / answered) if answered > 0 else 0.0
        return cls(
            total_questions=total_questions,
            answered=answered,
            correct=correct,
            incorrect=incorrect,
            score_percentage=score,
            total_time_seconds=total_time,
            average_time_per_question=avg_time,
        )


@dataclass
class ProgressRecord:
    """Full progress record for one quiz session."""

    progress_id: str
    set_id: str
    language: str  # "zh" or "en"
    started_at: str
    completed_at: str = ""
    status: str = "in_progress"  # "in_progress", "completed", "abandoned"
    answers: list[AnswerRecord] = field(default_factory=list)
    summary: Optional[SessionSummary] = None
    marked_review_question_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "progress_id": self.progress_id,
            "set_id": self.set_id,
            "language": self.language,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "answers": [a.to_dict() for a in self.answers],
            "summary": self.summary.to_dict() if self.summary is not None else None,
            "marked_review_question_ids": list(self.marked_review_question_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProgressRecord:
        answers = [AnswerRecord.from_dict(a) for a in data.get("answers", [])]
        summary = SessionSummary.from_dict(data["summary"]) if data.get("summary") else None
        return cls(
            progress_id=data.get("progress_id", ""),
            set_id=data.get("set_id", ""),
            language=data.get("language", "zh"),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            status=data.get("status", "in_progress"),
            answers=answers,
            summary=summary,
            marked_review_question_ids=list(data.get("marked_review_question_ids", [])),
        )

    @classmethod
    def create_new(cls, set_id: str, language: str = "zh") -> ProgressRecord:
        pid = f"progress-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            progress_id=pid,
            set_id=set_id,
            language=language,
            started_at=now,
        )
