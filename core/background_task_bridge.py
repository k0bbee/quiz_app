"""Bind one runtime worker to the current-session task lifecycle."""

from __future__ import annotations

from collections.abc import Callable

from core.background_task import TaskProgress
from core.background_task_center import BackgroundTaskCenter, TaskStatus


class BackgroundTaskBridge:
    """Translate worker callbacks into one session task snapshot."""

    def __init__(self, task_center: BackgroundTaskCenter, task_id: str):
        self.task_center = task_center
        self.task_id = str(task_id)
        self._terminal = False

    @property
    def is_terminal(self) -> bool:
        return self._terminal

    def start(self, cancel_callback: Callable[[], None]) -> bool:
        snapshot = self.task_center.get(self.task_id)
        if snapshot.status == TaskStatus.CANCELLED:
            self._terminal = True
            return False
        self.task_center.bind_cancel(self.task_id, cancel_callback)
        self.task_center.start(self.task_id)
        return True

    def report(self, progress: TaskProgress) -> None:
        if not self._terminal:
            self.task_center.report(self.task_id, progress)

    def complete(self, *, result_summary: str = "", result_count: int = 0) -> None:
        if self._terminal:
            return
        self.task_center.complete(
            self.task_id,
            result_summary=result_summary,
            result_count=result_count,
        )
        self._terminal = True

    def fail(self, error: object, *, result_count: int = 0) -> None:
        if self._terminal:
            return
        self.task_center.fail(self.task_id, error, result_count=result_count)
        self._terminal = True

    def cancelled(self, *, result_count: int = 0) -> None:
        if self._terminal:
            return
        self.task_center.mark_cancelled(self.task_id, result_count=result_count)
        self._terminal = True
