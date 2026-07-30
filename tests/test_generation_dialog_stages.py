import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.generation_session_state import GenerationStage
from ui.dialogs.ai_generation_dialog import AIGenerationDialog


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


if __name__ == "__main__":
    unittest.main()
