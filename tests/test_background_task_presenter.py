import unittest

from core.background_task import TaskProgress
from core.background_task_center import TaskSnapshot, TaskStatus
from core.background_task_presenter import build_task_center_view, task_toolbar_text


def snapshot(task_id, status, *, current=0, total=0, detail="", error=""):
    return TaskSnapshot(
        task_id=task_id,
        kind="question_generation",
        title=f"Task {task_id}",
        status=status,
        created_at=f"2026-07-15T08:00:0{task_id[-1]}+00:00",
        updated_at=f"2026-07-15T08:00:0{task_id[-1]}+00:00",
        progress=TaskProgress("generating_questions", current, total, detail),
        error=error,
    )


class BackgroundTaskPresenterTests(unittest.TestCase):
    def test_attention_view_prioritizes_active_failed_and_interrupted_tasks(self):
        view = build_task_center_view(
            [
                snapshot("task-4", TaskStatus.COMPLETED),
                snapshot("task-3", TaskStatus.FAILED, error="provider timed out"),
                snapshot("task-2", TaskStatus.INTERRUPTED, current=2, total=8),
                snapshot("task-1", TaskStatus.RUNNING, current=3, total=10),
            ],
            language="zh",
            attention_only=True,
        )

        self.assertEqual(3, view.attention_count)
        self.assertEqual(1, view.active_count)
        self.assertEqual(
            ["task-1", "task-3", "task-2"],
            [item.task_id for item in view.items],
        )
        self.assertEqual("运行中", view.items[0].status_text)
        self.assertEqual("3 / 10", view.items[0].progress_text)
        self.assertTrue(view.items[0].can_cancel)
        self.assertFalse(view.items[0].can_dismiss)
        self.assertEqual("provider timed out", view.items[1].detail_text)
        self.assertTrue(view.items[1].can_dismiss)

    def test_all_view_keeps_recent_completed_and_cancelled_records(self):
        view = build_task_center_view(
            [
                snapshot("task-3", TaskStatus.CANCELLED),
                snapshot("task-2", TaskStatus.COMPLETED),
                snapshot("task-1", TaskStatus.QUEUED),
            ],
            language="en",
            attention_only=False,
        )

        self.assertEqual(
            ["task-1", "task-3", "task-2"],
            [item.task_id for item in view.items],
        )
        self.assertEqual("Queued", view.items[0].status_text)
        self.assertEqual("Cancelled", view.items[1].status_text)
        self.assertEqual("Completed", view.items[2].status_text)

    def test_toolbar_text_only_adds_count_when_attention_is_needed(self):
        self.assertEqual("任务", task_toolbar_text(0, "zh"))
        self.assertEqual("任务 4", task_toolbar_text(4, "zh"))
        self.assertEqual("Tasks", task_toolbar_text(0, "en"))
        self.assertEqual("Tasks 4", task_toolbar_text(4, "en"))


if __name__ == "__main__":
    unittest.main()
