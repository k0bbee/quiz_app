import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.app_errors import AppError, format_app_error
from ui.course_context_controller import CourseContextController
from ui.navigation import Route, ScreenKey
from ui.workspace_navigation_controller import WorkspaceNavigationController


class CourseContextControllerTests(unittest.TestCase):
    def test_generation_context_uses_the_selected_exam_scope(self):
        selected_topic = SimpleNamespace(topic_id="io", title="I/O")
        course = SimpleNamespace(
            course_id="course-os",
            summary_markdown="# Operating Systems",
            exam_scope_mode="selected",
            topics=[SimpleNamespace(topic_id="all", title="All")],
            exam_topics=lambda: [selected_topic],
        )
        host = SimpleNamespace(
            course_manager=SimpleNamespace(current=lambda: course),
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text
            ),
        )

        content, topics, returned_course = CourseContextController(
            host
        ).generation_context()

        self.assertEqual("# Operating Systems", content)
        self.assertEqual([selected_topic], topics)
        self.assertIs(course, returned_course)


class WorkspaceNavigationControllerTests(unittest.TestCase):
    def test_default_generation_route_uses_the_current_course_identity(self):
        host = SimpleNamespace(
            SCREEN_HOME=0,
            SCREEN_TOPIC_SELECTION=1,
            SCREEN_QUIZ=2,
            SCREEN_RESULTS=3,
            SCREEN_PROGRESS=4,
            SCREEN_COURSES=5,
            SCREEN_QUESTION_BANK=6,
            SCREEN_PAST_EXAMS=7,
            SCREEN_GENERATION=8,
            SCREEN_INDEX_BY_KEY={ScreenKey.GENERATION: 8},
            course_context=SimpleNamespace(
                current_course_id=lambda: "course-current",
            ),
        )

        route = WorkspaceNavigationController(host).default_route(8)

        self.assertEqual(
            Route.course("course-current", tab="generation"),
            route,
        )


class MainWindowBoundaryTests(unittest.TestCase):
    @staticmethod
    def _main_window_method_names():
        source = Path("ui/main_window.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        main_window = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        )
        return {
            node.name
            for node in main_window.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def test_main_window_does_not_wrap_result_flow_actions(self):
        assert self._main_window_method_names().isdisjoint(
            {
                "_result_flow_controller",
                "_on_quiz_finished",
                "_on_open_progress_record",
                "_on_retry_incorrect",
                "_on_retry_unsure",
                "_on_retry_review",
                "_retry_current_session",
                "_on_practice_incorrect",
                "_on_retry_all",
            }
        )

    def test_main_window_does_not_wrap_first_run_state_queries(self):
        assert self._main_window_method_names().isdisjoint(
            {
                "_first_run_ai_error",
                "_first_run_required",
                "_refresh_first_run",
            }
        )

    def test_main_window_does_not_wrap_navigation_queries_or_refresh(self):
        assert self._main_window_method_names().isdisjoint(
            {
                "_screen_index_for_route",
                "_update_navigation_actions",
            }
        )

    def test_main_window_does_not_wrap_generation_flow_actions(self):
        assert self._main_window_method_names().isdisjoint(
            {
                "_generation_controller",
                "_prepare_generation_dialog",
                "_on_ai_generate",
                "_on_generation_workspace_accepted",
                "_on_generation_workspace_rejected",
                "_configure_generation_dialog",
                "_save_generated_dialog",
                "_generation_draft",
                "_sync_generation_draft",
                "_delete_generation_draft",
                "_on_resume_generation_draft",
            }
        )

    def test_main_window_does_not_wrap_course_context_actions(self):
        assert self._main_window_method_names().isdisjoint(
            {
                "_course_context_controller",
                "_on_course_changed",
                "_on_question_bank_changed",
                "_refresh_results_retry_availability",
                "_load_generation_context",
                "_sync_topic_screen_course",
                "_sync_question_bank_screen_course",
                "_sync_home_screen_course",
                "_sync_progress_screen_course",
                "_current_course_id",
            }
        )


class AppErrorTests(unittest.TestCase):
    def test_app_error_formats_localized_user_message_with_code_action_and_detail(self):
        error = AppError(
            code="GEN-QUOTA-001",
            severity="error",
            title_zh="生成未完成",
            title_en="Generation incomplete",
            message_zh="还有 6 道题没有满足当前分布设置。",
            message_en="6 questions still do not satisfy the requested distribution.",
            action_zh="请重试，或减少题目数量，或放宽权重。",
            action_en="Try again, reduce the count, or relax the weights.",
            technical_detail="Missing topic cache: 6",
        )

        zh = format_app_error(error, "zh")
        en = format_app_error(error, "en")

        self.assertIn("生成未完成", zh)
        self.assertIn("请重试", zh)
        self.assertIn("错误码: GEN-QUOTA-001", zh)
        self.assertIn("技术详情: Missing topic cache: 6", zh)
        self.assertIn("Generation incomplete", en)
        self.assertIn("Try again", en)
        self.assertIn("Error code: GEN-QUOTA-001", en)
        self.assertIn("Details: Missing topic cache: 6", en)
