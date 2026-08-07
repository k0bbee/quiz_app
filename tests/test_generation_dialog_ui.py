import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt

from ai.generation_config import GenerationConfig
from ai.exam_plan import ExamGenerationPlan
from core.question_set_builder import build_ai_question_set
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from ui.navigation import Route
from models.question import Question
from models.course_project import CourseTopic
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])

class GenerationDialogUiTests(unittest.TestCase):
    def test_generation_dialog_keeps_count_and_difficulty_in_primary_controls(self):
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache"],
            )
            self.addCleanup(dialog.close)

            self.assertIs(dialog.count_spin.parentWidget(), dialog.basic_group)
            self.assertIs(dialog.diff_combo.parentWidget(), dialog.basic_group)
            self.assertFalse(dialog.basic_group.isHidden())
            self.assertIs(dialog.goal_group.parentWidget(), dialog.basic_group)
            self.assertFalse(dialog.goal_group.isHidden())
            self.assertTrue(dialog.advanced_content.isHidden())
            self.assertTrue(dialog.config_group.isHidden())
            self.assertEqual(2000, dialog.generation_status_timer.interval())

    def test_generation_goal_shows_current_selection_in_basic_summary(self):
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache"],
            )
            self.addCleanup(dialog.close)

            self.assertTrue(dialog.quick_review_goal_btn.isChecked())
            self.assertIn("目标：快速复习", dialog.footer_summary_label.text())
            self.assertIn("难度：中等", dialog.footer_summary_label.text())

            dialog.mock_exam_goal_btn.click()

            self.assertTrue(dialog.mock_exam_goal_btn.isChecked())
            self.assertFalse(dialog.quick_review_goal_btn.isChecked())
            self.assertIn("目标：模拟考试", dialog.footer_summary_label.text())
            self.assertIn("难度：混合", dialog.footer_summary_label.text())

    def test_generation_dialog_keeps_review_action_after_save_error(self):
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["contract"],
            )
            self.addCleanup(dialog.close)
            dialog.generated_questions = [
                Question.create_new(
                    qtype=QuestionType.TRUE_FALSE,
                    difficulty=Difficulty.EASY,
                    bilingual={
                        "zh": {
                            "stem": "合同题",
                            "options": ["正确", "错误"],
                            "explanation": "解释。",
                        },
                        "en": {
                            "stem": "Contract question",
                            "options": ["True", "False"],
                            "explanation": "Explanation.",
                        },
                    },
                    correct_answer=True,
                    topic="contract",
                )
            ]

            dialog.show_save_error("disk full")

            self.assertFalse(dialog.review_partial_btn.isHidden())
            self.assertTrue(dialog.review_partial_btn.isEnabled())
            self.assertIn("disk full", dialog.status_label.text())
            self.assertIn("仍保留", dialog.status_label.text())

    def test_generation_dialog_restores_review_pending_draft(self):
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache"],
            )
            self.addCleanup(dialog.close)
            question = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "缓存恢复题",
                        "options": ["正确", "错误"],
                        "explanation": "解释。",
                    },
                    "en": {
                        "stem": "Cache recovery question",
                        "options": ["True", "False"],
                        "explanation": "Explanation.",
                    },
                },
                correct_answer=True,
                topic="cache",
            )
            draft = SimpleNamespace(
                questions=(question,),
                question_set_title="缓存恢复练习",
                exam_plan=ExamGenerationPlan(
                    question_count=10,
                    difficulty="mixed",
                    selected_topics=("cache",),
                    topic_weights={"cache": 100},
                ),
                review_warnings_only=True,
                review_state={question.question_id: "rejected"},
            )

            dialog.restore_generation_draft(draft)

            self.assertEqual([question], dialog.generated_questions)
            self.assertEqual("缓存恢复练习", dialog.question_set_title())
            self.assertEqual("mixed", dialog.build_exam_plan().difficulty)
            self.assertEqual({question.question_id: "rejected"}, dialog.review_state)
            self.assertFalse(dialog.review_partial_btn.isHidden())
            self.assertIn("1 道题", dialog.status_label.text())

    def test_review_state_exposes_one_save_action_without_destination_picker(self):
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache"],
            )
            self.addCleanup(dialog.close)
            question = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "缓存题",
                        "options": ["正确", "错误"],
                        "explanation": "解释",
                    },
                    "en": {
                        "stem": "Cache question",
                        "options": ["True", "False"],
                        "explanation": "Explanation",
                    },
                },
                correct_answer=True,
                topic="cache",
            )
            dialog.generated_questions = [question]
            dialog._show_review_pending_state()

            self.assertFalse(dialog.review_partial_btn.isHidden())
            self.assertFalse(hasattr(dialog, "publish_combo"))

    def test_generation_dialog_notifies_when_new_questions_become_durable(self):
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache"],
            )
            self.addCleanup(dialog.close)
            question = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "新草稿题",
                        "options": ["正确", "错误"],
                        "explanation": "解释。",
                    },
                    "en": {
                        "stem": "New draft question",
                        "options": ["True", "False"],
                        "explanation": "Explanation.",
                    },
                },
                correct_answer=True,
                topic="cache",
            )
            notifications = []
            dialog.draft_changed.connect(lambda: notifications.append("changed"))

            dialog._on_question_ready([question])

            self.assertEqual([question], dialog.generated_questions)
            self.assertEqual(["changed"], notifications)

    def test_regenerated_question_set_returns_to_library_set_tab(self):
            from ui.question_set_action_controller import (
                QuestionSetActionController,
            )

            question = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "重新生成题",
                        "options": ["正确", "错误"],
                        "explanation": "解释。",
                    },
                    "en": {
                        "stem": "Regenerated question",
                        "options": ["True", "False"],
                        "explanation": "Explanation.",
                    },
                },
                correct_answer=True,
                topic="cache",
            )
            question_set = QuestionSet.create_new(
                title={"zh": "缓存题集", "en": "Cache Set"},
                description={"zh": "", "en": ""},
                topics=["cache"],
                question_ids=[question.question_id],
            )
            dialog = SimpleNamespace(
                generated_questions=[question],
                diff_combo=SimpleNamespace(
                    currentData=lambda: Difficulty.MEDIUM.value,
                ),
                configure_from_question_set=Mock(),
                exec=Mock(return_value=QDialog.DialogCode.Accepted),
            )
            navigated = []
            shell = SimpleNamespace(
                lang_manager=SimpleNamespace(
                    current="zh",
                    get_text=lambda zh, _en: zh,
                ),
                history_protection=SimpleNamespace(
                    confirm_navigation=lambda _screen: True,
                ),
                set_manager=SimpleNamespace(get=lambda _set_id: question_set),
                question_bank=Mock(),
                progress_manager=Mock(),
                topic_screen=SimpleNamespace(refresh=Mock()),
                navigate_route=navigated.append,
                SCREEN_QUESTION_BANK=6,
                generation_flow=SimpleNamespace(
                    prepare=lambda **_kwargs: SimpleNamespace(
                        dialog=dialog,
                        course_project=Mock(),
                    )
                ),
            )
            controller = QuestionSetActionController(
                shell,
                message_box=SimpleNamespace(
                    information=Mock(),
                    warning=Mock(),
                    critical=Mock(),
                ),
                regenerator=Mock(return_value=(question_set, 1, [])),
            )

            controller.regenerate(question_set.set_id)

            self.assertEqual([Route.library("sets")], navigated)

    def test_generation_dialog_schedules_confirmed_plan_after_it_is_shown(self):
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache"],
            )
            self.addCleanup(dialog.close)

            with patch(
                "ui.dialogs.ai_generation_dialog.QTimer.singleShot",
            ) as single_shot:
                dialog.start_generation_when_shown()

            single_shot.assert_called_once()
            delay, callback = single_shot.call_args.args
            self.assertEqual(0, delay)
            self.assertIs(dialog, callback.__self__)
            self.assertEqual("_start_generation", callback.__name__)

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
            dialog.matching_slider.setValue(25)
            dialog.ordering_slider.setValue(15)
            dialog.short_answer_slider.setValue(35)
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
            self.assertEqual(config.question_type_weights["matching"], 25)
            self.assertEqual(config.question_type_weights["ordering"], 15)
            self.assertEqual(config.question_type_weights["short_answer"], 35)
            self.assertEqual(config.difficulty_weights["medium"], 60)
            self.assertEqual(config.topic_weights["cache"], 80)
            self.assertEqual(config.topic_weights["process"], 20)
            self.assertEqual(config.template, "final_exam")

    def test_dialog_shows_generation_plan_preview_from_current_controls(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process"],
            )
            dialog.count_spin.setValue(10)
            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
            dialog.topic_list.item(1).setCheckState(Qt.CheckState.Checked)
            dialog.topic_weight_sliders["cache"].setValue(70)
            dialog.topic_weight_sliders["process"].setValue(30)
            dialog.mc_slider.setValue(50)
            dialog.scenario_slider.setValue(30)
            dialog.true_false_slider.setValue(20)
            dialog.fill_blank_slider.setValue(0)
            dialog.easy_slider.setValue(20)
            dialog.medium_slider.setValue(50)
            dialog.hard_slider.setValue(30)

            dialog._refresh_weight_labels()
            dialog._update_preview()

            preview = dialog.plan_preview.toPlainText()
            self.assertIn("本次计划生成 10 题", preview)
            self.assertIn("主题分布", preview)
            self.assertIn("cache: 7", preview)
            self.assertIn("process: 3", preview)
            self.assertIn("题型分布", preview)
            self.assertIn("multiple_choice: 5", preview)
            self.assertIn("scenario_choice: 3", preview)
            self.assertIn("true_false: 2", preview)
            self.assertIn("难度分布", preview)
            self.assertIn("easy: 2", preview)
            self.assertIn("medium: 5", preview)
            self.assertIn("hard: 3", preview)
            self.assertIn("组合计划", preview)
            self.assertIn("cache", preview)
            self.assertIn("multiple_choice", preview)
            self.assertIn("definition", preview)

    def test_generation_plan_preview_updates_when_count_changes(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
            dialog.count_spin.setValue(6)
            self.assertIn("本次计划生成 6 题", dialog.plan_preview.toPlainText())

            dialog.count_spin.setValue(12)

            self.assertIn("本次计划生成 12 题", dialog.plan_preview.toPlainText())

    def test_generation_dialog_footer_summary_guides_empty_topic_state(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process"],
            )

            summary = dialog.footer_summary_label.text()

            self.assertEqual("generationFooterSummary", dialog.footer_summary_label.objectName())
            self.assertIn("已选主题：0", summary)
            self.assertIn("计划生成：15 题", summary)
            self.assertIn("请选择主题", summary)

    def test_generation_dialog_footer_summary_updates_with_selected_topics_and_count(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process"],
            )

            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
            dialog.count_spin.setValue(9)

            summary = dialog.footer_summary_label.text()

            self.assertIn("已选主题：1", summary)
            self.assertIn("计划生成：9 题", summary)
            self.assertIn("覆盖：cache", summary)

    def test_generation_dialog_disables_generate_button_when_no_topics_selected(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process"],
            )
            self.assertFalse(dialog.generate_btn.isEnabled())

            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
            self.assertTrue(dialog.generate_btn.isEnabled())

            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Unchecked)
            self.assertFalse(dialog.generate_btn.isEnabled())

    def test_dialog_exposes_question_set_title(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )

            dialog.set_title_input.setText("  I/O 中断专项  ")

            self.assertEqual("I/O 中断专项", dialog.question_set_title())

    def test_ai_question_set_uses_user_supplied_title_without_reusing_chinese_as_english(self):
            question = Question.create_new(
                QuestionType.MULTIPLE_CHOICE,
                Difficulty.MEDIUM,
                {
                    "zh": {"stem": "题干", "options": ["A. 对", "B. 错"], "explanation": "解释"},
                    "en": {"stem": "Stem", "options": ["A. True", "B. False"], "explanation": "Explanation"},
                },
                "A",
                "interrupts",
                source="ai_generated",
            )

            qset = build_ai_question_set(
                [question],
                selected_difficulty="medium",
                generation_config=GenerationConfig(),
                custom_title="I/O 中断专项",
                lang="zh",
            )

            self.assertEqual("I/O 中断专项", qset.get_title("zh"))
            self.assertIn("AI Practice", qset.get_title("en"))
            self.assertNotIn("中断", qset.get_title("en"))
            self.assertTrue(qset.metadata["renamed_by_user"])

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

    def test_dialog_language_change_refreshes_preview_after_difficulty_combo_rebuild(self):
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                    "default_difficulty": "hard",
                },
                available_topics=["cache"],
            )
            self.addCleanup(dialog.close)
            observed_difficulties = []
            dialog._update_preview = lambda: observed_difficulties.append(dialog.diff_combo.currentData())

            dialog._on_language_changed("en")

            self.assertEqual(["hard"], observed_difficulties)

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

    def test_dialog_toggle_all_topics_refreshes_preview_once(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process", "memory", "io", "network"],
            )
            self.addCleanup(dialog.close)
            calls = {"sync": 0, "preview": 0}
            original_sync = dialog._sync_topic_weight_rows
            original_preview = dialog._update_preview

            def counted_sync():
                calls["sync"] += 1
                original_sync()

            def counted_preview():
                calls["preview"] += 1
                original_preview()

            dialog._sync_topic_weight_rows = counted_sync
            dialog._update_preview = counted_preview

            dialog._toggle_all(True)

            self.assertEqual(
                [Qt.CheckState.Checked] * 5,
                [dialog.topic_list.item(index).checkState() for index in range(dialog.topic_list.count())],
            )
            self.assertEqual({"sync": 1, "preview": 1}, calls)

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

            self.assertEqual("56%", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())
            self.assertEqual("44%", dialog.weight_value_labels[dialog.topic_weight_sliders["process"]].text())
            self.assertNotIn("→", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())

    def test_single_selected_topic_weight_shows_effective_share_not_raw_weight(self):
            topics = [f"topic_{index}" for index in range(19)] + ["input_output_improvements"]
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=topics,
            )
            io_index = topics.index("input_output_improvements")

            dialog.topic_list.item(io_index).setCheckState(Qt.CheckState.Checked)

            label = dialog.weight_value_labels[
                dialog.topic_weight_sliders["input_output_improvements"]
            ]
            self.assertEqual("100%", label.text())
            self.assertNotEqual("5%", label.text())

    def test_generation_progress_hides_internal_plan_slot_keys(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["input_output_improvements"],
            )

            dialog._on_progress(
                "Filling plan slots: input_output_improvements/true_false/easy, "
                "input_output_improvements/multiple_choice/medium"
            )

            status = dialog.status_label.text()
            log_text = dialog.generation_log.toPlainText()
            self.assertIn("正在准备本批 2 个计划槽位", status)
            self.assertNotIn("input_output_improvements/true_false/easy", status)
            self.assertNotIn("input_output_improvements/true_false/easy", log_text)

    def test_generation_progress_names_known_topics_without_exposing_slot_keys(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=[CourseTopic("input_output_improvements", "I/O 改进")],
            )

            message = dialog._display_progress_message(
                "Filling plan slots: input_output_improvements/true_false/easy, "
                "input_output_improvements/multiple_choice/medium"
            )

            self.assertIn("2", message)
            self.assertIn("I/O 改进", message)
            self.assertNotIn("input_output_improvements/true_false/easy", message)

    def test_generation_progress_keeps_readable_plan_slot_summary(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )

            message = dialog._display_progress_message(
                "Filling plan slots: 3 planned slot(s) across Cache, Process"
            )

            self.assertIn("3", message)
            self.assertIn("Cache", message)
            self.assertIn("Process", message)
            self.assertNotIn("planned slot", message)

    def test_course_preview_keeps_more_context_for_selected_topic(self):
            long_content = (
                "## Input Output Improvements\n"
                + "DMA, interrupts, buffering and I/O controller details. " * 90
                + "deep sentinel detail about interrupt driven I/O latency."
            )
            dialog = AIGenerationDialog(
                long_content,
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["Input Output Improvements"],
            )

            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

            preview = dialog.prompt_preview.toPlainText()
            self.assertGreater(len(preview), 3000)
            self.assertIn("deep sentinel detail", preview)

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

    def test_generation_progress_uses_worker_counts_for_a_determinate_bar(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )

            dialog._generation_requested_count = 10
            dialog.progress_bar.setRange(0, 10)
            dialog._on_progress("Generating question 3/10... (attempt 1/10)")

            self.assertEqual(10, dialog.progress_bar.maximum())
            self.assertEqual(3, dialog.progress_bar.value())

            dialog._on_progress(
                "Accepted 2 question(s), rejected 1. Total accepted: 2/10"
            )
            self.assertEqual(2, dialog.progress_bar.value())

    def test_generation_progress_log_keeps_recent_events(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )

            dialog._on_progress("Building prompt...")
            dialog._on_progress("Accepted 2 question(s), rejected 1.")

            log_text = dialog.generation_log.toPlainText()
            self.assertIn("正在准备课程上下文", log_text)
            self.assertIn("本批接受 2 道，拒绝 1 道", log_text)
            self.assertEqual("generationProgressLog", dialog.generation_log.objectName())

    def test_generation_progress_log_collapses_consecutive_duplicate_events(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )

            dialog._append_generation_event("正在等待 AI 响应…")
            dialog._append_generation_event("正在等待 AI 响应…")
            dialog._append_generation_event("收到候选题")
            dialog._append_generation_event("正在等待 AI 响应…")

            self.assertEqual(
                ["正在等待 AI 响应…", "收到候选题", "正在等待 AI 响应…"],
                dialog._generation_events,
            )

    def test_generation_progress_log_scrolls_to_latest_event(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.generation_log.setFixedHeight(40)
            dialog.show()
            try:
                _APP.processEvents()
                for index in range(60):
                    dialog._append_generation_event(f"event {index}")
                _APP.processEvents()
                scrollbar = dialog.generation_log.verticalScrollBar()
                self.assertGreater(scrollbar.maximum(), 0)
                scrollbar.setValue(0)

                dialog._append_generation_event("latest event")
                _APP.processEvents()

                self.assertEqual(scrollbar.maximum(), scrollbar.value())
                self.assertTrue(dialog.generation_log.toPlainText().endswith("latest event"))
            finally:
                dialog.close()

    def test_generation_status_localizes_single_question_request_progress(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )

            message = dialog._display_progress_message(
                "Generating question 3/10... (attempt 4/30; requesting 1 candidate)"
            )

            self.assertIn("正在生成第 3/10 题", message)
