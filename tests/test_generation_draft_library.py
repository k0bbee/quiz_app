import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from ai.exam_plan import ExamGenerationPlan
from models.course_project import CourseProject, CourseTopic
from models.question import Question
from ui.generation_workspace_controller import GenerationWorkspaceController
from ui.main_window import MainWindow
from ui.navigation import Route
from ui.widgets.generation_draft_library_panel import _source_label
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


def _course() -> CourseProject:
    return CourseProject(
        course_id="course-draft",
        title="Draft Course",
        source_folder="",
        summary_markdown="# Draft Course",
        summary_path="",
        topics=[CourseTopic("topic-a", "Topic A")],
        documents=[],
        created_at="2026-07-29T00:00:00+00:00",
        updated_at="2026-07-29T00:00:00+00:00",
    )


def _question() -> Question:
    return Question(
        question_id="draft-q",
        type=QuestionType.TRUE_FALSE,
        difficulty=Difficulty.MEDIUM,
        bilingual={
            "zh": {
                "stem": "草稿题",
                "options": ["正确", "错误"],
                "explanation": "解释",
            },
            "en": {
                "stem": "Draft question",
                "options": ["True", "False"],
                "explanation": "Explanation",
            },
        },
        correct_answer=True,
        topic="topic-a",
        metadata={"course_id": "course-draft"},
    )


class GenerationDraftLibraryTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.project = _course()
        self.assertTrue(self.window.course_manager.save(self.project))
        self.window.generation_draft_store.save(
            course_id=self.project.course_id,
            questions=[_question()],
            question_set_title="Draft Review",
            exam_plan=ExamGenerationPlan(
                question_count=3,
                selected_topics=("topic-a",),
            ),
            source="manual",
        )

    def test_library_drafts_route_lists_and_resumes_the_course_draft(self):
        self.assertTrue(self.window.navigate_route(Route.library("drafts")))
        library = self.window._question_bank_screen

        self.assertEqual(Route.library("drafts"), self.window.current_route)
        self.assertFalse(hasattr(self.window, "drafts_tab_btn"))
        self.assertNotIn(
            "Generation Drafts",
            [button.text() for button in self.window.context_tabs()],
        )
        self.assertIs(
            library.draft_panel,
            library.workspace_tabs.currentWidget(),
        )
        self.assertEqual(1, library.draft_panel.table.rowCount())
        self.assertEqual(
            "Draft Review",
            library.draft_panel.table.item(0, 1).text(),
        )
        self.assertTrue(library.draft_panel.resume_btn.isEnabled())

        dialog = QDialog()
        self.addCleanup(dialog.close)
        with patch.object(
            GenerationWorkspaceController,
            "configure",
            return_value=(dialog, self.project, True, "manual"),
        ):
            library.draft_panel.resume_btn.click()

        self.assertEqual(
            Route.course(self.project.course_id, tab="generation"),
            self.window.current_route,
        )
        self.assertIs(
            dialog,
            self.window._get_generation_workspace().generation_widget(),
        )

    def test_archived_course_draft_is_visible_but_cannot_resume(self):
        self.assertTrue(self.window.course_manager.archive(self.project.course_id))

        self.assertTrue(self.window.navigate_route(Route.library("drafts")))
        panel = self.window._question_bank_screen.draft_panel

        self.assertEqual(1, panel.table.rowCount())
        self.assertFalse(panel.resume_btn.isEnabled())

    def test_resume_signal_identifies_the_selected_draft(self):
        self.window.generation_draft_store.save(
            course_id=self.project.course_id,
            draft_id="session-prediction",
            questions=[_question()],
            question_set_title="预测草稿",
            exam_plan=ExamGenerationPlan(
                question_count=3,
                selected_topics=("topic-a",),
            ),
            source="prediction",
        )

        self.assertTrue(self.window.navigate_route(Route.library("drafts")))
        panel = self.window._question_bank_screen.draft_panel
        events = []
        panel.resume_requested.connect(lambda *args: events.append(args))
        row = next(
            index
            for index, draft in enumerate(panel._visible_drafts)
            if draft.draft_id == "session-prediction"
        )
        panel.table.selectRow(row)
        panel._resume_selected()

        self.assertEqual(
            [(self.project.course_id, "prediction", "session-prediction")],
            events,
        )

    def test_library_uses_specific_labels_for_generation_workflows(self):
        def get_text(zh, _en):
            return zh

        self.assertEqual("补齐缺口", _source_label("course_hub_gap", get_text))
        self.assertEqual("弱项补强", _source_label("result_reinforcement", get_text))
        self.assertEqual("按知识点生成", _source_label("progress_topic", get_text))
        self.assertEqual("真题预测", _source_label("predicted_exam", get_text))
        self.assertEqual("热点材料", _source_label("current_event", get_text))


if __name__ == "__main__":
    unittest.main()
