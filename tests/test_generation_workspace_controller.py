import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ui.generation_workspace_controller import GenerationWorkspaceController


class GenerationWorkspaceControllerTests(unittest.TestCase):
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
