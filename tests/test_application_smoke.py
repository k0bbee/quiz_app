import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.application_services import ApplicationServices
from core.background_task_center import BackgroundTaskCenter
from core.current_events import CurrentEventMaterialManager
from core.mastery_overrides import MasteryOverrideStore
from core.progress_tracker import ProgressManager
from core.quiz_snapshot_manager import QuizSnapshotManager
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.past_exam import PastExamManager
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from ui.main_window import MainWindow
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


@pytest.mark.full
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
            course = CourseProject(
                course_id="smoke-course",
                title="真实启动课程",
                source_folder=str(root / "materials"),
                summary_markdown="# 真实启动课程",
                summary_path="",
                topics=[CourseTopic("smoke", "启动测试")],
                documents=[],
                created_at="2026-07-26T00:00:00+00:00",
                updated_at="2026-07-26T00:00:00+00:00",
            )
            self.assertTrue(course_manager.save(course))

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
                metadata={
                    "course_id": course.course_id,
                    "topic_title": "启动测试",
                },
            )
            self.assertTrue(question_bank.save(question))
            question_set = QuestionSet.create_new(
                title={"zh": "启动冒烟题集", "en": "Startup Smoke Set"},
                description={"zh": "", "en": ""},
                topics=["smoke"],
                question_ids=[question.question_id],
            )
            question_set.metadata["course_id"] = course.course_id
            self.assertTrue(set_manager.save(question_set))

            services = ApplicationServices(
                question_bank=question_bank,
                set_manager=set_manager,
                progress_manager=progress_manager,
                snapshot_manager=snapshot_manager,
                mastery_overrides=mastery,
                course_manager=course_manager,
                past_exam_manager=past_exam_manager,
                current_event_manager=CurrentEventMaterialManager(root / "events"),
                task_center=task_center,
            )
            with patch(
                "ui.screens.settings_screen.SETTINGS_FILE",
                str(root / "settings.json"),
            ):
                window = MainWindow(services)

                for destination in (
                    window.SCREEN_COURSES,
                    window.SCREEN_QUESTION_BANK,
                    window.SCREEN_HOME,
                ):
                    self.assertTrue(window.navigate_to(destination))
                    self.assertEqual(destination, window.stack.currentIndex())

                current_workspace = window.stack.currentIndex()
                window.open_settings()
                _APP.processEvents()
                self.assertEqual(current_workspace, window.stack.currentIndex())
                self.assertTrue(window.settings_window.isVisible())
                window.settings_window.close()

                window.home_screen.start_btn.click()
                _APP.processEvents()
                self.assertEqual(
                    window.SCREEN_QUIZ,
                    window.stack.currentIndex(),
                )
                window.quiz_screen.answer_area.set_answer("A")
                window.quiz_screen.next_question_btn.click()
                self.assertTrue(window.quiz_screen.feedback_frame.isVisibleTo(window.quiz_screen))
                window.quiz_screen.next_question_btn.click()
                _APP.processEvents()

                self.assertEqual(window.SCREEN_RESULTS, window.stack.currentIndex())
                records = progress_manager.load_all()
                self.assertEqual(1, len(records))
                self.assertEqual(1, records[0].summary.correct)
                self.assertTrue(records[0].set_id.startswith("set-"))
                self.assertNotEqual(question_set.set_id, records[0].set_id)
                self.assertTrue(window.results_screen.repeat_study_btn.isHidden())
                self.assertTrue(window.results_screen.retry_all_action.isEnabled())

                window.results_screen.retry_all_action.trigger()
                _APP.processEvents()
                self.assertEqual(
                    window.SCREEN_QUIZ,
                    window.stack.currentIndex(),
                )

                window.deleteLater()
                _APP.processEvents()


if __name__ == "__main__":
    unittest.main()
