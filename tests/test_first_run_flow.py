import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.first_run_flow import FirstRunStage, resolve_first_run_state
from models.course_project import CourseProject
from models.question import Question
from models.question_set import QuestionSet
from ui.main_window import MainWindow
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class FirstRunFlowTests(unittest.TestCase):
    def test_state_prioritizes_ai_course_generation_and_ready_steps(self):
        self.assertEqual(
            FirstRunStage.AI_SETUP,
            resolve_first_run_state(
                ai_error="API key missing",
                has_course=False,
                question_count=0,
            ).stage,
        )
        self.assertEqual(
            FirstRunStage.MATERIALS,
            resolve_first_run_state(
                ai_error="",
                has_course=False,
                question_count=0,
            ).stage,
        )
        self.assertEqual(
            FirstRunStage.IMPORTING,
            resolve_first_run_state(
                ai_error="",
                has_course=False,
                question_count=0,
                operation="importing",
            ).stage,
        )
        self.assertEqual(
            FirstRunStage.GENERATE,
            resolve_first_run_state(
                ai_error="",
                has_course=True,
                question_count=0,
            ).stage,
        )
        self.assertEqual(
            FirstRunStage.READY,
            resolve_first_run_state(
                ai_error="API key missing",
                has_course=True,
                question_count=10,
            ).stage,
        )

    def test_empty_application_routes_primary_workspaces_to_one_first_run_view(self):
        with patch(
            "ui.main_window.MainWindow._first_run_ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        window._first_run_ai_error = Mock(return_value="")

        self.assertEqual(window.SCREEN_HOME, window.stack.currentIndex())
        self.assertIs(
            window.first_run_screen,
            window.home_workspace.currentWidget(),
        )
        self.assertEqual("选择课程资料", window.first_run_screen.primary_btn.text())

        self.assertTrue(window.navigate_to(window.SCREEN_TOPIC_SELECTION))
        self.assertEqual(window.SCREEN_HOME, window.stack.currentIndex())
        self.assertIsNone(window._course_screen)
        self.assertTrue(window.navigate_to(window.SCREEN_COURSES))
        self.assertEqual(window.SCREEN_HOME, window.stack.currentIndex())
        self.assertIsNone(window._course_screen)

    def test_first_run_hands_selected_folder_to_background_course_import(self):
        with patch(
            "ui.main_window.MainWindow._first_run_ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        course_screen = Mock()
        course_screen.start_import.return_value = True
        window._get_course_screen = Mock(return_value=course_screen)

        with tempfile.TemporaryDirectory() as source_dir, patch(
            "ui.main_window.QFileDialog.getExistingDirectory",
            return_value=source_dir,
        ):
            window.first_run_screen.primary_btn.click()

        course_screen.start_import.assert_called_once_with(
            source_dir,
            "",
            present_result=False,
        )
        self.assertEqual(
            FirstRunStage.IMPORTING,
            window.first_run_screen.state.stage,
        )

    def test_first_run_offers_first_practice_after_questions_exist(self):
        with patch(
            "ui.main_window.MainWindow._first_run_ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        window._first_run_ai_error = Mock(return_value="")
        project = CourseProject(
            course_id="course-first-run",
            title="First Course",
            source_folder="",
            summary_markdown="# First Course",
            summary_path="",
            topics=[],
            documents=[],
            created_at="2026-07-28T00:00:00+00:00",
            updated_at="2026-07-28T00:00:00+00:00",
        )
        window.course_manager.save(project)
        question = Question(
            question_id="first-question",
            type=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "第一题",
                    "options": ["正确", "错误"],
                    "explanation": "第一题解析",
                },
                "en": {
                    "stem": "First question",
                    "options": ["True", "False"],
                    "explanation": "First explanation",
                },
            },
            correct_answer=True,
            topic="general",
            metadata={"course_id": project.course_id},
        )
        window.question_bank.save(question)

        window._refresh_first_run()

        self.assertEqual(
            FirstRunStage.GENERATE,
            window.first_run_screen.state.stage,
        )

        question_set = QuestionSet(
            set_id="first-set",
            title={"zh": "第一次练习", "en": "First Practice"},
            description={"zh": "", "en": ""},
            topics=[],
            difficulty=Difficulty.EASY,
            estimated_minutes=5,
            questions=[question.question_id],
            metadata={"course_id": project.course_id},
        )
        window.set_manager.save(question_set)
        window._refresh_first_run()

        self.assertIs(
            window.first_run_screen,
            window.home_workspace.currentWidget(),
        )
        self.assertEqual(
            FirstRunStage.READY,
            window.first_run_screen.state.stage,
        )
        self.assertEqual(
            "开始第一次练习",
            window.first_run_screen.primary_btn.text(),
        )


if __name__ == "__main__":
    unittest.main()
