"""Reusable cooperative cancellation and progress primitives for long tasks."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable


class BackgroundTaskCancelled(RuntimeError):
    """Raised at a safe boundary after a user requests cancellation."""


@dataclass(frozen=True)
class TaskProgress:
    stage: str
    current: int = 0
    total: int = 0
    detail: str = ""


class TaskControl:
    """Thread-safe cancellation token with optional structured progress callback."""

    def __init__(self, progress_callback: Callable[[TaskProgress], None] | None = None):
        self._cancelled = threading.Event()
        self._progress_callback = progress_callback

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def check_cancelled(self) -> None:
        if self.is_cancelled:
            raise BackgroundTaskCancelled("Background task cancelled")

    def report(self, stage: str, current: int = 0, total: int = 0, detail: str = "") -> None:
        self.check_cancelled()
        if self._progress_callback is not None:
            self._progress_callback(TaskProgress(stage, current, total, detail))
        self.check_cancelled()

    def complete(self, stage: str = "saved", detail: str = "") -> None:
        """Publish a committed result without turning a late cancel into failure."""
        if self._progress_callback is not None:
            self._progress_callback(TaskProgress(stage, detail=detail))
