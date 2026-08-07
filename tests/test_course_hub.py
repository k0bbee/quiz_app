import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog

from core.course_hub_presenter import build_course_hub_view
from models.course_project import CourseProject, CourseTopic
from models.question import Question, QuestionBank
from ui.generation_workspace_controller import GenerationWorkspaceController
from ui.main_window import MainWindow
from ui.navigation import Route
from ui.widgets.course_hub_panels import CourseKnowledgePanel
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


def _course() -> CourseProject:
    return CourseProject(
        course_id="course-systems",
        title="Computer Systems",
        source_folder="C:/courses/systems",
        summary_markdown="# Systems\n\nCourse summary.",
        summary_path="",
        topics=[
            CourseTopic(
                topic_id="input-output",
                title="Input / Output",
                source_files=["C:/courses/systems/io.pdf"],
            ),
            CourseTopic(
                topic_id="virtual-memory",
                title="Virtual Memory",
                source_files=["C:/courses/systems/memory.pptx"],
            ),
        ],
        documents=[
            {
                "path": "C:/courses/systems/io.pdf",
                "title": "I/O Lecture",
                "extension": ".pdf",
                "word_count": 1200,
                "page_count": 18,
                "pages": ["Interrupts and DMA"],
                "warnings": [],
            },
            {
                "path": "C:/courses/systems/memory.pptx",
                "title": "Memory Lecture",
                "extension": ".pptx",
                "word_count": 800,
                "page_count": 24,
                "pages": ["Address translation"],
                "warnings": ["OCR fallback used"],
            },
        ],
        created_at="2026-07-29T00:00:00+00:00",
        updated_at="2026-07-29T00:00:00+00:00",
        exam_scope_mode="selected",
        exam_scope_topic_ids=["input-output"],
        summary_source="ai",
    )


def _question(topic_id: str, course_id: str) -> Question:
    question = Question.create_new(
        qtype=QuestionType.TRUE_FALSE,
        difficulty=Difficulty.MEDIUM,
        bilingual={
            "zh": {
                "stem": "示例题",
                "options": ["正确", "错误"],
                "explanation": "示例解释。",
            },
            "en": {
                "stem": "Sample question",
                "options": ["True", "False"],
                "explanation": "Sample explanation.",
            },
        },
        correct_answer=True,
        topic=topic_id,
    )
    question.metadata["course_id"] = course_id
    question.metadata["topic_title"] = topic_id
    return question


class CourseHubPresenterTests(unittest.TestCase):
    def test_view_model_combines_sources_scope_and_indexed_question_coverage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            bank.save(_question("input-output", "course-systems"))
            bank.save(_question("input-output", "course-systems"))
            bank.save(_question("virtual-memory", "other-course"))

            view = build_course_hub_view(_course(), bank)

        self.assertEqual(2, view.document_count)
        self.assertEqual(2, view.topic_count)
        self.assertEqual(1, view.exam_topic_count)
        self.assertEqual(2, view.question_count)
        self.assertEqual(1, view.warning_count)
        self.assertEqual(1, view.covered_exam_topic_count)
        self.assertEqual(0, view.uncovered_exam_topic_count)
        self.assertEqual(
            [
                ("input-output", True, 1, 2),
                ("virtual-memory", False, 1, 0),
            ],
            [
                (
                    topic.topic_id,
                    topic.in_exam_scope,
                    topic.source_count,
                    topic.question_count,
                )
                for topic in view.topics
            ],
        )

    def test_invalid_question_index_degrades_to_empty_coverage(self):
        class InvalidIndex:
            def topic_index(self, course_id=None):
                return None

        view = build_course_hub_view(_course(), InvalidIndex())

        self.assertEqual(0, view.question_count)
        self.assertEqual([0, 0], [topic.question_count for topic in view.topics])

    def test_legacy_document_record_keeps_its_filename_and_type(self):
        project = _course()
        project.documents = [{
            "filename": "chapter-one.pdf",
            "status": "parsed",
            "characters": 2400,
        }]

        source = build_course_hub_view(project).sources[0]

        self.assertEqual("chapter-one.pdf", source.name)
        self.assertEqual(".pdf", source.extension)

    def test_exam_coverage_ignores_questions_outside_the_exam_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            bank.save(_question("virtual-memory", "course-systems"))

            view = build_course_hub_view(_course(), bank)

        self.assertEqual(0, view.covered_exam_topic_count)
        self.assertEqual(1, view.uncovered_exam_topic_count)

    def test_course_health_includes_source_details_learning_and_review_work(self):
        project = _course()
        project.generation_profile = {
            "topic_weights": {"input-output": 70, "virtual-memory": 30}
        }
        record = SimpleNamespace(
            status="completed",
            started_at="2026-07-29T09:00:00+08:00",
            completed_at="2026-07-29T09:10:00+08:00",
            answers=(
                SimpleNamespace(
                    question_id="q-io",
                    skipped=False,
                    is_correct=False,
                ),
            ),
        )
        question_bank = Mock()
        question_bank.topic_index.return_value = {
            "q-io": ("input-output", "Input / Output")
        }
        question_bank.get_many.return_value = [
            SimpleNamespace(
                question_id="q-io",
                metadata={"quality_warnings": ["weak explanation"]},
            )
        ]
        draft_store = Mock()
        draft_store.get.return_value = SimpleNamespace(questions=(1, 2, 3))

        view = build_course_hub_view(
            project,
            question_bank,
            progress_manager=SimpleNamespace(load_all=lambda: [record]),
            mastery_overrides=SimpleNamespace(
                is_topic_mastered=lambda _course_id, _topic_id: False
            ),
            generation_draft_store=draft_store,
        )

        self.assertEqual(1, view.quality_warning_count)
        self.assertEqual(3, view.pending_review_question_count)
        self.assertEqual(1, view.weak_topic_count)
        self.assertEqual(
            "Interrupts and DMA",
            view.sources[0].excerpt,
        )
        io_topic = view.topics[0]
        self.assertEqual(70, io_topic.generation_weight)
        self.assertEqual("0%", io_topic.mastery)
        self.assertEqual("2026-07-29", io_topic.recent_practice)
        self.assertEqual("weak", io_topic.status)


