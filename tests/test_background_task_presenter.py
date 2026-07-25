import unittest

from core.background_task import TaskProgress
from core.background_task_center import TaskSnapshot, TaskStatus
from core.background_task_presenter import build_task_center_view, task_toolbar_text
from core.background_task_recovery import task_destination


def snapshot(
    task_id,
    status,
    *,
    current=0,
    total=0,
    detail="",
    error="",
    kind="question_generation",
    metadata=None,
):
    return TaskSnapshot(
        task_id=task_id,
        kind=kind,
        title=f"Task {task_id}",
        status=status,
        created_at=f"2026-07-15T08:00:0{task_id[-1]}+00:00",
        updated_at=f"2026-07-15T08:00:0{task_id[-1]}+00:00",
        progress=TaskProgress("generating_questions", current, total, detail),
        metadata=metadata or {},
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
        self.assertNotIn("T", view.items[0].updated_at)
        self.assertNotIn("+00:00", view.items[0].updated_at)
        self.assertTrue(view.items[0].can_cancel)
        self.assertFalse(view.items[0].can_dismiss)
        self.assertTrue(view.items[0].can_open)
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

    def test_question_bank_validation_has_localized_task_kind(self):
        zh = build_task_center_view(
            [snapshot("task-1", TaskStatus.RUNNING, kind="question_bank_validation")],
            language="zh",
            attention_only=False,
        )
        en = build_task_center_view(
            [snapshot("task-1", TaskStatus.RUNNING, kind="question_bank_validation")],
            language="en",
            attention_only=False,
        )

        self.assertEqual("题库检查", zh.items[0].kind_text)
        self.assertEqual("Question bank check", en.items[0].kind_text)

    def test_unknown_task_kind_does_not_offer_a_dead_end_open_action(self):
        view = build_task_center_view(
            [snapshot("task-1", TaskStatus.FAILED, kind="future_unknown_task")],
            language="en",
            attention_only=False,
        )

        self.assertIs(False, getattr(view.items[0], "can_open", None))

    def test_every_persisted_task_kind_routes_to_an_existing_workspace(self):
        self.assertEqual("generation", task_destination("question_generation"))
        self.assertEqual("courses", task_destination("course_import"))
        self.assertEqual("courses", task_destination("course_summary"))
        self.assertEqual("past_exams", task_destination("past_exam_ocr"))
        self.assertEqual("past_exams", task_destination("past_exam_analysis"))
        self.assertEqual("settings_data", task_destination("app_data_import"))
        self.assertEqual("settings_data", task_destination("app_data_export"))
        self.assertEqual("question_bank", task_destination("question_bank_validation"))

    def test_retry_requires_safe_recovery_metadata_and_explains_rejection(self):
        recoverable = snapshot(
            "task-1",
            TaskStatus.INTERRUPTED,
            metadata={
                "course_id": "course-os",
                "topic_ids": ["input_output"],
                "requested_count": 10,
            },
        )
        incomplete = snapshot(
            "task-2",
            TaskStatus.FAILED,
            metadata={"course_id": "course-os"},
        )
        malformed = snapshot(
            "task-3",
            TaskStatus.FAILED,
            metadata={
                "course_id": "course-os",
                "exam_plan": {"question_count": "many"},
            },
        )

        view = build_task_center_view(
            [recoverable, incomplete, malformed],
            language="zh",
            attention_only=False,
        )
        by_id = {item.task_id: item for item in view.items}

        self.assertTrue(by_id["task-1"].can_retry)
        self.assertEqual("", by_id["task-1"].retry_reason)
        self.assertFalse(by_id["task-2"].can_retry)
        self.assertIn("缺少", by_id["task-2"].retry_reason)
        self.assertIn("出题方案", by_id["task-2"].retry_reason)
        self.assertNotIn("exam_plan", by_id["task-2"].retry_reason)
        self.assertFalse(by_id["task-3"].can_retry)
        self.assertIn("无效", by_id["task-3"].retry_reason)


if __name__ == "__main__":
    unittest.main()
