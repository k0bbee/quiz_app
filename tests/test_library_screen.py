import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from models.course_project import CourseProjectManager
from models.question import QuestionBank
from models.question_set import QuestionSet, SetManager
from utils.constants import Difficulty


_APP = QApplication.instance() or QApplication([])


class LibraryScreenTests(unittest.TestCase):
    def test_library_separates_question_records_from_question_set_assets(self):
        from ui.screens.library_screen import LibraryScreen

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            set_manager = SetManager(str(root / "sets"))
            question_set = QuestionSet.create_new(
                title={"zh": "操作系统复习", "en": "OS Review"},
                description={"zh": "", "en": ""},
                topics=["io"],
                question_ids=["q-1"],
                difficulty=Difficulty.MEDIUM,
            )
            question_set.metadata["course_id"] = "course-os"
            set_manager.save(question_set)
            screen = LibraryScreen(
                QuestionBank(str(root / "questions")),
                set_manager=set_manager,
                course_manager=CourseProjectManager(str(root / "courses")),
            )
            self.addCleanup(screen.close)

            screen.set_current_course("course-os")
            screen.refresh()

            self.assertEqual(2, screen.workspace_tabs.count())
            self.assertEqual("question_records", screen.workspace_tabs.widget(0).objectName())
            self.assertEqual("question_sets", screen.workspace_tabs.widget(1).objectName())
            self.assertTrue(screen.question_screen.page_header.isHidden())
            margins = screen.question_screen.layout().contentsMargins()
            self.assertEqual(
                (0, 0, 0, 0),
                (
                    margins.left(),
                    margins.top(),
                    margins.right(),
                    margins.bottom(),
                ),
            )
            self.assertEqual(1, screen.set_panel.set_list.count())
            self.assertEqual(
                question_set.set_id,
                screen.set_panel.set_list.item(0).data(
                    screen.set_panel.SET_ID_ROLE
                ),
            )
            for button in (
                screen.set_panel.rename_btn,
                screen.set_panel.export_btn,
                screen.set_panel.regenerate_btn,
                screen.set_panel.delete_btn,
            ):
                self.assertIsNotNone(button)


if __name__ == "__main__":
    unittest.main()
