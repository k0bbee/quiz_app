import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QCloseEvent, QPalette
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QFormLayout, QGridLayout, QLabel, QListWidget, QPushButton, QSplitter

from core.language_manager import LanguageManager
from core.progress_tracker import ProgressManager
from models.course_project import CourseProjectManager
from models.question import Question, QuestionBank
from models.question_set import SetManager
from main import _apply_dark_palette, load_stylesheet
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
from utils.constants import Difficulty, QuestionType, topic_label


_APP = QApplication.instance() or QApplication([])


class UiThemeTests(unittest.TestCase):
    def tearDown(self):
        """Close stray top-level widgets so PyQt does not crash during process teardown."""
        for widget in QApplication.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        _APP.processEvents()
        _APP.processEvents()

    def test_qss_uses_vscode_dark_tokens_and_top_level_backgrounds(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        for token in (
            "#181818", "#1f1f1f", "#252526", "#313131",
            "#0078d4", "#007fd4", "#cccccc",
        ):
            self.assertIn(token, qss)
        self.assertRegex(qss, r"qdialog[^\{]*\{[^}]*background-color:\s*#1f1f1f")
        self.assertIn("qpushbutton#primarybutton", qss)
        self.assertIn('qpushbutton#secondarybutton[marked="true"]', qss)
        self.assertIn("qlabel#settingsconnectionstatus", qss)
        self.assertIn("qlabel#settingsconnectionstatusok", qss)
        self.assertIn("qlabel#settingsconnectionstatuserror", qss)
        self.assertIn("qlabel#settingsenvironmentstatus", qss)
        self.assertIn('qlabel#settingsenvironmentstatus[envstate="warn"]', qss)
        self.assertIn('qlabel#settingsenvironmentstatus[envstate="fail"]', qss)
        self.assertIn("qlabel#settingssavestatus", qss)
        self.assertIn('qlabel#settingssavestatus[savestate="dirty"]', qss)
        self.assertIn('qlabel#settingssavestatus[savestate="saved"]', qss)
        self.assertIn("qlabel#settingsweightpreview", qss)
        self.assertIn("qlistwidget#settingsnavlist", qss)
        self.assertIn("qlistwidget#settingsnavlist::item:selected", qss)

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

    def test_menus_avoid_sticky_focus_chrome_and_toolbar_has_keyboard_focus_ring(self):
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
        toolbar_focus_rule = re.search(
            r"qtoolbar qpushbutton:focus\s*\{(?P<body>[^}]*)\}",
            qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(toolbar_focus_rule)
        self.assertIn("#007fd4", toolbar_focus_rule.group("body"))
        self.assertNotIn("border-color: transparent", toolbar_focus_rule.group("body"))

        main_window = MainWindow()
        self.addCleanup(main_window.close)

        self.assertEqual(Qt.FocusPolicy.NoFocus, main_window.menuBar().focusPolicy())
        for button in main_window.navigation_buttons():
            self.assertEqual(Qt.FocusPolicy.TabFocus, button.focusPolicy())

    def test_main_navigation_uses_top_text_toolbar_with_semantic_groups_and_no_exit_entry(self):
        main_window = MainWindow()
        self.addCleanup(main_window.close)
        self.addCleanup(main_window.lang_manager.set_language, "zh")
        main_window.lang_manager.set_language("en")

        self.assertEqual(
            Qt.ToolBarArea.TopToolBarArea,
            main_window.toolBarArea(main_window.toolbar),
        )
        self.assertFalse(hasattr(main_window, "exit_action"))
        self.assertEqual([], main_window.menuBar().actions())
        for legacy_attr in (
            "tools_menu",
            "help_menu",
            "topics_action",
            "progress_action",
            "settings_action",
            "courses_action",
            "bank_action",
            "about_action",
        ):
            self.assertFalse(hasattr(main_window, legacy_attr), legacy_attr)

        buttons = main_window.navigation_buttons()
        self.assertEqual(
            ["Back", "Home", "Question Sets", "Progress", "Courses", "Question Bank", "Settings", "About"],
            [button.text() for button in buttons],
        )
        self.assertEqual(
            ["navigation", "navigation", "practice", "practice", "management", "management", "management", "support"],
            [button.property("navGroup") for button in buttons],
        )
        self.assertGreaterEqual(
            sum(1 for action in main_window.toolbar.actions() if action.isSeparator()),
            2,
        )
        for button in buttons:
            self.assertNotRegex(button.text(), r"[^\w\s]")

        self.assertFalse(main_window.nav_back_btn.isEnabled())

        main_window.navigate_to(main_window.SCREEN_PROGRESS)
        self.assertTrue(main_window.nav_back_btn.isEnabled())

        main_window.nav_back_btn.click()
        self.assertEqual(main_window.SCREEN_HOME, main_window.stack.currentIndex())
        self.assertFalse(main_window.nav_back_btn.isEnabled())

        main_window.navigate_to(main_window.SCREEN_SETTINGS)
        main_window.nav_home_btn.click()
        self.assertEqual(main_window.SCREEN_HOME, main_window.stack.currentIndex())

    def test_top_navigation_confirms_before_leaving_active_quiz(self):
        main_window = MainWindow()
        self.addCleanup(main_window.close)
        main_window.stack.setCurrentIndex(main_window.SCREEN_QUIZ)
        main_window.quiz_screen.confirm_exit = Mock(return_value=False)

        main_window.navigate_to(main_window.SCREEN_SETTINGS)

        main_window.quiz_screen.confirm_exit.assert_called_once()
        self.assertEqual(main_window.SCREEN_QUIZ, main_window.stack.currentIndex())

        main_window.quiz_screen.confirm_exit.reset_mock()
        main_window.quiz_screen.confirm_exit.return_value = True

        main_window.navigate_to(main_window.SCREEN_SETTINGS)

        main_window.quiz_screen.confirm_exit.assert_called_once()
        self.assertEqual(main_window.SCREEN_SETTINGS, main_window.stack.currentIndex())

    def test_close_event_confirms_before_closing_active_quiz(self):
        main_window = MainWindow()
        self.addCleanup(main_window.deleteLater)
        main_window.stack.setCurrentIndex(main_window.SCREEN_QUIZ)
        main_window.quiz_screen.confirm_exit = Mock(return_value=False)
        main_window.settings_screen.save_settings = Mock()

        blocked_event = QCloseEvent()
        main_window.closeEvent(blocked_event)

        main_window.quiz_screen.confirm_exit.assert_called_once()
        self.assertFalse(blocked_event.isAccepted())
        main_window.settings_screen.save_settings.assert_not_called()

        main_window.quiz_screen.confirm_exit.reset_mock()
        main_window.quiz_screen.confirm_exit.return_value = True
        accepted_event = QCloseEvent()

        main_window.closeEvent(accepted_event)

        main_window.quiz_screen.confirm_exit.assert_called_once()
        self.assertTrue(accepted_event.isAccepted())
        main_window.settings_screen.save_settings.assert_called_once_with(silent=True)

    def test_semantic_action_buttons_keep_tab_focus_without_mouse_focus(self):
        load_stylesheet(_APP)

        primary = QPushButton("Primary")
        primary.setObjectName("primaryButton")
        secondary = QPushButton("Secondary")
        secondary.setObjectName("secondaryButton")
        danger = QPushButton("Danger")
        danger.setObjectName("dangerButton")
        toolbar = QPushButton("Toolbar")
        toolbar.setObjectName("toolbarButton")

        _APP.processEvents()

        for button in (primary, secondary, danger):
            self.assertEqual(Qt.FocusPolicy.TabFocus, button.focusPolicy())
        self.assertEqual(Qt.FocusPolicy.TabFocus, toolbar.focusPolicy())

    def test_load_stylesheet_returns_applied_qss_text(self):
        qss = load_stylesheet(_APP)

        self.assertIsInstance(qss, str)
        self.assertIn("QPushButton", qss)
        self.assertEqual(qss, _APP.styleSheet())

    def test_enabled_buttons_use_hand_cursor_and_disabled_buttons_use_arrow_cursor(self):
        load_stylesheet(_APP)

        button = QPushButton("Action")
        button.setObjectName("secondaryButton")
        button.show()
        _APP.processEvents()

        self.assertEqual(Qt.CursorShape.PointingHandCursor, button.cursor().shape())

        button.setEnabled(False)
        _APP.processEvents()

        self.assertEqual(Qt.CursorShape.ArrowCursor, button.cursor().shape())

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
            for button in (home.resume_btn, home.incorrect_btn, home.ai_btn, home.progress_btn, home.settings_btn):
                self.assertEqual("secondary", button.property("homeAction"))

    def test_home_incorrect_action_stays_clickable_when_no_incorrect_questions_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            home.refresh()

            self.assertTrue(home.incorrect_btn.isEnabled())
            self.assertEqual("true", home.incorrect_btn.property("emptyState"))

    def test_home_actions_have_dedicated_hover_pressed_and_focus_feedback(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        for selector in (
            'qpushbutton[homeaction="primary"]:hover',
            'qpushbutton[homeaction="primary"]:pressed',
            'qpushbutton[homeaction="primary"]:focus',
            'qpushbutton[homeaction="secondary"]:hover',
            'qpushbutton[homeaction="secondary"]:pressed',
            'qpushbutton[homeaction="secondary"]:focus',
        ):
            self.assertIn(selector, qss)

        primary_pressed = re.search(
            r'qpushbutton\[homeaction="primary"\]:pressed\s*\{(?P<body>[^}]*)\}',
            qss,
            flags=re.DOTALL,
        )
        secondary_pressed = re.search(
            r'qpushbutton\[homeaction="secondary"\]:pressed\s*\{(?P<body>[^}]*)\}',
            qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(primary_pressed)
        self.assertIsNotNone(secondary_pressed)
        for body in (primary_pressed.group("body"), secondary_pressed.group("body")):
            self.assertIn("padding-top", body)
            self.assertIn("padding-bottom", body)
            self.assertIn("border-color", body)

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
            for button in (home.resume_btn, home.incorrect_btn, home.ai_btn, home.progress_btn, home.settings_btn):
                self.assertEqual("secondaryButton", button.objectName())
            self.assertEqual("primaryButton", settings.save_btn.objectName())
            for button in (
                settings.test_ai_btn,
                settings.environment_check_btn,
                settings.ocr_fix_btn,
                settings.export_btn,
                settings.import_btn,
                settings.export_app_data_btn,
                settings.import_app_data_btn,
                settings.refresh_default_weight_preview_btn,
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
            for button in (course.browse_btn, course.set_current_btn, course.rename_btn, course.regenerate_btn, course.refresh_btn):
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
            self.assertEqual((1, 0, 1, 2), position(home.resume_btn))
            self.assertEqual((2, 0, 1, 1), position(home.incorrect_btn))
            self.assertEqual((2, 1, 1, 1), position(home.ai_btn))
            self.assertEqual((3, 0, 1, 1), position(home.progress_btn))
            self.assertEqual((3, 1, 1, 1), position(home.settings_btn))

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
            ["显示语言", "AI 出题", "练习默认值", "运行环境", "数据管理"],
            nav_labels,
        )
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

    def test_quiz_cards_use_soft_baicizhan_style_borders(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        card_rule = re.search(
            r"qframe#quizpreviewpane,\s*qframe#quizpracticecard,\s*qframe#questioncard,\s*qframe#reviewcard,\s*qframe#feedbackframe\s*\{(?P<body>[^}]*)\}",
            qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(card_rule)
        self.assertRegex(card_rule.group("body"), r"border-radius:\s*(1[6-9]|[2-9][0-9])px")
        self.assertIn("#4a4a4a", card_rule.group("body"))
        self.assertIn("qframe#quizpreviewpane", qss)
        self.assertIn("qframe#feedbackframe", qss)

    def test_quiz_screen_uses_horizontal_practice_workspace_with_review_hidden_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            quiz = QuizScreen(
                QuestionBank(str(Path(tmpdir) / "questions")),
                ProgressManager(str(Path(tmpdir) / "progress")),
            )

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
        self.assertNotIn(".setStyleSheet(", Path("ui/widgets/answer_area.py").read_text(encoding="utf-8"))

        qss = Path("style.qss").read_text(encoding="utf-8").lower()
        progress_rule = re.search(r"qprogressbar\s*\{(?P<body>[^}]*)\}", qss, flags=re.DOTALL)
        self.assertIsNotNone(progress_rule)
        self.assertRegex(progress_rule.group("body"), r"border-radius:\s*([6-9]|[1-9][0-9])px")
        self.assertIn("qprogressbar::chunk", qss)
        self.assertIn('qlabel#correctindicator[answerstate="correct"]', qss)
        self.assertIn('qlabel#correctindicator[answerstate="incorrect"]', qss)
        self.assertIn("qlabel#quizshortcuthint", qss)

        with tempfile.TemporaryDirectory() as tmpdir:
            quiz = QuizScreen(
                QuestionBank(str(Path(tmpdir) / "questions")),
                ProgressManager(str(Path(tmpdir) / "progress")),
            )

        self.assertEqual("secondaryButton", quiz.lang_btn.objectName())
        self.assertIsInstance(quiz.uncertain_checkbox, QCheckBox)
        self.assertEqual("quizUncertainCheck", quiz.uncertain_checkbox.objectName())
        self.assertIsInstance(quiz.review_checkbox, QCheckBox)
        self.assertEqual("quizReviewCheck", quiz.review_checkbox.objectName())
        self.assertEqual("secondaryButton", quiz.prev_question_btn.objectName())
        self.assertEqual("primaryButton", quiz.next_question_btn.objectName())
        self.assertFalse(hasattr(quiz, "back_btn"))
        self.assertFalse(hasattr(quiz, "skip_btn"))
        self.assertFalse(hasattr(quiz, "submit_btn"))
        self.assertFalse(hasattr(quiz, "mark_review_btn"))
        self.assertFalse(hasattr(quiz, "unsure_btn"))
        self.assertEqual("不确定", quiz.uncertain_checkbox.text())
        self.assertEqual("复查", quiz.review_checkbox.text())
        self.assertEqual("上一题", quiz.prev_question_btn.text())
        self.assertEqual("下一题", quiz.next_question_btn.text())
        self.assertEqual("quizShortcutHint", quiz.shortcut_hint_label.objectName())
        self.assertIn("1-9", quiz.shortcut_hint_label.text())
        self.assertIn("Enter", quiz.shortcut_hint_label.text())
        self.assertIn("结果页", quiz.uncertain_checkbox.toolTip())
        self.assertIn("交卷后", quiz.review_checkbox.toolTip())
        self.assertNotRegex(quiz.uncertain_checkbox.text(), r"[^\w\s]")
        self.assertNotRegex(quiz.review_checkbox.text(), r"[^\w\s]")
        self.assertNotRegex(quiz.prev_question_btn.text(), r"[^\w\s]")
        self.assertNotRegex(quiz.next_question_btn.text(), r"[^\w\s]")

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

            lang_manager = LanguageManager.instance()
            previous_lang = lang_manager.current
            lang_manager.set_language("zh")
            self.addCleanup(lang_manager.set_language, previous_lang)

            topic = TopicSelectionScreen(SetManager(str(root / "sets")), progress_manager)
            results = ResultsScreen()
            progress = ProgressDashboard(progress_manager, question_bank)
            main_window = MainWindow()
            self.addCleanup(main_window.close)

        self.assertEqual("secondaryButton", topic.export_btn.objectName())
        self.assertEqual("secondaryButton", topic.regenerate_btn.objectName())
        self.assertEqual("导出模拟卷", topic.export_btn.text())
        self.assertEqual("重新生成题目", topic.regenerate_btn.text())
        lang_manager.set_language("en")
        self.assertEqual("Export Mock Exam", topic.export_btn.text())
        self.assertEqual("Regenerate Questions", topic.regenerate_btn.text())
        self.assertEqual("secondaryButton", topic.rename_btn.objectName())
        self.assertEqual("primaryButton", topic.start_btn.objectName())
        self.assertFalse(hasattr(topic, "back_btn"))
        self.assertNotRegex(topic.rename_btn.text(), r"[^\w\s]")
        self.assertNotRegex(topic.start_btn.text(), r"[^\w\s]")

        self.assertEqual("primaryButton", results.retry_incorrect_btn.objectName())
        self.assertEqual("secondaryButton", results.retry_unsure_btn.objectName())
        self.assertEqual("secondaryButton", results.retry_all_btn.objectName())
        self.assertEqual("resultsNextActionLabel", results.next_action_label.objectName())
        self.assertFalse(hasattr(results, "back_btn"))
        self.assertNotRegex(results.retry_incorrect_btn.text(), r"[^\w\s]")
        self.assertNotRegex(results.retry_unsure_btn.text(), r"[^\w\s]")
        self.assertNotRegex(results.retry_all_btn.text(), r"[^\w\s]")

        self.assertEqual("secondaryButton", progress.refresh_btn.objectName())
        self.assertEqual("secondaryButton", progress.mark_mastered_btn.objectName())
        self.assertEqual("dangerButton", progress.reset_btn.objectName())
        self.assertEqual("dashboardRecommendationLabel", progress.recommendation_label.objectName())
        self.assertEqual("dashboardSourceRefsLabel", progress.source_refs_label.objectName())
        self.assertNotRegex(progress.refresh_btn.text(), r"[^\w\s]")
        self.assertNotRegex(progress.mark_mastered_btn.text(), r"[^\w\s]")
        self.assertNotRegex(progress.reset_btn.text(), r"[^\w\s]")

        qss = Path("style.qss").read_text(encoding="utf-8").lower()
        self.assertIn("qlabel#dashboardrecommendationlabel", qss)
        self.assertIn("qlabel#dashboardsourcerefslabel", qss)
        self.assertIn("qlabel#generationpartialrecoverylabel", qss)

        for button in (main_window.topics_btn, main_window.progress_btn, main_window.courses_btn):
            self.assertEqual("toolbarButton", button.objectName())

    def test_review_dialog_and_ordering_controls_use_theme_roles(self):
        source = Path("ui/dialogs/question_review_dialog.py").read_text(encoding="utf-8")
        self.assertNotIn(".setStyleSheet(", source)
        self.assertNotIn(".setStyleSheet(", Path("ui/widgets/question_review_card.py").read_text(encoding="utf-8"))

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
        for button in (
            dialog.accept_all_btn,
            dialog.reject_all_btn,
            dialog.accept_btn,
            dialog.reject_btn,
            ordering.up_btn,
            ordering.down_btn,
        ):
            self.assertNotRegex(button.text(), r"[^\w\s]")

    def test_course_and_matching_widgets_use_theme_roles(self):
        self.assertNotIn(".setStyleSheet(", Path("ui/screens/course_screen.py").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmpdir:
            course = CourseScreen(CourseProjectManager(str(Path(tmpdir) / "courses")))
        self.assertEqual("courseSummaryLabel", course.summary_label.objectName())

        from ui.widgets.answer_area import MatchingWidget

        matching = MatchingWidget()
        matching.set_options({"left": ["CPU"], "right": ["processor"]})

        self.assertEqual("matchingLeftList", matching.left_list.objectName())
        self.assertEqual("matchingLeftItem", matching.left_item_labels[0].objectName())
        self.assertEqual("matchingCombo", matching.combos[0].objectName())

        qss = Path("style.qss").read_text(encoding="utf-8").lower()
        for selector in (
            "qlabel#coursesummarylabel",
            "qlabel#reviewindexlabel",
            "qlistwidget#matchingleftlist",
            "qlabel#matchingleftitem",
            "qcombobox#matchingcombo",
        ):
            self.assertIn(selector, qss)


if __name__ == "__main__":
    unittest.main()
