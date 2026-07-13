"""Persistent historical-exam source records and extracted content."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from config import PAST_EXAMS_DIR
from utils.json_io import read_json, sanitize_filename_part, write_json


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

    def load_all(self) -> list[PastExamRecord]:
        records = []
        for path in self._dir.glob("*/record.json"):
            data = read_json(str(path))
            if isinstance(data, dict):
                record = PastExamRecord.from_dict(data)
                if record.exam_id:
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
        record = self.get(exam_id)
        if record is None:
            return None
        normalized_course_id = str(course_id or "").strip()
        updated = replace(
            record,
            course_id=normalized_course_id,
            assignment_mode="manual" if normalized_course_id else "unassigned",
        )
        if not self.save_record(updated):
            raise OSError(f"Failed to update historical exam {exam_id}")
        return updated

    def resolve_source_path(self, record: PastExamRecord) -> Path:
        exam_dir = self.exam_directory(record.exam_id).resolve()
        resolved = (exam_dir / record.source_path).resolve()
        try:
            resolved.relative_to(exam_dir)
        except ValueError as exc:
            raise ValueError("Historical exam source path escapes its record directory") from exc
        return resolved
