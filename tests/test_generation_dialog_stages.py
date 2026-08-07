import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.generation_session_state import GenerationStage
from ai.exam_plan import ExamGenerationPlan
from models.course_project import CourseProject, CourseTopic
from models.question import Question
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class GenerationDialogStageTests(unittest.TestCase):
    def test_partial_results_and_review_state_follow_the_session_lifecycle(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto"},
            available_topics=["cache"],
        )
        self.addCleanup(dialog.close)

        self.assertEqual(GenerationStage.CONFIGURING, dialog.generation_stage)
        dialog._session_state.start()
        dialog._on_partial_done([], "network timeout")
        self.assertEqual(GenerationStage.PARTIAL, dialog.generation_stage)
        dialog._show_review_pending_state()
        self.assertEqual(GenerationStage.REVIEW_PENDING, dialog.generation_stage)

    def test_restored_draft_enters_review_pending_stage_without_a_new_request(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto"},
            available_topics=["cache"],
        )
        self.addCleanup(dialog.close)
        question = Question.create_new(
            qtype=QuestionType.TRUE_FALSE,
            topic="cache",
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {"stem": "缓存是易失性存储。", "options": [], "explanation": ""},
                "en": {"stem": "Cache is volatile.", "options": [], "explanation": ""},
            },
            correct_answer=True,
        )
        draft = type("Draft", (), {
            "questions": (question,),
            "exam_plan": ExamGenerationPlan(question_count=3),
            "question_set_title": "缓存复习",
            "review_warnings_only": False,
        })()

        dialog.restore_generation_draft(draft)

        self.assertEqual(GenerationStage.REVIEW_PENDING, dialog.generation_stage)

    def test_goal_presets_configure_a_clear_generation_intent(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto"},
            available_topics=["cache"],
        )
        self.addCleanup(dialog.close)

        dialog.mock_exam_goal_btn.click()

        self.assertEqual("final_exam", dialog.template_combo.currentData())
        self.assertEqual(30, dialog.count_spin.value())
        self.assertEqual("mixed", dialog.diff_combo.currentData())

        dialog.gap_fill_goal_btn.click()

        self.assertEqual("quick_review", dialog.template_combo.currentData())
        self.assertEqual(8, dialog.count_spin.value())

    def test_gap_fill_goal_selects_only_real_gap_topics_when_available(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto"},
            available_topics=["cache", "process", "io"],
        )
        self.addCleanup(dialog.close)

        dialog.set_generation_gap_topics(("process", "io"))
        dialog.gap_fill_goal_btn.click()

        selected = [
            item.data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.topic_list.count())
            if (item := dialog.topic_list.item(index)).checkState() == Qt.CheckState.Checked
        ]
        self.assertEqual(["process", "io"], selected)
        self.assertTrue(dialog.generate_btn.isEnabled())

    def test_gap_fill_goal_disables_generation_when_scope_has_no_gaps(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto"},
            available_topics=["cache"],
        )
        self.addCleanup(dialog.close)

        dialog.set_generation_gap_topics(())
        dialog.gap_fill_goal_btn.click()

        self.assertFalse(dialog.generate_btn.isEnabled())
        self.assertIn("没有待补齐", dialog.status_label.text())

    def test_mock_exam_goal_uses_exam_scope_and_saved_topic_weights(self):
        topics = [
            CourseTopic("cache", "Cache"),
            CourseTopic("process", "Process"),
            CourseTopic("io", "I/O"),
        ]
        course = CourseProject(
            course_id="course-gap",
            title="Gap course",
            source_folder="",
            summary_markdown="# Gap course\nCache and process",
            summary_path="",
            topics=topics,
            documents=[],
            created_at="",
            updated_at="",
            generation_profile={"topic_weights": {"cache": 70, "process": 30}},
            exam_scope_mode="selected",
            exam_scope_topic_ids=["cache", "process"],
        )
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto"},
            available_topics=["cache", "process", "io"],
            course_project=course,
        )
        self.addCleanup(dialog.close)

        dialog.mock_exam_goal_btn.click()

        selected = [
            item.data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.topic_list.count())
            if (item := dialog.topic_list.item(index)).checkState() == Qt.CheckState.Checked
        ]
        self.assertEqual(["cache", "process"], selected)
        self.assertEqual(70, dialog.topic_weight_sliders["cache"].value())
        self.assertEqual(30, dialog.topic_weight_sliders["process"].value())


if __name__ == "__main__":
    unittest.main()
