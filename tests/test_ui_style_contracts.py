import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main as main_module

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QCloseEvent, QPalette
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QFormLayout, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QSplitter, QTextEdit, QWidget

from core.language_manager import LanguageManager
from core.background_task_center import BackgroundTaskCenter
from core.current_events import CurrentEventMaterialManager
from core.progress_tracker import ProgressManager
from core.mastery_overrides import MasteryOverrideStore
from core.quiz_snapshot_manager import QuizSnapshotManager
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.past_exam import PastExamManager
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from core.background_task_recovery import generation_plan_from_task_metadata
from ui.application_style import apply_dark_palette as _apply_dark_palette, load_stylesheet
from ui.main_window import MainWindow
from ui.navigation import Route
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

class UiStyleContractTests(unittest.TestCase):
    def test_stylesheet_font_scaling_is_based_on_original_sizes(self):
            from ui.font_scale import scale_stylesheet_font_sizes

            source = "QLabel { font-size: 10px; } QPushButton { font-size: 15px; }"

            self.assertEqual(
                "QLabel { font-size: 12px; } QPushButton { font-size: 18px; }",
                scale_stylesheet_font_sizes(source, "large"),
            )
            self.assertEqual(source, scale_stylesheet_font_sizes(source, "medium"))

    def test_settings_exposes_and_persists_global_font_scale(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                settings_file = Path(tmpdir) / "settings.json"
                with patch("ui.screens.settings_screen.SETTINGS_FILE", str(settings_file)):
                    screen = SettingsScreen()
                    screen.font_scale_combo.setCurrentIndex(
                        screen.font_scale_combo.findData("large")
                    )
                    with patch("ui.screens.settings_screen.apply_font_scale") as apply_scale:
                        screen.save_settings(silent=True)

                saved = __import__("json").loads(settings_file.read_text(encoding="utf-8"))
                self.assertEqual("large", saved["font_scale"])
                apply_scale.assert_called_once_with(QApplication.instance(), "large")

    def test_font_scale_control_follows_display_language(self):
            screen = SettingsScreen()
            previous_language = screen.lang_manager.current
            self.addCleanup(screen.lang_manager.set_language, previous_language)

            screen.lang_manager.set_language("en")

            self.assertEqual("Font size:", screen.font_scale_label.text())
            self.assertEqual(["Small", "Medium", "Large"], [
                screen.font_scale_combo.itemText(index)
                for index in range(screen.font_scale_combo.count())
            ])
            _APP.processEvents()

    def test_editor_fonts_do_not_fall_back_to_legacy_windows_fixedsys(self):
            qss = Path("style.qss").read_text(encoding="utf-8").lower()

            self.assertNotIn("monospace", qss)
            self.assertIn('"courier new"', qss)

            load_stylesheet(_APP)
            for object_name in (
                "pastExamContentPreview",
                "courseSummaryPreview",
                "dialogDetailEditor",
            ):
                editor = QTextEdit()
                editor.setObjectName(object_name)
                editor.ensurePolished()
                self.assertNotEqual("fixedsys", editor.font().family().casefold())
            self.assertIn("qlabel#settingsconnectionstatusok", qss)
            self.assertIn("qlabel#settingsconnectionstatuserror", qss)
            self.assertIn("qlabel#settingsenvironmentstatus", qss)
            self.assertIn('qlabel#settingsenvironmentstatus[envstate="warn"]', qss)
            self.assertIn('qlabel#settingsenvironmentstatus[envstate="fail"]', qss)
            self.assertIn("qlabel#settingssavestatus", qss)
            self.assertIn('qlabel#settingssavestatus[savestate="dirty"]', qss)
            self.assertIn('qlabel#settingssavestatus[savestate="saved"]', qss)
            self.assertIn("qlabel#settingsweightpreview", qss)
            self.assertIn("qwidget#homefocuspanel", qss)
            self.assertIn("qwidget#homecontextpanel", qss)
            self.assertIn("qwidget#homeoverviewpanel", qss)
            self.assertIn("qlabel#hometodayplantitle", qss)
            self.assertIn("qlabel#hometodayplandetail", qss)
            self.assertIn("qlabel#pastexamassignmentstatus", qss)
            self.assertIn("qlabel#pastexammetadata", qss)
            self.assertIn("qlabel#pastexamanalysissummary", qss)
            self.assertIn("qtextedit#pastexamcontentpreview", qss)
            self.assertIn("qlabel#courseremovalimpact", qss)
            self.assertIn("qlabel#secondarytext", qss)
            self.assertIn("qlistwidget#settingsnavlist", qss)
            self.assertIn("qlistwidget#settingsnavlist::item:selected", qss)

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
                for name in (
                    "free_practice_btn",
                    "resume_btn",
                    "incorrect_btn",
                    "ai_btn",
                    "progress_btn",
                    "settings_btn",
                ):
                    self.assertFalse(hasattr(home, name))

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
                for name in (
                    "free_practice_btn",
                    "resume_btn",
                    "incorrect_btn",
                    "ai_btn",
                    "progress_btn",
                    "settings_btn",
                ):
                    self.assertFalse(hasattr(home, name))
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
                bank = QuestionBankScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    course_manager=CourseProjectManager(str(Path(tmpdir) / "courses")),
                )
                dialog = AIGenerationDialog(
                    "# Course",
                    {"ai_provider": "openai", "ai_base_url": "https://api.openai.com/v1", "ai_model": "gpt-4.1-mini"},
                    available_topics=["cache"],
                )

                self.assertEqual("primaryButton", course.init_btn.objectName())
                self.assertEqual("dangerAction", course.delete_action.objectName())
                for button in (
                    course.browse_btn,
                    course.set_current_btn,
                    course.scope_btn,
                    course.more_actions_btn,
                ):
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
                results = ResultsScreen(
                    course_manager=CourseProjectManager(str(root / "courses"))
                )
                progress = ProgressDashboard(
                    progress_manager,
                    question_bank,
                    set_manager=SetManager(str(root / "sets")),
                    mastery_overrides=MasteryOverrideStore(
                        root / "mastery_overrides.json"
                    ),
                    course_manager=CourseProjectManager(str(root / "courses")),
                )
                main_window = MainWindow()

            self.assertEqual("练习模式", topic.free_practice_mode_btn.text())
            self.assertTrue(topic.today_mode_btn.isHidden())
            self.assertEqual("模拟考试", topic.mock_exam_mode_btn.text())
            lang_manager.set_language("en")
            self.assertEqual("Practice Mode", topic.free_practice_mode_btn.text())
            self.assertEqual("Mock Exam", topic.mock_exam_mode_btn.text())
            self.assertEqual("primaryButton", topic.start_btn.objectName())
            self.assertFalse(hasattr(topic, "back_btn"))
            self.assertFalse(hasattr(topic, "rename_btn"))
            self.assertFalse(hasattr(topic, "export_btn"))
            self.assertFalse(hasattr(topic, "regenerate_btn"))
            self.assertNotRegex(topic.start_btn.text(), r"[^\w\s]")

            self.assertEqual("secondaryButton", results.next_action_btn.objectName())
            self.assertEqual("primaryButton", results.retry_incorrect_btn.objectName())
            self.assertEqual("secondaryButton", results.more_practice_btn.objectName())
            self.assertEqual("resultsNextActionLabel", results.next_action_label.objectName())
            self.assertFalse(hasattr(results, "back_btn"))
            self.assertNotRegex(results.retry_incorrect_btn.text(), r"[^\w\s]")
            self.assertNotRegex(results.more_practice_btn.text(), r"[^\w\s]")

            self.assertEqual("secondaryButton", progress.refresh_btn.objectName())
            self.assertEqual("secondaryButton", progress.more_topic_actions_btn.objectName())
            self.assertFalse(hasattr(progress, "reset_btn"))
            self.assertEqual("dashboardRecommendationLabel", progress.recommendation_label.objectName())
            self.assertEqual("dashboardSourceRefsLabel", progress.source_refs_label.objectName())
            self.assertEqual("sourcePanelHeader", progress.source_refs_panel.header_label.objectName())
            self.assertEqual("sourcePanelList", progress.source_refs_panel.source_list.objectName())
            self.assertNotRegex(progress.refresh_btn.text(), r"[^\w\s]")
            self.assertNotRegex(progress.more_topic_actions_btn.text(), r"[^\w\s]")

            qss = Path("style.qss").read_text(encoding="utf-8").lower()
            self.assertIn("qlabel#dashboardrecommendationlabel", qss)
            self.assertIn("qwidget#dashboardsourcerefslabel", qss)
            self.assertIn("qlabel#sourcepanelheader", qss)
            self.assertIn("qlistwidget#sourcepanellist", qss)
            self.assertIn("qlabel#generationpartialrecoverylabel", qss)

            for button in main_window.navigation_buttons():
                self.assertEqual("sidebarNavButton", button.objectName())

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
