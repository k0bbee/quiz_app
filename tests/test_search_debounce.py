import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from models.course_project import CourseProjectManager
from models.question import QuestionBank
from models.question_set import SetManager
from ui.screens.question_bank_screen import QuestionBankScreen
from ui.screens.topic_selection_screen import TopicSelectionScreen


_APP = QApplication.instance() or QApplication([])


class SearchDebounceTests(unittest.TestCase):
    def test_question_bank_search_input_uses_single_shot_debounce(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = QuestionBankScreen(
                QuestionBank(str(Path(tmpdir) / "questions")),
                SetManager(str(Path(tmpdir) / "sets")),
                course_manager=CourseProjectManager(str(Path(tmpdir) / "courses")),
            )
            self.addCleanup(screen.close)

            self.assertTrue(screen.search_debounce_timer.isSingleShot())
            self.assertEqual(250, screen.search_debounce_timer.interval())

            screen.search_input.setText("cache")

            self.assertTrue(screen.search_debounce_timer.isActive())
            screen.search_debounce_timer.stop()

    def test_topic_selection_search_input_uses_single_shot_debounce(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = TopicSelectionScreen(SetManager(str(Path(tmpdir) / "sets")))
            self.addCleanup(screen.close)

            self.assertTrue(screen.search_debounce_timer.isSingleShot())
            self.assertEqual(250, screen.search_debounce_timer.interval())

            screen.search_input.setText("cache")

            self.assertTrue(screen.search_debounce_timer.isActive())
            screen.search_debounce_timer.stop()


if __name__ == "__main__":
    unittest.main()
