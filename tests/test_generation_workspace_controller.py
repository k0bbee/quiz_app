import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.qt

from ui.generation_workspace_controller import GenerationWorkspaceController
from ui.main_window import MainWindow


class GenerationWorkspaceControllerTests(unittest.TestCase):
    def test_main_window_reuses_one_generation_controller(self):
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertIsInstance(
            window.generation_flow,
            GenerationWorkspaceController,
        )

    def test_open_reuses_the_active_course_generation_workspace(self):
        workspace = Mock()
        workspace.generation_widget.return_value = object()
        host = SimpleNamespace(
            _generation_workspace=workspace,
            SCREEN_GENERATION=8,
            navigate_to=Mock(return_value=True),
        )

        opened = GenerationWorkspaceController(host).open()

        self.assertTrue(opened)
        host.navigate_to.assert_called_once_with(
            8,
            allow_first_run_redirect=False,
        )


if __name__ == "__main__":
    unittest.main()
