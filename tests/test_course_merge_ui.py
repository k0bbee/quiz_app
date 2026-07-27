import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog

from core.course_asset_lifecycle import CourseAssetImpact
from models.course_project import CourseProject, CourseProjectManager, CourseTopic


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

    def test_dialog_summarizes_selected_assets_and_preserved_history_identity(self):
        from ui.dialogs.course_merge_dialog import CourseMergeDialog

        target = _project("course-a", "Course A")
        source = _project("course-b", "Course B")
        impact = CourseAssetImpact(
            course_id=source.course_id,
            question_ids=("q1", "q2"),
            affected_set_ids=("set-1",),
            progress_ids=("progress-1", "progress-2", "progress-3"),
            complete_archive_ids=("progress-1",),
            incomplete_archive_ids=("progress-2",),
            legacy_archive_ids=("progress-3",),
            draft_progress_ids=("progress-draft",),
            snapshot_ids=("snapshot-1",),
            past_exam_ids=("exam-1",),
            current_event_pack_ids=("pack-1",),
        )
        dialog = CourseMergeDialog(
            target,
            [target, source],
            impacts={source.course_id: impact},
        )

        dialog.source_list.item(0).setCheckState(Qt.CheckState.Checked)

        text = dialog.impact_label.text()
        self.assertIn("题目：2", text)
        self.assertIn("题集：1", text)
        self.assertIn("完成历史：3", text)
        self.assertIn("完整归档：1", text)
        self.assertIn("残缺归档：1", text)
        self.assertIn("合并前待迁移：1", text)
        self.assertIn("未完成草稿：2", text)
        self.assertIn("历史发生时的课程身份保持不变", text)
        self.assertIn("Course A", text)

    def test_course_screen_supplies_real_source_impacts_to_merge_dialog(self):
        from ui.screens.course_screen import CourseScreen

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
            target = _project("course-a", "Course A")
            source = _project("course-b", "Course B")
            manager.save(target, make_current=True)
            manager.save(source, make_current=False)
            captured = {}

            def dialog_factory(
                retained,
                courses,
                parent=None,
                *,
                impacts=None,
            ):
                captured["target"] = retained
                captured["courses"] = courses
                captured["impacts"] = impacts
                return SimpleNamespace(
                    exec=lambda: QDialog.DialogCode.Rejected,
                )

            screen = CourseScreen(
                manager,
                merge_dialog_factory=dialog_factory,
            )
            for row in range(screen.project_list.count()):
                item = screen.project_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == target.course_id:
                    screen.project_list.setCurrentRow(row)
                    break

            screen._merge_selected_project()

            self.assertEqual(target.course_id, captured["target"].course_id)
            self.assertIn(source.course_id, captured["impacts"])
            self.assertEqual(
                source.course_id,
                captured["impacts"][source.course_id].course_id,
            )


if __name__ == "__main__":
    unittest.main()
