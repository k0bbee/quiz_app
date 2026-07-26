import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

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
        task_recovery = SimpleNamespace(
            open_page=Mock(return_value=True),
            retry=Mock(return_value=True),
        )
        shell = SimpleNamespace(
            task_center=object(),
            lang_manager=SimpleNamespace(current="zh"),
            task_recovery=task_recovery,
            _refresh_task_center_action=Mock(),
        )
        with patch(
            "ui.main_window.BackgroundTaskDialog",
            return_value=_DialogResult("open"),
        ):
            MainWindow._open_task_center(shell)

        task_recovery.open_page.assert_called_once_with("task-1")
        task_recovery.retry.assert_not_called()

    def test_retry_action_uses_validating_recovery_path(self):
        task_recovery = SimpleNamespace(
            open_page=Mock(return_value=True),
            retry=Mock(return_value=True),
        )
        shell = SimpleNamespace(
            task_center=object(),
            lang_manager=SimpleNamespace(current="zh"),
            task_recovery=task_recovery,
            _refresh_task_center_action=Mock(),
        )
        with patch(
            "ui.main_window.BackgroundTaskDialog",
            return_value=_DialogResult("retry"),
        ):
            MainWindow._open_task_center(shell)

        task_recovery.retry.assert_called_once_with("task-1")
        task_recovery.open_page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
