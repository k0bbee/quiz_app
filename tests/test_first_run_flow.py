import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ai.generation_config import GenerationConfig
from core.first_run_flow import (
    FirstRunStage,
    build_first_run_exam_plan,
    resolve_first_run_state,
)
from core.language_manager import LanguageManager
from models.course_project import CourseProject, CourseTopic
from models.question import Question
from models.question_set import QuestionSet
from ui.main_window import MainWindow
from ui.screens.first_run_workspace import FirstRunWorkspace
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class FirstRunFlowTests(unittest.TestCase):
    def test_first_run_workspace_uses_wide_window_without_large_side_gutters(self):
        workspace = FirstRunWorkspace()
        self.addCleanup(workspace.close)
        workspace.resize(1200, 760)
        workspace.show()
        _APP.processEvents()

        side_gutter = (workspace.width() - workspace.card.width()) // 2

        self.assertGreaterEqual(workspace.card.width(), 960)
        self.assertLessEqual(side_gutter, 120)

    def test_first_run_plan_uses_ten_quick_review_questions_in_exam_scope(self):
        project = CourseProject(
            course_id="course-plan",
            title="Operating Systems",
            source_folder="",
            summary_markdown="# Operating Systems",
            summary_path="",
            topics=[
                CourseTopic("io", "I/O"),
                CourseTopic("memory", "Memory"),
            ],
            documents=[],
            created_at="2026-07-28T00:00:00+00:00",
            updated_at="2026-07-28T00:00:00+00:00",
            exam_scope_mode="selected",
            exam_scope_topic_ids=["io"],
        )

        plan = build_first_run_exam_plan(project)

        self.assertEqual(10, plan.question_count)
        self.assertEqual("quick_review", plan.template)
        self.assertEqual("mixed", plan.difficulty)
        self.assertEqual(("io",), plan.selected_topics)
        self.assertEqual({"io": 100}, dict(plan.topic_weights))

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

    def test_auto_generation_saves_and_starts_the_new_question_set(self):
        from PyQt6.QtWidgets import QDialog

        from ui.main_window import MainWindow

        question = Question(
            question_id="first-generated-question",
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
            topic="io",
            metadata={"course_id": "course-first-run"},
        )
        question_set = QuestionSet(
            set_id="first-generated-set",
            title={"zh": "快速复习", "en": "Quick Review"},
            description={"zh": "", "en": ""},
            topics=["io"],
            difficulty=Difficulty.EASY,
            estimated_minutes=5,
            questions=[question.question_id],
            metadata={"course_id": "course-first-run"},
        )
        dialog = Mock()
        dialog.exec.return_value = QDialog.DialogCode.Accepted
        dialog.generated_questions = [question]
        dialog.diff_combo.currentData.return_value = "mixed"
        dialog._build_generation_config.return_value = GenerationConfig(
            topic_weights={"io": 100},
        )
        dialog.question_set_title.return_value = "操作系统快速复习"
        course = Mock(
            course_id="course-first-run",
            title="操作系统",
        )
        shell = Mock()
        shell.lang_manager = LanguageManager.instance()
        shell.question_bank = Mock()
        shell.set_manager = Mock()
        shell.SCREEN_TOPIC_SELECTION = 1
        plan = build_first_run_exam_plan(
            CourseProject(
                course_id="course-first-run",
                title="操作系统",
                source_folder="",
                summary_markdown="# 操作系统",
                summary_path="",
                topics=[CourseTopic("io", "I/O")],
                documents=[],
                created_at="2026-07-28T00:00:00+00:00",
                updated_at="2026-07-28T00:00:00+00:00",
            )
        )

        with patch.object(
            MainWindow,
            "_prepare_generation_dialog",
            return_value=Mock(dialog=dialog, course_project=course),
        ), patch(
            "ui.main_window.build_ai_question_set",
            return_value=question_set,
        ), patch(
            "ui.main_window.persist_new_question_set",
            return_value=(question_set, 1),
        ), patch("ui.main_window.QMessageBox.information") as information:
            MainWindow._on_ai_generate(
                shell,
                initial_plan=plan,
                auto_start=True,
                start_after_save=True,
                review_warnings_only=True,
                question_set_title="操作系统快速复习",
            )

        dialog.apply_exam_plan.assert_called_once_with(plan)
        dialog.set_review_warnings_only.assert_called_once_with(True)
        dialog.start_generation_when_shown.assert_called_once_with()
        dialog.set_title_input.setText.assert_called_once_with("操作系统快速复习")
        shell._on_question_bank_changed.assert_called_once_with()
        shell._on_study_quiz_start.assert_called_once()
        started_intent, started_question_ids = (
            shell._on_study_quiz_start.call_args.args
        )
        self.assertEqual(question_set.set_id, started_intent.set_id)
        self.assertEqual("course-first-run", started_intent.course_id)
        self.assertEqual("practice", started_intent.submission_mode)
        self.assertEqual("first_run_generation", started_intent.source)
        self.assertEqual(question_set.questions, started_question_ids)
        information.assert_not_called()

    def test_first_run_generate_uses_default_plan_without_configuration_step(self):
        with patch(
            "ui.main_window.MainWindow._first_run_ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        project = CourseProject(
            course_id="course-auto-generate",
            title="大学物理",
            source_folder="",
            summary_markdown="# 大学物理",
            summary_path="",
            topics=[CourseTopic("mechanics", "力学")],
            documents=[],
            created_at="2026-07-28T00:00:00+00:00",
            updated_at="2026-07-28T00:00:00+00:00",
        )
        window.course_manager.save(project)
        window._on_ai_generate = Mock()

        window._on_first_run_generate()

        kwargs = window._on_ai_generate.call_args.kwargs
        self.assertEqual(project.course_id, kwargs["course_override"].course_id)
        self.assertEqual(10, kwargs["initial_plan"].question_count)
        self.assertEqual(("mechanics",), kwargs["initial_plan"].selected_topics)
        self.assertTrue(kwargs["auto_start"])
        self.assertTrue(kwargs["start_after_save"])
        self.assertTrue(kwargs["review_warnings_only"])
        self.assertEqual("大学物理快速复习", kwargs["question_set_title"])


if __name__ == "__main__":
    unittest.main()
