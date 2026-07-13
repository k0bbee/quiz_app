"""Transactional import pipeline for historical-exam source documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from core.document_parser import DocumentParser, SUPPORTED_EXTENSIONS
from core.past_exam_course_matcher import match_exam_to_courses
from models.past_exam import PastExamContent, PastExamManager, PastExamRecord


@dataclass(frozen=True)
class PastExamImportResult:
    record: PastExamRecord
    duplicate: bool = False


class PastExamImporter:
    """Parse, assign and atomically publish one historical-exam source."""

    def __init__(self, manager: PastExamManager, course_manager, parser=None):
        self.manager = manager
        self.course_manager = course_manager
        self.parser = parser or DocumentParser()

    def import_file(
        self,
        source_path: str | Path,
        *,
        title: str = "",
        manual_course_id: str | None = None,
        task=None,
    ) -> PastExamImportResult:
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Historical exam file not found: {source}")
        if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported historical exam file type: {source.suffix}")

        source_hash = _sha256_file(source, task=task)
        duplicate = self.manager.find_by_hash(source_hash)
        if duplicate is not None:
            return PastExamImportResult(duplicate, duplicate=True)

        document = self.parser.parse_file(source, task=task)
        if task is not None:
            task.check_cancelled()
        courses = self.course_manager.load_all() if self.course_manager is not None else []
        match = match_exam_to_courses(title or source.stem, document.text, courses)
        course_id, assignment_mode = self._assignment(manual_course_id, match.assigned_course_id)
        exam_id = _new_exam_id()
        source_relative = (Path("source") / source.name).as_posix()
        record = PastExamRecord(
            exam_id=exam_id,
            title=str(title or source.stem).strip() or source.stem,
            source_filename=source.name,
            source_path=source_relative,
            content_path="content.json",
            source_sha256=source_hash,
            imported_at=datetime.now(timezone.utc).isoformat(),
            course_id=course_id,
            assignment_mode=assignment_mode,
            match_candidates=[candidate.to_dict() for candidate in match.candidates],
            warnings=list(document.warnings),
        )
        content = PastExamContent(document.text, list(document.pages))
        self._publish(source, record, content, task=task)
        return PastExamImportResult(record)

    def _assignment(self, manual_course_id, automatic_course_id) -> tuple[str, str]:
        manual = str(manual_course_id or "").strip()
        if manual:
            if self.course_manager is None or self.course_manager.get(manual) is None:
                raise ValueError(f"Unknown course for historical exam: {manual}")
            return manual, "manual"
        if automatic_course_id:
            return automatic_course_id, "auto"
        return "", "unassigned"

    def _publish(self, source: Path, record: PastExamRecord, content: PastExamContent, task=None):
        root = Path(self.manager.directory)
        target = self.manager.exam_directory(record.exam_id)
        if target.exists():
            raise FileExistsError(f"Historical exam already exists: {record.exam_id}")

        with tempfile.TemporaryDirectory(prefix=".past-exam-import-", dir=root) as temp_dir:
            payload_dir = Path(temp_dir) / record.exam_id
            staged_source = payload_dir / record.source_path
            staged_source.parent.mkdir(parents=True, exist_ok=True)
            _copy_source(source, staged_source, task=task)
            if _sha256_file(staged_source) != record.source_sha256:
                raise OSError("Historical exam source changed during import")
            _write_json(payload_dir / "content.json", content.to_dict())
            _write_json(payload_dir / "record.json", record.to_dict())
            if task is not None:
                task.check_cancelled()
                task.report("publishing", detail=source.name)
            os.replace(payload_dir, target)


def _new_exam_id() -> str:
    return f"past-exam-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def _sha256_file(path: Path, task=None) -> str:
    digest = hashlib.sha256()
    total = path.stat().st_size
    current = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            current += len(chunk)
            if task is not None:
                task.check_cancelled()
                task.report("hashing_source", current, total, path.name)
    return digest.hexdigest()


def _copy_source(source: Path, destination: Path, task=None):
    total = source.stat().st_size
    current = 0
    with source.open("rb") as source_file, destination.open("wb") as destination_file:
        while True:
            chunk = source_file.read(1024 * 1024)
            if not chunk:
                break
            destination_file.write(chunk)
            current += len(chunk)
            if task is not None:
                task.check_cancelled()
                task.report("copying_source", current, total, source.name)
    shutil.copystat(source, destination)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
