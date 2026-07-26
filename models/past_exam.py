"""Persistent historical-exam source records and extracted content."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import shutil
import threading
from typing import Optional
from uuid import uuid4

from config import PAST_EXAMS_DIR
from utils.json_io import read_json, sanitize_filename_part, write_json
from utils.logger import warning


class PastExamStateConflict(RuntimeError):
    """Raised when a background result no longer matches the current exam state."""


@dataclass(frozen=True)
class PastExamContent:
    text: str
    pages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"text": self.text, "pages": list(self.pages)}

    @classmethod
    def from_dict(cls, data: dict) -> "PastExamContent":
        return cls(
            text=str(data.get("text", "") or ""),
            pages=[str(page or "") for page in data.get("pages", []) or []],
        )


@dataclass(frozen=True)
class PastExamQuestionTypeProfile:
    question_type: str
    count: int
    confidence: float
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "question_type": self.question_type,
            "count": self.count,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PastExamQuestionTypeProfile":
        return cls(
            question_type=str(data.get("question_type", "") or ""),
            count=max(0, int(data.get("count", 0) or 0)),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            evidence=tuple(str(item) for item in data.get("evidence", []) or []),
        )


@dataclass(frozen=True)
class PastExamTopicProfile:
    topic_id: str
    topic_title: str
    weight: int
    match_count: int
    matched_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "topic_title": self.topic_title,
            "weight": self.weight,
            "match_count": self.match_count,
            "matched_terms": list(self.matched_terms),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PastExamTopicProfile":
        return cls(
            topic_id=str(data.get("topic_id", "") or ""),
            topic_title=str(data.get("topic_title", "") or ""),
            weight=max(0, int(data.get("weight", 0) or 0)),
            match_count=max(0, int(data.get("match_count", 0) or 0)),
            matched_terms=tuple(str(item) for item in data.get("matched_terms", []) or []),
        )


@dataclass(frozen=True)
class PastExamAnalysis:
    source_sha256: str
    analyzed_at: str
    detected_question_count: int
    question_types: tuple[PastExamQuestionTypeProfile, ...] = ()
    topic_profile: tuple[PastExamTopicProfile, ...] = ()
    warnings: tuple[str, ...] = ()
    method: str = "local_rules_v1"
    schema_version: int = 1

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_sha256": self.source_sha256,
            "analyzed_at": self.analyzed_at,
            "method": self.method,
            "detected_question_count": self.detected_question_count,
            "question_types": [item.to_dict() for item in self.question_types],
            "topic_profile": [item.to_dict() for item in self.topic_profile],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PastExamAnalysis":
        return cls(
            schema_version=max(1, int(data.get("schema_version", 1) or 1)),
            source_sha256=str(data.get("source_sha256", "") or ""),
            analyzed_at=str(data.get("analyzed_at", "") or ""),
            method=str(data.get("method", "local_rules_v1") or "local_rules_v1"),
            detected_question_count=max(0, int(data.get("detected_question_count", 0) or 0)),
            question_types=tuple(
                PastExamQuestionTypeProfile.from_dict(item)
                for item in data.get("question_types", []) or []
                if isinstance(item, dict)
            ),
            topic_profile=tuple(
                PastExamTopicProfile.from_dict(item)
                for item in data.get("topic_profile", []) or []
                if isinstance(item, dict)
            ),
            warnings=tuple(str(item) for item in data.get("warnings", []) or []),
        )


@dataclass(frozen=True)
class PastExamRecord:
    exam_id: str
    title: str
    source_filename: str
    source_path: str
    content_path: str
    source_sha256: str
    imported_at: str
    course_id: str = ""
    assignment_mode: str = "unassigned"
    match_candidates: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    analysis_status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "exam_id": self.exam_id,
            "title": self.title,
            "source_filename": self.source_filename,
            "source_path": self.source_path,
            "content_path": self.content_path,
            "source_sha256": self.source_sha256,
            "imported_at": self.imported_at,
            "course_id": self.course_id,
            "assignment_mode": self.assignment_mode,
            "match_candidates": list(self.match_candidates),
            "warnings": list(self.warnings),
            "analysis_status": self.analysis_status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PastExamRecord":
        return cls(
            exam_id=str(data.get("exam_id", "") or ""),
            title=str(data.get("title", "") or ""),
            source_filename=str(data.get("source_filename", "") or ""),
            source_path=str(data.get("source_path", "") or ""),
            content_path=str(data.get("content_path", "content.json") or "content.json"),
            source_sha256=str(data.get("source_sha256", "") or ""),
            imported_at=str(data.get("imported_at", "") or ""),
            course_id=str(data.get("course_id", "") or ""),
            assignment_mode=str(data.get("assignment_mode", "unassigned") or "unassigned"),
            match_candidates=[
                dict(candidate)
                for candidate in data.get("match_candidates", []) or []
                if isinstance(candidate, dict)
            ],
            warnings=[str(warning) for warning in data.get("warnings", []) or []],
            analysis_status=str(data.get("analysis_status", "pending") or "pending"),
        )


class PastExamManager:
    """Persistence and safe path resolution for imported historical exams."""

    def __init__(self, exams_dir: str | Path = PAST_EXAMS_DIR):
        self._dir = Path(exams_dir)
        self._lock = threading.RLock()
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> str:
        return str(self._dir)

    def exam_directory(self, exam_id: str) -> Path:
        return self._dir / sanitize_filename_part(exam_id)

    def save_record(self, record: PastExamRecord) -> bool:
        return write_json(
            str(self.exam_directory(record.exam_id) / "record.json"),
            record.to_dict(),
        )

    def save_content(self, exam_id: str, content: PastExamContent) -> bool:
        return write_json(
            str(self.exam_directory(exam_id) / "content.json"),
            content.to_dict(),
        )

    def get(self, exam_id: str) -> Optional[PastExamRecord]:
        try:
            path = self.exam_directory(exam_id) / "record.json"
        except ValueError:
            return None
        data = read_json(str(path))
        return PastExamRecord.from_dict(data) if isinstance(data, dict) else None

    def get_content(self, exam_id: str) -> Optional[PastExamContent]:
        try:
            path = self.exam_directory(exam_id) / "content.json"
        except ValueError:
            return None
        data = read_json(str(path))
        return PastExamContent.from_dict(data) if isinstance(data, dict) else None

    def save_analysis(self, exam_id: str, analysis: PastExamAnalysis) -> bool:
        return write_json(
            str(self.exam_directory(exam_id) / "analysis.json"),
            analysis.to_dict(),
        )

    def get_analysis(self, exam_id: str) -> Optional[PastExamAnalysis]:
        record = self.get(exam_id)
        if record is None or record.analysis_status != "complete":
            return None
        data = read_json(str(self.exam_directory(exam_id) / "analysis.json"))
        if not isinstance(data, dict):
            return None
        analysis = PastExamAnalysis.from_dict(data)
        if analysis.source_sha256 != record.source_sha256:
            return None
        return analysis

    def publish_analysis(
        self,
        exam_id: str,
        analysis: PastExamAnalysis,
        *,
        expected_course_id: str,
        expected_source_sha256: str,
    ) -> PastExamRecord:
        """Conditionally publish analysis without overwriting newer assignment state."""
        with self._lock:
            current = self.get(exam_id)
            if (
                current is None
                or current.course_id != expected_course_id
                or current.source_sha256 != expected_source_sha256
            ):
                raise PastExamStateConflict(
                    "Historical exam changed during analysis; run analysis again"
                )
            if analysis.source_sha256 != expected_source_sha256:
                raise PastExamStateConflict(
                    "Historical exam source changed during analysis; run analysis again"
                )
            if not self.save_analysis(exam_id, analysis):
                raise OSError("Failed to save historical exam analysis")
            completed = replace(current, analysis_status="complete")
            if not self.save_record(completed):
                raise OSError("Failed to mark historical exam analysis complete")
            return completed

    def load_all(self) -> list[PastExamRecord]:
        records = []
        for path in self._dir.glob("*/record.json"):
            data = read_json(str(path))
            if isinstance(data, dict):
                record = PastExamRecord.from_dict(data)
                if not record.exam_id:
                    continue
                try:
                    safe_id = sanitize_filename_part(record.exam_id)
                except ValueError:
                    continue
                if path.parent.name != safe_id:
                    continue
                records.append(record)
        return sorted(records, key=lambda record: record.imported_at, reverse=True)

    def find_by_hash(self, source_sha256: str) -> Optional[PastExamRecord]:
        normalized = str(source_sha256 or "").strip().lower()
        if not normalized:
            return None
        return next(
            (
                record
                for record in self.load_all()
                if record.source_sha256.lower() == normalized
            ),
            None,
        )

    def reassign_course(self, exam_id: str, course_id: str) -> Optional[PastExamRecord]:
        """Persist a user-confirmed course assignment, or explicit unassignment."""
        with self._lock:
            record = self.get(exam_id)
            if record is None:
                return None
            normalized_course_id = str(course_id or "").strip()
            course_changed = normalized_course_id != record.course_id
            updated = replace(
                record,
                course_id=normalized_course_id,
                assignment_mode="manual" if normalized_course_id else "unassigned",
                analysis_status="pending" if course_changed else record.analysis_status,
            )
            if not self.save_record(updated):
                raise OSError(f"Failed to update historical exam {exam_id}")
            if course_changed:
                analysis_path = self.exam_directory(exam_id) / "analysis.json"
                try:
                    analysis_path.unlink(missing_ok=True)
                except OSError:
                    # The pending record status prevents stale analysis from being consumed.
                    pass
            return updated

    def delete(self, exam_id: str) -> bool:
        """Atomically remove one app-managed exam record and all linked files."""
        with self._lock:
            try:
                exam_dir = self.exam_directory(exam_id)
            except ValueError:
                return False
            if not exam_dir.is_dir():
                return False
            tombstone = self._dir.parent / (
                f".{self._dir.name}-{exam_dir.name}-{uuid4().hex}.deleted"
            )
            try:
                exam_dir.replace(tombstone)
            except OSError as exc:
                raise OSError(
                    f"Failed to remove historical exam {exam_id}"
                ) from exc
        try:
            shutil.rmtree(tombstone)
        except OSError as exc:
            warning(
                f"Historical exam {exam_id} was removed but temporary cleanup "
                f"failed: {exc}"
            )
        return True

    def resolve_source_path(self, record: PastExamRecord) -> Path:
        exam_dir = self.exam_directory(record.exam_id).resolve()
        resolved = (exam_dir / record.source_path).resolve()
        try:
            resolved.relative_to(exam_dir)
        except ValueError as exc:
            raise ValueError("Historical exam source path escapes its record directory") from exc
        return resolved
