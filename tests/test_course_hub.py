import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog

from core.course_hub_presenter import build_course_hub_view
from models.course_project import CourseProject, CourseTopic
from models.question import Question, QuestionBank
from ui.main_window import MainWindow
from ui.navigation import Route
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

        self.assertEqual(
            ["overview", "sources", "knowledge", "generation", "qa"],
            [
                route.tab
                for button, route in self.window.app_shell._context_routes.items()
                if not button.isHidden() and route.workspace.value == "courses"
            ],
        )
        self.assertTrue(self.window.course_overview_tab_btn.isChecked())
        self.assertTrue(self.window._course_screen.qa_mode_btn.isHidden())
        self.assertTrue(
            self.window._course_screen.generate_questions_btn.isHidden()
        )

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

        self.assertTrue(
            self.window.navigate_route(
                Route.course(self.project.course_id, tab="knowledge"),
                allow_first_run_redirect=False,
            )
        )

        self.assertIs(screen.knowledge_panel, screen.content_stack.currentWidget())
        self.assertEqual(2, screen.knowledge_table.rowCount())
        self.assertEqual("Input / Output", screen.knowledge_table.item(0, 0).text())
        self.assertEqual("0", screen.knowledge_table.item(0, 3).text())

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
            MainWindow,
            "_configure_generation_dialog",
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

    def test_browsing_another_course_does_not_change_the_active_course(self):
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
            self.project.course_id,
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
            self.project.course_id,
            self.window.course_manager.current().course_id,
        )


if __name__ == "__main__":
    unittest.main()
