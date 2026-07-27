"""Compatibility migration for immutable completed-quiz archives."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from models.progress import ProgressRecord, QuestionReviewSnapshot


ARCHIVE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProgressArchiveMigrationResult:
    """Outcome of migrating one completed progress record."""

    progress_id: str
    status: str
    changed: bool
    missing_fields: tuple[str, ...] = ()
    error: str = ""


class ProgressArchiveMigrator:
    """Backfill historical review data from assets that still exist."""

    def __init__(
        self,
        *,
        progress_manager,
        question_bank,
        set_manager,
        course_manager,
    ):
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.course_manager = course_manager

    def migrate_record(
        self,
        record: ProgressRecord,
    ) -> ProgressArchiveMigrationResult:
        if record.status != "completed":
            return ProgressArchiveMigrationResult(
                progress_id=record.progress_id,
                status=record.archive_status,
                changed=False,
            )
        if (
            record.archive_schema_version >= ARCHIVE_SCHEMA_VERSION
            and record.archive_status == "complete"
        ):
            return ProgressArchiveMigrationResult(
                progress_id=record.progress_id,
                status=record.archive_status,
                changed=False,
            )
        migrated = copy.deepcopy(record)
        question_set = self.set_manager.get(migrated.set_id)
        missing_fields: list[str] = []
        existing_snapshots = {
            snapshot.question_id: snapshot
            for snapshot in migrated.question_snapshots
            if snapshot.question_id
        }
        migrated_snapshots: list[QuestionReviewSnapshot] = []
        available_questions = []
        seen_question_ids = set()
        for answer in migrated.answers:
            question_id = str(answer.question_id or "").strip()
            if not question_id or question_id in seen_question_ids:
                continue
            seen_question_ids.add(question_id)
            existing_snapshot = existing_snapshots.get(question_id)
            if existing_snapshot is not None:
                migrated_snapshots.append(copy.deepcopy(existing_snapshot))
                continue
            question = self.question_bank.get(question_id)
            if question is None:
                missing_fields.append(f"question:{question_id}")
                continue
            available_questions.append(question)
            migrated_snapshots.append(
                _question_review_snapshot(question, migrated.language)
            )
        for question_id, snapshot in existing_snapshots.items():
            if question_id not in seen_question_ids:
                migrated_snapshots.append(copy.deepcopy(snapshot))
        if not migrated_snapshots:
            missing_fields.append("question_snapshots")

        if not migrated.set_title_snapshot and question_set is not None:
            migrated.set_title_snapshot = (
                question_set.get_title(migrated.language)
                or question_set.get_title("zh")
                or question_set.get_title("en")
            )
        if migrated.set_id and not migrated.set_title_snapshot:
            missing_fields.append("set_title_snapshot")

        set_metadata = (
            question_set.metadata or {}
            if question_set is not None
            else {}
        )
        question_course_ids = {
            str((question.metadata or {}).get("course_id", "") or "").strip()
            for question in available_questions
        }
        question_course_ids.discard("")
        migrated.course_id_snapshot = (
            migrated.course_id_snapshot
            or str(set_metadata.get("course_id", "") or "").strip()
            or (
                next(iter(question_course_ids))
                if len(question_course_ids) == 1
                else ""
            )
        )
        question_course_titles = {
            str((question.metadata or {}).get("course_title", "") or "").strip()
            for question in available_questions
        }
        question_course_titles.discard("")
        migrated.course_title_snapshot = (
            migrated.course_title_snapshot
            or str(set_metadata.get("course_title", "") or "").strip()
            or (
                next(iter(question_course_titles))
                if len(question_course_titles) == 1
                else ""
            )
        )
        if migrated.course_id_snapshot and not migrated.course_title_snapshot:
            course = self.course_manager.get(migrated.course_id_snapshot)
            if course is not None:
                migrated.course_title_snapshot = str(course.title or "").strip()
        if migrated.course_id_snapshot and not migrated.course_title_snapshot:
            missing_fields.append("course_title_snapshot")

        migrated.question_snapshots = migrated_snapshots
        migrated.archive_schema_version = ARCHIVE_SCHEMA_VERSION
        migrated.archive_status = "incomplete" if missing_fields else "complete"
        migrated.archive_missing_fields = missing_fields

        try:
            saved = self.progress_manager.save(migrated)
        except Exception as exc:
            return ProgressArchiveMigrationResult(
                progress_id=record.progress_id,
                status=record.archive_status,
                changed=False,
                error=f"Failed to save migrated progress archive: {exc}",
            )
        if not saved:
            return ProgressArchiveMigrationResult(
                progress_id=record.progress_id,
                status=record.archive_status,
                changed=False,
                error="Failed to save migrated progress archive",
            )
        return ProgressArchiveMigrationResult(
            progress_id=record.progress_id,
            status=migrated.archive_status,
            changed=migrated.to_dict() != record.to_dict(),
            missing_fields=tuple(missing_fields),
        )

    def migrate_all(
        self,
        records: list[ProgressRecord] | None = None,
    ) -> tuple[ProgressArchiveMigrationResult, ...]:
        """Migrate every completed record, leaving drafts untouched."""
        candidates = (
            list(records)
            if records is not None
            else self.progress_manager.load_all()
        )
        return tuple(
            self.migrate_record(record)
            for record in candidates
            if record.status == "completed"
        )


def _question_review_snapshot(question, language: str) -> QuestionReviewSnapshot:
    metadata = question.metadata or {}
    source_refs = metadata.get("source_refs", [])
    return QuestionReviewSnapshot(
        question_id=question.question_id,
        question_type=question.type.value,
        topic_id=question.topic_id(),
        topic_title=question.topic_title(),
        stem=_localized_question_value(question, "get_stem", language),
        options=copy.deepcopy(
            _localized_question_value(question, "get_options", language)
        ),
        correct_answer=copy.deepcopy(question.correct_answer),
        explanation=_localized_question_value(
            question,
            "get_explanation",
            language,
        ),
        source_refs=[
            copy.deepcopy(ref)
            for ref in (source_refs or [])
            if isinstance(ref, dict)
        ],
    )


def _localized_question_value(question, method_name: str, language: str):
    getter = getattr(question, method_name)
    value = getter(language)
    if value not in ("", [], {}, None):
        return value
    fallback_language = "en" if language == "zh" else "zh"
    return getter(fallback_language)
