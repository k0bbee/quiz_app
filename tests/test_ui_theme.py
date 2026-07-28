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
from models.question_set import SetManager
from core.background_task_recovery import generation_plan_from_task_metadata
from ui.application_style import apply_dark_palette as _apply_dark_palette, load_stylesheet
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
    def test_default_main_window_uses_isolated_services_during_qt_tests(self):
        from config import QUESTIONS_DIR

        window = MainWindow()
        self.addCleanup(window.close)

        self.assertNotEqual(
            Path(QUESTIONS_DIR).resolve(),
            Path(window.question_bank.directory).resolve(),
        )

    def test_main_window_uses_injected_application_services(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            services = SimpleNamespace(
                question_bank=QuestionBank(str(root / "questions")),
                set_manager=SetManager(str(root / "sets")),
                progress_manager=ProgressManager(str(root / "progress")),
                snapshot_manager=QuizSnapshotManager(str(root / "snapshots")),
                mastery_overrides=MasteryOverrideStore(root / "mastery.json"),
                course_manager=CourseProjectManager(str(root / "courses")),
                past_exam_manager=PastExamManager(root / "past-exams"),
                current_event_manager=CurrentEventMaterialManager(
                    root / "current-event-materials"
                ),
                task_center=BackgroundTaskCenter(root / "tasks.json"),
            )

            window = MainWindow(services=services)

            self.assertIs(services.question_bank, window.question_bank)
            self.assertIs(services.course_manager, window.course_manager)
            self.assertIs(
                services.current_event_manager,
                window.current_event_manager,
            )
            self.assertIs(services.task_center, window.task_center)
            self.assertIs(services.set_manager, window.progress_screen.set_manager)

    def test_main_window_lazy_loads_management_workspaces_at_stable_routes(self):
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertIsNone(window._course_screen)
        self.assertIsNone(window._question_bank_screen)
        self.assertIsNone(window._past_exam_screen)
        self.assertEqual(8, window.stack.count())

        self.assertTrue(window.navigate_to(window.SCREEN_QUESTION_BANK))
        self.assertEqual(window.SCREEN_QUESTION_BANK, window.stack.currentIndex())
        self.assertIsNone(window._course_screen)
        self.assertIsNotNone(window._question_bank_screen)
        self.assertIsNone(window._past_exam_screen)

        self.assertTrue(window.navigate_to(window.SCREEN_PAST_EXAMS))
        self.assertEqual(window.SCREEN_PAST_EXAMS, window.stack.currentIndex())
        self.assertIsNone(window._course_screen)
        self.assertIsNotNone(window._past_exam_screen)

    def test_stylesheet_font_scaling_is_based_on_original_sizes(self):
        from ui.font_scale import scale_stylesheet_font_sizes

        source = "QLabel { font-size: 10px; } QPushButton { font-size: 15px; }"

        self.assertEqual(
            "QLabel { font-size: 12px; } QPushButton { font-size: 18px; }",
            scale_stylesheet_font_sizes(source, "large"),
        )
        self.assertEqual(source, scale_stylesheet_font_sizes(source, "medium"))

    def test_main_reads_startup_settings_through_supported_json_api(self):
        app = Mock()
        app.exec.return_value = 0

        def read_settings(filepath):
            self.assertEqual(main_module.SETTINGS_FILE, filepath)
            return {"font_scale": "large"}

        with patch.object(main_module, "QApplication", return_value=app), \
                patch.object(main_module, "MainWindow") as window_type, \
                patch.object(main_module, "read_json", side_effect=read_settings), \
                patch.object(main_module, "load_stylesheet") as load_theme:
            with self.assertRaisesRegex(SystemExit, "0"):
                main_module.main()

        load_theme.assert_called_once_with(app, font_scale="large")
        window_type.return_value.show.assert_called_once_with()

    def test_main_runs_data_migration_before_constructing_window(self):
        app = Mock()
        app.exec.return_value = 0
        services = object()
        report = object()
        events = []

        with patch.object(main_module, "QApplication", return_value=app), \
                patch.object(
                    main_module.ApplicationServices,
                    "default",
                    side_effect=lambda: events.append("services") or services,
                ), \
                patch.object(main_module, "ApplicationDataMigrator") as migrator_type, \
                patch.object(main_module, "MainWindow") as window_type, \
                patch.object(main_module, "read_json", return_value={}), \
                patch.object(main_module, "load_stylesheet"):
            migrator_type.return_value.migrate.side_effect = (
                lambda: events.append("migration") or report
            )
            window_type.side_effect = (
                lambda **_kwargs: events.append("window") or Mock()
            )

            with self.assertRaisesRegex(SystemExit, "0"):
                main_module.main()

        self.assertEqual(["services", "migration", "window"], events)
        migrator_type.assert_called_once_with(services)
        window_type.assert_called_once_with(
            services=services,
            startup_migration_report=report,
        )

    def test_failed_startup_migration_blocks_history_sensitive_workflows(self):
        report = SimpleNamespace(
            has_failures=True,
            failed_progress_ids=("legacy-progress",),
            errors=("legacy-progress: permission denied",),
        )
        with patch("ui.main_window.QTimer.singleShot"):
            window = MainWindow(startup_migration_report=report)
        self.addCleanup(window.close)

        with patch(
            "ui.main_window.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Cancel,
        ):
            self.assertFalse(window.navigate_to(window.SCREEN_COURSES))

        self.assertEqual(window.SCREEN_HOME, window.stack.currentIndex())
        self.assertTrue(window.navigate_to(window.SCREEN_PROGRESS))
        self.assertFalse(window.settings_screen.import_btn.isEnabled())
        self.assertFalse(window.settings_screen.import_app_data_btn.isEnabled())
        self.assertFalse(window.settings_screen.reset_progress_btn.isEnabled())
        self.assertTrue(window.settings_screen.export_btn.isEnabled())
        self.assertTrue(window.settings_screen.export_app_data_btn.isEnabled())

    def test_successful_migration_retry_reopens_history_sensitive_workflows(self):
        failed_report = SimpleNamespace(
            has_failures=True,
            failed_progress_ids=("legacy-progress",),
            errors=("legacy-progress: permission denied",),
        )
        success_report = SimpleNamespace(
            has_failures=False,
            failed_progress_ids=(),
            errors=(),
        )
        with patch("ui.main_window.QTimer.singleShot"):
            window = MainWindow(startup_migration_report=failed_report)
        self.addCleanup(window.close)

        with patch(
            "core.application_data_migration.ApplicationDataMigrator.migrate",
            return_value=success_report,
        ), patch("ui.main_window.QMessageBox.information"):
            self.assertTrue(window._retry_startup_migration())

        self.assertTrue(window.settings_screen.import_btn.isEnabled())
        self.assertTrue(window.settings_screen.import_app_data_btn.isEnabled())
        self.assertTrue(window.settings_screen.reset_progress_btn.isEnabled())
        self.assertTrue(window.navigate_to(window.SCREEN_COURSES))

    def test_history_protection_blocks_direct_progress_import_handler(self):
        screen = SettingsScreen()
        screen.set_history_protection_blocked(
            True,
            "Legacy history protection is incomplete.",
        )

        with patch(
            "ui.screens.settings_screen.QFileDialog.getOpenFileName"
        ) as choose_file, patch(
            "ui.screens.settings_screen.QMessageBox.warning"
        ) as warning:
            screen._import_progress()

        choose_file.assert_not_called()
        warning.assert_called_once()

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

    def test_main_navigation_uses_left_workspaces_and_context_tabs(self):
        main_window = MainWindow()
        self.addCleanup(main_window.close)
        self.addCleanup(main_window.lang_manager.set_language, "zh")
        main_window.lang_manager.set_language("en")

        self.assertEqual("AppShell", type(main_window.centralWidget()).__name__)
        self.assertEqual(
            "NavigationRouter",
            type(getattr(main_window, "navigation_router", None)).__name__,
        )
        self.assertFalse(hasattr(main_window, "toolbar"))
        self.assertEqual("applicationSidebar", main_window.navigation_sidebar.objectName())
        self.assertGreaterEqual(main_window.navigation_sidebar.minimumWidth(), 156)
        self.assertLessEqual(main_window.navigation_sidebar.maximumWidth(), 220)
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
            ["Study", "Courses", "Question Bank"],
            [button.text() for button in buttons],
        )
        self.assertEqual(
            ["learning", "courses", "library"],
            [button.property("workspace") for button in buttons],
        )
        self.assertFalse(hasattr(main_window, "home_nav_btn"))
        for button in buttons:
            self.assertNotRegex(button.text(), r"[^\w\s]")
            self.assertTrue(button.isCheckable())
            self.assertEqual(Qt.FocusPolicy.TabFocus, button.focusPolicy())
        self.assertEqual(Qt.FocusPolicy.NoFocus, main_window.menuBar().focusPolicy())
        self.assertEqual("Settings", main_window.settings_nav_btn.text())
        self.assertEqual("settings", main_window.settings_nav_btn.property("workspace"))
        self.assertFalse(main_window.settings_nav_btn.isCheckable())
        self.assertEqual("sidebarUtilityButton", main_window.task_center_btn.objectName())
        self.assertEqual("tasks", main_window.task_center_btn.property("workspace"))
        self.assertIs(main_window.navigation_sidebar, main_window.task_center_btn.parent())

        self.assertTrue(main_window.learning_nav_btn.isChecked())
        self.assertEqual("Study", main_window.context_title.text())
        self.assertFalse(main_window.context_back_btn.isVisible())
        self.assertTrue(main_window.home_screen.question_context_label.text())

        main_window.navigate_to(main_window.SCREEN_PROGRESS)
        self.assertTrue(main_window.learning_nav_btn.isChecked())
        self.assertEqual(["Question Sets", "Progress"], [button.text() for button in main_window.context_tabs()])
        self.assertTrue(main_window.progress_tab_btn.isChecked())
        self.assertFalse(main_window.incorrect_review_btn.isHidden())
        self.assertEqual("Review Incorrect", main_window.incorrect_review_btn.text())
        self.assertFalse(main_window.context_back_btn.isVisible())

        main_window.learning_nav_btn.click()
        self.assertEqual(main_window.SCREEN_HOME, main_window.stack.currentIndex())

        main_window.library_nav_btn.click()
        self.assertEqual(main_window.SCREEN_QUESTION_BANK, main_window.stack.currentIndex())
        self.assertEqual(["Question Bank", "Historical Exams"], [button.text() for button in main_window.context_tabs()])
        main_window.past_exams_tab_btn.click()
        self.assertEqual(main_window.SCREEN_PAST_EXAMS, main_window.stack.currentIndex())
        self.assertIs(main_window.past_exam_manager, main_window._past_exam_screen.manager)
        self.assertIs(main_window.course_manager, main_window._past_exam_screen.course_manager)

        main_window.navigate_to(main_window.SCREEN_PROGRESS)
        current_screen = main_window.stack.currentIndex()

        main_window.settings_nav_btn.click()
        _APP.processEvents()

        self.assertEqual(current_screen, main_window.stack.currentIndex())
        self.assertTrue(main_window.learning_nav_btn.isChecked())
        self.assertFalse(main_window.settings_nav_btn.isCheckable())
        self.assertEqual("sidebarUtilityButton", main_window.settings_nav_btn.objectName())
        self.assertTrue(main_window.settings_window.isVisible())
        self.assertFalse(hasattr(main_window, "SCREEN_SETTINGS"))

        main_window.settings_window.close()
        main_window.navigate_to(main_window.SCREEN_QUIZ)
        main_window.quiz_screen.confirm_exit = Mock(return_value=False)

        main_window.settings_nav_btn.click()
        _APP.processEvents()

        main_window.quiz_screen.confirm_exit.assert_not_called()
        self.assertEqual(main_window.SCREEN_QUIZ, main_window.stack.currentIndex())
        self.assertTrue(main_window.settings_window.isVisible())

    def test_main_window_routes_context_actions_to_existing_flows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            center = BackgroundTaskCenter(Path(tmpdir) / "generation-tasks.json")
            task = center.create(kind="question_generation", title="Generate questions")
            center.fail(task.task_id, "provider timeout")
            generate_patch = patch.object(MainWindow, "_on_ai_generate")
            generate = generate_patch.start()
            self.addCleanup(generate_patch.stop)
            main_window = MainWindow()
            self.addCleanup(main_window.close)
            self.addCleanup(main_window.lang_manager.set_language, "zh")
            main_window.task_center = center
            main_window.lang_manager.set_language("en")

            main_window._refresh_task_center_action()

            self.assertFalse(main_window.task_center_btn.isHidden())
            self.assertEqual("Tasks 1", main_window.task_center_btn.text())
            with patch("ui.main_window.BackgroundTaskDialog") as dialog_type:
                main_window.task_center_btn.click()
            dialog_type.assert_called_once_with(
                center,
                language="en",
                parent=main_window,
            )
            dialog_type.return_value.exec.assert_called_once_with()

            import_center = BackgroundTaskCenter(Path(tmpdir) / "import-tasks.json")
            import_task = import_center.create(
                kind="course_import",
                title="Import Physics",
                metadata={
                    "source_folder": "C:/courses/physics",
                    "course_title": "Physics",
                },
            )
            import_center.fail(import_task.task_id, "application closed")
            main_window.task_center = import_center
            main_window.task_recovery.task_center = import_center

            reopened = main_window.task_recovery.restore(import_task.task_id)

            self.assertTrue(reopened)
            self.assertEqual(main_window.SCREEN_COURSES, main_window.stack.currentIndex())
            self.assertEqual("C:/courses/physics", main_window._course_screen.folder_input.text())
            self.assertEqual("Physics", main_window._course_screen.title_input.text())
            self.assertFalse(main_window._course_screen.import_group.isHidden())

            prediction_handler = Mock()
            main_window._on_generate_predicted_exam = prediction_handler
            prediction = object()
            main_window._get_past_exam_screen().prediction_requested.emit(
                "course-a",
                prediction,
            )
            prediction_handler.assert_called_once_with("course-a", prediction)

            main_window._get_course_screen().generate_questions_requested.emit(
                "course-a"
            )
            generate.assert_called_once_with()

    def test_generation_task_recovery_rebuilds_the_confirmed_exam_plan(self):
        metadata = {
            "requested_count": 12,
            "topic_ids": ["cache"],
            "exam_plan": {
                "question_count": 12,
                "difficulty": "mixed",
                "template": "final_exam",
                "selected_topics": ["cache"],
                "question_type_weights": {
                    "multiple_choice": 50,
                    "scenario_choice": 20,
                    "true_false": 10,
                    "fill_in_blank": 10,
                    "matching": 5,
                    "ordering": 5,
                    "short_answer": 0,
                },
                "difficulty_weights": {"easy": 20, "medium": 50, "hard": 30},
                "topic_weights": {"cache": 100},
            },
        }

        plan = generation_plan_from_task_metadata(metadata)

        self.assertEqual(12, plan.question_count)
        self.assertEqual("mixed", plan.difficulty)
        self.assertEqual("final_exam", plan.template)
        self.assertEqual(("cache",), plan.selected_topics)
        self.assertEqual(50, plan.question_type_weights["multiple_choice"])
        self.assertEqual(100, plan.topic_weights["cache"])

    def test_focus_mode_navigation_guards_active_quiz_and_restores_shell(self):
        main_window = MainWindow()
        self.addCleanup(main_window.close)
        main_window.quiz_screen.confirm_exit = Mock(return_value=False)

        main_window.navigate_to(main_window.SCREEN_QUIZ)
        self.assertTrue(main_window.navigation_sidebar.isHidden())
        self.assertFalse(main_window.context_header.isHidden())
        self.assertFalse(main_window.context_back_btn.isHidden())

        main_window.navigate_to(main_window.SCREEN_HOME)

        main_window.quiz_screen.confirm_exit.assert_called_once()
        self.assertEqual(main_window.SCREEN_QUIZ, main_window.stack.currentIndex())

        main_window.quiz_screen.confirm_exit.reset_mock()
        main_window.quiz_screen.confirm_exit.return_value = True

        main_window.navigate_to(main_window.SCREEN_HOME)

        main_window.quiz_screen.confirm_exit.assert_called_once()
        self.assertEqual(main_window.SCREEN_HOME, main_window.stack.currentIndex())
        self.assertFalse(main_window.navigation_sidebar.isHidden())
        self.assertTrue(main_window.context_back_btn.isHidden())

        main_window.navigate_to(main_window.SCREEN_QUIZ)
        self.assertTrue(main_window.navigation_sidebar.isHidden())

        main_window.navigate_to(main_window.SCREEN_RESULTS, confirm_current=False)
        self.assertTrue(main_window.navigation_sidebar.isHidden())

        main_window.navigate_to(main_window.SCREEN_HOME, confirm_current=False)
        self.assertFalse(main_window.navigation_sidebar.isHidden())
        self.assertTrue(main_window.context_back_btn.isHidden())

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

    def test_close_event_waits_for_course_worker_shutdown_without_blocking(self):
        main_window = MainWindow()
        self.addCleanup(main_window.deleteLater)
        main_window.settings_screen.save_settings = Mock()
        course_screen = main_window._get_course_screen()
        course_screen.request_shutdown = Mock(return_value=False)
        event = QCloseEvent()

        main_window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        course_screen.request_shutdown.assert_called_once_with()
        main_window.settings_screen.save_settings.assert_not_called()

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
            for button in (
                home.free_practice_btn,
                home.resume_btn,
                home.incorrect_btn,
                home.ai_btn,
                home.progress_btn,
                home.settings_btn,
            ):
                self.assertEqual("secondary", button.property("homeAction"))

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

    def test_home_incorrect_action_stays_clickable_when_no_incorrect_questions_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            home.refresh()

            self.assertTrue(home.incorrect_btn.isEnabled())
            self.assertEqual("true", home.incorrect_btn.property("emptyState"))

    def test_home_screen_uses_today_plan_as_first_use_guidance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            home.refresh()

            self.assertTrue(home.first_use_label.isHidden())
            self.assertIn("导入", home.start_btn.text())
            self.assertIn("导入课件", home.today_plan_detail.text())
            self.assertFalse(home.stats_label.isHidden())
            self.assertIn("尚无练习记录", home.stats_label.text())

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
            for button in (
                home.free_practice_btn,
                home.resume_btn,
                home.incorrect_btn,
                home.ai_btn,
                home.progress_btn,
                home.settings_btn,
            ):
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

    def test_course_workspace_prioritizes_current_course_generation(self):
        project = CourseProject(
            course_id="course-a",
            title="Physics",
            source_folder="",
            summary_markdown="# Mechanics\n\nNewton's laws",
            summary_path="",
            topics=[CourseTopic(topic_id="mechanics", title="Mechanics")],
            documents=[],
            created_at="2026-07-16T00:00:00+00:00",
            updated_at="2026-07-16T00:00:00+00:00",
        )

        class Manager:
            def current(self):
                return project

            def load_all(self):
                return [project]

            def get(self, course_id):
                return project if course_id == project.course_id else None

        screen = CourseScreen(Manager())

        self.assertTrue(screen.import_group.isHidden())
        self.assertEqual("导入课程", screen.import_toggle_btn.text())
        self.assertEqual("primaryButton", screen.generate_questions_btn.objectName())
        self.assertEqual("secondaryButton", screen.init_btn.objectName())
        self.assertEqual(project.course_id, screen.project_list.currentItem().data(Qt.ItemDataRole.UserRole))
        self.assertIn("Newton", screen.summary_preview.toPlainText())
        self.assertLess(screen.left_layout.indexOf(screen.project_list), screen.left_layout.indexOf(screen.generate_questions_btn))

    def test_course_generation_activates_selected_course_before_routing(self):
        projects = [
            CourseProject(
                course_id=course_id,
                title=title,
                source_folder="",
                summary_markdown=f"# {title}",
                summary_path="",
                topics=[CourseTopic(topic_id="topic", title="Topic")],
                documents=[],
                created_at="2026-07-16T00:00:00+00:00",
                updated_at=f"2026-07-16T00:00:0{index}+00:00",
            )
            for index, (course_id, title) in enumerate((("course-a", "Physics"), ("course-b", "Law")))
        ]

        class Manager:
            def __init__(self):
                self.current_id = "course-a"

            def current(self):
                return next(project for project in projects if project.course_id == self.current_id)

            def load_all(self):
                return list(reversed(projects))

            def get(self, course_id):
                return next((project for project in projects if project.course_id == course_id), None)

            def set_current(self, course_id):
                self.current_id = course_id
                return True

        manager = Manager()
        screen = CourseScreen(manager)
        requested = []
        screen.generate_questions_requested.connect(requested.append)
        law_row = next(
            row
            for row in range(screen.project_list.count())
            if screen.project_list.item(row).data(Qt.ItemDataRole.UserRole) == "course-b"
        )
        screen.project_list.setCurrentRow(law_row)

        screen.generate_questions_btn.click()

        self.assertEqual("course-b", manager.current_id)
        self.assertEqual(["course-b"], requested)

    def test_empty_course_workspace_explains_the_next_action(self):
        class Manager:
            def current(self):
                return None

            def load_all(self):
                return []

        screen = CourseScreen(Manager())

        self.assertFalse(screen.import_group.isHidden())
        self.assertFalse(screen.empty_state_label.isHidden())
        self.assertIn("导入", screen.empty_state_label.text())
        self.assertTrue(screen.generate_questions_btn.isHidden())
        self.assertEqual("primaryButton", screen.init_btn.objectName())
        self.assertTrue(screen.summary_preview.toPlainText().strip())

    def test_course_summary_preview_uses_readable_document_typography(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = CourseScreen(CourseProjectManager(str(Path(tmpdir) / "courses")))

        document_css = screen.summary_preview.document().defaultStyleSheet().lower()
        self.assertIn("font-family", document_css)
        self.assertIn("line-height", document_css)
        self.assertRegex(document_css, r"h1\s*\{[^}]*font-size:\s*20px")
        self.assertRegex(document_css, r"h2\s*\{[^}]*font-size:\s*17px")

    def test_home_visual_center_uses_recommendation_and_context_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            self.assertIsInstance(home.hero_layout, QHBoxLayout)
            self.assertEqual(13, home.hero_layout.stretch(0))
            self.assertEqual(7, home.hero_layout.stretch(1))
            self.assertEqual("homeFocusPanel", home.today_plan_frame.objectName())
            self.assertEqual("homeContextPanel", home.context_frame.objectName())
            self.assertEqual("homeOverviewPanel", home.overview_frame.objectName())
            self.assertTrue(home.title.alignment() & Qt.AlignmentFlag.AlignLeft)
            self.assertTrue(home.course_context_label.alignment() & Qt.AlignmentFlag.AlignLeft)
            self.assertTrue(home.question_context_label.text())
            self.assertTrue(home.stats_label.text())

            visible_actions = [
                button
                for button in home.findChildren(QPushButton)
                if not button.isHidden()
            ]
            self.assertEqual([home.start_btn], visible_actions)
            for button in (
                home.free_practice_btn,
                home.incorrect_btn,
                home.ai_btn,
                home.progress_btn,
                home.resume_btn,
                home.settings_btn,
            ):
                self.assertTrue(button.isHidden())

    def test_home_screen_shows_current_course_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            home.set_current_course("course-a", "Computer Architecture")

            self.assertIn("当前课程", home.course_context_label.text())
            self.assertIn("Computer Architecture", home.course_context_label.text())

            home.set_current_course("", "")

            self.assertIn("全部课程", home.course_context_label.text())

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
        self.assertIn("展开高级设置", dialog.advanced_toggle_btn.text())
        self.assertTrue(dialog.generation_log_group.isHidden())
        self.assertTrue(dialog.advanced_content.isAncestorOf(dialog.topic_weight_group))
        self.assertTrue(dialog.advanced_content.isAncestorOf(dialog.structure_group))
        self.assertTrue(dialog.advanced_content.isAncestorOf(dialog.plan_group))
        self.assertTrue(dialog.advanced_content.isAncestorOf(dialog.runtime_instruction_group))

        dialog.advanced_toggle_btn.click()

        self.assertFalse(dialog.advanced_content.isHidden())
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

        self.assertEqual("secondaryButton", results.next_action_btn.objectName())
        self.assertEqual("primaryButton", results.retry_incorrect_btn.objectName())
        self.assertEqual("secondaryButton", results.more_practice_btn.objectName())
        self.assertEqual("resultsNextActionLabel", results.next_action_label.objectName())
        self.assertFalse(hasattr(results, "back_btn"))
        self.assertNotRegex(results.retry_incorrect_btn.text(), r"[^\w\s]")
        self.assertNotRegex(results.more_practice_btn.text(), r"[^\w\s]")

        self.assertEqual("secondaryButton", progress.refresh_btn.objectName())
        self.assertEqual("secondaryButton", progress.more_topic_actions_btn.objectName())
        self.assertEqual("dangerButton", progress.reset_btn.objectName())
        self.assertEqual("dashboardRecommendationLabel", progress.recommendation_label.objectName())
        self.assertEqual("dashboardSourceRefsLabel", progress.source_refs_label.objectName())
        self.assertEqual("sourcePanelHeader", progress.source_refs_panel.header_label.objectName())
        self.assertEqual("sourcePanelList", progress.source_refs_panel.source_list.objectName())
        self.assertNotRegex(progress.refresh_btn.text(), r"[^\w\s]")
        self.assertNotRegex(progress.more_topic_actions_btn.text(), r"[^\w\s]")
        self.assertNotRegex(progress.reset_btn.text(), r"[^\w\s]")

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


if __name__ == "__main__":
    unittest.main()
