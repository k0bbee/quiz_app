"""Stable destinations for reopening persisted background-task context."""

from __future__ import annotations

from ai.exam_plan import ExamGenerationPlan


_TASK_DESTINATIONS = {
    "question_generation": "generation",
    "course_import": "courses",
    "course_summary": "courses",
    "past_exam_ocr": "past_exams",
    "past_exam_analysis": "past_exams",
    "app_data_import": "settings_data",
    "app_data_export": "settings_data",
    "question_bank_validation": "question_bank",
}


def task_destination(kind: str) -> str:
    """Return the existing workspace that owns a task, or an empty string."""
    return _TASK_DESTINATIONS.get(str(kind or "").strip(), "")


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
