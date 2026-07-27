"""Compatibility migration for immutable completed-quiz archives."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from models.progress import ProgressRecord, QuestionReviewSnapshot
from utils.constants import QuestionType


ARCHIVE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProgressArchiveMigrationResult:
    """Outcome of migrating one completed progress record."""

    progress_id: str
    status: str
    changed: bool
    missing_fields: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class SnapshotValidation:
    """Type-aware review snapshot validation result."""

    valid: bool
    missing_fields: tuple[str, ...] = ()


def validate_review_snapshot(
    snapshot: QuestionReviewSnapshot,
) -> SnapshotValidation:
    """Validate the minimum immutable data needed for truthful review."""
    missing: list[str] = []
    question_id = str(getattr(snapshot, "question_id", "") or "").strip()
    if not question_id:
        missing.append("question_id")
    try:
        question_type = QuestionType(
            str(getattr(snapshot, "question_type", "") or "").strip()
        )
    except ValueError:
        question_type = None
        missing.append("question_type")
    if not str(getattr(snapshot, "stem", "") or "").strip():
        missing.append("stem")
    correct_answer = getattr(snapshot, "correct_answer", None)
    if _is_empty_value(correct_answer):
        missing.append("correct_answer")

    options = getattr(snapshot, "options", None)
    if question_type in {
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.TRUE_FALSE,
        QuestionType.SCENARIO_CHOICE,
    }:
        if not isinstance(options, (list, tuple)) or len(options) < 2:
            missing.append("options")
    elif question_type is QuestionType.MATCHING:
        left, right = _matching_sides(options)
        if not left or not right or len(left) != len(right):
            missing.append("options")
        elif not _valid_matching_answer(correct_answer, left, right):
            if "correct_answer" not in missing:
                missing.append("correct_answer")
    elif question_type is QuestionType.ORDERING:
        option_ids = _option_ids(options)
        if len(option_ids) < 2 or len(option_ids) != len(set(option_ids)):
            missing.append("options")
        elif not _valid_ordering_answer(correct_answer, option_ids):
            if "correct_answer" not in missing:
                missing.append("correct_answer")

    return SnapshotValidation(
        valid=not missing,
        missing_fields=tuple(missing),
    )


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
            and _record_snapshots_are_complete(record)
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
                validation = validate_review_snapshot(existing_snapshot)
                if validation.valid:
                    migrated_snapshots.append(copy.deepcopy(existing_snapshot))
                    continue
            question = self.question_bank.get(question_id)
            if question is not None:
                available_questions.append(question)
                migrated_snapshots.append(
                    _question_review_snapshot(question, migrated.language)
                )
                continue
            if existing_snapshot is not None:
                migrated_snapshots.append(copy.deepcopy(existing_snapshot))
                missing_fields.extend(
                    f"snapshot:{question_id}:{field_name}"
                    for field_name in validation.missing_fields
                )
            else:
                missing_fields.append(f"question:{question_id}")
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
        changed = migrated.to_dict() != record.to_dict()
        if not changed:
            return ProgressArchiveMigrationResult(
                progress_id=record.progress_id,
                status=migrated.archive_status,
                changed=False,
                missing_fields=tuple(missing_fields),
            )

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
            changed=True,
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


def _record_snapshots_are_complete(record: ProgressRecord) -> bool:
    valid_ids = {
        snapshot.question_id
        for snapshot in record.question_snapshots
        if validate_review_snapshot(snapshot).valid
    }
    answer_ids = {
        str(answer.question_id or "").strip()
        for answer in record.answers
        if str(answer.question_id or "").strip()
    }
    return bool(valid_ids) and answer_ids.issubset(valid_ids)


def _is_empty_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    return False


def _matching_sides(options) -> tuple[list, list]:
    if not isinstance(options, dict):
        return [], []
    left = options.get("left", [])
    right = options.get("right", [])
    if not isinstance(left, (list, tuple)) or not isinstance(
        right,
        (list, tuple),
    ):
        return [], []
    return list(left), list(right)


def _option_ids(options) -> list[str]:
    if not isinstance(options, (list, tuple)):
        return []
    identities: list[str] = []
    for option in options:
        if isinstance(option, dict):
            identity = str(option.get("id", "") or "").strip()
        else:
            identity = str(option or "").strip()
        if not identity:
            return []
        identities.append(identity)
    return identities


def _valid_matching_answer(correct_answer, left: list, right: list) -> bool:
    if not isinstance(correct_answer, (list, tuple)) or not correct_answer:
        return False
    left_ids = set(_option_ids(left))
    right_ids = set(_option_ids(right))
    if not left_ids or not right_ids:
        return False
    pairs = []
    for pair in correct_answer:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return False
        pairs.append((str(pair[0] or "").strip(), str(pair[1] or "").strip()))
    return (
        len(pairs) == len(left_ids)
        and {left_id for left_id, _right_id in pairs} == left_ids
        and all(right_id in right_ids for _left_id, right_id in pairs)
    )


def _valid_ordering_answer(correct_answer, option_ids: list[str]) -> bool:
    if not isinstance(correct_answer, (list, tuple)):
        return False
    answer_ids = [str(value or "").strip() for value in correct_answer]
    return (
        len(answer_ids) == len(option_ids)
        and len(answer_ids) == len(set(answer_ids))
        and set(answer_ids) == set(option_ids)
    )
