import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt

from ai.batch_generator import GenerationWorker
from ai.generation_config import GenerationConfig
from ai.exam_plan import ExamGenerationPlan
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

    def test_prompt_specifies_fill_in_blank_answer_list_format(self):
        prompt = PromptBuilder.build_user_prompt(
            "## Cache\nA cache line stores a block.",
            ["cache"],
            count=3,
            generation_config=GenerationConfig(
                question_type_weights={
                    "multiple_choice": 0,
                    "scenario_choice": 0,
                    "true_false": 0,
                    "fill_in_blank": 100,
                }
            ),
        )

        self.assertIn("fill_in_blank", prompt)
        self.assertIn('"correct_answer": ["accepted answer"', prompt)

    def test_prompt_marks_selected_topics_as_hard_generation_boundary(self):
        prompt = PromptBuilder.build_user_prompt(
            "## Input Output Improvements\nPolling, interrupts, buffers, and DMA.",
            ["Input Output Improvements"],
            count=3,
        )

        self.assertIn("Selected-topic boundary", prompt)
        self.assertIn("Do not expand into neighboring course topics", prompt)

    def test_prompt_context_can_use_topic_keywords_to_respect_selected_topic(self):
        content = (
            "## Cache Mapping\n"
            "This overview only says cache mapping at a high level.\n\n"
            "## Address Breakdown\n"
            "The tag, set index, and byte offset determine lookup behavior.\n"
        )

        prompt = PromptBuilder.build_user_prompt(
            content,
            ["cache mapping"],
            count=3,
            topic_keywords={"Cache Mapping": ["tag", "set index", "byte offset"]},
            max_context_chars=160,
        )

        self.assertIn("Address Breakdown", prompt)
        self.assertIn("byte offset", prompt)

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

    def test_dialog_uses_saved_practice_defaults_as_initial_generation_settings(self):
        dialog = AIGenerationDialog(
            "course content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
                "default_question_count": 24,
                "default_difficulty": "hard",
                "default_generation_template": "final_exam",
                "default_question_type_weights": {
                    "multiple_choice": 45,
                    "scenario_choice": 35,
                    "true_false": 15,
                    "fill_in_blank": 5,
                },
                "default_difficulty_weights": {
                    "easy": 10,
                    "medium": 70,
                    "hard": 20,
                },
            },
            available_topics=["cache"],
        )

        self.assertEqual(24, dialog.count_spin.value())
        self.assertEqual("hard", dialog.diff_combo.currentData())
        self.assertEqual("final_exam", dialog.template_combo.currentData())
        self.assertEqual(45, dialog.mc_slider.value())
        self.assertEqual(35, dialog.scenario_slider.value())
        self.assertEqual(15, dialog.true_false_slider.value())
        self.assertEqual(5, dialog.fill_blank_slider.value())
        self.assertEqual(10, dialog.easy_slider.value())
        self.assertEqual(70, dialog.medium_slider.value())
        self.assertEqual(20, dialog.hard_slider.value())

    def test_dialog_topic_weight_rows_follow_selected_topics(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process", "memory"],
        )

        self.assertTrue(dialog.topic_weight_rows["cache"].isHidden())
        self.assertTrue(dialog.topic_weight_rows["process"].isHidden())
        self.assertTrue(dialog.topic_weight_labels["cache"].isHidden())

        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

        self.assertFalse(dialog.topic_weight_rows["cache"].isHidden())
        self.assertFalse(dialog.topic_weight_labels["cache"].isHidden())
        self.assertTrue(dialog.topic_weight_rows["process"].isHidden())

        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Unchecked)

        self.assertTrue(dialog.topic_weight_rows["cache"].isHidden())

    def test_dialog_weight_labels_update_normalized_effective_percentages_after_confirmation(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.topic_list.item(1).setCheckState(Qt.CheckState.Checked)

        self.assertEqual("50%", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())
        self.assertEqual("50%", dialog.weight_value_labels[dialog.topic_weight_sliders["process"]].text())

        dialog.topic_weight_sliders["cache"].setValue(100)
        dialog.topic_weight_sliders["process"].setValue(80)

        self.assertEqual("50%", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())
        self.assertEqual("50%", dialog.weight_value_labels[dialog.topic_weight_sliders["process"]].text())

        dialog.refresh_weight_preview_btn.click()

        self.assertEqual("100 (56%)", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())
        self.assertEqual("80 (44%)", dialog.weight_value_labels[dialog.topic_weight_sliders["process"]].text())
        self.assertNotIn("→", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())

    def test_generation_status_keeps_latest_progress_and_elapsed_hint(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        dialog._generation_started_at = 100.0

        with patch("ui.dialogs.ai_generation_dialog.time.monotonic", return_value=106.4):
            dialog._on_progress("Requesting batch 1/3 from AI...")

        text = dialog.status_label.text()
        self.assertIn("Requesting batch 1/3", text)
        self.assertIn("6s", text)
        self.assertIn("可取消", text)

    def test_local_agent_generation_start_does_not_read_persisted_api_key(self):
        class ForbiddenSecrets:
            def get_key(self):
                raise AssertionError("local agent generation must not read persisted API keys")

        class FakeSignal:
            def connect(self, _callback):
                pass

        class FakeWorker:
            def __init__(self, *args, **kwargs):
                self.progress = FakeSignal()
                self.batch_done = FakeSignal()
                self.error = FakeSignal()
                self.finished = FakeSignal()
                self.args = args
                self.kwargs = kwargs
                self.started = False

            def start(self):
                self.started = True

        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

        with patch("core.secrets_manager.SecretsManager.instance", return_value=ForbiddenSecrets()), \
             patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FakeWorker):
            dialog._start_generation()

        self.assertIsInstance(dialog.worker, FakeWorker)
        self.assertTrue(dialog.worker.started)

    def test_cancel_during_generation_does_not_block_waiting_for_worker(self):
        class BlockingWorker:
            def __init__(self):
                self.cancelled = False

            def isRunning(self):
                return True

            def cancel(self):
                self.cancelled = True

            def wait(self, *_args):
                raise AssertionError("cancel must not block the UI thread waiting for worker")

            def terminate(self):
                raise AssertionError("cancel must not force-terminate worker from the UI thread")

        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        worker = BlockingWorker()
        dialog.worker = worker

        dialog.reject()

        self.assertTrue(worker.cancelled)

    def test_generation_finished_handler_does_not_wait_on_worker(self):
        class FinishedWorker:
            def wait(self, *_args):
                raise AssertionError("finished handler must not wait on worker in the UI thread")

        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        dialog.worker = FinishedWorker()
        dialog._generation_failed = True

        dialog._on_finished()

        self.assertFalse(dialog.progress_bar.isVisible())
        self.assertTrue(dialog.generate_btn.isEnabled())

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

    def test_dialog_exam_plan_round_trip_applies_all_controls(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        target = ExamGenerationPlan(
            question_count=22,
            difficulty="mixed",
            template="final_exam",
            selected_topics=("process",),
            question_type_weights={
                "multiple_choice": 40,
                "scenario_choice": 30,
                "true_false": 20,
                "fill_in_blank": 10,
            },
            difficulty_weights={"easy": 10, "medium": 50, "hard": 40},
            topic_weights={"process": 100},
        )

        dialog.apply_exam_plan(target)
        rebuilt = dialog.build_exam_plan()

        self.assertEqual(target.to_dict(), rebuilt.to_dict())
        checked = {
            dialog.topic_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.topic_list.count())
            if dialog.topic_list.item(index).checkState() == Qt.CheckState.Checked
        }
        self.assertEqual({"process"}, checked)

    def test_accepted_exam_assistant_plan_is_applied(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        target = ExamGenerationPlan(
            question_count=30,
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )

        with patch("ui.dialogs.exam_assistant_dialog.ExamAssistantDialog") as assistant_class:
            assistant = assistant_class.return_value
            assistant.exec.return_value = QDialog.DialogCode.Accepted
            assistant.get_confirmed_plan.return_value = target

            dialog._open_exam_assistant()

        self.assertEqual(30, dialog.count_spin.value())
        assistant_class.assert_called_once()

    def test_dialog_prefills_all_controls_from_course_generation_profile(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        profile = ExamGenerationPlan(
            question_count=26,
            difficulty="mixed",
            template="calculation_practice",
            selected_topics=("cache", "process"),
            question_type_weights={
                "multiple_choice": 30,
                "scenario_choice": 30,
                "true_false": 10,
                "fill_in_blank": 30,
            },
            difficulty_weights={"easy": 10, "medium": 40, "hard": 50},
            topic_weights={"cache": 70, "process": 30},
        )
        course = SimpleNamespace(generation_profile=profile.to_dict())

        applied = dialog.configure_from_course_profile(course)

        self.assertTrue(applied)
        self.assertEqual(profile.to_dict(), dialog.build_exam_plan().to_dict())

    def test_malformed_course_profile_keeps_current_controls_and_shows_error(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        before = dialog.build_exam_plan().to_dict()
        course = SimpleNamespace(
            generation_profile={"selected_topics": ["invented topic"]}
        )

        applied = dialog.configure_from_course_profile(course)

        self.assertFalse(applied)
        self.assertEqual(before, dialog.build_exam_plan().to_dict())
        self.assertIn("invented topic", dialog.status_label.text())

    def test_question_set_history_overrides_course_profile_on_regeneration(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        course_profile = ExamGenerationPlan(
            question_count=20,
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )
        dialog.configure_from_course_profile(
            SimpleNamespace(generation_profile=course_profile.to_dict())
        )
        question_set = QuestionSet(
            set_id="set-history",
            title={"zh": "历史", "en": "History"},
            description={"zh": "", "en": ""},
            topics=["process"],
            difficulty=Difficulty.HARD,
            estimated_minutes=30,
            questions=[f"q-{index}" for index in range(18)],
            metadata={
                "difficulty_mode": "hard",
                "generation_template": "final_exam",
                "question_type_weights": {
                    "multiple_choice": 40,
                    "scenario_choice": 40,
                    "true_false": 10,
                    "fill_in_blank": 10,
                },
                "difficulty_weights": {"easy": 10, "medium": 30, "hard": 60},
                "topic_weights": {"process": 100},
            },
        )

        dialog.configure_from_question_set(question_set)
        rebuilt = dialog.build_exam_plan()

        self.assertEqual(18, rebuilt.question_count)
        self.assertEqual("final_exam", rebuilt.template)
        self.assertEqual(("process",), rebuilt.selected_topics)
        self.assertEqual(60, rebuilt.difficulty_weights["hard"])

    def test_main_generation_flow_applies_active_course_profile_before_opening(self):
        from core.language_manager import LanguageManager
        from ui.main_window import MainWindow

        class ForbiddenSecrets:
            def get_key(self):
                raise AssertionError("local agent generation preflight must not read persisted API keys")

        settings = {
            "ai_provider": "local_agent",
            "ai_base_url": "local-agent://auto",
            "ai_model": "codex",
        }
        course = SimpleNamespace(generation_profile={"question_count": 20})
        shell = SimpleNamespace(
            settings_screen=SimpleNamespace(_settings=settings),
            lang_manager=LanguageManager.instance(),
            _load_generation_context=lambda: ("summary", ["cache"], course),
        )

        with patch("ui.main_window._ai_generation_settings_error", return_value=""), \
             patch("core.secrets_manager.SecretsManager.instance", return_value=ForbiddenSecrets()), \
             patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog") as dialog_class:
            dialog_class.return_value.exec.return_value = QDialog.DialogCode.Rejected

            MainWindow._on_ai_generate(shell)

        dialog_class.return_value.configure_from_course_profile.assert_called_once_with(course)


if __name__ == "__main__":
    unittest.main()
