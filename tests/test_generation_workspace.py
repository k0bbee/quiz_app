import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QLabel

from models.course_project import CourseProject, CourseTopic
from ui.main_window import MainWindow
from ui.screens.generation_workspace import GenerationWorkspace


_APP = QApplication.instance() or QApplication([])


class GenerationWorkspaceTests(unittest.TestCase):
    def test_workspace_hosts_generation_surface_without_turning_it_into_a_window(self):
        workspace = GenerationWorkspace()
        self.addCleanup(workspace.close)
        generation_surface = QDialog()
        QLabel("generation", generation_surface)

        workspace.show_generation_widget(
            generation_surface,
            course_id="course-os",
            course_title="操作系统",
        )

        self.assertIs(generation_surface, workspace.generation_widget())
        self.assertIs(workspace.generation_host, generation_surface.parent())
        self.assertEqual(Qt.WindowType.Widget, generation_surface.windowType())
        self.assertEqual("course-os", workspace.course_id)
        self.assertIn("操作系统", workspace.context_label.text())

    def test_main_generation_flow_uses_persistent_route_without_modal_exec(self):
        window = MainWindow()
        self.addCleanup(window.close)
        course = CourseProject(
            course_id="course-workspace",
            title="操作系统",
            source_folder="",
            summary_markdown="# 操作系统",
            summary_path="",
            topics=[CourseTopic("io", "I/O")],
            documents=[],
            created_at="2026-07-29T00:00:00+00:00",
            updated_at="2026-07-29T00:00:00+00:00",
        )
        window.course_manager.save(course)
        dialog = QDialog()
        dialog.exec = Mock(
            side_effect=AssertionError("ordinary generation must not open a modal loop")
        )
        dialog.start_generation_when_shown = Mock()

        with patch.object(
            MainWindow,
            "_configure_generation_dialog",
            return_value=(dialog, course, False, "manual"),
        ):
            opened = window._on_ai_generate(auto_start=True)

        self.assertTrue(opened)
        self.assertEqual(window.SCREEN_GENERATION, window.stack.currentIndex())
        self.assertIs(dialog, window._get_generation_workspace().generation_widget())
        dialog.exec.assert_not_called()
        dialog.start_generation_when_shown.assert_called_once_with()

        self.assertTrue(window.navigate_to(window.SCREEN_HOME))
        self.assertTrue(window.navigate_to(window.SCREEN_GENERATION))
        self.assertIs(dialog, window._get_generation_workspace().generation_widget())

    def test_main_window_defers_close_while_generation_shutdown_is_pending(self):
        window = MainWindow()
        self.addCleanup(window.close)
        workspace = window._get_generation_workspace()
        workspace.request_shutdown = Mock(return_value=False)
        event = QCloseEvent()

        window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertTrue(window._generation_close_pending)
        workspace.request_shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
