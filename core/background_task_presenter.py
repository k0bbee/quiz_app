"""Localized, UI-neutral presentation models for background tasks."""

from __future__ import annotations

from dataclasses import dataclass

from core.background_task_center import TaskSnapshot, TaskStatus


_ACTIVE = {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCELLING}
_ATTENTION = _ACTIVE | {TaskStatus.FAILED, TaskStatus.INTERRUPTED}
_DISMISSIBLE = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.INTERRUPTED,
}


@dataclass(frozen=True)
class TaskDisplayItem:
    task_id: str
    title: str
    kind_text: str
    status_text: str
    progress_text: str
    detail_text: str
    updated_at: str
    can_cancel: bool
    can_dismiss: bool
    needs_attention: bool


@dataclass(frozen=True)
class TaskCenterView:
    items: tuple[TaskDisplayItem, ...]
    attention_count: int
    active_count: int
    empty_text: str


def build_task_center_view(
    snapshots: list[TaskSnapshot] | tuple[TaskSnapshot, ...],
    *,
    language: str,
    attention_only: bool,
) -> TaskCenterView:
    """Return stable task ordering and localized display text."""
    lang = "zh" if language == "zh" else "en"
    all_snapshots = list(snapshots)
    attention_count = sum(item.status in _ATTENTION for item in all_snapshots)
    active_count = sum(item.status in _ACTIVE for item in all_snapshots)
    visible = [
        item
        for item in all_snapshots
        if not attention_only or item.status in _ATTENTION
    ]
    visible.sort(key=lambda item: (item.updated_at, item.task_id), reverse=True)
    visible.sort(key=lambda item: _status_priority(item.status))
    items = tuple(_display_item(item, lang) for item in visible)
    empty_text = (
        "当前没有需要处理的后台任务。"
        if attention_only and lang == "zh"
        else "No background tasks need attention."
        if attention_only
        else "还没有后台任务记录。"
        if lang == "zh"
        else "No background task history yet."
    )
    return TaskCenterView(items, attention_count, active_count, empty_text)


def task_toolbar_text(attention_count: int, language: str) -> str:
    base = "任务" if language == "zh" else "Tasks"
    count = max(0, int(attention_count))
    return f"{base} {count}" if count else base


def _display_item(snapshot: TaskSnapshot, language: str) -> TaskDisplayItem:
    return TaskDisplayItem(
        task_id=snapshot.task_id,
        title=snapshot.title,
        kind_text=_kind_text(snapshot.kind, language),
        status_text=_status_text(snapshot.status, language),
        progress_text=_progress_text(snapshot),
        detail_text=(
            snapshot.error
            or snapshot.progress.detail
            or snapshot.result_summary
        ),
        updated_at=snapshot.updated_at,
        can_cancel=snapshot.status in _ACTIVE,
        can_dismiss=snapshot.status in _DISMISSIBLE,
        needs_attention=snapshot.status in _ATTENTION,
    )


def _status_priority(status: TaskStatus) -> int:
    if status in _ACTIVE:
        return 0
    if status in {TaskStatus.FAILED, TaskStatus.INTERRUPTED}:
        return 1
    return 2


def _progress_text(snapshot: TaskSnapshot) -> str:
    current = max(0, int(snapshot.progress.current))
    total = max(0, int(snapshot.progress.total))
    if total:
        return f"{current} / {total}"
    if current:
        return str(current)
    return ""


def _status_text(status: TaskStatus, language: str) -> str:
    labels = {
        TaskStatus.QUEUED: ("等待中", "Queued"),
        TaskStatus.RUNNING: ("运行中", "Running"),
        TaskStatus.CANCELLING: ("正在取消", "Cancelling"),
        TaskStatus.COMPLETED: ("已完成", "Completed"),
        TaskStatus.FAILED: ("失败", "Failed"),
        TaskStatus.CANCELLED: ("已取消", "Cancelled"),
        TaskStatus.INTERRUPTED: ("已中断", "Interrupted"),
    }
    zh, en = labels[status]
    return zh if language == "zh" else en


def _kind_text(kind: str, language: str) -> str:
    labels = {
        "question_generation": ("AI 出题", "AI generation"),
        "course_import": ("课程导入", "Course import"),
        "past_exam_ocr": ("真题 OCR", "Exam OCR"),
        "app_data_import": ("数据导入", "Data import"),
        "app_data_export": ("数据导出", "Data export"),
    }
    zh, en = labels.get(kind, ("后台任务", "Background task"))
    return zh if language == "zh" else en
