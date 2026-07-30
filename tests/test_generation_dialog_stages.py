import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.generation_session_state import GenerationStage
from ai.exam_plan import ExamGenerationPlan
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


if __name__ == "__main__":
    unittest.main()
