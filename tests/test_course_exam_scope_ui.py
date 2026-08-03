"""Course exam-scope dialog and screen integration tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from models.course_project import CourseProject, CourseTopic
from ui.dialogs.course_exam_scope_dialog import CourseExamScopeDialog
from ui.screens.course_screen import CourseScreen


def _project() -> CourseProject:
    return CourseProject(
        course_id="course-systems",
        title="Systems",
        source_folder="",
        summary_markdown="# Systems",
        summary_path="",
        topics=[
            CourseTopic(topic_id="io", title="I/O"),
            CourseTopic(topic_id="memory", title="Memory"),
            CourseTopic(topic_id="concurrency", title="Concurrency"),
        ],
        documents=[],
        created_at="2026-07-14T00:00:00+00:00",
        updated_at="2026-07-14T00:00:00+00:00",
    )


class CourseExamScopeDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_restores_selected_scope_and_reports_count(self):
        project = _project()
        project.set_exam_scope("selected", ["memory"])

        dialog = CourseExamScopeDialog(project)

        self.assertTrue(dialog.selected_radio.isChecked())
        checked_ids = {
            dialog.topic_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(dialog.topic_list.count())
            if dialog.topic_list.item(row).checkState() == Qt.CheckState.Checked
        }
        self.assertEqual({"memory"}, checked_ids)
        self.assertIn("1 / 3", dialog.count_label.text())
        self.assertEqual(("selected", ["memory"]), dialog.scope())

    def test_dialog_rejects_empty_selected_scope(self):
        dialog = CourseExamScopeDialog(_project())
        dialog.selected_radio.setChecked(True)
        dialog._set_all_topics(False)

        with patch.object(QMessageBox, "warning") as warning:
            dialog._accept_scope()

        self.assertEqual(QDialog.DialogCode.Rejected, dialog.result())
        warning.assert_called_once()


class CourseExamScopeScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    class Manager:
        def __init__(self, project, save_success=True):
            self.project = project
            self.save_success = save_success
            self.saved = None

        def current(self):
            return self.project

        def load_all(self):
            return [self.project]

        def get(self, course_id):
            return self.project if course_id == self.project.course_id else None

        def save(self, project, make_current=True):
            self.saved = project
            if self.save_success:
                self.project = project
            return self.save_success

    def test_course_list_shows_effective_scope_count_and_enables_action(self):
        project = _project()
        project.set_exam_scope("selected", ["io"])
        screen = CourseScreen(self.Manager(project))

        screen.project_list.setCurrentRow(0)

        self.assertIn("1/3", screen.project_list.item(0).text())
        self.assertTrue(screen.scope_btn.isEnabled())

    def test_course_actions_use_three_text_only_top_level_entries(self):
        screen = CourseScreen(self.Manager(_project()))

        top_level_widgets = [
            screen.course_action_layout.itemAt(index).widget()
            for index in range(screen.course_action_layout.count())
            if screen.course_action_layout.itemAt(index).widget() is not None
        ]

        self.assertEqual(
            [screen.set_current_btn, screen.scope_btn, screen.more_actions_btn],
            top_level_widgets,
        )
        self.assertTrue(screen.more_actions_btn.icon().isNull())
        self.assertEqual(
            [
                "重命名",
                "重新生成总结",
                "归档课程",
                "刷新",
                "永久删除…",
            ],
            [action.text() for action in screen.more_actions_menu.actions() if not action.isSeparator()],
        )

    def test_scope_edit_persists_copy_and_emits_course_change(self):
        manager = self.Manager(_project())
        screen = CourseScreen(manager)
        screen.project_list.setCurrentRow(0)
        changed = []
        screen.current_course_changed.connect(lambda: changed.append(True))
        fake_dialog = SimpleNamespace(
            exec=lambda: QDialog.DialogCode.Accepted,
            scope=lambda: ("selected", ["io"]),
        )

        with patch(
            "ui.screens.course_screen.CourseExamScopeDialog",
            return_value=fake_dialog,
        ):
            screen._edit_exam_scope()

        self.assertIsNotNone(manager.saved)
        self.assertEqual(["io"], manager.saved.exam_scope_topic_ids)
        self.assertEqual([True], changed)

    def test_scope_edit_failure_keeps_original_scope_and_does_not_emit(self):
        project = _project()
        manager = self.Manager(project, save_success=False)
        screen = CourseScreen(manager)
        screen.project_list.setCurrentRow(0)
        changed = []
        screen.current_course_changed.connect(lambda: changed.append(True))
        fake_dialog = SimpleNamespace(
            exec=lambda: QDialog.DialogCode.Accepted,
            scope=lambda: ("selected", ["io"]),
        )

        with patch(
            "ui.screens.course_screen.CourseExamScopeDialog",
            return_value=fake_dialog,
        ), patch.object(QMessageBox, "critical") as critical:
            screen._edit_exam_scope()

        self.assertEqual("all", project.exam_scope_mode)
        self.assertEqual([], changed)
        critical.assert_called_once()


if __name__ == "__main__":
    unittest.main()
