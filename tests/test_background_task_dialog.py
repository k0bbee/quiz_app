import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QDialog

from core.background_task_center import BackgroundTaskCenter
from ui.dialogs.background_task_dialog import BackgroundTaskDialog


_APP = QApplication.instance() or QApplication([])


class BackgroundTaskDialogTests(unittest.TestCase):
    def test_failed_task_is_visible_and_can_be_dismissed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = BackgroundTaskCenter(Path(tmpdir) / "tasks.json")
            task = center.create(kind="question_generation", title="生成练习题")
            center.fail(task.task_id, "服务暂时不可用")

            dialog = BackgroundTaskDialog(center, language="zh")

            self.assertEqual(1, dialog.task_list.topLevelItemCount())
            item = dialog.task_list.topLevelItem(0)
            self.assertEqual(task.task_id, item.data(0, dialog.TASK_ID_ROLE))
            self.assertEqual("失败", item.text(2))
            dialog.task_list.setCurrentItem(item)
            self.assertTrue(dialog.dismiss_btn.isEnabled())
            self.assertIn("服务暂时不可用", dialog.detail_label.text())

            dialog.dismiss_btn.click()

            self.assertEqual(0, dialog.task_list.topLevelItemCount())
            self.assertEqual((), center.snapshots())

    def test_history_filter_can_reveal_completed_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = BackgroundTaskCenter(Path(tmpdir) / "tasks.json")
            task = center.create(kind="course_import", title="导入课程")
            center.start(task.task_id)
            center.complete(task.task_id, result_summary="已完成")

            dialog = BackgroundTaskDialog(center, language="en")

            self.assertEqual(0, dialog.task_list.topLevelItemCount())
            dialog.attention_only_btn.setChecked(False)
            _APP.processEvents()
            self.assertEqual(1, dialog.task_list.topLevelItemCount())
            self.assertEqual("Completed", dialog.task_list.topLevelItem(0).text(2))

    def test_open_task_page_returns_the_selected_task_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = BackgroundTaskCenter(Path(tmpdir) / "tasks.json")
            task = center.create(
                kind="course_import",
                title="导入课程",
                metadata={"source_folder": "C:/courses/physics"},
            )
            center.fail(task.task_id, "interrupted")
            dialog = BackgroundTaskDialog(center, language="zh")

            item = dialog.task_list.topLevelItem(0)
            dialog.task_list.setCurrentItem(item)
            open_task_btn = getattr(dialog, "open_task_btn", None)
            self.assertIsNotNone(open_task_btn)
            self.assertTrue(open_task_btn.isEnabled())

            open_task_btn.click()

            self.assertEqual(task.task_id, dialog.requested_task_id)
            self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())


if __name__ == "__main__":
    unittest.main()
