"""Progress tracking data models."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


ERROR_REASON_VALUES = ("concept_gap", "misread", "guess")


@dataclass
class AnswerRecord:
    """A single answer given during a quiz session."""

    question_id: str
    index_in_session: int
    user_answer: object  # str for choice, list for matching/ordering, etc.
    is_correct: bool
    skipped: bool = False
    confidence: str = "sure"  # "sure" or "unsure"
    error_reason: str = ""  # concept_gap, misread, guess, or empty
    grading_method: str = "automatic"
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
            "error_reason": (
                self.error_reason if self.error_reason in ERROR_REASON_VALUES else ""
            ),
            "grading_method": self.grading_method,
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
            error_reason=(
                data.get("error_reason", "")
                if data.get("error_reason", "") in ERROR_REASON_VALUES
                else ""
            ),
            grading_method=data.get("grading_method", "automatic"),
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
    skipped: int = 0
    score_percentage: float = 0.0
    total_time_seconds: float = 0.0
    average_time_per_question: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_questions": self.total_questions,
            "answered": self.answered,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "skipped": self.skipped,
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
            skipped=data.get("skipped", 0),
            score_percentage=data.get("score_percentage", 0.0),
            total_time_seconds=data.get("total_time_seconds", 0.0),
            average_time_per_question=data.get("average_time_per_question", 0.0),
        )

    @classmethod
    def compute(cls, answers: list[AnswerRecord], total_questions: int, total_time: float) -> SessionSummary:
        """Compute summary from a list of answers."""
        skipped = sum(1 for answer in answers if answer.skipped)
        answered = len(answers) - skipped
        correct = sum(1 for a in answers if a.is_correct)
        incorrect = sum(1 for answer in answers if not answer.skipped and not answer.is_correct)
        score = (correct / total_questions * 100) if total_questions > 0 else 0.0
        avg_time = (total_time / answered) if answered > 0 else 0.0
        return cls(
            total_questions=total_questions,
            answered=answered,
            correct=correct,
            incorrect=incorrect,
            skipped=skipped,
            score_percentage=score,
            total_time_seconds=total_time,
            average_time_per_question=avg_time,
        )


@dataclass
class QuestionReviewSnapshot:
    """Question content preserved for reviewing a historical quiz attempt."""

    question_id: str
    question_type: str
    topic_id: str
    topic_title: str
    stem: str
    options: object
    correct_answer: object
    explanation: str
    source_refs: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "question_type": self.question_type,
            "topic_id": self.topic_id,
            "topic_title": self.topic_title,
            "stem": self.stem,
            "options": copy.deepcopy(self.options),
            "correct_answer": copy.deepcopy(self.correct_answer),
            "explanation": self.explanation,
            "source_refs": copy.deepcopy(self.source_refs),
        }

    @classmethod
    def from_dict(cls, data: dict) -> QuestionReviewSnapshot:
        return cls(
            question_id=str(data.get("question_id", "") or ""),
            question_type=str(data.get("question_type", "") or ""),
            topic_id=str(data.get("topic_id", "") or ""),
            topic_title=str(data.get("topic_title", "") or ""),
            stem=str(data.get("stem", "") or ""),
            options=copy.deepcopy(data.get("options", [])),
            correct_answer=copy.deepcopy(data.get("correct_answer")),
            explanation=str(data.get("explanation", "") or ""),
            source_refs=[
                copy.deepcopy(ref)
                for ref in (data.get("source_refs", []) or [])
                if isinstance(ref, dict)
            ],
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
    set_title_snapshot: str = ""
    course_id_snapshot: str = ""
    course_title_snapshot: str = ""
    question_snapshots: list[QuestionReviewSnapshot] = field(default_factory=list)
    archive_schema_version: int = 0
    archive_status: str = ""
    archive_missing_fields: list[str] = field(default_factory=list)

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
            "set_title_snapshot": self.set_title_snapshot,
            "course_id_snapshot": self.course_id_snapshot,
            "course_title_snapshot": self.course_title_snapshot,
            "question_snapshots": [
                snapshot.to_dict() for snapshot in self.question_snapshots
            ],
            "archive_schema_version": self.archive_schema_version,
            "archive_status": self.archive_status,
            "archive_missing_fields": list(self.archive_missing_fields),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProgressRecord:
        answers = [AnswerRecord.from_dict(a) for a in data.get("answers", [])]
        summary = SessionSummary.from_dict(data["summary"]) if data.get("summary") else None
        if summary is not None and answers:
            corrected = SessionSummary.compute(
                answers,
                total_questions=summary.total_questions,
                total_time=summary.total_time_seconds,
            )
            summary.answered = corrected.answered
            summary.correct = corrected.correct
            summary.incorrect = corrected.incorrect
            summary.skipped = corrected.skipped
            summary.score_percentage = corrected.score_percentage
            summary.average_time_per_question = corrected.average_time_per_question
        status = str(data.get("status", "in_progress") or "in_progress")
        archive_status = str(data.get("archive_status", "") or "")
        if "archive_status" not in data and status == "completed":
            archive_status = "legacy"
        try:
            archive_schema_version = max(
                0,
                int(data.get("archive_schema_version", 0) or 0),
            )
        except (TypeError, ValueError):
            archive_schema_version = 0
        return cls(
            progress_id=data.get("progress_id", ""),
            set_id=data.get("set_id", ""),
            language=data.get("language", "zh"),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            status=status,
            answers=answers,
            summary=summary,
            marked_review_question_ids=list(data.get("marked_review_question_ids", [])),
            set_title_snapshot=str(data.get("set_title_snapshot", "") or ""),
            course_id_snapshot=str(data.get("course_id_snapshot", "") or ""),
            course_title_snapshot=str(data.get("course_title_snapshot", "") or ""),
            question_snapshots=[
                QuestionReviewSnapshot.from_dict(snapshot)
                for snapshot in (data.get("question_snapshots", []) or [])
                if isinstance(snapshot, dict)
            ],
            archive_schema_version=archive_schema_version,
            archive_status=archive_status,
            archive_missing_fields=[
                str(field_name)
                for field_name in (data.get("archive_missing_fields", []) or [])
                if str(field_name or "").strip()
            ],
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
