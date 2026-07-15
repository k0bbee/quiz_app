import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.background_task_center import BackgroundTaskCenter
from core.mastery_overrides import MasteryOverrideStore
from core.progress_tracker import ProgressManager
from core.quiz_snapshot_manager import QuizSnapshotManager
from models.course_project import CourseProjectManager
from models.past_exam import PastExamManager
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from ui.main_window import MainWindow
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class ApplicationSmokeTests(unittest.TestCase):
    def test_main_window_navigation_and_one_question_practice_close_the_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))
            progress_manager = ProgressManager(str(root / "progress"))
            snapshot_manager = QuizSnapshotManager(str(root / "snapshots"))
            course_manager = CourseProjectManager(str(root / "courses"))
            past_exam_manager = PastExamManager(root / "past_exams")
            task_center = BackgroundTaskCenter(root / "tasks.json")
            mastery = MasteryOverrideStore(root / "mastery.json")

            question = Question(
                question_id="smoke-q1",
                type=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "哪一个选项用于真实启动冒烟测试？",
                        "options": ["A. 正确选项", "B. 错误选项"],
                        "explanation": "用于验证完整作答闭环。",
                    },
                    "en": {
                        "stem": "Which option is used by the startup smoke test?",
                        "options": ["A. Correct", "B. Incorrect"],
                        "explanation": "Verifies the complete quiz loop.",
                    },
                },
                correct_answer="A",
                topic="smoke",
            )
            self.assertTrue(question_bank.save(question))
            question_set = QuestionSet.create_new(
                title={"zh": "启动冒烟题集", "en": "Startup Smoke Set"},
                description={"zh": "", "en": ""},
                topics=["smoke"],
                question_ids=[question.question_id],
            )
            self.assertTrue(set_manager.save(question_set))

            with ExitStack() as stack:
                stack.enter_context(patch("ui.main_window.QuestionBank", return_value=question_bank))
                stack.enter_context(patch("ui.main_window.SetManager", return_value=set_manager))
                stack.enter_context(patch("ui.main_window.ProgressManager", return_value=progress_manager))
                stack.enter_context(patch("ui.main_window.QuizSnapshotManager", return_value=snapshot_manager))
                stack.enter_context(patch("ui.main_window.CourseProjectManager", return_value=course_manager))
                stack.enter_context(patch("ui.main_window.PastExamManager", return_value=past_exam_manager))
                stack.enter_context(patch("ui.main_window.BackgroundTaskCenter", return_value=task_center))
                stack.enter_context(patch("ui.main_window.MasteryOverrideStore", return_value=mastery))
                window = MainWindow()

                for destination in (
                    window.SCREEN_COURSES,
                    window.SCREEN_QUESTION_BANK,
                    window.SCREEN_PAST_EXAMS,
                    window.SCREEN_SETTINGS,
                    window.SCREEN_HOME,
                ):
                    self.assertTrue(window.navigate_to(destination))
                    self.assertEqual(destination, window.stack.currentIndex())

                window._on_quiz_start(question_set.set_id, [question.question_id])
                self.assertEqual(window.SCREEN_QUIZ, window.stack.currentIndex())
                window.quiz_screen.answer_area.set_answer("A")
                window.quiz_screen.next_question_btn.click()
                self.assertTrue(window.quiz_screen.feedback_frame.isVisibleTo(window.quiz_screen))
                window.quiz_screen.next_question_btn.click()
                _APP.processEvents()

                self.assertEqual(window.SCREEN_RESULTS, window.stack.currentIndex())
                records = progress_manager.load_all()
                self.assertEqual(1, len(records))
                self.assertEqual(1, records[0].summary.correct)
                self.assertEqual(question_set.set_id, records[0].set_id)

                window.deleteLater()
                _APP.processEvents()


if __name__ == "__main__":
    unittest.main()
