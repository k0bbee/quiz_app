"""Validated, staged and rollback-safe standalone progress import."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile

from core.background_task import BackgroundTaskCancelled, TaskControl
from core.input_limits import (
    InputLimitError,
    MAX_PROGRESS_IMPORT_BYTES,
    MAX_PROGRESS_IMPORT_RECORDS,
)
from core.progress_archive import ProgressArchiveMigrator
from core.progress_tracker import ProgressManager
from models.course_project import CourseProjectManager
from models.progress import ProgressRecord
from models.question import QuestionBank
from models.question_set import SetManager
from utils.json_io import sanitize_filename_part, write_json


@dataclass(frozen=True)
class ProgressImportResult:
    imported: int
    overwritten: int = 0
    invalid: int = 0
    invalid_details: tuple[str, ...] = ()
    migrated_complete: int = 0
    migrated_incomplete: int = 0


class ProgressImportError(ValueError):
    def __init__(self, code: str, message_zh: str, message_en: str):
        super().__init__(f"[{code}] {message_en}")
        self.code = code
        self.message_zh = message_zh
        self.message_en = message_en


class ProgressImportValidationError(ProgressImportError):
    pass


class ProgressImportCommitError(ProgressImportError):
    pass


class ProgressImportService:
    """Import progress without exposing partially written records."""

    def __init__(
        self,
        *,
        progress_manager: ProgressManager,
        question_bank,
        set_manager,
        course_manager,
    ):
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.course_manager = course_manager

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> "ProgressImportService":
        root = Path(data_dir)
        return cls(
            progress_manager=ProgressManager(str(root / "progress")),
            question_bank=QuestionBank(str(root / "questions")),
            set_manager=SetManager(str(root / "question_sets")),
            course_manager=CourseProjectManager(
                str(root / "courses"),
                current_course_file=root / "current_course.json",
            ),
        )

    def import_file(
        self,
        source_path: str | Path,
        *,
        task: TaskControl | None = None,
    ) -> ProgressImportResult:
        source = Path(source_path)
        _report(task, "validating", detail=source.name)
        try:
            source_size = source.stat().st_size
        except OSError as exc:
            raise ProgressImportValidationError(
                "PROGRESS-IMPORT-001",
                f"无法读取进度文件：{exc}",
                f"Could not read the progress file: {exc}",
            ) from exc
        if source_size > MAX_PROGRESS_IMPORT_BYTES:
            raise InputLimitError(
                "PROGRESS-IMPORT-002",
                f"进度文件超过 {MAX_PROGRESS_IMPORT_BYTES} 字节上限。",
                f"Progress file exceeds the {MAX_PROGRESS_IMPORT_BYTES}-byte limit.",
            )
        try:
            with source.open("r", encoding="utf-8-sig") as stream:
                payload = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProgressImportValidationError(
                "PROGRESS-IMPORT-003",
                f"进度文件不是有效的 UTF-8 JSON：{exc}",
                f"The progress file is not valid UTF-8 JSON: {exc}",
            ) from exc
        if not isinstance(payload, list):
            raise ProgressImportValidationError(
                "PROGRESS-IMPORT-004",
                "进度文件顶层必须是记录列表。",
                "The progress file must contain a top-level list of records.",
            )
        if len(payload) > MAX_PROGRESS_IMPORT_RECORDS:
            raise InputLimitError(
                "PROGRESS-IMPORT-005",
                f"进度记录超过 {MAX_PROGRESS_IMPORT_RECORDS} 条上限。",
                f"Progress record count exceeds the {MAX_PROGRESS_IMPORT_RECORDS} limit.",
            )

        records: list[ProgressRecord] = []
        invalid_details: list[str] = []
        seen_ids: set[str] = set()
        total = len(payload)
        for index, raw_record in enumerate(payload, start=1):
            _report(task, "validating", index, total, f"record {index}")
            try:
                record = _parse_progress_record(raw_record)
                if record.progress_id in seen_ids:
                    raise ValueError("duplicate progress_id")
                seen_ids.add(record.progress_id)
                records.append(record)
            except (TypeError, ValueError) as exc:
                invalid_details.append(f"record {index}: {exc}")

        staged_store = _StagedProgressStore(records)
        migration_results = ProgressArchiveMigrator(
            progress_manager=staged_store,
            question_bank=self.question_bank,
            set_manager=self.set_manager,
            course_manager=self.course_manager,
        ).migrate_all()
        migration_errors = [
            outcome.error for outcome in migration_results if outcome.error
        ]
        if migration_errors:
            raise ProgressImportValidationError(
                "PROGRESS-IMPORT-006",
                "旧历史迁移未完成，未写入任何记录。",
                "Legacy history migration failed; no records were written.",
            )

        final_records = staged_store.load_all()
        overwritten = sum(
            self.progress_manager.get(record.progress_id) is not None
            for record in final_records
        )
        if final_records:
            self._commit_records(final_records, task=task)
        if task is not None:
            task.complete("saved", str(len(final_records)))
        return ProgressImportResult(
            imported=len(final_records),
            overwritten=overwritten,
            invalid=len(invalid_details),
            invalid_details=tuple(invalid_details),
            migrated_complete=sum(
                outcome.changed and outcome.status == "complete"
                for outcome in migration_results
            ),
            migrated_incomplete=sum(
                outcome.status == "incomplete"
                for outcome in migration_results
            ),
        )

    def _commit_records(
        self,
        records: list[ProgressRecord],
        *,
        task: TaskControl | None,
    ) -> None:
        target_dir = Path(self.progress_manager.directory)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".progress-import-",
            dir=target_dir.parent,
        ) as temporary_directory:
            transaction_dir = Path(temporary_directory)
            staging_dir = transaction_dir / "staging"
            backup_dir = transaction_dir / "backup"
            staging_dir.mkdir(parents=True)
            backup_dir.mkdir(parents=True)
            ordered = sorted(records, key=lambda record: record.progress_id)
            total = len(ordered)
            staged: list[tuple[Path, Path, Path | None]] = []
            for index, record in enumerate(ordered, start=1):
                _report(
                    task,
                    "staging",
                    index,
                    total,
                    record.progress_id,
                )
                safe_id = sanitize_filename_part(record.progress_id)
                stage_path = staging_dir / f"{safe_id}.json"
                if not write_json(str(stage_path), record.to_dict()):
                    raise ProgressImportCommitError(
                        "PROGRESS-IMPORT-007",
                        f"无法暂存进度记录：{record.progress_id}",
                        f"Could not stage progress record: {record.progress_id}",
                    )
                target_path = target_dir / f"{safe_id}.json"
                backup_path = None
                if target_path.exists():
                    backup_path = backup_dir / target_path.name
                    shutil.copy2(target_path, backup_path)
                staged.append((stage_path, target_path, backup_path))

            committed: list[tuple[Path, Path | None]] = []
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                for index, (stage_path, target_path, backup_path) in enumerate(
                    staged,
                    start=1,
                ):
                    _report(
                        task,
                        "committing",
                        index,
                        total,
                        target_path.stem,
                    )
                    _replace_staged_file(stage_path, target_path)
                    committed.append((target_path, backup_path))
            except BackgroundTaskCancelled:
                _rollback_committed_files(committed)
                self.progress_manager.rebuild_index()
                raise
            except Exception as exc:
                _rollback_committed_files(committed)
                self.progress_manager.rebuild_index()
                raise ProgressImportCommitError(
                    "PROGRESS-IMPORT-008",
                    f"提交进度失败，已恢复原记录：{exc}",
                    f"Progress commit failed and original records were restored: {exc}",
                ) from exc
            self.progress_manager.rebuild_index()


class _StagedProgressStore:
    """In-memory migration target; disk is untouched until all records pass."""

    def __init__(self, records: list[ProgressRecord]):
        self._records = {
            record.progress_id: copy.deepcopy(record) for record in records
        }

    def load_all(self):
        return [copy.deepcopy(record) for record in self._records.values()]

    def get(self, progress_id: str):
        record = self._records.get(progress_id)
        return copy.deepcopy(record) if record is not None else None

    def save(self, record: ProgressRecord) -> bool:
        self._records[record.progress_id] = copy.deepcopy(record)
        return True


def _parse_progress_record(raw_record) -> ProgressRecord:
    if not isinstance(raw_record, dict):
        raise TypeError("record must be an object")
    raw_id = raw_record.get("progress_id")
    safe_id = sanitize_filename_part(raw_id)
    status = str(raw_record.get("status", "in_progress") or "in_progress")
    if status not in {"in_progress", "completed", "abandoned"}:
        raise ValueError(f"unsupported status: {status}")
    if not str(raw_record.get("started_at", "") or "").strip():
        raise ValueError("started_at is required")
    answers = raw_record.get("answers", [])
    if not isinstance(answers, list) or not all(
        isinstance(answer, dict) for answer in answers
    ):
        raise TypeError("answers must be a list of objects")
    summary = raw_record.get("summary")
    if summary is not None and not isinstance(summary, dict):
        raise TypeError("summary must be an object or null")
    record = ProgressRecord.from_dict(raw_record)
    record.progress_id = safe_id
    return record


def _replace_staged_file(source_path: Path, target_path: Path) -> None:
    os.replace(source_path, target_path)


def _rollback_committed_files(
    committed: list[tuple[Path, Path | None]],
) -> None:
    for target_path, backup_path in reversed(committed):
        try:
            target_path.unlink(missing_ok=True)
            if backup_path is not None and backup_path.exists():
                shutil.copy2(backup_path, target_path)
        except OSError:
            # Keep attempting remaining restores; the raised commit error still
            # tells the caller that the transaction did not finish.
            continue


def _report(
    task: TaskControl | None,
    stage: str,
    current: int = 0,
    total: int = 0,
    detail: str = "",
) -> None:
    if task is not None:
        task.report(stage, current, total, detail)
