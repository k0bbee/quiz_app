import tempfile
import unittest

from ai.generation_events import (
    CompletedEvent,
    FailedEvent,
    PartialResultEvent,
    ProgressEvent,
    QuestionsReadyEvent,
)
from ai.generation_report import GenerationReport
from ai.generation_task_bridge import GenerationTaskBridge
from core.background_task_center import BackgroundTaskCenter, TaskStatus


class GenerationTaskBridgeTests(unittest.TestCase):
    def _center(self, tmpdir):
        ids = iter(["task-1", "task-2"])
        return BackgroundTaskCenter(
            id_factory=lambda: next(ids),
        )

    def test_maps_generation_progress_and_completion_to_session_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = self._center(tmpdir)
            task = center.create(kind="question_generation", title="生成模拟卷")
            bridge = GenerationTaskBridge(center, task.task_id, requested_count=3)

            bridge.start(lambda: None)
            bridge.handle(ProgressEvent("Generating question 1/3"))
            bridge.handle(QuestionsReadyEvent.from_questions([object()]))
            running = center.get(task.task_id)
            bridge.handle(CompletedEvent.from_questions([object(), object(), object()]))
            completed = center.get(task.task_id)

            self.assertEqual(TaskStatus.RUNNING, running.status)
            self.assertEqual("generating_questions", running.progress.stage)
            self.assertEqual((1, 3), (running.progress.current, running.progress.total))
            self.assertEqual(TaskStatus.COMPLETED, completed.status)
            self.assertEqual(3, completed.result_count)

    def test_partial_result_is_retryable_and_preserves_accepted_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = self._center(tmpdir)
            task = center.create(kind="question_generation", title="生成题目")
            bridge = GenerationTaskBridge(center, task.task_id, requested_count=5)
            bridge.start(lambda: None)
            report = GenerationReport(
                requested_count=5,
                accepted_count=2,
                status="partial",
            )

            bridge.handle(PartialResultEvent.from_questions([object(), object()], report))
            failed = center.get(task.task_id)
            retry = center.retry(task.task_id)

            self.assertEqual(TaskStatus.FAILED, failed.status)
            self.assertEqual(2, failed.result_count)
            self.assertIn("2/5", failed.error)
            self.assertEqual(task.task_id, retry.retry_of)

    def test_cancelled_partial_and_empty_cancel_both_end_as_cancelled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = self._center(tmpdir)
            first = center.create(kind="question_generation", title="第一次生成")
            first_bridge = GenerationTaskBridge(center, first.task_id, requested_count=5)
            first_bridge.start(lambda: None)
            report = GenerationReport(
                requested_count=5,
                accepted_count=2,
                status="cancelled",
            )
            first_bridge.handle(
                PartialResultEvent.from_questions([object(), object()], report)
            )

            second = center.create(kind="question_generation", title="第二次生成")
            second_bridge = GenerationTaskBridge(center, second.task_id, requested_count=5)
            second_bridge.start(lambda: None)
            second_bridge.finish_cancelled()

            self.assertEqual(TaskStatus.CANCELLED, center.get(first.task_id).status)
            self.assertEqual(2, center.get(first.task_id).result_count)
            self.assertEqual(TaskStatus.CANCELLED, center.get(second.task_id).status)
            self.assertEqual(0, center.get(second.task_id).result_count)

    def test_task_center_cancel_invokes_generation_cancel_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = self._center(tmpdir)
            task = center.create(kind="question_generation", title="生成题目")
            cancelled = []
            bridge = GenerationTaskBridge(center, task.task_id, requested_count=3)
            bridge.start(lambda: cancelled.append(True))

            center.request_cancel(task.task_id)

            self.assertEqual([True], cancelled)
            self.assertEqual(TaskStatus.CANCELLING, center.get(task.task_id).status)

    def test_failure_event_records_provider_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = self._center(tmpdir)
            task = center.create(kind="question_generation", title="生成题目")
            bridge = GenerationTaskBridge(center, task.task_id, requested_count=3)
            bridge.start(lambda: None)

            bridge.handle(FailedEvent("provider timed out"))

            failed = center.get(task.task_id)
            self.assertEqual(TaskStatus.FAILED, failed.status)
            self.assertEqual("provider timed out", failed.error)


if __name__ == "__main__":
    unittest.main()
