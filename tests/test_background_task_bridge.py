import tempfile
import unittest
from pathlib import Path

from core.background_task import TaskProgress
from core.background_task_center import BackgroundTaskCenter, TaskStatus
from core.background_task_bridge import BackgroundTaskBridge


class BackgroundTaskBridgeTests(unittest.TestCase):
    def _center(self, root):
        return BackgroundTaskCenter(
            Path(root) / "tasks.json",
            id_factory=lambda: "task-1",
            progress_persist_interval=0,
        )

    def test_bridge_maps_worker_lifecycle_to_persistent_task_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = self._center(tmpdir)
            snapshot = center.create(kind="course_import", title="Import Systems")
            cancelled = []
            bridge = BackgroundTaskBridge(center, snapshot.task_id)

            self.assertTrue(bridge.start(lambda: cancelled.append(True)))
            bridge.report(TaskProgress("parsing_file", 2, 5, "io.pdf"))

            running = center.get(snapshot.task_id)
            self.assertEqual(TaskStatus.RUNNING, running.status)
            self.assertEqual("parsing_file", running.progress.stage)
            self.assertEqual(2, running.progress.current)

            center.request_cancel(snapshot.task_id)
            self.assertEqual([True], cancelled)
            bridge.cancelled(result_count=2)

            terminal = center.get(snapshot.task_id)
            self.assertEqual(TaskStatus.CANCELLED, terminal.status)
            self.assertEqual(2, terminal.result_count)
            self.assertTrue(bridge.is_terminal)

    def test_bridge_ignores_late_worker_events_after_terminal_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = self._center(tmpdir)
            snapshot = center.create(kind="past_exam_ocr", title="Import Final")
            bridge = BackgroundTaskBridge(center, snapshot.task_id)
            bridge.start(lambda: None)
            bridge.complete(result_summary="Imported", result_count=1)

            bridge.report(TaskProgress("late", 9, 10, "stale"))
            bridge.fail("late error")

            terminal = center.get(snapshot.task_id)
            self.assertEqual(TaskStatus.COMPLETED, terminal.status)
            self.assertEqual("Imported", terminal.result_summary)
            self.assertEqual("", terminal.error)

    def test_bridge_does_not_start_a_task_cancelled_while_queued(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = self._center(tmpdir)
            snapshot = center.create(kind="course_import", title="Import Systems")
            center.request_cancel(snapshot.task_id)
            bridge = BackgroundTaskBridge(center, snapshot.task_id)

            self.assertFalse(bridge.start(lambda: None))
            self.assertTrue(bridge.is_terminal)
            self.assertEqual(TaskStatus.CANCELLED, center.get(snapshot.task_id).status)


if __name__ == "__main__":
    unittest.main()
