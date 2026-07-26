"""Analyze data assets linked to a course before lifecycle operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum


@dataclass(frozen=True)
class CourseAssetImpact:
    """Stable snapshot of records affected by deleting or unlinking a course."""

    course_id: str
    question_ids: tuple[str, ...] = ()
    direct_set_ids: tuple[str, ...] = ()
    affected_set_ids: tuple[str, ...] = ()
    progress_ids: tuple[str, ...] = ()
    snapshot_ids: tuple[str, ...] = ()
    past_exam_ids: tuple[str, ...] = ()

    @property
    def question_count(self) -> int:
        return len(self.question_ids)

    @property
    def question_set_count(self) -> int:
        return len(self.affected_set_ids)

    @property
    def progress_count(self) -> int:
        return len(self.progress_ids)

    @property
    def snapshot_count(self) -> int:
        return len(self.snapshot_ids)

    @property
    def past_exam_count(self) -> int:
        return len(self.past_exam_ids)


class CourseRemovalMode(str, Enum):
    """User-visible policies for removing a course."""

    KEEP_ASSETS = "keep_assets"
    UNLINK_ASSETS = "unlink_assets"
    DELETE_LINKED_BANK = "delete_linked_bank"


@dataclass(frozen=True)
class CourseRemovalResult:
    success: bool
    impact: CourseAssetImpact
    error: str = ""
    rollback_errors: tuple[str, ...] = ()


def analyze_course_asset_impact(
    course_id: str,
    question_bank=None,
    set_manager=None,
    progress_manager=None,
    snapshot_manager=None,
    past_exam_manager=None,
) -> CourseAssetImpact:
    """Return direct and indirect assets linked to ``course_id``."""
    normalized_course_id = str(course_id or "").strip()
    question_ids = {
        str(getattr(question, "question_id", "") or "").strip()
        for question in _load_all(question_bank)
        if _metadata_course_id(question) == normalized_course_id
    }
    question_ids.discard("")

    direct_set_ids: set[str] = set()
    affected_set_ids: set[str] = set()
    for question_set in _load_all(set_manager):
        set_id = str(getattr(question_set, "set_id", "") or "").strip()
        if not set_id:
            continue
        is_direct = _metadata_course_id(question_set) == normalized_course_id
        contains_course_question = bool(
            question_ids.intersection(getattr(question_set, "questions", []) or [])
        )
        if is_direct:
            direct_set_ids.add(set_id)
        if is_direct or contains_course_question:
            affected_set_ids.add(set_id)

    progress_ids = {
        str(getattr(record, "progress_id", "") or "").strip()
        for record in _load_all(progress_manager)
        if str(getattr(record, "set_id", "") or "").strip() in affected_set_ids
    }
    progress_ids.discard("")
    snapshot_ids = {
        str(getattr(snapshot, "snapshot_id", "") or "").strip()
        for snapshot in _load_all(snapshot_manager)
        if str(getattr(snapshot, "set_id", "") or "").strip() in affected_set_ids
    }
    snapshot_ids.discard("")
    past_exam_ids = {
        str(getattr(record, "exam_id", "") or "").strip()
        for record in _load_all(past_exam_manager)
        if str(getattr(record, "course_id", "") or "").strip()
        == normalized_course_id
    }
    past_exam_ids.discard("")

    return CourseAssetImpact(
        course_id=normalized_course_id,
        question_ids=tuple(sorted(question_ids)),
        direct_set_ids=tuple(sorted(direct_set_ids)),
        affected_set_ids=tuple(sorted(affected_set_ids)),
        progress_ids=tuple(sorted(progress_ids)),
        snapshot_ids=tuple(sorted(snapshot_ids)),
        past_exam_ids=tuple(sorted(past_exam_ids)),
    )


def remove_course_assets(
    course_id: str,
    mode: CourseRemovalMode,
    *,
    course_manager,
    question_bank=None,
    set_manager=None,
    progress_manager=None,
    snapshot_manager=None,
    past_exam_manager=None,
) -> CourseRemovalResult:
    """Apply one course-removal policy with compensating rollback on failure."""
    mode = CourseRemovalMode(mode)
    impact = analyze_course_asset_impact(
        course_id,
        question_bank,
        set_manager,
        progress_manager,
        snapshot_manager,
        past_exam_manager,
    )
    project = course_manager.get(impact.course_id)
    if project is None:
        return CourseRemovalResult(False, impact, "Course no longer exists")

    current = course_manager.current()
    was_current = getattr(current, "course_id", "") == impact.course_id
    questions = _load_by_ids(question_bank, "get", impact.question_ids)
    question_sets = _load_by_ids(set_manager, "get", impact.affected_set_ids)
    snapshots = _load_by_ids(snapshot_manager, "get", impact.snapshot_ids)
    past_exams = _load_by_ids(past_exam_manager, "get", impact.past_exam_ids)

    try:
        if mode is CourseRemovalMode.UNLINK_ASSETS:
            _unlink_course_assets(
                impact,
                deepcopy(questions),
                deepcopy(question_sets),
                question_bank,
                set_manager,
            )
        elif mode is CourseRemovalMode.DELETE_LINKED_BANK:
            _delete_linked_bank(
                impact,
                deepcopy(questions),
                deepcopy(question_sets),
                deepcopy(snapshots),
                question_bank,
                set_manager,
                snapshot_manager,
            )
        _unlink_past_exams(past_exams, past_exam_manager)
        _require_success(
            course_manager.delete(impact.course_id),
            f"delete course {impact.course_id}",
        )
    except Exception as exc:
        rollback_errors = _restore_assets(
            project,
            was_current,
            questions,
            question_sets,
            snapshots,
            past_exams,
            course_manager,
            question_bank,
            set_manager,
            snapshot_manager,
            past_exam_manager,
        )
        return CourseRemovalResult(
            False,
            impact,
            str(exc),
            tuple(rollback_errors),
        )

    return CourseRemovalResult(True, impact)


_COURSE_METADATA_KEYS = {
    "course_id",
    "course_title",
    "course_updated_at",
    "source_refs",
    "source_ref_status",
    "invalid_source_ref_ids",
    "plan_evidence_chunk_ids",
}


def _unlink_course_assets(impact, questions, question_sets, question_bank, set_manager):
    for question in questions:
        question.metadata = _without_course_metadata(getattr(question, "metadata", {}))
        _require_success(question_bank.save(question), f"unlink question {question.question_id}")
    direct_set_ids = set(impact.direct_set_ids)
    for question_set in question_sets:
        if question_set.set_id not in direct_set_ids:
            continue
        question_set.metadata = _without_course_metadata(getattr(question_set, "metadata", {}))
        _require_success(set_manager.save(question_set), f"unlink question set {question_set.set_id}")


def _delete_linked_bank(
    impact,
    questions,
    question_sets,
    snapshots,
    question_bank,
    set_manager,
    snapshot_manager,
):
    direct_set_ids = set(impact.direct_set_ids)
    course_question_ids = set(impact.question_ids)
    for question_set in question_sets:
        if question_set.set_id in direct_set_ids:
            _require_success(
                set_manager.delete(question_set.set_id),
                f"delete question set {question_set.set_id}",
            )
            continue
        question_set.questions = [
            question_id
            for question_id in question_set.questions
            if question_id not in course_question_ids
        ]
        if question_set.questions:
            _require_success(
                set_manager.save(question_set),
                f"update question set {question_set.set_id}",
            )
        else:
            _require_success(
                set_manager.delete(question_set.set_id),
                f"delete empty question set {question_set.set_id}",
            )

    for question in questions:
        _require_success(
            question_bank.delete(question.question_id),
            f"delete question {question.question_id}",
        )
    for snapshot in snapshots:
        _require_success(
            snapshot_manager.delete(snapshot.snapshot_id),
            f"delete quiz draft {snapshot.snapshot_id}",
        )


def _unlink_past_exams(past_exams, past_exam_manager):
    if past_exam_manager is None:
        return
    for record in past_exams:
        updated = replace(
            record,
            course_id="",
            assignment_mode="unassigned",
            analysis_status="pending",
        )
        _require_success(
            past_exam_manager.save_record(updated),
            f"unlink historical exam {record.exam_id}",
        )


def _restore_assets(
    project,
    was_current,
    questions,
    question_sets,
    snapshots,
    past_exams,
    course_manager,
    question_bank,
    set_manager,
    snapshot_manager,
    past_exam_manager,
) -> list[str]:
    errors: list[str] = []
    restore_groups = (
        (question_bank, questions, "question"),
        (set_manager, question_sets, "question set"),
        (snapshot_manager, snapshots, "quiz draft"),
    )
    for manager, items, label in restore_groups:
        if manager is None:
            continue
        for item in items:
            try:
                _require_success(manager.save(deepcopy(item)), f"restore {label}")
            except Exception as exc:
                errors.append(str(exc))
    if past_exam_manager is not None:
        for record in past_exams:
            try:
                _require_success(
                    past_exam_manager.save_record(deepcopy(record)),
                    f"restore historical exam {record.exam_id}",
                )
            except Exception as exc:
                errors.append(str(exc))
    try:
        _require_success(
            course_manager.save(deepcopy(project), make_current=was_current),
            f"restore course {getattr(project, 'course_id', '')}",
        )
    except Exception as exc:
        errors.append(str(exc))
    return errors


def _load_by_ids(manager, method_name: str, item_ids) -> list:
    if manager is None:
        return []
    method = getattr(manager, method_name)
    items = []
    for item_id in item_ids:
        item = method(item_id)
        if item is not None:
            items.append(deepcopy(item))
    return items


def _without_course_metadata(metadata) -> dict:
    cleaned = dict(metadata or {}) if isinstance(metadata, dict) else {}
    for key in _COURSE_METADATA_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _require_success(success, operation: str) -> None:
    if not success:
        raise OSError(f"Failed to {operation}")


def _load_all(manager) -> list:
    if manager is None:
        return []
    return list(manager.load_all())


def _metadata_course_id(item) -> str:
    metadata = getattr(item, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("course_id", "") or "").strip()
