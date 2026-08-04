import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main as main_module

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QMessageBox, QPushButton

from core.background_task_center import BackgroundTaskCenter
from core.progress_tracker import ProgressManager
from core.mastery_overrides import MasteryOverrideStore
from core.quiz_snapshot_manager import QuizSnapshotManager
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from ui.main_window import MainWindow
from ui.navigation import Route
from ui.screens.course_screen import CourseScreen
from ui.screens.home_screen import HomeScreen
from ui.screens.settings_screen import SettingsScreen
from ui.screens.topic_selection_screen import TopicSelectionScreen
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])

class AppShellUiTests(unittest.TestCase):
    def test_study_setup_keeps_the_only_saved_set_optional(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                set_manager = SetManager(str(Path(tmpdir) / "sets"))
                question_set = QuestionSet.create_new(
                    title={"zh": "哲学导论综合练习", "en": "Philosophy Practice"},
                    description={"zh": "", "en": ""},
                    topics=["philosophy"],
                    question_ids=["q-1"],
                )
                set_manager.save(question_set)
                screen = TopicSelectionScreen(set_manager)
                self.addCleanup(screen.close)

                screen.set_current_course("course-a")
                screen.refresh()

                self.assertEqual(2, screen.preset_combo.count())
                self.assertEqual(
                    "",
                    screen.preset_combo.currentData(),
                )
                self.assertEqual(
                    question_set.set_id,
                    screen.preset_combo.itemData(1),
                )

    def test_study_setup_uses_one_compact_scope_card_at_narrow_width(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                screen = TopicSelectionScreen(
                    SetManager(str(Path(tmpdir) / "sets")),
                )
                self.addCleanup(screen.close)

                screen.resize(820, 680)
                screen.show()
                _APP.processEvents()

                self.assertTrue(screen.setup_card.isVisibleTo(screen))
                self.assertTrue(screen.setup_card.isAncestorOf(screen.preset_combo))
                self.assertTrue(screen.setup_card.isAncestorOf(screen.topic_filter))
                self.assertTrue(screen.setup_card.isAncestorOf(screen.question_count_input))
                self.assertFalse(hasattr(screen, "content_splitter"))

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
                    task_center=BackgroundTaskCenter(),
                )

                window = MainWindow(services=services)

                self.assertIs(services.question_bank, window.question_bank)
                self.assertIs(services.course_manager, window.course_manager)
                self.assertIs(services.task_center, window.task_center)
                self.assertIs(services.set_manager, window.progress_screen.set_manager)
                self.assertFalse(hasattr(window, "_task_center_timer"))

    def test_main_window_lazy_loads_management_workspaces_at_stable_routes(self):
            window = MainWindow()
            self.addCleanup(window.close)

            self.assertIsNone(window._course_screen)
            self.assertIsNone(window._question_bank_screen)
            self.assertFalse(hasattr(window, "_past_exam_screen"))
            self.assertIsNone(window._generation_workspace)
            self.assertFalse(hasattr(window, "SCREEN_PAST_EXAMS"))
            self.assertEqual(8, window.stack.count())

            self.assertTrue(window.navigate_to(window.SCREEN_QUESTION_BANK))
            self.assertEqual(window.SCREEN_QUESTION_BANK, window.stack.currentIndex())
            self.assertIsNone(window._course_screen)
            self.assertIsNotNone(window._question_bank_screen)
            self.assertFalse(hasattr(window, "_past_exam_screen"))

            with self.assertRaises(ValueError):
                window.navigate_to(99)

            self.assertTrue(window.navigate_to(window.SCREEN_GENERATION))
            self.assertEqual(window.SCREEN_GENERATION, window.stack.currentIndex())
            self.assertIsNotNone(window._generation_workspace)
            self.assertIsNone(window._generation_workspace.generation_widget())

    def test_settings_window_is_created_only_when_opened(self):
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertIsNone(getattr(window, "_settings_window", None))
        self.assertIsNone(getattr(window, "_settings_screen", None))

        window.open_settings()

        self.assertIsNotNone(window._settings_window)
        self.assertIs(window._settings_window.screen, window.settings_screen)

    def test_main_window_does_not_keep_unreachable_task_recovery_controller(self):
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertFalse(hasattr(window, "task_recovery"))

    def test_progress_dashboard_is_created_only_when_opened(self):
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertIsNone(getattr(window, "_progress_screen", None))

        self.assertTrue(window.navigate_to(window.SCREEN_PROGRESS))

        self.assertIsNotNone(window._progress_screen)
        self.assertIs(window._progress_screen, window.progress_screen)

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
                self.assertTrue(window.history_protection.retry())

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

            buttons = main_window.app_shell.navigation_buttons()
            self.assertEqual(
                ["Study", "Courses"],
                [button.text() for button in buttons],
            )
            self.assertEqual(
                ["learning", "courses"],
                [button.property("workspace") for button in buttons],
            )
            self.assertFalse(hasattr(main_window, "library_nav_btn"))
            self.assertFalse(hasattr(main_window, "home_nav_btn"))
            for button in buttons:
                self.assertNotRegex(button.text(), r"[^\w\s]")
                self.assertTrue(button.isCheckable())
                self.assertEqual(Qt.FocusPolicy.TabFocus, button.focusPolicy())
            self.assertEqual(Qt.FocusPolicy.NoFocus, main_window.menuBar().focusPolicy())
            self.assertEqual("Settings", main_window.settings_nav_btn.text())
            self.assertEqual("settings", main_window.settings_nav_btn.property("workspace"))
            self.assertFalse(main_window.settings_nav_btn.isCheckable())
            self.assertFalse(hasattr(main_window, "task_center_btn"))

            self.assertTrue(main_window.learning_nav_btn.isChecked())
            self.assertEqual("Study", main_window.context_title.text())
            self.assertEqual(Route.study("today"), main_window.current_route)
            self.assertEqual(
                ["Today", "Free Practice", "Learning Analysis"],
                [button.text() for button in main_window.app_shell.context_tabs()],
            )
            self.assertTrue(main_window.today_tab_btn.isChecked())
            self.assertFalse(hasattr(main_window, "incorrect_review_btn"))
            self.assertFalse(main_window.context_back_btn.isVisible())
            self.assertTrue(main_window.home_screen.question_context_label.text())

            main_window.navigate_to(main_window.SCREEN_PROGRESS)
            self.assertTrue(main_window.learning_nav_btn.isChecked())
            self.assertEqual(Route.study("analysis"), main_window.current_route)
            self.assertEqual(
                ["Today", "Free Practice", "Learning Analysis"],
                [button.text() for button in main_window.app_shell.context_tabs()],
            )
            self.assertTrue(main_window.progress_tab_btn.isChecked())
            self.assertFalse(main_window.context_back_btn.isVisible())

            main_window.learning_nav_btn.click()
            self.assertEqual(main_window.SCREEN_HOME, main_window.stack.currentIndex())

            main_window.navigate_route(Route.library("questions"))
            self.assertEqual(main_window.SCREEN_QUESTION_BANK, main_window.stack.currentIndex())
            self.assertEqual(Route.library("questions"), main_window.current_route)
            self.assertTrue(main_window.navigation_sidebar.isHidden())
            self.assertFalse(main_window.context_back_btn.isHidden())
            self.assertEqual(
                [
                    "Questions",
                    "Question Sets",
                ],
                [button.text() for button in main_window.app_shell.context_tabs()],
            )
            self.assertTrue(main_window.bank_tab_btn.isChecked())
            self.assertTrue(
                main_window._question_bank_screen.workspace_tabs.tabBar().isHidden()
            )
            main_window.sets_tab_btn.click()
            self.assertEqual(Route.library("sets"), main_window.current_route)
            self.assertEqual(
                main_window._question_bank_screen.set_panel,
                main_window._question_bank_screen.workspace_tabs.currentWidget(),
            )
            main_window.navigate_route(Route.study("practice"))
            self.assertTrue(main_window.topic_screen.today_mode_btn.isHidden())
            self.assertEqual(
                ["Practice Mode", "Mock Exam"],
                [
                    button.text()
                    for button in (
                        main_window.topic_screen.free_practice_mode_btn,
                        main_window.topic_screen.mock_exam_mode_btn,
                    )
                ],
            )

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

    def test_course_context_does_not_promote_qna_to_primary_navigation(self):
            main_window = MainWindow()
            self.addCleanup(main_window.close)

            self.assertTrue(
                main_window.navigate_route(
                    Route.course(tab="overview"),
                    allow_first_run_redirect=False,
                )
            )

            self.assertNotIn(
                "Q&A",
                [button.text() for button in main_window.app_shell.context_tabs()],
            )

    def test_library_context_does_not_promote_historical_exam_workspace(self):
            main_window = MainWindow()
            self.addCleanup(main_window.close)

            self.assertTrue(
                main_window.navigate_route(
                    Route.library("questions"),
                    allow_first_run_redirect=False,
                )
            )

            self.assertNotIn(
                "Historical Exams",
                [button.text() for button in main_window.app_shell.context_tabs()],
            )

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

    def test_home_screen_uses_today_plan_as_first_use_guidance(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                home = HomeScreen(
                    ProgressManager(str(Path(tmpdir) / "progress")),
                    QuestionBank(str(Path(tmpdir) / "questions")),
                )

                home.refresh()

                self.assertIn("导入", home.start_btn.text())
                self.assertIn("导入课件", home.today_plan_detail.text())
                self.assertIn("生成新题", home.generate_link.text())
                self.assertIn("切换课程", home.switch_course_link.text())

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
            self.assertFalse(hasattr(screen, "generate_questions_btn"))
            self.assertEqual("secondaryButton", screen.init_btn.objectName())
            self.assertEqual(project.course_id, screen.project_list.currentItem().data(Qt.ItemDataRole.UserRole))
            self.assertIn("Newton", screen.summary_preview.toPlainText())

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
                self.assertTrue(home.title.alignment() & Qt.AlignmentFlag.AlignLeft)
                self.assertTrue(home.course_context_label.alignment() & Qt.AlignmentFlag.AlignLeft)
                self.assertTrue(home.question_context_label.text())

                visible_actions = [
                    button
                    for button in home.findChildren(QPushButton)
                    if not button.isHidden()
                ]
                self.assertEqual(
                    [home.start_btn, home.generate_link, home.switch_course_link],
                    visible_actions,
                )
                for name in (
                    "free_practice_btn",
                    "incorrect_btn",
                    "ai_btn",
                    "progress_btn",
                    "resume_btn",
                    "settings_btn",
                ):
                    self.assertFalse(hasattr(home, name))

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

                self.assertIn("尚未选择", home.course_context_label.text())

    def test_learning_surfaces_do_not_treat_missing_current_course_as_global_scope(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                bank = QuestionBank(str(root / "questions"))
                bank.save(Question(
                    question_id="archived-question",
                    type=QuestionType.TRUE_FALSE,
                    difficulty=Difficulty.EASY,
                    bilingual={
                        "zh": {
                            "stem": "归档课程题目",
                            "options": ["正确", "错误"],
                            "explanation": "",
                        },
                        "en": {
                            "stem": "Archived course question",
                            "options": ["True", "False"],
                            "explanation": "",
                        },
                    },
                    correct_answer=True,
                    topic="archived-topic",
                    metadata={"course_id": "course-archived"},
                ))
                progress = ProgressManager(str(root / "progress"))
                home = HomeScreen(progress, bank)
                topic = TopicSelectionScreen(
                    SetManager(str(root / "sets")),
                    progress,
                    question_bank=bank,
                )

                home.set_current_course("", "")
                topic.set_current_course("", "")

                self.assertEqual(set(), home._visible_question_ids())
                self.assertEqual({}, topic._scheduling_index)
                self.assertFalse(topic.start_btn.isEnabled())
