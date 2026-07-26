import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from tests.test_current_events import law_project
from ui.main_window import MainWindow
from ui.screens.course_screen import CourseScreen


_APP = QApplication.instance() or QApplication([])


class Manager:
    def __init__(self, project):
        self.project = project
        self.current_id = project.course_id

    def current(self):
        return self.project if self.current_id else None

    def load_all(self):
        return [self.project]

    def get(self, course_id):
        return self.project if course_id == self.project.course_id else None

    def set_current(self, course_id):
        self.current_id = course_id
        return course_id == self.project.course_id


class AcceptedDialog:
    def __init__(self, project, parent=None):
        self.project = project
        self.parent = parent
        self.saved_pack = object()
        self.generate_after_save = True

    def exec(self):
        return QDialog.DialogCode.Accepted


class CurrentEventCourseFlowTests(unittest.TestCase):
    def test_default_review_dialog_uses_injected_material_manager(self):
        project = law_project()
        material_manager = object()
        screen = CourseScreen(
            Manager(project),
            current_event_manager=material_manager,
        )

        with patch(
            "ui.dialogs.current_event_review_dialog.CurrentEventReviewDialog"
        ) as dialog_class:
            screen._create_current_event_dialog(project, parent=screen)

        dialog_class.assert_called_once_with(
            project,
            parent=screen,
            material_manager=material_manager,
        )

    def test_course_secondary_action_opens_review_for_selected_course(self):
        project = law_project()
        created = []

        def factory(selected, parent=None):
            dialog = AcceptedDialog(selected, parent)
            created.append(dialog)
            return dialog

        screen = CourseScreen(
            Manager(project),
            current_event_dialog_factory=factory,
        )
        requests = []
        screen.current_event_generation_requested.connect(
            lambda course_id, pack: requests.append((course_id, pack))
        )

        self.assertTrue(screen.current_events_action.isEnabled())
        screen.current_events_action.trigger()

        self.assertEqual(project, created[0].project)
        self.assertEqual(
            [(project.course_id, created[0].saved_pack)],
            requests,
        )

    def test_saving_materials_without_generation_does_not_start_generation(self):
        project = law_project()

        class SaveOnlyDialog(AcceptedDialog):
            def __init__(self, selected, parent=None):
                super().__init__(selected, parent)
                self.generate_after_save = False

        screen = CourseScreen(
            Manager(project),
            current_event_dialog_factory=SaveOnlyDialog,
        )
        requests = []
        screen.current_event_generation_requested.connect(
            lambda course_id, pack: requests.append((course_id, pack))
        )

        screen.current_events_action.trigger()

        self.assertEqual([], requests)

    def test_main_window_routes_reviewed_pack_to_generation(self):
        project = law_project()
        pack = object()
        shell = type("Shell", (), {})()
        shell.course_manager = Manager(project)
        calls = []
        shell._on_ai_generate = lambda **kwargs: calls.append(kwargs)

        MainWindow._on_current_event_generation(shell, project.course_id, pack)

        self.assertEqual(
            [{"course_override": project, "material_pack": pack}],
            calls,
        )

    def test_main_window_connects_course_material_generation_signal(self):
        with patch.object(MainWindow, "_on_current_event_generation") as handler:
            window = MainWindow()
            self.addCleanup(window.close)
            pack = object()

            window._get_course_screen().current_event_generation_requested.emit(
                "course-a", pack
            )

        handler.assert_called_once_with("course-a", pack)


if __name__ == "__main__":
    unittest.main()
