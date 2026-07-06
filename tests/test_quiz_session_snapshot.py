import tempfile
import unittest
from pathlib import Path

from core.quiz_snapshot_manager import QuizSnapshotManager
from models.progress import AnswerRecord
from models.quiz_snapshot import QuizSessionSnapshot


class QuizSessionSnapshotTests(unittest.TestCase):
    def _snapshot(self, snapshot_id: str = "snapshot-a") -> QuizSessionSnapshot:
        return QuizSessionSnapshot(
            snapshot_id=snapshot_id,
            set_id="set-1",
            title="系统结构练习",
            question_order=["q1", "q2", "q3"],
            current_index=1,
            submitted_answers=[
                AnswerRecord(
                    question_id="q1",
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                    confidence="unsure",
                    time_spent_seconds=3.5,
                    attempted_at="2026-06-29T00:00:00+00:00",
                )
            ],
            draft_answers={"q2": "B"},
            unsure_question_ids=["q1", "q2"],
            marked_review_question_ids=["q2"],
            started_at="2026-06-29T00:00:00+00:00",
            updated_at="2026-06-29T00:01:00+00:00",
            elapsed_seconds=60.0,
            language="zh",
            mode="practice",
        )

    def test_snapshot_round_trips_all_recovery_fields(self):
        snapshot = self._snapshot()

        loaded = QuizSessionSnapshot.from_dict(snapshot.to_dict())

        self.assertEqual("snapshot-a", loaded.snapshot_id)
        self.assertEqual("set-1", loaded.set_id)
        self.assertEqual("系统结构练习", loaded.title)
        self.assertEqual(["q1", "q2", "q3"], loaded.question_order)
        self.assertEqual(1, loaded.current_index)
        self.assertEqual("A", loaded.submitted_answers[0].user_answer)
        self.assertEqual("unsure", loaded.submitted_answers[0].confidence)
        self.assertEqual({"q2": "B"}, loaded.draft_answers)
        self.assertEqual(["q1", "q2"], loaded.unsure_question_ids)
        self.assertEqual(["q2"], loaded.marked_review_question_ids)
        self.assertEqual(60.0, loaded.elapsed_seconds)
        self.assertEqual("practice", loaded.mode)

    def test_snapshot_manager_saves_loads_latest_and_deletes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = QuizSnapshotManager(tmpdir)
            old = self._snapshot("snapshot-old")
            old.updated_at = "2026-06-29T00:00:00+00:00"
            latest = self._snapshot("snapshot-latest")
            latest.updated_at = "2026-06-29T00:10:00+00:00"

            self.assertTrue(manager.save(old))
            self.assertTrue(manager.save(latest))

            self.assertEqual("snapshot-latest", manager.load_latest().snapshot_id)
            self.assertEqual("snapshot-old", manager.get("snapshot-old").snapshot_id)
            self.assertTrue(manager.delete("snapshot-latest"))
            self.assertIsNone(manager.get("snapshot-latest"))
            self.assertEqual("snapshot-old", manager.load_latest().snapshot_id)

    def test_snapshot_manager_deletes_snapshots_for_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = QuizSnapshotManager(tmpdir)
            set_a = self._snapshot("snapshot-a")
            set_b = self._snapshot("snapshot-b")
            set_b.set_id = "set-b"
            manager.save(set_a)
            manager.save(set_b)

            deleted = manager.delete_for_set("set-1")

            self.assertEqual(1, deleted)
            self.assertIsNone(manager.get("snapshot-a"))
            self.assertIsNotNone(manager.get("snapshot-b"))

    def test_snapshot_manager_creates_directory_on_init(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshots_dir = Path(tmpdir) / "missing" / "snapshots"

            manager = QuizSnapshotManager(str(snapshots_dir))

            self.assertEqual(str(snapshots_dir), manager.directory)
            self.assertTrue(snapshots_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
