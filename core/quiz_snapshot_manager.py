"""Persistence for resumable quiz-session snapshots."""

from __future__ import annotations

from typing import Optional

from config import QUIZ_SNAPSHOTS_DIR
from models.quiz_snapshot import QuizSessionSnapshot
from utils.json_io import (
    delete_json,
    list_json_files,
    read_json,
    sanitize_filename_part,
    write_json,
)


class QuizSnapshotManager:
    """Manages persisted quiz snapshots."""

    def __init__(self, snapshots_dir: str = QUIZ_SNAPSHOTS_DIR):
        self._dir = snapshots_dir

    @property
    def directory(self) -> str:
        return self._dir

    def load_all(self) -> list[QuizSessionSnapshot]:
        """Load all snapshots sorted by most recent update first."""
        snapshots: list[QuizSessionSnapshot] = []
        for filename in list_json_files(self._dir):
            data = read_json(f"{self._dir}/{filename}")
            if data:
                snapshots.append(QuizSessionSnapshot.from_dict(data))
        return sorted(snapshots, key=lambda item: item.updated_at, reverse=True)

    def load_latest(self) -> Optional[QuizSessionSnapshot]:
        """Return the newest snapshot, if any."""
        snapshots = self.load_all()
        return snapshots[0] if snapshots else None

    def get(self, snapshot_id: str) -> Optional[QuizSessionSnapshot]:
        """Load one snapshot by id."""
        data = read_json(f"{self._dir}/{sanitize_filename_part(snapshot_id)}.json")
        return QuizSessionSnapshot.from_dict(data) if data else None

    def save(self, snapshot: QuizSessionSnapshot) -> bool:
        """Persist a snapshot."""
        return write_json(
            f"{self._dir}/{sanitize_filename_part(snapshot.snapshot_id)}.json",
            snapshot.to_dict(),
        )

    def delete(self, snapshot_id: str) -> bool:
        """Delete one snapshot by id."""
        return delete_json(f"{self._dir}/{sanitize_filename_part(snapshot_id)}.json")

    def delete_for_set(self, set_id: str) -> int:
        """Delete all snapshots belonging to a question set."""
        deleted = 0
        for snapshot in self.load_all():
            if snapshot.set_id != set_id:
                continue
            if self.delete(snapshot.snapshot_id):
                deleted += 1
        return deleted
