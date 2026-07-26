import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from models.course_project import CourseProject, CourseTopic


def _project(course_id: str, title: str) -> CourseProject:
    return CourseProject(
        course_id=course_id,
        title=title,
        source_folder="",
        summary_markdown=f"# {title}",
        summary_path="",
        topics=[CourseTopic(f"{course_id}-topic", title)],
        documents=[],
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
    )


class CourseMergeDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_excludes_target_and_requires_a_source_selection(self):
        from ui.dialogs.course_merge_dialog import CourseMergeDialog

        target = _project("course-a", "Course A")
        source_b = _project("course-b", "Course B")
        source_c = _project("course-c", "Course C")
        dialog = CourseMergeDialog(target, [target, source_b, source_c])

        listed_ids = [
            dialog.source_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(dialog.source_list.count())
        ]
        self.assertEqual(["course-b", "course-c"], listed_ids)
        self.assertFalse(dialog.merge_btn.isEnabled())

        dialog.source_list.item(1).setCheckState(Qt.CheckState.Checked)

        self.assertTrue(dialog.merge_btn.isEnabled())
        self.assertEqual(["course-c"], dialog.selected_source_ids())
        self.assertIn("Course A", dialog.target_label.text())


if __name__ == "__main__":
    unittest.main()
