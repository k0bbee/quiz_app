import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from ai.batch_generator import GenerationWorker
from ai.generation_config import GenerationConfig
from ai.llm_client import LLMClient
from ai.prompt_templates import PromptBuilder
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from models.question_set import QuestionSet
from utils.constants import Difficulty


_APP = QApplication.instance() or QApplication([])


class GenerationConfigTests(unittest.TestCase):
    def test_prompt_includes_question_type_and_difficulty_distribution(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 50,
                "scenario_choice": 30,
                "true_false": 10,
                "fill_in_blank": 10,
            },
            difficulty_weights={"easy": 20, "medium": 50, "hard": 30},
            topic_weights={"cache mapping": 70, "process scheduling": 30},
            template="final_exam",
        )

        prompt = PromptBuilder.build_user_prompt(
            "## Cache Mapping\nTag/set/offset example.",
            ["cache mapping", "process scheduling"],
            count=20,
            difficulty="mixed",
            generation_config=config,
        )

        self.assertIn("Question type distribution", prompt)
        self.assertIn("multiple_choice: 50%", prompt)
        self.assertIn("scenario_choice: 30%", prompt)
        self.assertIn("Difficulty distribution", prompt)
        self.assertIn("hard: 30%", prompt)
        self.assertIn("Topic coverage weights", prompt)
        self.assertIn("cache mapping: 70%", prompt)
        self.assertIn("Final exam style", prompt)

    def test_worker_keeps_generation_config(self):
        config = GenerationConfig(template="quick_review")
        worker = GenerationWorker(
            LLMClient(api_key="", base_url="local-agent://auto", model="codex"),
            course_content="content",
            topics=["cache"],
            count=5,
            difficulty="mixed",
            generation_config=config,
        )

        self.assertIs(worker.generation_config, config)

    def test_worker_records_source_course_metadata_on_generated_questions(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def generate_with_json(self, *_args, **_kwargs):
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "cache",
                            "subtopic": "mapping",
                            "correct_answer": "A",
                            "bilingual": {
                                "zh": {
                                    "stem": "哪一个说法正确？",
                                    "options": ["A. 正确", "B. 错误", "C. 错误", "D. 错误"],
                                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                                },
                                "en": {
                                    "stem": "Which statement is correct?",
                                    "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                                    "explanation": "This is a sufficiently detailed English explanation for the answer.",
                                },
                            },
                        }
                    ]
                }

        course = SimpleNamespace(
            course_id="course-20260618-demo",
            title="Systems 2B",
            updated_at="2026-06-18T12:00:00+00:00",
        )
        worker = GenerationWorker(
            FakeClient(),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
            course_project=course,
        )
        batches = []
        worker.batch_done.connect(batches.append)

        with patch("ai.batch_generator.retrieve_course_context", return_value="Cache context"):
            worker.run()

        question = batches[0][0]
        self.assertEqual("course-20260618-demo", question.metadata["course_id"])
        self.assertEqual("Systems 2B", question.metadata["course_title"])
        self.assertEqual("2026-06-18T12:00:00+00:00", question.metadata["course_updated_at"])
        self.assertEqual("test-model", question.metadata["ai_model"])

    def test_dialog_returns_generation_config_from_controls(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        dialog.mc_slider.setValue(40)
        dialog.scenario_slider.setValue(30)
        dialog.true_false_slider.setValue(20)
        dialog.fill_blank_slider.setValue(10)
        dialog.easy_slider.setValue(10)
        dialog.medium_slider.setValue(60)
        dialog.hard_slider.setValue(30)
        dialog.topic_weight_sliders["cache"].setValue(80)
        dialog.topic_weight_sliders["process"].setValue(20)
        dialog.template_combo.setCurrentIndex(dialog.template_combo.findData("final_exam"))
        for index in range(dialog.topic_list.count()):
            dialog.topic_list.item(index).setCheckState(Qt.CheckState.Checked)

        config = dialog._build_generation_config()

        self.assertEqual(config.question_type_weights["multiple_choice"], 40)
        self.assertEqual(config.question_type_weights["scenario_choice"], 30)
        self.assertEqual(config.difficulty_weights["medium"], 60)
        self.assertEqual(config.topic_weights["cache"], 80)
        self.assertEqual(config.topic_weights["process"], 20)
        self.assertEqual(config.template, "final_exam")

    def test_dialog_can_prefill_from_existing_question_set(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process", "gpu"],
        )
        qset = QuestionSet(
            set_id="set-review",
            title={"zh": "复习", "en": "Review"},
            description={"zh": "", "en": ""},
            topics=["cache", "gpu"],
            difficulty=Difficulty.HARD,
            estimated_minutes=20,
            questions=["q1", "q2", "q3", "q4", "q5"],
        )

        dialog.configure_from_question_set(qset)

        self.assertEqual(dialog.count_spin.value(), 5)
        self.assertEqual(dialog.diff_combo.currentData(), "hard")
        checked = {
            dialog.topic_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.topic_list.count())
            if dialog.topic_list.item(index).checkState() == Qt.CheckState.Checked
        }
        self.assertEqual({"cache", "gpu"}, checked)


if __name__ == "__main__":
    unittest.main()
