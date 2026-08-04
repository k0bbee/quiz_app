import unittest

from core.background_task import TaskProgress
from core.background_task_center import BackgroundTaskCenter, TaskStatus


class BackgroundTaskCenterTests(unittest.TestCase):
    def test_task_lifecycle_is_scoped_to_the_current_session(self):
        center = BackgroundTaskCenter(
            id_factory=lambda: "task-1",
            clock=lambda: "2026-07-15T08:00:00+00:00",
        )
        created = center.create(
            kind="document_ocr",
            title="马克思主义基本原理真题",
            metadata={"course_id": "course-marx"},
        )
        center.start(created.task_id)
        center.report(
            created.task_id,
            TaskProgress("parsing_page", current=12, total=80, detail="第 12 页"),
        )
        completed = center.complete(
            created.task_id,
            result_summary="已导入 80 页",
            result_count=80,
        )

        new_session = BackgroundTaskCenter()

        self.assertEqual(TaskStatus.COMPLETED, completed.status)
        with self.assertRaises(KeyError):
            new_session.get(created.task_id)

    def test_cancel_request_is_idempotent_and_invokes_runtime_hook_once(self):
        center = BackgroundTaskCenter(id_factory=lambda: "task-1")
        task = center.create(kind="generation", title="生成模拟卷")
        center.start(task.task_id)
        cancelled = []
        center.bind_cancel(task.task_id, lambda: cancelled.append(task.task_id))

        first = center.request_cancel(task.task_id)
        second = center.request_cancel(task.task_id)
        final = center.mark_cancelled(task.task_id, result_count=7)

        self.assertEqual(TaskStatus.CANCELLING, first.status)
        self.assertEqual(TaskStatus.CANCELLING, second.status)
        self.assertEqual([task.task_id], cancelled)
        self.assertEqual(TaskStatus.CANCELLED, final.status)
        self.assertEqual(7, final.result_count)

    def test_retry_creates_a_new_queued_task_linked_to_the_failed_task(self):
        ids = iter(["task-1", "task-2"])
        center = BackgroundTaskCenter(id_factory=lambda: next(ids))
        task = center.create(
            kind="app_data_import",
            title="导入应用数据",
            metadata={"source": "backup.zip"},
        )
        center.start(task.task_id)
        center.fail(task.task_id, "校验失败", result_count=2)

        retried = center.retry(task.task_id)

        self.assertEqual("task-2", retried.task_id)
        self.assertEqual(TaskStatus.QUEUED, retried.status)
        self.assertEqual("task-1", retried.retry_of)
        self.assertEqual(task.kind, retried.kind)
        self.assertEqual(task.title, retried.title)
        self.assertEqual(task.metadata, retried.metadata)

    def test_rejects_completion_before_a_task_starts(self):
        center = BackgroundTaskCenter(id_factory=lambda: "task-1")
        task = center.create(kind="generation", title="生成题目")

        with self.assertRaisesRegex(ValueError, "queued.*completed"):
            center.complete(task.task_id)

    def test_report_updates_in_memory_without_frequency_persistence(self):
        center = BackgroundTaskCenter(id_factory=lambda: "task-1")
        task = center.create(kind="document_ocr", title="大型扫描件")
        center.start(task.task_id)

        center.report(task.task_id, TaskProgress("ocr", 1, 500, "第 1 页"))
        center.report(task.task_id, TaskProgress("ocr", 2, 500, "第 2 页"))

        in_memory = center.get(task.task_id)
        self.assertEqual(2, in_memory.progress.current)
        self.assertEqual("第 2 页", in_memory.progress.detail)

    def test_snapshot_metadata_cannot_mutate_the_session_record(self):
        center = BackgroundTaskCenter(id_factory=lambda: "task-1")
        created = center.create(
            kind="course_import",
            title="操作系统",
            metadata={"course_id": "course-os", "files": ["io.pdf"]},
        )

        created.metadata["course_id"] = "other-course"
        created.metadata["files"].append("noise.pdf")
        fetched = center.get(created.task_id)
        fetched.metadata["course_id"] = "third-course"

        current = center.get(created.task_id)
        self.assertEqual("course-os", current.metadata["course_id"])
        self.assertEqual(["io.pdf"], current.metadata["files"])

    def test_dismiss_removes_only_terminal_tasks(self):
        ids = iter(["task-1", "task-2"])
        center = BackgroundTaskCenter(id_factory=lambda: next(ids))
        running = center.create(kind="ocr", title="正在识别")
        center.start(running.task_id)
        completed = center.create(kind="generation", title="已经完成")
        center.start(completed.task_id)
        center.complete(completed.task_id, result_count=3)

        with self.assertRaisesRegex(ValueError, "running"):
            center.dismiss(running.task_id)
        center.dismiss(completed.task_id)

        self.assertEqual(
            [running.task_id],
            [item.task_id for item in center.snapshots()],
        )


if __name__ == "__main__":
    unittest.main()
