"""Stable destinations for reopening persisted background-task context."""

from __future__ import annotations


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
