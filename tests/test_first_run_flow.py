import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QLabel

from ai.generation_config import GenerationConfig
from ai.exam_plan import ExamGenerationPlan
from core.first_run_flow import (
    FirstRunStage,
    FirstRunState,
    build_first_run_exam_plan,
    resolve_first_run_state,
)
from core.language_manager import LanguageManager
from models.course_project import CourseProject, CourseTopic
from models.question import Question
from models.question_set import QuestionSet
from ui.main_window import MainWindow
from ui.generation_launch_controller import GenerationLaunchIssue
from ui.generation_workspace_controller import GenerationWorkspaceController
from ui.screens.first_run_workspace import FirstRunWorkspace
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class FirstRunFlowTests(unittest.TestCase):
    def test_first_run_has_no_standalone_ai_setup_gate(self):
        self.assertFalse(hasattr(FirstRunStage, "AI_SETUP"))
        workspace = FirstRunWorkspace()
        self.addCleanup(workspace.close)
        self.assertFalse(hasattr(workspace, "ai_step"))

    def test_first_run_workspace_hosts_generation_surface_in_place(self):
        workspace = FirstRunWorkspace()
        self.addCleanup(workspace.close)
        generation_surface = QDialog()
        QLabel("generation", generation_surface)

        workspace.show_generation_widget(generation_surface)

        self.assertIs(
            generation_surface,
            workspace.generation_widget(),
        )
        self.assertIs(
            workspace.generation_page,
            workspace.content_stack.currentWidget(),
        )
        self.assertIs(workspace.generation_host, generation_surface.parent())
        self.assertEqual(Qt.WindowType.Widget, generation_surface.windowType())

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

    def test_state_keeps_materials_primary_when_ai_is_not_needed_yet(self):
        self.assertEqual(
            FirstRunStage.MATERIALS,
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
                ai_error="API key missing",
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

    def test_archived_courses_offer_recovery_before_empty_install_onboarding(self):
        state = resolve_first_run_state(
            ai_error="API key missing",
            has_course=False,
            question_count=0,
            archived_course_count=2,
        )

        self.assertEqual(FirstRunStage.ARCHIVED_RECOVERY, state.stage)
        self.assertEqual(2, state.archived_course_count)

    def test_first_run_workspace_offers_restore_or_new_import_for_archived_courses(self):
        workspace = FirstRunWorkspace()
        self.addCleanup(workspace.close)
        requested = []
        workspace.restore_courses_requested.connect(
            lambda: requested.append("restore")
        )
        workspace.choose_materials_requested.connect(
            lambda: requested.append("import")
        )

        workspace.set_state(
            FirstRunState(
                FirstRunStage.ARCHIVED_RECOVERY,
                archived_course_count=2,
            )
        )

        self.assertEqual("暂无进行中的课程", workspace.title_label.text())
        self.assertIn("2 门已归档课程", workspace.subtitle_label.text())
        self.assertFalse(hasattr(workspace, "ai_step"))
        self.assertEqual("恢复课程", workspace.primary_btn.text())
        self.assertEqual("导入新课程", workspace.alternate_btn.text())

        workspace.primary_btn.click()
        workspace.alternate_btn.click()

        self.assertEqual(["restore", "import"], requested)

    def test_first_run_workspace_offers_offline_example_without_replacing_import(self):
        workspace = FirstRunWorkspace()
        self.addCleanup(workspace.close)
        requested = []
        workspace.example_requested.connect(
            lambda: requested.append("example")
        )
        workspace.choose_materials_requested.connect(
            lambda: requested.append("import")
        )

        workspace.set_state(FirstRunState(FirstRunStage.MATERIALS))

        self.assertFalse(workspace.example_btn.isHidden())
        self.assertTrue(workspace.alternate_btn.isHidden())
        self.assertEqual("体验示例课程", workspace.example_btn.text())
        self.assertEqual("选择课程资料", workspace.primary_btn.text())

        workspace.example_btn.click()
        workspace.primary_btn.click()

        self.assertEqual(["example", "import"], requested)

    def test_stale_ai_error_is_hidden_until_generation_is_requested(self):
        workspace = FirstRunWorkspace()
        self.addCleanup(workspace.close)
        requested = []
        workspace.example_requested.connect(
            lambda: requested.append("example")
        )
        workspace.choose_materials_requested.connect(
            lambda: requested.append("import")
        )

        workspace.set_state(
            FirstRunState(
                FirstRunStage.MATERIALS,
                ai_error="API key missing",
            )
        )

        self.assertEqual("选择课程资料", workspace.primary_btn.text())
        self.assertTrue(workspace.alternate_btn.isHidden())
        self.assertFalse(workspace.example_btn.isHidden())
        self.assertFalse(workspace.status_label.isVisible())

        workspace.example_btn.click()
        workspace.primary_btn.click()

        self.assertEqual(["example", "import"], requested)

    def test_first_run_example_installs_without_ai_and_becomes_ready(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        window.first_run.ai_error = Mock(return_value="API key missing")
        window.first_run_screen.set_state(FirstRunState(FirstRunStage.MATERIALS))

        window.first_run_screen.example_btn.click()

        self.assertEqual("example-study-skills", window.course_context.current_course_id())
        self.assertEqual(10, window.question_bank.count("example-study-skills"))
        self.assertEqual(
            FirstRunStage.READY,
            window.first_run_screen.state.stage,
        )

    def test_review_pending_draft_precedes_regeneration(self):
        state = resolve_first_run_state(
            ai_error="API key missing",
            has_course=True,
            question_count=0,
            draft_question_count=4,
        )

        self.assertEqual(FirstRunStage.REVIEW_PENDING, state.stage)
        self.assertEqual(4, state.draft_question_count)

    def test_first_run_workspace_offers_resume_for_review_pending_draft(self):
        workspace = FirstRunWorkspace()
        self.addCleanup(workspace.close)

        workspace.set_state(
            FirstRunState(
                FirstRunStage.REVIEW_PENDING,
                draft_question_count=4,
            )
        )

        self.assertEqual("继续审核 4 道题", workspace.primary_btn.text())
        self.assertTrue(workspace.primary_btn.isEnabled())

    def test_empty_application_routes_primary_workspaces_to_one_first_run_view(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        window.first_run.ai_error = Mock(return_value="API key missing")

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
        self.assertEqual(window.SCREEN_COURSES, window.stack.currentIndex())
        self.assertIsNotNone(window._course_screen)

    def test_first_run_hands_selected_folder_to_background_course_import(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        course_screen = Mock()
        course_screen.start_import.return_value = True
        window._get_course_screen = Mock(return_value=course_screen)

        with tempfile.TemporaryDirectory() as source_dir, patch(
            "ui.first_run_controller.QFileDialog.getExistingDirectory",
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

    def test_archived_only_application_routes_to_course_recovery_workspace(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        project = CourseProject(
            course_id="course-archived",
            title="Archived Course",
            source_folder="",
            summary_markdown="# Archived Course",
            summary_path="",
            topics=[],
            documents=[],
            created_at="2026-07-28T00:00:00+00:00",
            updated_at="2026-07-28T00:00:00+00:00",
            status="archived",
        )
        self.assertTrue(window.course_manager.save(project, make_current=False))

        window.first_run.refresh()

        self.assertEqual(
            FirstRunStage.ARCHIVED_RECOVERY,
            window.first_run_screen.state.stage,
        )
        self.assertTrue(window.navigate_to(window.SCREEN_COURSES))
        self.assertEqual(window.SCREEN_COURSES, window.stack.currentIndex())
        self.assertTrue(window._course_screen.archived_scope_btn.isChecked())
        self.assertEqual(1, window._course_screen.project_list.count())

    def test_first_run_offers_first_practice_after_questions_exist(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        window.first_run.ai_error = Mock(return_value="")
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

        window.first_run.refresh()

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
        window.first_run.refresh()

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

    def test_first_run_restores_review_pending_generation_without_new_request(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        project = CourseProject(
            course_id="course-draft",
            title="Draft Course",
            source_folder="",
            summary_markdown="# Draft Course",
            summary_path="",
            topics=[CourseTopic("io", "I/O")],
            documents=[],
            created_at="2026-07-29T00:00:00+00:00",
            updated_at="2026-07-29T00:00:00+00:00",
        )
        window.course_manager.save(project)
        question = Question(
            question_id="draft-question",
            type=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "草稿题",
                    "options": ["正确", "错误"],
                    "explanation": "草稿解释",
                },
                "en": {
                    "stem": "Draft question",
                    "options": ["True", "False"],
                    "explanation": "Draft explanation",
                },
            },
            correct_answer=True,
            topic="io",
            metadata={"course_id": project.course_id},
        )
        plan = ExamGenerationPlan(
            question_count=10,
            difficulty="mixed",
            selected_topics=("io",),
            topic_weights={"io": 100},
        )
        window.generation_draft_store.save(
            course_id=project.course_id,
            questions=[question],
            question_set_title="待审核快速复习",
            exam_plan=plan,
            review_warnings_only=True,
            source="first_run",
        )

        window.first_run.refresh()

        self.assertEqual(
            FirstRunStage.REVIEW_PENDING,
            window.first_run_screen.state.stage,
        )
        self.assertEqual(
            "继续审核 1 道题",
            window.first_run_screen.primary_btn.text(),
        )

        from ui.dialogs.ai_generation_dialog import AIGenerationDialog

        dialog = AIGenerationDialog(
            project.summary_markdown,
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=project.topics,
            course_project=project,
        )
        self.addCleanup(dialog.close)
        dialog.exec = Mock(return_value=dialog.DialogCode.Rejected)
        dialog.start_generation_when_shown = Mock()
        preparation = Mock(dialog=dialog, course_project=project)

        with patch(
            "ui.generation_workspace_controller.GenerationWorkspaceController.prepare",
            return_value=preparation,
        ):
            window.generation_flow.open(
                course_override=project,
                initial_plan=plan,
                auto_start=True,
                start_after_save=True,
                review_warnings_only=True,
                question_set_title="新标题不应覆盖草稿",
                draft_source="first_run",
            )

        self.assertEqual(
            ["draft-question"],
            [item.question_id for item in dialog.generated_questions],
        )
        self.assertEqual("待审核快速复习", dialog.question_set_title())
        dialog.start_generation_when_shown.assert_not_called()
        self.assertIsNotNone(
            window.generation_draft_store.get(project.course_id)
        )

    def test_saving_restored_generation_removes_draft_and_creates_set(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        project = CourseProject(
            course_id="course-save-draft",
            title="Save Draft Course",
            source_folder="",
            summary_markdown="# Save Draft Course",
            summary_path="",
            topics=[CourseTopic("io", "I/O")],
            documents=[],
            created_at="2026-07-29T00:00:00+00:00",
            updated_at="2026-07-29T00:00:00+00:00",
        )
        window.course_manager.save(project)
        question = Question(
            question_id="saved-draft-question",
            type=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "待保存题",
                    "options": ["正确", "错误"],
                    "explanation": "待保存解释",
                },
                "en": {
                    "stem": "Question to save",
                    "options": ["True", "False"],
                    "explanation": "Explanation to save",
                },
            },
            correct_answer=True,
            topic="io",
            metadata={"course_id": project.course_id},
        )
        plan = ExamGenerationPlan(
            question_count=10,
            difficulty="mixed",
            selected_topics=("io",),
            topic_weights={"io": 100},
        )
        window.generation_draft_store.save(
            course_id=project.course_id,
            questions=[question],
            question_set_title="恢复后保存",
            exam_plan=plan,
            review_warnings_only=True,
            source="first_run",
        )

        from ui.dialogs.ai_generation_dialog import AIGenerationDialog

        dialog = AIGenerationDialog(
            project.summary_markdown,
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=project.topics,
            course_project=project,
        )
        self.addCleanup(dialog.close)
        dialog.exec = Mock(return_value=dialog.DialogCode.Accepted)
        preparation = Mock(dialog=dialog, course_project=project)

        with patch(
            "ui.generation_workspace_controller.GenerationWorkspaceController.prepare",
            return_value=preparation,
        ), patch("ui.generation_workspace_controller.QMessageBox.information"):
            window.generation_flow.open(
                course_override=project,
                start_after_save=False,
                draft_source="first_run",
            )
            dialog.accept()

        self.assertIsNone(
            window.generation_draft_store.get(project.course_id)
        )
        saved_sets = [
            question_set
            for question_set in window.set_manager.load_all()
            if question_set.metadata.get("course_id") == project.course_id
        ]
        self.assertEqual(1, len(saved_sets))
        self.assertEqual("恢复后保存", saved_sets[0].get_title("zh"))

    def test_auto_generation_saves_and_starts_the_new_question_set(self):
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
        shell.SCREEN_GENERATION = 8
        shell._generation_workspace = Mock()
        shell._generation_workspace.generation_widget.return_value = None
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

        with patch(
            "ui.generation_workspace_controller.GenerationWorkspaceController.prepare",
            return_value=Mock(dialog=dialog, course_project=course),
        ), patch(
            "ui.generation_workspace_controller.build_ai_question_set",
            return_value=question_set,
        ), patch(
            "ui.generation_workspace_controller.persist_new_question_set",
            return_value=(question_set, 1),
        ), patch("ui.generation_workspace_controller.QMessageBox.information") as information:
            GenerationWorkspaceController(shell).open(
                initial_plan=plan,
                auto_start=True,
                start_after_save=True,
                review_warnings_only=True,
                question_set_title="操作系统快速复习",
            )
            dialog.accepted.connect.call_args.args[0]()

        dialog.apply_exam_plan.assert_called_once_with(plan)
        dialog.set_review_warnings_only.assert_called_once_with(True)
        dialog.start_generation_when_shown.assert_called_once_with()
        dialog.set_title_input.setText.assert_called_once_with("操作系统快速复习")
        dialog.exec.assert_not_called()
        shell.course_context.question_bank_changed.assert_called_once_with()
        shell.study_flow.start_prefilled.assert_called_once()
        started_intent, started_question_ids = (
            shell.study_flow.start_prefilled.call_args.args
        )
        self.assertEqual(question_set.set_id, started_intent.set_id)
        self.assertEqual("course-first-run", started_intent.course_id)
        self.assertEqual("practice", started_intent.submission_mode)
        self.assertEqual("first_run_generation", started_intent.source)
        self.assertEqual(question_set.questions, started_question_ids)
        information.assert_not_called()

    def test_embedded_generation_save_failure_stays_on_generation_surface(self):
        question = Question(
            question_id="unsaved-inline-question",
            type=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "合同依法成立。",
                    "options": ["正确", "错误"],
                    "explanation": "依法成立的合同受法律保护。",
                },
                "en": {
                    "stem": "A contract is formed according to law.",
                    "options": ["True", "False"],
                    "explanation": "A lawfully formed contract is protected.",
                },
            },
            correct_answer=True,
            topic="contract",
            metadata={"course_id": "course-save-failure"},
        )
        dialog = Mock(
            generated_questions=[question],
            diff_combo=Mock(),
        )
        dialog.diff_combo.currentData.return_value = "mixed"
        dialog._build_generation_config.return_value = GenerationConfig(
            topic_weights={"contract": 100},
        )
        dialog.question_set_title.return_value = "合同法快速复习"
        course = Mock(course_id="course-save-failure", title="合同法")
        shell = Mock(
            lang_manager=LanguageManager.instance(),
            question_bank=Mock(),
            set_manager=Mock(),
        )

        with patch(
            "ui.generation_workspace_controller.persist_new_question_set",
            side_effect=RuntimeError("disk full"),
        ), patch(
            "ui.generation_workspace_controller.QMessageBox.critical"
        ) as critical:
            saved = GenerationWorkspaceController(shell).save(
                dialog,
                course,
                start_after_save=True,
                present_error=False,
            )

        self.assertFalse(saved)
        critical.assert_not_called()
        dialog.show_save_error.assert_called_once_with("disk full")

    def test_first_run_generate_uses_default_plan_without_configuration_step(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
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

        with patch.object(
            window.generation_flow,
            "configure",
            return_value=None,
        ) as configure:
            window.first_run.generate()

        kwargs = configure.call_args.kwargs
        self.assertEqual(project.course_id, kwargs["course_override"].course_id)
        self.assertEqual(10, kwargs["initial_plan"].question_count)
        self.assertEqual(("mechanics",), kwargs["initial_plan"].selected_topics)
        self.assertTrue(kwargs["review_warnings_only"])
        self.assertEqual("大学物理快速复习", kwargs["question_set_title"])
        self.assertFalse(kwargs["present_error"])

    def test_first_run_generation_settings_error_stays_in_workspace(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        project = CourseProject(
            course_id="course-inline-error",
            title="法学",
            source_folder="",
            summary_markdown="# 法学",
            summary_path="",
            topics=[CourseTopic("contract", "合同")],
            documents=[],
            created_at="2026-07-29T00:00:00+00:00",
            updated_at="2026-07-29T00:00:00+00:00",
        )
        window.course_manager.save(project)
        window.first_run.ai_error = Mock(return_value="API key missing")
        failed = Mock(
            ok=False,
            issue=GenerationLaunchIssue.INVALID_AI_SETTINGS,
            message="API key missing",
        )

        with patch(
            "ui.generation_workspace_controller.GenerationLaunchController.prepare",
            return_value=failed,
        ), patch(
            "ui.generation_workspace_controller.QMessageBox.warning"
        ) as warning:
            window.first_run.generate()

        warning.assert_not_called()
        self.assertEqual(
            FirstRunStage.GENERATE,
            window.first_run_screen.state.stage,
        )
        self.assertEqual(
            "API key missing",
            window.first_run_screen.status_label.text(),
        )
        self.assertIsNone(window.first_run_screen.generation_widget())

        window.first_run.ai_error.return_value = ""
        window.first_run.settings_saved()

        self.assertEqual(
            FirstRunStage.GENERATE,
            window.first_run_screen.state.stage,
        )
        self.assertFalse(window.first_run_screen.status_label.isVisible())

    def test_first_run_generation_is_embedded_without_modal_exec(self):
        with patch(
            "ui.first_run_controller.FirstRunController.ai_error",
            return_value="",
            create=True,
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        project = CourseProject(
            course_id="course-inline-generation",
            title="大学物理",
            source_folder="",
            summary_markdown="# 大学物理",
            summary_path="",
            topics=[CourseTopic("mechanics", "力学")],
            documents=[],
            created_at="2026-07-29T00:00:00+00:00",
            updated_at="2026-07-29T00:00:00+00:00",
        )
        window.course_manager.save(project)

        from ui.dialogs.ai_generation_dialog import AIGenerationDialog

        dialog = AIGenerationDialog(
            project.summary_markdown,
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=project.topics,
            course_project=project,
        )
        self.addCleanup(dialog.close)
        dialog.exec = Mock(
            side_effect=AssertionError("first-run generation must not be modal")
        )
        dialog.start_generation_when_shown = Mock()
        preparation = Mock(dialog=dialog, course_project=project)

        with patch(
            "ui.generation_workspace_controller.GenerationWorkspaceController.prepare",
            return_value=preparation,
        ):
            window.first_run.generate()

        self.assertIs(
            dialog,
            window.first_run_screen.generation_widget(),
        )
        dialog.exec.assert_not_called()
        dialog.start_generation_when_shown.assert_called_once_with()

        dialog.generated_questions = [
            Question(
                question_id="inline-generated-question",
                type=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "力是矢量。",
                        "options": ["正确", "错误"],
                        "explanation": "力同时具有大小和方向。",
                    },
                    "en": {
                        "stem": "Force is a vector.",
                        "options": ["True", "False"],
                        "explanation": "Force has both magnitude and direction.",
                    },
                },
                correct_answer=True,
                topic="mechanics",
                metadata={"course_id": project.course_id},
            )
        ]
        window.study_flow.start_prefilled = Mock()

        dialog.accept()

        self.assertIsNone(window.first_run_screen.generation_widget())
        saved_sets = [
            question_set
            for question_set in window.set_manager.load_all()
            if question_set.metadata.get("course_id") == project.course_id
        ]
        self.assertEqual(1, len(saved_sets))
        window.study_flow.start_prefilled.assert_called_once()


if __name__ == "__main__":
    unittest.main()
