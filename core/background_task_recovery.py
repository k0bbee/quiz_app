"""Stable destinations for reopening persisted background-task context."""

from __future__ import annotations

from dataclasses import dataclass

from ai.exam_plan import ExamGenerationPlan


_TASK_DESTINATIONS = {
    "question_generation": "generation",
    "course_import": "courses",
    "course_summary": "courses",
    "app_data_import": "settings_data",
    "app_data_export": "settings_data",
    "question_bank_validation": "question_bank",
}

_RETRY_METADATA_KEYS = {
    "course_import": ("source_folder",),
    "course_summary": ("course_id",),
}


@dataclass(frozen=True)
class TaskRetryAssessment:
    can_retry: bool
    reason: str = ""


def task_destination(kind: str) -> str:
    """Return the existing workspace that owns a task, or an empty string."""
    return _TASK_DESTINATIONS.get(str(kind or "").strip(), "")


def task_retry_assessment(snapshot, language: str = "zh") -> TaskRetryAssessment:
    """Allow retry only when the owning page can safely restore required inputs."""
    status = str(getattr(getattr(snapshot, "status", ""), "value", "") or "")
    if status not in {"failed", "cancelled", "interrupted"}:
        return TaskRetryAssessment(False)
    kind = str(getattr(snapshot, "kind", "") or "").strip()
    metadata = getattr(snapshot, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return TaskRetryAssessment(False, _retry_reason("invalid", language))

    if kind == "question_generation":
        raw_plan = metadata.get("exam_plan")
        if raw_plan is not None and not _valid_exam_plan(raw_plan):
            return TaskRetryAssessment(False, _retry_reason("invalid", language))
        has_plan = raw_plan is not None
        has_legacy_plan = (
            isinstance(metadata.get("topic_ids"), (list, tuple))
            and bool(metadata.get("topic_ids"))
            and _positive_int(metadata.get("requested_count"))
        )
        missing = [] if metadata.get("course_id") else ["course_id"]
        if not has_plan and not has_legacy_plan:
            missing.append("exam_plan")
    elif kind in _RETRY_METADATA_KEYS:
        missing = [
            key for key in _RETRY_METADATA_KEYS[kind]
            if not str(metadata.get(key, "") or "").strip()
        ]
    else:
        return TaskRetryAssessment(False, _retry_reason("unsupported", language))

    if missing:
        separator = "、" if language == "zh" else ", "
        detail = separator.join(
            _recovery_field_label(key, language)
            for key in missing
        )
        return TaskRetryAssessment(
            False,
            _retry_reason("missing", language, detail),
        )
    return TaskRetryAssessment(True)


def generation_plan_from_task_metadata(metadata: dict) -> ExamGenerationPlan:
    """Build a validated generation draft from current or legacy task metadata."""
    metadata = metadata if isinstance(metadata, dict) else {}
    raw = metadata.get("exam_plan")
    raw = raw if isinstance(raw, dict) else {}
    try:
        count = int(raw.get("question_count", metadata.get("requested_count", 15)))
    except (TypeError, ValueError):
        count = 15
    count = max(3, min(60, count))
    selected = raw.get("selected_topics", metadata.get("topic_ids", ()))
    if not isinstance(selected, (list, tuple)):
        selected = ()
    selected = tuple(str(item).strip() for item in selected if str(item).strip())
    kwargs = {
        "question_count": count,
        "difficulty": raw.get("difficulty", "medium"),
        "template": raw.get("template", metadata.get("template", "quick_review")),
        "selected_topics": selected,
    }
    for key in ("question_type_weights", "difficulty_weights", "topic_weights"):
        value = raw.get(key)
        if isinstance(value, dict):
            kwargs[key] = value
    try:
        return ExamGenerationPlan(**kwargs)
    except (TypeError, ValueError):
        return ExamGenerationPlan(question_count=count, selected_topics=selected)


def _positive_int(value) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _valid_exam_plan(value) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    try:
        plan = ExamGenerationPlan(**value)
    except (TypeError, ValueError):
        return False
    return bool(plan.selected_topics)


def _retry_reason(reason: str, language: str, detail: str = "") -> str:
    zh = language == "zh"
    if reason == "missing":
        return (
            f"缺少安全恢复字段：{detail}"
            if zh
            else f"Missing safe recovery fields: {detail}"
        )
    if reason == "invalid":
        return "恢复信息格式无效。" if zh else "Recovery metadata is invalid."
    return (
        "该任务类型不支持安全重试。"
        if zh
        else "This task type does not support safe retry."
    )


def _recovery_field_label(key: str, language: str) -> str:
    labels = {
        "course_id": ("课程", "course"),
        "exam_plan": ("出题方案", "generation plan"),
        "source_folder": ("课件文件夹", "course folder"),
        "source_path": ("源文件", "source file"),
    }
    zh, en = labels.get(key, (key, key))
    return zh if language == "zh" else en
