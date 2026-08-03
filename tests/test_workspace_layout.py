import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFormLayout, QLabel, QListWidget, QSplitter, QWidget

from core.language_manager import LanguageManager
from core.progress_tracker import ProgressManager
from core.mastery_overrides import MasteryOverrideStore
from models.course_project import CourseProjectManager
from models.question import QuestionBank
from models.question_set import SetManager
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from ui.screens.home_screen import HomeScreen
from ui.screens.progress_dashboard import ProgressDashboard
from ui.screens.question_bank_screen import QuestionBankScreen
from ui.screens.quiz_screen import QuizScreen
from ui.screens.settings_screen import SettingsScreen
from utils.constants import topic_label


_APP = QApplication.instance() or QApplication([])

class WorkspaceLayoutTests(unittest.TestCase):
    def test_workspace_pages_share_page_header_contract(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                progress_manager = ProgressManager(str(root / "progress"))
                question_bank = QuestionBank(str(root / "questions"))
                screens = (
                    HomeScreen(progress_manager, question_bank),
                    ProgressDashboard(
                        progress_manager,
                        question_bank,
                        set_manager=SetManager(str(root / "sets")),
                        mastery_overrides=MasteryOverrideStore(
                            root / "mastery_overrides.json"
                        ),
                        course_manager=CourseProjectManager(str(root / "courses")),
                    ),
                    QuestionBankScreen(
                        question_bank,
                        course_manager=CourseProjectManager(str(root / "courses")),
                    ),
                )

            headers = [
                screen.findChild(QWidget, "pageHeader")
                for screen in screens
            ]
            for screen, header in zip(screens, headers):
                with self.subTest(screen=type(screen).__name__):
                    self.assertIsNotNone(header)
                    self.assertIsNotNone(header.findChild(QLabel, "screenTitle"))
                    self.assertIsNotNone(header.findChild(QLabel, "screenSubtitle"))

            home_subtitle = headers[0].findChild(QLabel, "screenSubtitle")
            progress_subtitle = headers[1].findChild(QLabel, "screenSubtitle")
            self.assertFalse(home_subtitle.isHidden())
            self.assertTrue(progress_subtitle.isHidden())

    def test_settings_content_and_actions_follow_desktop_form_layout(self):
            settings = SettingsScreen()

            self.assertIsInstance(settings.settings_nav_list, QListWidget)
            self.assertEqual("settingsNavList", settings.settings_nav_list.objectName())
            self.assertLessEqual(settings.settings_nav_list.maximumWidth(), 220)
            nav_labels = [
                settings.settings_nav_list.item(index).text()
                for index in range(settings.settings_nav_list.count())
            ]
            self.assertEqual(
                ["显示语言", "AI 出题", "练习默认值", "运行环境", "数据管理", "关于"],
                nav_labels,
            )
            self.assertEqual("aboutSettingsGroup", settings.about_group.objectName())
            self.assertIn("GPL-3.0-only", settings.about_license_label.text())
            self.assertEqual(960, settings.settings_content.maximumWidth())
            self.assertEqual(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                settings.ai_form_layout.labelAlignment(),
            )
            self.assertLess(
                settings.ai_action_layout.indexOf(settings.test_ai_btn),
                settings.ai_action_layout.indexOf(settings.save_btn),
            )
            self.assertGreaterEqual(settings.ai_action_layout.contentsMargins().top(), 8)
            self.assertLess(
                settings.settings_content.layout().indexOf(settings.ai_group),
                settings.settings_content.layout().indexOf(settings.practice_group),
            )
            self.assertIsNotNone(settings.default_template_combo)
            self.assertGreaterEqual(settings.default_template_combo.count(), 3)
            self.assertIsNotNone(settings.default_mc_weight_input)
            self.assertIsNotNone(settings.default_hard_weight_input)
            self.assertEqual("settingsWeightPreview", settings.question_type_weight_preview.objectName())
            self.assertEqual("settingsWeightPreview", settings.difficulty_weight_preview.objectName())
            self.assertLess(
                settings.practice_form_layout.indexOf(settings.default_fill_blank_weight_input),
                settings.practice_form_layout.indexOf(settings.question_type_weight_preview),
            )
            self.assertLess(
                settings.practice_form_layout.indexOf(settings.default_hard_weight_input),
                settings.practice_form_layout.indexOf(settings.difficulty_weight_preview),
            )
            self.assertLess(
                settings.practice_form_layout.indexOf(settings.difficulty_weight_preview),
                settings.practice_form_layout.indexOf(settings.refresh_default_weight_preview_btn),
            )
            self.assertLess(
                settings.settings_content.layout().indexOf(settings.practice_group),
                settings.settings_content.layout().indexOf(settings.environment_group),
            )
            self.assertLess(
                settings.data_action_layout.indexOf(settings.export_btn),
                settings.data_action_layout.indexOf(settings.import_btn),
            )
            self.assertLess(
                settings.data_action_layout.indexOf(settings.import_btn),
                settings.data_action_layout.indexOf(settings.export_app_data_btn),
            )
            self.assertLess(
                settings.data_action_layout.indexOf(settings.export_app_data_btn),
                settings.data_action_layout.indexOf(settings.import_app_data_btn),
            )
            self.assertLess(
                settings.data_action_layout.indexOf(settings.import_app_data_btn),
                settings.data_action_layout.indexOf(settings.reset_progress_btn),
            )

    def test_settings_explains_relative_weights_and_confirms_effective_share(self):
            lang_manager = LanguageManager.instance()
            previous_lang = lang_manager.current
            self.addCleanup(lang_manager.set_language, previous_lang)
            lang_manager.set_language("zh")
            settings = SettingsScreen()

            self.assertIn("相对权重", settings.weight_help_label.text())
            self.assertIn("无需合计 100", settings.weight_help_label.text())
            self.assertEqual("确认并更新占比", settings.refresh_default_weight_preview_btn.text())
            self.assertEqual("", settings.default_mc_weight_input.suffix())

            for spinbox in (
                settings.default_mc_weight_input,
                settings.default_scenario_weight_input,
                settings.default_true_false_weight_input,
                settings.default_fill_blank_weight_input,
            ):
                spinbox.setValue(50)
            settings.refresh_default_weight_preview_btn.click()

            settings.default_mc_weight_input.setValue(100)
            settings.default_scenario_weight_input.setValue(0)
            settings.default_true_false_weight_input.setValue(0)
            settings.default_fill_blank_weight_input.setValue(0)
            previous_preview = settings.question_type_weight_preview.text()

            self.assertNotIn("选择题 100%", previous_preview)

            settings.refresh_default_weight_preview_btn.click()

            self.assertIn("选择题 100%", settings.question_type_weight_preview.text())

            lang_manager.set_language("en")
            self.assertIn("relative weights", settings.weight_help_label.text().lower())
            self.assertEqual("Confirm Effective Shares", settings.refresh_default_weight_preview_btn.text())

    def test_settings_nav_selects_matching_section(self):
            settings = SettingsScreen()

            environment_row = [
                index for index in range(settings.settings_nav_list.count())
                if settings.settings_nav_list.item(index).data(Qt.ItemDataRole.UserRole) == settings.environment_group
            ][0]

            settings.settings_nav_list.setCurrentRow(environment_row)

            self.assertEqual(settings.environment_group, settings._active_settings_group)

    def test_generation_dialog_uses_two_pane_desktop_layout(self):
            dialog = AIGenerationDialog(
                "# Course\nCache content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache", "process"],
            )

            self.assertIsInstance(dialog.content_splitter, QSplitter)
            self.assertEqual(Qt.Orientation.Horizontal, dialog.content_splitter.orientation())
            self.assertEqual(dialog.left_pane, dialog.content_splitter.widget(0))
            self.assertEqual(dialog.right_scroll, dialog.content_splitter.widget(1))
            self.assertTrue(dialog.left_pane.isAncestorOf(dialog.topic_group))
            self.assertTrue(dialog.left_pane.isAncestorOf(dialog.prompt_group))
            self.assertTrue(dialog.right_content.isAncestorOf(dialog.config_group))
            self.assertTrue(dialog.right_content.isAncestorOf(dialog.structure_group))
            self.assertLess(
                dialog.footer_action_layout.indexOf(dialog.cancel_btn),
                dialog.footer_action_layout.indexOf(dialog.generate_btn),
            )

    def test_generation_dialog_hides_advanced_controls_until_requested(self):
            dialog = AIGenerationDialog(
                "# Course\nCache content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache", "process"],
            )

            self.assertTrue(dialog.advanced_content.isHidden())
            self.assertTrue(dialog.config_group.isHidden())
            self.assertIn("展开高级设置", dialog.advanced_toggle_btn.text())
            self.assertTrue(dialog.generation_log_group.isHidden())
            self.assertTrue(dialog.advanced_content.isAncestorOf(dialog.topic_weight_group))
            self.assertTrue(dialog.advanced_content.isAncestorOf(dialog.structure_group))
            self.assertTrue(dialog.advanced_content.isAncestorOf(dialog.plan_group))
            self.assertTrue(dialog.advanced_content.isAncestorOf(dialog.runtime_instruction_group))

            dialog.advanced_toggle_btn.click()

            self.assertFalse(dialog.advanced_content.isHidden())
            self.assertFalse(dialog.config_group.isHidden())
            self.assertIn("收起高级设置", dialog.advanced_toggle_btn.text())

            dialog._append_generation_event("Generating question 1/5")

            self.assertFalse(dialog.generation_log_group.isHidden())

    def test_generation_dialog_weight_panel_uses_compact_topic_labels(self):
            long_topic = (
                "非常非常非常长的课程主题名称包含根据课件整理概念关键条件中间状态输出结果 "
                "Cache Mapping Address Breakdown Set Associativity Replacement Policy"
            )
            dialog = AIGenerationDialog(
                "# Course\nCache content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=[long_topic],
            )

            topic_weight_layout = dialog.topic_weight_group.layout()
            self.assertIsInstance(topic_weight_layout, QFormLayout)
            self.assertEqual(QFormLayout.RowWrapPolicy.DontWrapRows, topic_weight_layout.rowWrapPolicy())

            topic_labels = [
                label
                for label in dialog.topic_weight_group.findChildren(QLabel)
                if label.objectName() == "weightTopicLabel"
            ]
            display_topic = topic_label(long_topic)
            self.assertTrue(topic_labels)
            self.assertTrue(all(not label.wordWrap() for label in topic_labels))
            self.assertTrue(all(label.maximumWidth() <= 220 for label in topic_labels))
            self.assertTrue(all(label.toolTip() == display_topic for label in topic_labels))
            self.assertTrue(all("…" in label.text() for label in topic_labels))
            self.assertLessEqual(dialog.right_content.minimumSizeHint().width(), 760)

    def test_quiz_screen_uses_desktop_practice_workspace_with_review_hidden_by_default(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                quiz = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )

            quiz.resize(1280, 720)
            quiz._update_responsive_layout()

            self.assertIsInstance(quiz.practice_splitter, QSplitter)
            self.assertEqual(Qt.Orientation.Horizontal, quiz.practice_splitter.orientation())
            self.assertIsInstance(quiz.question_answer_splitter, QSplitter)
            self.assertEqual(Qt.Orientation.Horizontal, quiz.question_answer_splitter.orientation())
            self.assertEqual("quizPreviewPane", quiz.preview_pane.objectName())
            self.assertTrue(quiz.preview_pane.isHidden())
            self.assertEqual("整卷复查", quiz.review_toggle_btn.text())
            self.assertEqual("quizPracticeCard", quiz.practice_card.objectName())
            self.assertGreaterEqual(quiz.practice_card.maximumWidth(), 1100)
            self.assertLessEqual(quiz.preview_pane.maximumWidth(), 360)
            self.assertTrue(quiz.practice_card.isAncestorOf(quiz.question_card))
            self.assertTrue(quiz.practice_card.isAncestorOf(quiz.answer_area))
            self.assertTrue(quiz.practice_card.isAncestorOf(quiz.prev_question_btn))
            self.assertTrue(quiz.practice_card.isAncestorOf(quiz.uncertain_checkbox))
            self.assertTrue(quiz.practice_card.isAncestorOf(quiz.review_checkbox))
            self.assertTrue(quiz.practice_card.isAncestorOf(quiz.next_question_btn))
            self.assertTrue(quiz.practice_card.isAncestorOf(quiz.feedback_frame))
            self.assertEqual(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                quiz.practice_scroll.alignment(),
            )

    def test_quiz_screen_uses_vertical_answer_layout_when_window_is_narrow(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                quiz = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )

            quiz.resize(900, 680)
            quiz._update_responsive_layout()

            self.assertEqual(
                Qt.Orientation.Vertical,
                quiz.question_answer_splitter.orientation(),
            )
            self.assertEqual(
                Qt.Orientation.Vertical,
                quiz.practice_splitter.orientation(),
            )
            self.assertEqual(0, quiz.practice_card.minimumWidth())

            quiz.resize(1280, 720)
            quiz._update_responsive_layout()
            self.assertEqual(
                Qt.Orientation.Horizontal,
                quiz.question_answer_splitter.orientation(),
            )
