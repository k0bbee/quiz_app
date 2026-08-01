import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.background_task_center import TaskStatus


class TaskRecoveryControllerTests(unittest.TestCase):
    @staticmethod
    def _controller(snapshot, **overrides):
        from ui.task_recovery_controller import TaskRecoveryController

        dependencies = {
            "task_center": SimpleNamespace(get=Mock(return_value=snapshot)),
            "course_manager": SimpleNamespace(
                get=Mock(return_value=None),
                current=Mock(return_value=None),
                set_current=Mock(return_value=False),
            ),
            "current_language": lambda: "zh",
            "navigate": Mock(return_value=True),
            "open_settings": Mock(),
            "course_changed": Mock(),
            "get_course_screen": Mock(),
            "get_past_exam_screen": Mock(),
            "generate_questions": Mock(),
            "courses_screen_index": 1,
            "past_exams_screen_index": 2,
            "question_bank_screen_index": 3,
        }
        dependencies.update(overrides)
        return TaskRecoveryController(**dependencies)

    def test_open_generation_task_returns_to_course_generation_workspace(self):
        snapshot = SimpleNamespace(
            kind="question_generation",
            metadata={
                "course_id": "course-1",
                "draft_id": "draft-1",
                "draft_source": "manual",
            },
        )
        course = object()
        course_manager = SimpleNamespace(
            get=Mock(return_value=course),
            current=Mock(return_value=None),
            set_current=Mock(return_value=True),
        )
        navigate = Mock(return_value=True)
        get_course_screen = Mock()
        generate_questions = Mock(return_value=True)
        controller = self._controller(
            snapshot,
            course_manager=course_manager,
            navigate=navigate,
            get_course_screen=get_course_screen,
            generate_questions=generate_questions,
        )

        opened = controller.open_page("task-1")

        self.assertTrue(opened)
        navigate.assert_not_called()
        get_course_screen.assert_not_called()
        generate_questions.assert_called_once_with(
            course_override=course,
            recovery_context=snapshot.metadata,
            draft_source="manual",
            draft_id="draft-1",
            present_error=False,
        )

    def test_open_generation_task_with_deleted_course_uses_course_recovery_page(self):
        snapshot = SimpleNamespace(
            kind="question_generation",
            metadata={"course_id": "deleted-course"},
        )
        navigate = Mock(return_value=True)
        controller = self._controller(snapshot, navigate=navigate)

        opened = controller.open_page("task-1")

        self.assertTrue(opened)
        navigate.assert_called_once_with(1)

    def test_retry_rejects_incomplete_generation_metadata(self):
        snapshot = SimpleNamespace(
            status=TaskStatus.FAILED,
            kind="question_generation",
            metadata={"course_id": "course-1"},
        )
        navigate = Mock(return_value=True)
        controller = self._controller(snapshot, navigate=navigate)

        restored = controller.retry("task-1")

        self.assertFalse(restored)
        navigate.assert_not_called()

    def test_open_data_task_uses_settings_utility_without_navigation(self):
        snapshot = SimpleNamespace(kind="app_data_export", metadata={})
        navigate = Mock(return_value=True)
        open_settings = Mock()
        controller = self._controller(
            snapshot,
            navigate=navigate,
            open_settings=open_settings,
        )

        opened = controller.open_page("task-1")

        self.assertTrue(opened)
        open_settings.assert_called_once_with("data")
        navigate.assert_not_called()

    def test_retry_restores_valid_course_import_without_starting_it(self):
        snapshot = SimpleNamespace(
            status=TaskStatus.FAILED,
            kind="course_import",
            metadata={"source_folder": "C:/courses/physics"},
        )
        course_screen = SimpleNamespace(restore_task_context=Mock())
        navigate = Mock(return_value=True)
        controller = self._controller(
            snapshot,
            navigate=navigate,
            get_course_screen=Mock(return_value=course_screen),
        )

        restored = controller.retry("task-1")

        self.assertTrue(restored)
        navigate.assert_called_once_with(1)
        course_screen.restore_task_context.assert_called_once_with(snapshot)

    def test_retry_generation_rebuilds_plan_after_activating_course(self):
        snapshot = SimpleNamespace(
            status=TaskStatus.FAILED,
            kind="question_generation",
            metadata={
                "course_id": "course-1",
                "requested_count": 6,
                "topic_ids": ["cache"],
            },
        )
        course = object()
        course_manager = SimpleNamespace(
            get=Mock(return_value=course),
            current=Mock(return_value=None),
            set_current=Mock(return_value=True),
        )
        course_changed = Mock()
        generate_questions = Mock(return_value=True)
        controller = self._controller(
            snapshot,
            course_manager=course_manager,
            course_changed=course_changed,
            generate_questions=generate_questions,
        )
        navigate = controller._navigate

        restored = controller.retry("task-1")

        self.assertTrue(restored)
        navigate.assert_not_called()
        course_manager.set_current.assert_called_once_with("course-1")
        course_changed.assert_called_once_with()
        kwargs = generate_questions.call_args.kwargs
        self.assertIs(course, kwargs["course_override"])
        self.assertEqual(6, kwargs["initial_plan"].question_count)
        self.assertEqual(("cache",), kwargs["initial_plan"].selected_topics)
        self.assertEqual(snapshot.metadata, kwargs["recovery_context"])


if __name__ == "__main__":
    unittest.main()