class CourseHubActionTests(unittest.TestCase):
    def test_knowledge_detail_action_emits_topic_action(self):
        view = build_course_hub_view(_course())
        panel = CourseKnowledgePanel()
        self.addCleanup(panel.close)
        actions = []
        panel.topic_action_requested.connect(
            lambda topic_id, action: actions.append((topic_id, action))
        )
        panel.render(view, lambda zh, _en: zh)

        panel.table.selectRow(0)
        panel.detail_action_btn.click()

        self.assertEqual([("input-output", "generate")], actions)


class CourseHubNavigationTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.project = _course()
        self.assertTrue(self.window.course_manager.save(self.project))

    def test_course_routes_use_one_visible_context_navigation_layer(self):
        self.assertTrue(
            self.window.navigate_route(
                Route.course(self.project.course_id, tab="overview"),
                allow_first_run_redirect=False,
            )
        )
        screen = self.window._course_screen
        self.assertIn("资料健康", screen.course_health_label.text())
        self.assertIn("内容覆盖", screen.course_coverage_label.text())
        self.assertIn("学习状态", screen.course_learning_label.text())
        self.assertIn("内容生产", screen.course_production_label.text())
        self.assertIs(screen.overview_panel, screen.content_stack.currentWidget())
        self.assertFalse(hasattr(screen, "exam_goal_btn"))

        self.assertEqual(
            ["overview", "sources", "knowledge", "generation", "qa"],
            [
                route.tab
                for button, route in self.window.app_shell._context_routes.items()
                if not button.isHidden() and route.workspace.value == "courses"
            ],
        )
        self.assertTrue(self.window.course_overview_tab_btn.isChecked())
        self.assertTrue(hasattr(self.window._course_screen, "qa_panel"))
        self.assertFalse(hasattr(self.window._course_screen, "generate_questions_btn"))

        self.window.course_sources_tab_btn.click()

        self.assertEqual(
            Route.course(self.project.course_id, tab="sources"),
            self.window.current_route,
        )
        self.assertEqual(
            self.project.course_id,
            self.window._course_screen.selected_course_id(),
        )

    def test_sources_and_knowledge_routes_render_selected_course_data(self):
        self.assertTrue(
            self.window.navigate_route(
                Route.course(self.project.course_id, tab="sources"),
                allow_first_run_redirect=False,
            )
        )
        screen = self.window._course_screen

        self.assertIs(screen.sources_panel, screen.content_stack.currentWidget())
        self.assertEqual(2, screen.sources_table.rowCount())
        self.assertEqual("I/O Lecture", screen.sources_table.item(0, 0).text())
        screen.sources_table.selectRow(0)
        self.assertIn("18", screen.sources_panel.detail_label.text())
        self.assertIn("Input / Output", screen.sources_panel.detail_label.text())
        self.assertIn(
            "Interrupts and DMA",
            screen.sources_panel.excerpt.toPlainText(),
        )

        self.assertTrue(
            self.window.navigate_route(
                Route.course(self.project.course_id, tab="knowledge"),
                allow_first_run_redirect=False,
            )
        )

        self.assertIs(screen.knowledge_panel, screen.content_stack.currentWidget())
        self.assertEqual(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
            screen.project_list.horizontalScrollBarPolicy(),
        )
        self.assertEqual(2, screen.knowledge_table.rowCount())
        self.assertEqual(4, screen.knowledge_table.columnCount())
        self.assertEqual("Input / Output", screen.knowledge_table.item(0, 0).text())
        self.assertEqual("1", screen.knowledge_table.item(0, 1).text())
        self.assertEqual("0", screen.knowledge_table.item(0, 2).text())
        self.assertIn("尚未覆盖", screen.knowledge_table.item(0, 3).text())
        self.assertEqual(
            "资料覆盖",
            screen.knowledge_table.horizontalHeaderItem(1).text(),
        )
        self.assertEqual(
            "题目数量",
            screen.knowledge_table.horizontalHeaderItem(2).text(),
        )
        self.assertIn("历史表现", screen.knowledge_panel.detail_summary.text())
        self.assertEqual("补齐题目", screen.knowledge_panel.detail_action_btn.text())

    def test_generation_route_initializes_selected_course_workspace(self):
        dialog = QDialog()
        self.addCleanup(dialog.close)
        dialog.start_generation_when_shown = Mock()

        self.assertTrue(
            self.window.navigate_route(
                Route.course(self.project.course_id, tab="overview"),
                allow_first_run_redirect=False,
            )
        )
        with patch.object(
            GenerationWorkspaceController,
            "configure",
            return_value=(dialog, self.project, False, "manual"),
        ):
            self.window.course_generation_tab_btn.click()

        self.assertEqual(
            Route.course(self.project.course_id, tab="generation"),
            self.window.current_route,
        )
        self.assertIs(
            dialog,
            self.window._get_generation_workspace().generation_widget(),
        )
        self.assertEqual(
            self.project.course_id,
            self.window._get_generation_workspace().course_id,
        )

    def test_uncovered_topic_action_opens_a_scoped_generation_plan(self):
        self.assertTrue(
            self.window.navigate_route(
                Route.course(self.project.course_id, tab="knowledge"),
                allow_first_run_redirect=False,
            )
        )
        self.window.generation_flow.open = Mock()

        self.window._course_screen.knowledge_table.selectRow(0)
        self.window._course_screen.knowledge_panel.detail_action_btn.click()

        self.window.generation_flow.open.assert_called_once()
        call = self.window.generation_flow.open.call_args
        plan = call.kwargs["initial_plan"]
        self.assertEqual(("input-output",), plan.selected_topics)
        self.assertEqual({"input-output": 100}, plan.topic_weights)
        self.assertEqual("course_hub_gap", call.kwargs["draft_source"])

    def test_view_topic_action_opens_knowledge_route_and_selects_topic(self):
        self.assertTrue(
            self.window.navigate_route(
                Route.course(self.project.course_id, tab="overview"),
                allow_first_run_redirect=False,
            )
        )

        self.window._course_screen.knowledge_table.selectRow(1)
        self.window._course_screen.knowledge_panel.detail_action_btn.click()

        self.assertEqual(
            Route.course(self.project.course_id, tab="knowledge"),
            self.window.current_route,
        )
        self.assertEqual(1, self.window._course_screen.knowledge_table.currentRow())

    def test_selecting_another_course_changes_the_active_course(self):
        other = _course()
        other.course_id = "course-other"
        other.title = "Other Course"
        other.updated_at = "2026-07-29T01:00:00+00:00"
        self.assertTrue(
            self.window.course_manager.save(other, make_current=False)
        )
        self.assertTrue(
            self.window.navigate_route(
                Route.course(self.project.course_id, tab="overview"),
                allow_first_run_redirect=False,
            )
        )
        screen = self.window._course_screen
        for row in range(screen.project_list.count()):
            item = screen.project_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == other.course_id:
                screen.project_list.setCurrentRow(row)
                break

        self.window.course_sources_tab_btn.click()

        self.assertEqual(
            other.course_id,
            self.window.course_manager.current().course_id,
        )
        self.assertEqual(
            Route.course(other.course_id, tab="sources"),
            self.window.current_route,
        )

    def test_direct_course_route_selects_the_course_named_by_the_route(self):
        other = _course()
        other.course_id = "course-other"
        other.title = "Other Course"
        other.updated_at = "2026-07-29T01:00:00+00:00"
        other.documents[0]["title"] = "Other Source"
        self.assertTrue(
            self.window.course_manager.save(other, make_current=False)
        )

        self.assertTrue(
            self.window.navigate_route(
                Route.course(other.course_id, tab="sources"),
                allow_first_run_redirect=False,
            )
        )

        screen = self.window._course_screen
        self.assertEqual(other.course_id, screen.selected_course_id())
        self.assertEqual("Other Source", screen.sources_table.item(0, 0).text())
        self.assertEqual(
            other.course_id,
            self.window.course_manager.current().course_id,
        )


if __name__ == "__main__":
    unittest.main()
