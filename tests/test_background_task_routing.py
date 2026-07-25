import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from core.background_task_center import TaskStatus
from ui.main_window import MainWindow


pytestmark = pytest.mark.qt


class _DialogResult:
    def __init__(self, action: str):
        self.requested_task_id = "task-1"
        self.requested_action = action

    def exec(self):
        return 0


class BackgroundTaskRoutingTests(unittest.TestCase):
    def test_open_action_navigates_without_using_retry_restore_path(self):
        shell = SimpleNamespace(
            task_center=object(),
            lang_manager=SimpleNamespace(current="zh"),
            _open_task_page=Mock(return_value=True),
            _retry_task_context=Mock(return_value=True),
            _refresh_task_center_action=Mock(),
        )
        with patch(
            "ui.main_window.BackgroundTaskDialog",
            return_value=_DialogResult("open"),
        ):
            MainWindow._open_task_center(shell)

        shell._open_task_page.assert_called_once_with("task-1")
        shell._retry_task_context.assert_not_called()

    def test_retry_action_revalidates_metadata_before_restoring_inputs(self):
        snapshot = SimpleNamespace(
            status=TaskStatus.FAILED,
            kind="question_generation",
            metadata={"course_id": "course-1"},
        )
        shell = SimpleNamespace(
            task_center=SimpleNamespace(get=Mock(return_value=snapshot)),
            lang_manager=SimpleNamespace(current="zh"),
            _open_task_context=Mock(return_value=True),
        )

        restored = MainWindow._retry_task_context(shell, "task-1")

        self.assertFalse(restored)
        shell._open_task_context.assert_not_called()

    def test_open_generation_task_only_navigates_to_course_page(self):
        snapshot = SimpleNamespace(
            kind="question_generation",
            metadata={"course_id": "missing-course"},
        )
        shell = SimpleNamespace(
            task_center=SimpleNamespace(get=Mock(return_value=snapshot)),
            course_manager=SimpleNamespace(get=Mock(return_value=None)),
            navigate_to=Mock(return_value=True),
            SCREEN_COURSES=1,
            SCREEN_PAST_EXAMS=2,
            SCREEN_QUESTION_BANK=3,
        )

        opened = MainWindow._open_task_page(shell, "task-1")

        self.assertTrue(opened)
        shell.navigate_to.assert_called_once_with(shell.SCREEN_COURSES)

    def test_open_data_task_uses_settings_utility_window(self):
        snapshot = SimpleNamespace(
            kind="app_data_export",
            metadata={},
        )
        shell = SimpleNamespace(
            task_center=SimpleNamespace(get=Mock(return_value=snapshot)),
            course_manager=SimpleNamespace(get=Mock(return_value=None)),
            navigate_to=Mock(return_value=True),
            open_settings=Mock(),
            SCREEN_COURSES=1,
            SCREEN_PAST_EXAMS=2,
            SCREEN_QUESTION_BANK=3,
        )

        opened = MainWindow._open_task_page(shell, "task-1")

        self.assertTrue(opened)
        shell.open_settings.assert_called_once_with("data")
        shell.navigate_to.assert_not_called()


if __name__ == "__main__":
    unittest.main()
