"""Map transport-neutral generation events to persistent task lifecycle state."""

from __future__ import annotations

from ai.generation_events import (
    CompletedEvent,
    FailedEvent,
    PartialResultEvent,
    ProgressEvent,
    QuestionsReadyEvent,
)
from core.background_task import TaskProgress
from core.background_task_center import BackgroundTaskCenter, TaskStatus


class GenerationTaskBridge:
    """Keep task-center state aligned with one generation runner."""

    def __init__(
        self,
        task_center: BackgroundTaskCenter,
        task_id: str,
        *,
        requested_count: int,
    ):
        self.task_center = task_center
        self.task_id = task_id
        self.requested_count = max(0, int(requested_count))
        self.accepted_count = 0
        self._terminal = False

    @property
    def is_terminal(self) -> bool:
        return self._terminal

    def start(self, cancel_callback) -> bool:
        """Bind runtime cancellation and move a queued task to running."""
        snapshot = self.task_center.get(self.task_id)
        if snapshot.status == TaskStatus.CANCELLED:
            self._terminal = True
            return False
        self.task_center.bind_cancel(self.task_id, cancel_callback)
        self.task_center.start(self.task_id)
        return True

    def handle(self, event) -> None:
        if self._terminal:
            return
        if isinstance(event, ProgressEvent):
            self._report(event.message)
            return
        if isinstance(event, QuestionsReadyEvent):
            self.accepted_count += len(event.questions)
            self._report(
                f"Accepted {self.accepted_count}/{self.requested_count} questions"
            )
            return
        if isinstance(event, CompletedEvent):
            self.accepted_count = len(event.questions)
            self.task_center.complete(
                self.task_id,
                result_summary=f"Generated {self.accepted_count} questions",
                result_count=self.accepted_count,
            )
            self._terminal = True
            return
        if isinstance(event, PartialResultEvent):
            self.accepted_count = len(event.questions)
            if event.report.status == "cancelled":
                self.task_center.mark_cancelled(
                    self.task_id,
                    result_count=self.accepted_count,
                )
            else:
                self.task_center.fail(
                    self.task_id,
                    event.report.summary_text("en"),
                    result_count=self.accepted_count,
                )
            self._terminal = True
            return
        if isinstance(event, FailedEvent):
            self.fail(event.error)
            return
        raise TypeError(f"Unsupported generation event: {type(event).__name__}")

    def fail(self, error: object) -> None:
        if self._terminal:
            return
        self.task_center.fail(
            self.task_id,
            error,
            result_count=self.accepted_count,
        )
        self._terminal = True

    def finish_cancelled(self) -> None:
        if self._terminal:
            return
        self.task_center.mark_cancelled(
            self.task_id,
            result_count=self.accepted_count,
        )
        self._terminal = True

    def _report(self, detail: str) -> None:
        self.task_center.report(
            self.task_id,
            TaskProgress(
                "generating_questions",
                current=self.accepted_count,
                total=self.requested_count,
                detail=str(detail or ""),
            ),
        )
