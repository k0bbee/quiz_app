"""Persistent, UI-independent lifecycle state for long-running app tasks."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

from core.background_task import TaskProgress
from utils.json_io import read_json, write_json


_SCHEMA_VERSION = 1


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


_ACTIVE_STATUSES = {TaskStatus.RUNNING, TaskStatus.CANCELLING}
_RETRYABLE_STATUSES = {
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.INTERRUPTED,
}
_TERMINAL_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.INTERRUPTED,
}


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    kind: str
    title: str
    status: TaskStatus
    created_at: str
    updated_at: str
    progress: TaskProgress = field(default_factory=lambda: TaskProgress("queued"))
    metadata: dict = field(default_factory=dict)
    result_summary: str = ""
    result_count: int = 0
    error: str = ""
    retry_of: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": {
                "stage": self.progress.stage,
                "current": self.progress.current,
                "total": self.progress.total,
                "detail": self.progress.detail,
            },
            "metadata": copy.deepcopy(self.metadata),
            "result_summary": self.result_summary,
            "result_count": self.result_count,
            "error": self.error,
            "retry_of": self.retry_of,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskSnapshot":
        progress = data.get("progress") or {}
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("task metadata must be an object")
        return cls(
            task_id=str(data["task_id"]),
            kind=str(data["kind"]),
            title=str(data["title"]),
            status=TaskStatus(data["status"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            progress=TaskProgress(
                stage=str(progress.get("stage", "")),
                current=int(progress.get("current", 0)),
                total=int(progress.get("total", 0)),
                detail=str(progress.get("detail", "")),
            ),
            metadata=copy.deepcopy(metadata),
            result_summary=str(data.get("result_summary", "")),
            result_count=max(0, int(data.get("result_count", 0))),
            error=str(data.get("error", "")),
            retry_of=str(data.get("retry_of", "")),
        )


class BackgroundTaskCenter:
    """Store task snapshots atomically and coordinate runtime cancellation."""

    def __init__(
        self,
        path: str | Path,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        progress_persist_interval: float = 0.5,
    ):
        self.path = Path(path)
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock or _utc_now
        self._monotonic = monotonic or time.monotonic
        self._progress_persist_interval = max(0.0, float(progress_persist_interval))
        self._lock = threading.RLock()
        self._records: dict[str, TaskSnapshot] = self._load()
        self._last_progress_persisted: dict[str, float] = {}
        self._cancel_callbacks: dict[str, Callable[[], None]] = {}
        self._cancel_notified: set[str] = set()
        self._recover_interrupted_tasks()

    def create(
        self,
        *,
        kind: str,
        title: str,
        metadata: dict | None = None,
        retry_of: str = "",
    ) -> TaskSnapshot:
        task_id = str(self._id_factory()).strip()
        kind = str(kind).strip()
        title = str(title).strip()
        if not task_id or not kind or not title:
            raise ValueError("task_id, kind and title must be non-empty")
        now = self._clock()
        snapshot = TaskSnapshot(
            task_id=task_id,
            kind=kind,
            title=title,
            status=TaskStatus.QUEUED,
            created_at=now,
            updated_at=now,
            progress=TaskProgress("queued"),
            metadata=copy.deepcopy(metadata or {}),
            retry_of=retry_of,
        )
        with self._lock:
            if task_id in self._records:
                raise ValueError(f"duplicate task id: {task_id}")
            self._replace_record(snapshot)
        return snapshot

    def get(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            try:
                return _copy_snapshot(self._records[task_id])
            except KeyError as exc:
                raise KeyError(f"unknown background task: {task_id}") from exc

    def snapshots(self) -> tuple[TaskSnapshot, ...]:
        with self._lock:
            return tuple(
                _copy_snapshot(snapshot)
                for snapshot in sorted(
                    self._records.values(),
                    key=lambda item: (item.created_at, item.task_id),
                    reverse=True,
                )
            )

    def start(self, task_id: str) -> TaskSnapshot:
        return self._transition(task_id, TaskStatus.RUNNING, progress=TaskProgress("starting"))

    def report(self, task_id: str, progress: TaskProgress) -> TaskSnapshot:
        with self._lock:
            current = self.get(task_id)
            if current.status not in _ACTIVE_STATUSES:
                raise ValueError(
                    f"cannot report progress for task in {current.status.value} state"
                )
            updated = replace(current, progress=progress, updated_at=self._clock())
            tick = self._monotonic()
            last_persisted = self._last_progress_persisted.get(task_id)
            should_persist = (
                last_persisted is None
                or progress.stage != current.progress.stage
                or tick - last_persisted >= self._progress_persist_interval
            )
            if should_persist:
                self._replace_record(updated)
                self._last_progress_persisted[task_id] = tick
            else:
                self._records[task_id] = _copy_snapshot(updated)
            return updated

    def bind_cancel(self, task_id: str, callback: Callable[[], None]) -> None:
        if not callable(callback):
            raise TypeError("cancel callback must be callable")
        with self._lock:
            self.get(task_id)
            self._cancel_callbacks[task_id] = callback

    def request_cancel(self, task_id: str) -> TaskSnapshot:
        callback = None
        with self._lock:
            current = self.get(task_id)
            if current.status == TaskStatus.CANCELLING:
                return current
            if current.status == TaskStatus.QUEUED:
                updated = self._transition_locked(task_id, TaskStatus.CANCELLED)
            else:
                updated = self._transition_locked(task_id, TaskStatus.CANCELLING)
                if task_id not in self._cancel_notified:
                    callback = self._cancel_callbacks.get(task_id)
                    self._cancel_notified.add(task_id)
        if callback is not None:
            callback()
        return updated

    def complete(
        self,
        task_id: str,
        *,
        result_summary: str = "",
        result_count: int = 0,
    ) -> TaskSnapshot:
        return self._transition(
            task_id,
            TaskStatus.COMPLETED,
            result_summary=str(result_summary),
            result_count=max(0, int(result_count)),
            error="",
        )

    def fail(
        self,
        task_id: str,
        error: object,
        *,
        result_count: int = 0,
    ) -> TaskSnapshot:
        return self._transition(
            task_id,
            TaskStatus.FAILED,
            error=str(error),
            result_count=max(0, int(result_count)),
        )

    def mark_cancelled(self, task_id: str, *, result_count: int = 0) -> TaskSnapshot:
        return self._transition(
            task_id,
            TaskStatus.CANCELLED,
            result_count=max(0, int(result_count)),
        )

    def retry(self, task_id: str) -> TaskSnapshot:
        original = self.get(task_id)
        if original.status not in _RETRYABLE_STATUSES:
            raise ValueError(f"cannot retry task in {original.status.value} state")
        return self.create(
            kind=original.kind,
            title=original.title,
            metadata=original.metadata,
            retry_of=original.task_id,
        )

    def dismiss(self, task_id: str) -> None:
        """Remove one terminal task from persisted history."""
        with self._lock:
            snapshot = self.get(task_id)
            if snapshot.status not in _TERMINAL_STATUSES:
                raise ValueError(
                    f"cannot dismiss task in {snapshot.status.value} state"
                )
            records = dict(self._records)
            records.pop(task_id)
            payload = {
                "schema_version": _SCHEMA_VERSION,
                "tasks": [item.to_dict() for item in records.values()],
            }
            if not write_json(str(self.path), payload):
                raise OSError(f"failed to persist background tasks: {self.path}")
            self._records = records
            self._cancel_callbacks.pop(task_id, None)
            self._cancel_notified.discard(task_id)
            self._last_progress_persisted.pop(task_id, None)

    def _transition(self, task_id: str, status: TaskStatus, **changes) -> TaskSnapshot:
        with self._lock:
            return self._transition_locked(task_id, status, **changes)

    def _transition_locked(
        self,
        task_id: str,
        status: TaskStatus,
        **changes,
    ) -> TaskSnapshot:
        current = self.get(task_id)
        if status not in _ALLOWED_TRANSITIONS[current.status]:
            raise ValueError(
                f"cannot transition task from {current.status.value} to {status.value}"
            )
        updated = replace(current, status=status, updated_at=self._clock(), **changes)
        self._replace_record(updated)
        return updated

    def _replace_record(self, snapshot: TaskSnapshot) -> None:
        records = dict(self._records)
        records[snapshot.task_id] = _copy_snapshot(snapshot)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "tasks": [item.to_dict() for item in records.values()],
        }
        if not write_json(str(self.path), payload):
            raise OSError(f"failed to persist background tasks: {self.path}")
        self._records = records

    def _load(self) -> dict[str, TaskSnapshot]:
        payload = read_json(str(self.path))
        if not isinstance(payload, dict):
            return {}
        tasks = payload.get("tasks", [])
        if not isinstance(tasks, list):
            return {}
        records = {}
        for data in tasks:
            try:
                snapshot = TaskSnapshot.from_dict(data)
            except (KeyError, TypeError, ValueError):
                continue
            records[snapshot.task_id] = snapshot
        return records

    def _recover_interrupted_tasks(self) -> None:
        with self._lock:
            interrupted = {
                task_id: replace(
                    snapshot,
                    status=TaskStatus.INTERRUPTED,
                    updated_at=self._clock(),
                )
                for task_id, snapshot in self._records.items()
                if snapshot.status in _ACTIVE_STATUSES
            }
            if not interrupted:
                return
            records = dict(self._records)
            records.update(interrupted)
            payload = {
                "schema_version": _SCHEMA_VERSION,
                "tasks": [item.to_dict() for item in records.values()],
            }
            if not write_json(str(self.path), payload):
                raise OSError(f"failed to recover background tasks: {self.path}")
            self._records = records


_ALLOWED_TRANSITIONS = {
    TaskStatus.QUEUED: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.CANCELLING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.CANCELLING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.INTERRUPTED: set(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_snapshot(snapshot: TaskSnapshot) -> TaskSnapshot:
    return replace(snapshot, metadata=copy.deepcopy(snapshot.metadata))
