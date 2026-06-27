import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QPalette
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QGridLayout, QSplitter

from core.progress_tracker import ProgressManager
from models.course_project import CourseProjectManager
from models.question import Question, QuestionBank
from models.question_set import SetManager
from main import _apply_dark_palette
from ui.main_window import MainWindow
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from ui.dialogs.question_review_dialog import QuestionReviewDialog
from ui.screens.course_screen import CourseScreen
from ui.screens.home_screen import HomeScreen
from ui.screens.progress_dashboard import ProgressDashboard
from ui.screens.question_bank_screen import QuestionBankScreen
from ui.screens.quiz_screen import QuizScreen
from ui.screens.results_screen import ResultsScreen
from ui.screens.settings_screen import SettingsScreen
from ui.screens.topic_selection_screen import TopicSelectionScreen
from ui.widgets.answer_area import OrderingWidget
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class UiThemeTests(unittest.TestCase):
    def test_qss_uses_vscode_dark_tokens_and_top_level_backgrounds(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        for token in (
            "#181818", "#1f1f1f", "#252526", "#313131",
            "#0078d4", "#007fd4", "#cccccc",
        ):
            self.assertIn(token, qss)
        self.assertRegex(qss, r"qdialog[^\{]*\{[^}]*background-color:\s*#1f1f1f")
        self.assertIn("qpushbutton#primarybutton", qss)
        self.assertIn("qlabel#settingsconnectionstatus", qss)
        self.assertIn("qlabel#settingsconnectionstatusok", qss)
        self.assertIn("qlabel#settingsconnectionstatuserror", qss)

    def test_default_button_is_secondary_instead_of_primary_blue(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()
        match = re.search(r"qpushbutton\s*\{(?P<body>[^}]*)\}", qss, flags=re.DOTALL)

        self.assertIsNotNone(match)
        default_rule = match.group("body")
        self.assertIn("#313131", default_rule)
        self.assertNotIn("#0078d4", default_rule)

    def test_buttons_use_soft_radius_and_complete_interaction_states(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        default_rule = re.search(r"qpushbutton\s*\{(?P<body>[^}]*)\}", qss, flags=re.DOTALL)
        self.assertIsNotNone(default_rule)
        self.assertRegex(default_rule.group("body"), r"border-radius:\s*(1[0-9]|[2-9][0-9])px")
        self.assertIn("outline: none", default_rule.group("body"))

        for selector in (
            "qpushbutton:hover",
            "qpushbutton:pressed",
            "qpushbutton:focus",
            "qpushbutton#primarybutton:hover",
            "qpushbutton#primarybutton:pressed",
            "qpushbutton#primarybutton:focus",
            "qpushbutton#secondarybutton:hover",
            "qpushbutton#secondarybutton:pressed",
            "qpushbutton#secondarybutton:focus",
            "qpushbutton#dangerbutton:hover",
            "qpushbutton#dangerbutton:pressed",
            "qpushbutton#dangerbutton:focus",
        ):
            self.assertIn(selector, qss)

    def test_menus_have_clear_hover_pressed_and_open_states(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        menu_bar_item = re.search(r"qmenubar::item\s*\{(?P<body>[^}]*)\}", qss, flags=re.DOTALL)
        self.assertIsNotNone(menu_bar_item)
        self.assertIn("border-radius", menu_bar_item.group("body"))
        self.assertIn("border:", menu_bar_item.group("body"))

        menu_item = re.search(r"qmenu::item\s*\{(?P<body>[^}]*)\}", qss, flags=re.DOTALL)
        self.assertIsNotNone(menu_item)
        self.assertIn("border:", menu_item.group("body"))
        self.assertIn("border-radius", menu_item.group("body"))

        for selector in (
            "qmenubar::item:selected",
            "qmenubar::item:pressed",
            "qmenubar::item:open",
            "qmenu::item:selected",
            "qmenu::item:pressed",
            "qtoolbar qpushbutton:hover",
            "qtoolbar qpushbutton:pressed",
            "qtoolbar qpushbutton:focus",
        ):
            self.assertIn(selector, qss)

    def test_menus_and_toolbar_avoid_sticky_focus_chrome(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        menu_active_rule = re.search(
            r"qmenubar::item:pressed,\s*qmenubar::item:open\s*\{(?P<body>[^}]*)\}",
            qss,
            flags=re.DOTALL,
        )
        menu_selected_rule = re.search(
            r"qmenubar::item:selected,\s*qtoolbar qpushbutton:hover\s*\{(?P<body>[^}]*)\}",
            qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(menu_active_rule)
        self.assertIsNotNone(menu_selected_rule)
        self.assertNotIn("#094771", menu_active_rule.group("body"))
        self.assertNotIn("#007fd4", menu_selected_rule.group("body"))

        main_window = MainWindow()
        self.addCleanup(main_window.close)

        self.assertEqual(Qt.FocusPolicy.NoFocus, main_window.menuBar().focusPolicy())
        for button in (main_window.topics_btn, main_window.progress_btn, main_window.courses_btn):
            self.assertEqual(Qt.FocusPolicy.NoFocus, button.focusPolicy())

    def test_home_actions_use_dedicated_soft_button_treatment(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        primary_home_rule = re.search(
            r"qpushbutton\[homeaction=\"primary\"\]\s*\{(?P<body>[^}]*)\}",
            qss,
            flags=re.DOTALL,
        )
        secondary_home_rule = re.search(
            r"qpushbutton\[homeaction=\"secondary\"\]\s*\{(?P<body>[^}]*)\}",
            qss,
            flags=re.DOTALL,
        )

        self.assertIsNotNone(primary_home_rule)
        self.assertIsNotNone(secondary_home_rule)
        self.assertRegex(primary_home_rule.group("body"), r"border-radius:\s*(1[4-9]|[2-9][0-9])px")
        self.assertRegex(secondary_home_rule.group("body"), r"border-radius:\s*(1[2-9]|[2-9][0-9])px")

        with tempfile.TemporaryDirectory() as tmpdir:
            home = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            self.assertEqual("primary", home.start_btn.property("homeAction"))
            for button in (home.incorrect_btn, home.ai_btn, home.progress_btn, home.settings_btn):
                self.assertEqual("secondary", button.property("homeAction"))

    def test_fallback_palette_matches_vscode_dark_base(self):
        _apply_dark_palette(_APP)
        palette = _APP.palette()

        self.assertEqual("#1f1f1f", palette.color(QPalette.ColorRole.Window).name())
        self.assertEqual("#cccccc", palette.color(QPalette.ColorRole.WindowText).name())
        self.assertEqual("#313131", palette.color(QPalette.ColorRole.Base).name())
        self.assertEqual("#0078d4", palette.color(QPalette.ColorRole.Highlight).name())

    def test_home_and_settings_buttons_have_semantic_roles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )
            settings = SettingsScreen()

            self.assertEqual("primaryButton", home.start_btn.objectName())
            for button in (home.incorrect_btn, home.ai_btn, home.progress_btn, home.settings_btn):
                self.assertEqual("secondaryButton", button.objectName())
            self.assertEqual("primaryButton", settings.save_btn.objectName())
            for button in (
                settings.test_ai_btn,
                settings.environment_check_btn,
                settings.ocr_fix_btn,
                settings.export_btn,
                settings.import_btn,
                settings.clear_api_key_btn,
            ):
                self.assertEqual("secondaryButton", button.objectName())
            self.assertEqual("dangerButton", settings.reset_progress_btn.objectName())

    def test_course_bank_and_generation_dialog_buttons_have_semantic_roles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            course = CourseScreen(CourseProjectManager(str(Path(tmpdir) / "courses")))
            bank = QuestionBankScreen(QuestionBank(str(Path(tmpdir) / "questions")))
            dialog = AIGenerationDialog(
                "# Course",
                {"ai_provider": "openai", "ai_base_url": "https://api.openai.com/v1", "ai_model": "gpt-4.1-mini"},
                available_topics=["cache"],
            )

            self.assertEqual("primaryButton", course.init_btn.objectName())
            self.assertEqual("dangerButton", course.delete_btn.objectName())
            for button in (course.browse_btn, course.set_current_btn, course.regenerate_btn, course.refresh_btn):
                self.assertEqual("secondaryButton", button.objectName())

            self.assertEqual("primaryButton", bank.save_btn.objectName())
            self.assertEqual("dangerButton", bank.delete_btn.objectName())
            for button in (bank.new_btn, bank.prev_btn, bank.next_btn):
                self.assertEqual("secondaryButton", button.objectName())

            self.assertEqual("primaryButton", dialog.generate_btn.objectName())
            for button in (
                dialog.cancel_btn,
                dialog.select_all_btn,
                dialog.deselect_btn,
                dialog.exam_assistant_btn,
            ):
                self.assertEqual("secondaryButton", button.objectName())

    def test_home_actions_use_a_balanced_two_column_grid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            self.assertIsInstance(home.action_layout, QGridLayout)
            self.assertLessEqual(home.action_frame.maximumWidth(), 640)

            def position(button):
                return home.action_layout.getItemPosition(home.action_layout.indexOf(button))

            self.assertEqual((0, 0, 1, 2), position(home.start_btn))
            self.assertEqual((1, 0, 1, 1), position(home.incorrect_btn))
            self.assertEqual((1, 1, 1, 1), position(home.ai_btn))
            self.assertEqual((2, 0, 1, 1), position(home.progress_btn))
            self.assertEqual((2, 1, 1, 1), position(home.settings_btn))

    def test_settings_content_and_actions_follow_desktop_form_layout(self):
        settings = SettingsScreen()

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
            settings.data_action_layout.indexOf(settings.reset_progress_btn),
        )

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

    def test_quiz_cards_use_soft_baicizhan_style_borders(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        card_rule = re.search(
            r"qframe#questioncard,\s*qframe#reviewcard,\s*qframe#feedbackframe\s*\{(?P<body>[^}]*)\}",
            qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(card_rule)
        self.assertIn("border-radius: 14px", card_rule.group("body"))
        self.assertIn("#4a4a4a", card_rule.group("body"))
        self.assertIn("qframe#feedbackframe", qss)

    def test_answer_inputs_have_themeable_soft_option_roles(self):
        from ui.widgets.answer_area import FillInBlankWidget, MultipleChoiceWidget, ShortAnswerWidget, TrueFalseWidget
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        option_rule = re.search(
            r"q(?:radiobutton|checkbox)#answeroption\s*\{(?P<body>[^}]*)\}",
            qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(option_rule)
        self.assertRegex(option_rule.group("body"), r"border-radius:\s*(1[2-9]|[2-9][0-9])px")
        self.assertIn("border:", option_rule.group("body"))
        for selector in (
            "qradiobutton#answeroption:hover",
            "qcheckbox#answeroption:hover",
            "qradiobutton#answeroption:checked",
            "qcheckbox#answeroption:checked",
            "qradiobutton#answeroption:focus",
            "qcheckbox#answeroption:focus",
        ):
            self.assertIn(selector, qss)

        choices = MultipleChoiceWidget()
        choices.set_options(["A. one", "B. two"])
        self.assertTrue(choices.buttons)
        for button in choices.buttons:
            self.assertEqual("answerOption", button.objectName())

        true_false = TrueFalseWidget()
        self.assertEqual("answerOption", true_false.true_btn.objectName())
        self.assertEqual("answerOption", true_false.false_btn.objectName())

        fill = FillInBlankWidget()
        short = ShortAnswerWidget()
        self.assertEqual("fillInput", fill.input.objectName())
        self.assertEqual("shortAnswerInput", short.editor.objectName())

    def test_quiz_screen_uses_theme_roles_instead_of_inline_styles(self):
        source = Path("ui/screens/quiz_screen.py").read_text(encoding="utf-8")
        self.assertNotIn(".setStyleSheet(", source)

        qss = Path("style.qss").read_text(encoding="utf-8").lower()
        progress_rule = re.search(r"qprogressbar\s*\{(?P<body>[^}]*)\}", qss, flags=re.DOTALL)
        self.assertIsNotNone(progress_rule)
        self.assertRegex(progress_rule.group("body"), r"border-radius:\s*([6-9]|[1-9][0-9])px")
        self.assertIn("qprogressbar::chunk", qss)
        self.assertIn('qlabel#correctindicator[answerstate="correct"]', qss)
        self.assertIn('qlabel#correctindicator[answerstate="incorrect"]', qss)

        with tempfile.TemporaryDirectory() as tmpdir:
            quiz = QuizScreen(
                QuestionBank(str(Path(tmpdir) / "questions")),
                ProgressManager(str(Path(tmpdir) / "progress")),
            )

        self.assertEqual("secondaryButton", quiz.lang_btn.objectName())
        self.assertEqual("secondaryButton", quiz.back_btn.objectName())
        self.assertEqual("secondaryButton", quiz.skip_btn.objectName())
        self.assertEqual("primaryButton", quiz.submit_btn.objectName())
        self.assertEqual("primaryButton", quiz.next_btn.objectName())

    def test_main_flow_pages_use_theme_button_roles(self):
        for path in (
            Path("ui/screens/topic_selection_screen.py"),
            Path("ui/screens/results_screen.py"),
            Path("ui/screens/progress_dashboard.py"),
        ):
            self.assertNotIn(".setStyleSheet(", path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            progress_manager = ProgressManager(str(root / "progress"))
            question_bank = QuestionBank(str(root / "questions"))

            topic = TopicSelectionScreen(SetManager(str(root / "sets")), progress_manager)
            results = ResultsScreen()
            progress = ProgressDashboard(progress_manager, question_bank)
            main_window = MainWindow()
            self.addCleanup(main_window.close)

        self.assertEqual("secondaryButton", topic.back_btn.objectName())
        self.assertEqual("secondaryButton", topic.export_btn.objectName())
        self.assertEqual("secondaryButton", topic.regenerate_btn.objectName())
        self.assertEqual("primaryButton", topic.start_btn.objectName())

        self.assertEqual("primaryButton", results.retry_incorrect_btn.objectName())
        self.assertEqual("secondaryButton", results.retry_all_btn.objectName())
        self.assertEqual("secondaryButton", results.back_btn.objectName())

        self.assertEqual("secondaryButton", progress.refresh_btn.objectName())
        self.assertEqual("dangerButton", progress.reset_btn.objectName())

        for button in (main_window.topics_btn, main_window.progress_btn, main_window.courses_btn):
            self.assertEqual("toolbarButton", button.objectName())

    def test_review_dialog_and_ordering_controls_use_theme_roles(self):
        source = Path("ui/dialogs/question_review_dialog.py").read_text(encoding="utf-8")
        self.assertNotIn(".setStyleSheet(", source)

        question = Question.create_new(
            QuestionType.MULTIPLE_CHOICE,
            Difficulty.MEDIUM,
            {
                "zh": {"stem": "问题？", "options": ["A", "B"], "explanation": "解释"},
                "en": {"stem": "Question?", "options": ["A", "B"], "explanation": "Explanation"},
            },
            "A",
            "general",
        )
        dialog = QuestionReviewDialog([question])
        ordering = OrderingWidget()

        self.assertEqual("secondaryButton", dialog.accept_all_btn.objectName())
        self.assertEqual("dangerButton", dialog.reject_all_btn.objectName())
        self.assertEqual("secondaryButton", dialog.accept_btn.objectName())
        self.assertEqual("dangerButton", dialog.reject_btn.objectName())
        self.assertEqual("secondaryButton", dialog.cancel_btn.objectName())
        self.assertEqual("primaryButton", dialog.save_btn.objectName())

        self.assertEqual("secondaryButton", ordering.up_btn.objectName())
        self.assertEqual("secondaryButton", ordering.down_btn.objectName())


if __name__ == "__main__":
    unittest.main()
