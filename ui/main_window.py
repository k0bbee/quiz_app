"""Main window — application shell with QStackedWidget navigation."""

from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QDialog,
    QMessageBox, QWidget, QPushButton, QFileDialog,
)
from PyQt6.QtCore import QTimer, Qt

from core.application_data_migration import ApplicationDataMigrator
from core.application_services import ApplicationServices
from core.first_run_flow import (
    build_first_run_exam_plan,
    resolve_first_run_state,
)
from core.language_manager import LanguageManager
from core.question_set_regenerator import persist_new_question_set, persist_regenerated_question_set
from core.question_set_builder import build_ai_question_set
from core.background_task_presenter import build_task_center_view, task_toolbar_text
from core.topic_display import topic_display_name
from core.past_exam_prediction import prediction_prefill_status
from core.session_retry import SessionRetryMode, session_retry_question_ids
from core.study_intent import StudyAction, StudyIntent
from ui.dialogs.background_task_dialog import BackgroundTaskDialog
from ui.generation_launch_controller import (
    GenerationLaunchController,
    generation_launch_copy,
)
from ui.session_retry_presenter import session_retry_copy
from ui.study_flow_controller import StudyFlowController
from ui.task_recovery_controller import TaskRecoveryController
from ui.navigation import NavigationRouter
from ui.shell import AppShell
from config import APP_NAME, APP_NAME_EN

from ui.screens.home_screen import HomeScreen
from ui.screens.first_run_workspace import FirstRunWorkspace
from ui.screens.topic_selection_screen import TopicSelectionScreen
from ui.screens.quiz_screen import QuizScreen
from ui.screens.results_screen import ResultsScreen
from ui.screens.progress_dashboard import ProgressDashboard
from ui.settings_window import SettingsWindow
from utils.constants import Difficulty, topic_value
from ai.course_summary_factory import provider_requires_api_key as _provider_requires_api_key
from ai.exam_plan import ExamGenerationPlan
from ai.settings_validation import (
    ai_generation_settings_error as _ai_generation_settings_error,
)
from models.question_set import QuestionSet


class MainWindow(QMainWindow):
    """Main application window with QStackedWidget navigation."""

    # Screen indices
    SCREEN_HOME = 0
    SCREEN_TOPIC_SELECTION = 1
    SCREEN_QUIZ = 2
    SCREEN_RESULTS = 3
    SCREEN_PROGRESS = 4
    SCREEN_COURSES = 5
    SCREEN_QUESTION_BANK = 6
    SCREEN_PAST_EXAMS = 7

    def __init__(
        self,
        services: ApplicationServices | None = None,
        startup_migration_report=None,
    ):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 680)

        services = services or ApplicationServices.default()
        self.services = services
        self.question_bank = services.question_bank
        self.set_manager = services.set_manager
        self.progress_manager = services.progress_manager
        self.snapshot_manager = services.snapshot_manager
        self.mastery_overrides = services.mastery_overrides
        self.course_manager = services.course_manager
        self.past_exam_manager = services.past_exam_manager
        self.current_event_manager = services.current_event_manager
        self.task_center = services.task_center
        self.daily_plan_store = getattr(services, "daily_plan_store", None)
        self.lang_manager = LanguageManager.instance()
        self.startup_migration_report = startup_migration_report
        self._first_run_operation = ""
        self._first_run_error = ""
        self._first_run_progress = None
        self._history_protection_blocked = bool(
            getattr(startup_migration_report, "has_failures", False)
        )

        # Central stacked widget
        self.stack = QStackedWidget()
        self.navigation_router = NavigationRouter(
            self.stack,
            skip_history_from={self.SCREEN_QUIZ},
        )

        # Create screens
        self.home_screen = HomeScreen(
            self.progress_manager,
            self.question_bank,
            mastery_overrides=self.mastery_overrides,
            daily_plan_store=self.daily_plan_store,
        )
        self.first_run_screen = FirstRunWorkspace()
        self.home_workspace = QStackedWidget()
        self.home_workspace.setObjectName("homeWorkspace")
        self.home_workspace.addWidget(self.home_screen)
        self.home_workspace.addWidget(self.first_run_screen)
        self.topic_screen = TopicSelectionScreen(
            self.set_manager,
            self.progress_manager,
            question_bank=self.question_bank,
        )
        self.quiz_screen = QuizScreen(
            self.question_bank,
            self.progress_manager,
            snapshot_manager=self.snapshot_manager,
        )
        self.results_screen = ResultsScreen(course_manager=self.course_manager)
        self.progress_screen = ProgressDashboard(
            self.progress_manager,
            self.question_bank,
            set_manager=self.set_manager,
            mastery_overrides=self.mastery_overrides,
            course_manager=self.course_manager,
            daily_plan_store=self.daily_plan_store,
        )
        self.settings_window = SettingsWindow(
            task_center=self.task_center,
            daily_plan_store=self.daily_plan_store,
            parent=self,
        )
        self.settings_screen = self.settings_window.screen
        self.settings_screen.set_history_protection_blocked(
            self._history_protection_blocked,
            self._history_protection_message()
            if self._history_protection_blocked
            else "",
        )
        self._course_screen = None
        self._question_bank_screen = None
        self._past_exam_screen = None
        self._active_questions: dict = {}

        # Management screens 6-8 are lazily created on first access.
        self.stack.addWidget(self.home_workspace)    # 0
        self.stack.addWidget(self.topic_screen)       # 1
        self.stack.addWidget(self.quiz_screen)        # 2
        self.stack.addWidget(self.results_screen)     # 3
        self.stack.addWidget(self.progress_screen)    # 4
        self._workspace_placeholders = {}
        for index, name in (
            (self.SCREEN_COURSES, "courses"),
            (self.SCREEN_QUESTION_BANK, "questionBank"),
            (self.SCREEN_PAST_EXAMS, "pastExams"),
        ):
            placeholder = QWidget()
            placeholder.setObjectName(f"{name}WorkspacePlaceholder")
            self._workspace_placeholders[index] = placeholder
            self.stack.addWidget(placeholder)

        self._create_application_shell()
        self.study_flow = StudyFlowController(
            question_bank=self.question_bank,
            set_manager=self.set_manager,
            course_manager=self.course_manager,
            topic_screen=self.topic_screen,
            quiz_screen=self.quiz_screen,
            lang_manager=self.lang_manager,
            navigate=self.navigate_to,
            setup_screen_index=self.SCREEN_TOPIC_SELECTION,
            quiz_screen_index=self.SCREEN_QUIZ,
            courses_screen_index=self.SCREEN_COURSES,
            current_course_id=self._current_course_id,
            course_changed=self._on_course_changed,
            resume_session=self._on_resume_abandoned,
            review_questions=self._on_practice_incorrect,
            generate_questions=self._on_ai_generate,
            show_timer=self._show_timer_setting,
        )
        self.task_recovery = TaskRecoveryController(
            task_center=self.task_center,
            course_manager=self.course_manager,
            current_language=lambda: self.lang_manager.current,
            navigate=lambda screen_index: self.navigate_to(
                screen_index,
                allow_first_run_redirect=False,
            ),
            open_settings=self.open_settings,
            course_changed=self._on_course_changed,
            get_course_screen=self._get_course_screen,
            get_past_exam_screen=self._get_past_exam_screen,
            generate_questions=self._on_ai_generate,
            courses_screen_index=self.SCREEN_COURSES,
            past_exams_screen_index=self.SCREEN_PAST_EXAMS,
            question_bank_screen_index=self.SCREEN_QUESTION_BANK,
        )

        # Keep the shell free of duplicate menu navigation.
        self.menuBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Connect screen navigation signals
        self._connect_signals()
        self._sync_home_screen_course()
        self._sync_topic_screen_course()
        self._sync_progress_screen_course()
        self._refresh_first_run()

        # Apply initial language
        self._on_language_changed()

        # Start on home screen
        self.stack.setCurrentIndex(self.SCREEN_HOME)
        self._update_navigation_actions()
        self._task_center_timer = QTimer(self)
        self._task_center_timer.setInterval(1000)
        self._task_center_timer.timeout.connect(self._refresh_task_center_action)
        self._task_center_timer.start()
        if bool(getattr(startup_migration_report, "has_failures", False)):
            QTimer.singleShot(0, self._show_startup_migration_warning)

    def _show_startup_migration_warning(self) -> None:
        if not self._history_protection_blocked:
            return
        reply = QMessageBox.warning(
            self,
            self.lang_manager.get_text(
                "旧历史保护未完成",
                "Legacy History Protection Incomplete",
            ),
            self._history_protection_message(),
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Retry,
        )
        if reply == QMessageBox.StandardButton.Retry:
            self._retry_startup_migration()

    def _history_protection_message(self) -> str:
        report = self.startup_migration_report
        failed_count = len(tuple(getattr(report, "failed_progress_ids", ()) or ()))
        detail = "\n".join(
            str(error)
            for error in tuple(getattr(report, "errors", ()) or ())[:3]
        )
        suffix = f"\n\n{detail}" if detail else ""
        return self.lang_manager.get_text(
            f"{failed_count} 条旧练习记录暂未完成保护。请先检查数据目录权限，"
            f"为避免历史答案失真，课程、题库、历史真题维护以及数据导入/重置"
            f"已暂时停用。修复后可重试。{suffix}",
            f"{failed_count} legacy practice record(s) could not be protected. "
            f"To preserve historical answers, course, question-bank and "
            f"historical-exam maintenance plus data import/reset are temporarily "
            f"disabled. Fix the data-directory issue, then retry.{suffix}",
        )

    def _set_history_protection_blocked(self, blocked: bool, report=None) -> None:
        if report is not None:
            self.startup_migration_report = report
        self._history_protection_blocked = bool(blocked)
        self.settings_screen.set_history_protection_blocked(
            self._history_protection_blocked,
            self._history_protection_message()
            if self._history_protection_blocked
            else "",
        )

    def _retry_startup_migration(self) -> bool:
        report = ApplicationDataMigrator(self.services).migrate()
        blocked = bool(getattr(report, "has_failures", False))
        self._set_history_protection_blocked(blocked, report)
        if blocked:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text(
                    "仍未完成保护",
                    "Protection Still Incomplete",
                ),
                self._history_protection_message(),
            )
            return False
        QMessageBox.information(
            self,
            self.lang_manager.get_text(
                "历史保护已完成",
                "History Protection Complete",
            ),
            self.lang_manager.get_text(
                "旧历史已完成保护，课程与资料维护功能已恢复。",
                "Legacy history is now protected. Course and library "
                "maintenance are available again.",
            ),
        )
        return True

    def _confirm_history_sensitive_navigation(self, screen_index: int) -> bool:
        if not self._history_protection_blocked or screen_index not in {
            self.SCREEN_COURSES,
            self.SCREEN_QUESTION_BANK,
            self.SCREEN_PAST_EXAMS,
        }:
            return True
        reply = QMessageBox.warning(
            self,
            self.lang_manager.get_text(
                "数据保护模式",
                "Data Protection Mode",
            ),
            self._history_protection_message(),
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Retry,
        )
        return (
            reply == QMessageBox.StandardButton.Retry
            and self._retry_startup_migration()
        )

    def _get_course_screen(self):
        """Lazy-init the course screen on first access."""
        if self._course_screen is None:
            from ui.screens.course_screen import CourseScreen
            self._course_screen = CourseScreen(
                self.course_manager,
                question_bank=self.question_bank,
                set_manager=self.set_manager,
                progress_manager=self.progress_manager,
                snapshot_manager=self.snapshot_manager,
                past_exam_manager=self.past_exam_manager,
                mastery_overrides=self.mastery_overrides,
                current_event_manager=self.current_event_manager,
                task_center=self.task_center,
            )
            self._course_screen.current_course_changed.connect(
                self._on_course_changed
            )
            self._course_screen.generate_questions_requested.connect(
                lambda _course_id: self._on_ai_generate()
            )
            self._course_screen.current_event_generation_requested.connect(
                self._on_current_event_generation
            )
            self._course_screen.course_import_started.connect(
                self._on_first_run_import_started
            )
            self._course_screen.course_import_progressed.connect(
                self._on_first_run_import_progress
            )
            self._course_screen.course_import_completed.connect(
                self._on_first_run_import_completed
            )
            self._course_screen.course_import_failed.connect(
                self._on_first_run_import_failed
            )
            self._course_screen.course_import_cancelled.connect(
                self._on_first_run_import_cancelled
            )
            self._install_workspace(self.SCREEN_COURSES, self._course_screen)
        return self._course_screen

    def _get_question_bank_screen(self):
        """Lazy-init the question bank screen on first access."""
        if self._question_bank_screen is None:
            from ui.screens.question_bank_screen import QuestionBankScreen
            self._question_bank_screen = QuestionBankScreen(
                self.question_bank,
                set_manager=self.set_manager,
                course_manager=self.course_manager,
                task_center=self.task_center,
            )
            self._sync_question_bank_screen_course()
            self._question_bank_screen.question_bank_changed.connect(
                self._on_question_bank_changed
            )
            self._install_workspace(
                self.SCREEN_QUESTION_BANK,
                self._question_bank_screen,
            )
        return self._question_bank_screen

    def _get_past_exam_screen(self):
        """Lazy-init the historical exam workbench on first access."""
        if self._past_exam_screen is None:
            from ui.screens.past_exam_screen import PastExamScreen
            self._past_exam_screen = PastExamScreen(
                self.past_exam_manager,
                self.course_manager,
                task_center=self.task_center,
            )
            self._past_exam_screen.prediction_requested.connect(
                self._on_generate_predicted_exam
            )
            self._install_workspace(
                self.SCREEN_PAST_EXAMS,
                self._past_exam_screen,
            )
        return self._past_exam_screen

    def _install_workspace(self, index: int, screen: QWidget) -> None:
        """Replace one fixed-route placeholder without shifting other routes."""
        placeholder = self._workspace_placeholders.pop(index, None)
        if placeholder is not None:
            self.stack.removeWidget(placeholder)
            placeholder.deleteLater()
        self.stack.insertWidget(index, screen)

    def _create_application_shell(self):
        self.app_shell = AppShell(
            self.stack,
            workspace_routes=(
                ("learning_nav_btn", "learning", self.SCREEN_HOME),
                ("courses_nav_btn", "courses", self.SCREEN_COURSES),
                ("library_nav_btn", "library", self.SCREEN_QUESTION_BANK),
            ),
            context_routes=(
                ("topics_tab_btn", self.SCREEN_TOPIC_SELECTION),
                ("progress_tab_btn", self.SCREEN_PROGRESS),
                ("bank_tab_btn", self.SCREEN_QUESTION_BANK),
                ("past_exams_tab_btn", self.SCREEN_PAST_EXAMS),
            ),
            navigate=self.navigate_to,
            open_settings=self.open_settings,
            navigate_back=self.navigate_back,
            practice_incorrect=self._on_practice_incorrect,
            open_task_center=self._open_task_center,
        )
        for attribute in (
            "navigation_sidebar",
            "sidebar_title",
            "sidebar_utility_separator",
            "settings_nav_btn",
            "context_header",
            "context_back_btn",
            "context_title",
            "incorrect_review_btn",
            "task_center_btn",
            "learning_nav_btn",
            "courses_nav_btn",
            "library_nav_btn",
            "topics_tab_btn",
            "progress_tab_btn",
            "bank_tab_btn",
            "past_exams_tab_btn",
        ):
            setattr(self, attribute, getattr(self.app_shell, attribute))
        self.setCentralWidget(self.app_shell)

    def navigation_buttons(self) -> tuple[QPushButton, ...]:
        return self.app_shell.navigation_buttons()

    def _all_context_tabs(self) -> tuple[QPushButton, ...]:
        return self.app_shell.all_context_tabs()

    def context_tabs(self) -> tuple[QPushButton, ...]:
        return self.app_shell.context_tabs()

    def _connect_signals(self):
        # Home screen
        self.home_screen.start_practice.connect(self._on_start_practice)
        self.home_screen.study_requested.connect(self._handle_study_intent)
        self.home_screen.resume_practice.connect(self._on_resume_abandoned)
        self.home_screen.practice_incorrect.connect(self._on_practice_incorrect)
        self.home_screen.ai_generate.connect(self._on_ai_generate)
        self.home_screen.view_progress.connect(lambda: self.navigate_to(self.SCREEN_PROGRESS))
        self.home_screen.open_settings.connect(self.open_settings)
        self.home_screen.manage_courses.connect(lambda: self.navigate_to(self.SCREEN_COURSES))
        self.first_run_screen.configure_ai_requested.connect(
            lambda: self.open_settings("ai")
        )
        self.first_run_screen.choose_materials_requested.connect(
            self._on_first_run_choose_materials
        )
        self.first_run_screen.generate_requested.connect(
            self._on_first_run_generate
        )
        self.first_run_screen.start_requested.connect(
            self._on_first_run_start
        )
        self.first_run_screen.cancel_requested.connect(
            self._on_first_run_cancel
        )
        self.settings_screen.settings_saved.connect(self._refresh_first_run)

        # Topic selection
        self.topic_screen.quiz_start.connect(self._on_quiz_start)
        self.topic_screen.study_start.connect(self._on_study_quiz_start)
        self.topic_screen.generate_missing.connect(self.study_flow.generate_missing)
        self.topic_screen.export_mock_exam.connect(self._on_export_mock_exam)
        self.topic_screen.export_mock_exams.connect(self._on_export_mock_exams)
        self.topic_screen.regenerate_questions.connect(self._on_regenerate_question_set)

        # Quiz screen
        self.quiz_screen.quiz_finished.connect(self._on_quiz_finished)
        self.quiz_screen.return_home.connect(
            lambda: self.navigate_to(self.SCREEN_HOME, confirm_current=False)
        )

        # Results screen
        self.results_screen.retry_incorrect.connect(self._on_retry_incorrect)
        self.results_screen.retry_unsure.connect(self._on_retry_unsure)
        self.results_screen.retry_review.connect(self._on_retry_review)
        self.results_screen.retry_all.connect(self._on_retry_all)
        self.results_screen.study_requested.connect(self._handle_study_intent)
        self.results_screen.practice_topic_requested.connect(self._on_practice_progress_topic)
        self.results_screen.review_topic_requested.connect(self._on_review_progress_topic)
        self.progress_screen.practice_topic_requested.connect(self._on_practice_progress_topic)
        self.progress_screen.review_topic_requested.connect(self._on_review_progress_topic)
        self.progress_screen.generate_topic_requested.connect(self._on_generate_progress_topic)
        self.progress_screen.history_requested.connect(self._on_open_progress_record)
        # Language manager
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang: str = None):
        """Update all UI text based on current language."""
        lang = lang or self.lang_manager.current
        gm = self.lang_manager.get_text

        self.context_back_btn.setText(gm("返回", "Back"))
        self.sidebar_title.setText(gm(APP_NAME, APP_NAME_EN))
        self.learning_nav_btn.setText(gm("学习", "Study"))
        self.courses_nav_btn.setText(gm("课程", "Courses"))
        self.library_nav_btn.setText(gm("题库", "Question Bank"))
        self.settings_nav_btn.setText(gm("设置", "Settings"))
        self.topics_tab_btn.setText(gm("题目集", "Question Sets"))
        self.progress_tab_btn.setText(gm("进度", "Progress"))
        self.bank_tab_btn.setText(gm("题库", "Question Bank"))
        self.past_exams_tab_btn.setText(gm("历史真题", "Historical Exams"))
        self.incorrect_review_btn.setText(gm("错题复习", "Review Incorrect"))
        self._refresh_task_center_action()
        self._update_navigation_actions()

    def navigate_to(
        self,
        screen_index: int,
        remember: bool = True,
        confirm_current: bool = True,
        *,
        allow_first_run_redirect: bool = True,
    ) -> bool:
        """Switch to a screen by index."""
        if not self._confirm_history_sensitive_navigation(screen_index):
            self._update_navigation_actions()
            return False
        if (
            allow_first_run_redirect
            and self._first_run_required()
            and screen_index == self.SCREEN_TOPIC_SELECTION
        ):
            screen_index = self.SCREEN_HOME
        elif (
            allow_first_run_redirect
            and self._first_run_required()
            and screen_index == self.SCREEN_COURSES
            and self._course_screen is None
        ):
            screen_index = self.SCREEN_HOME
        if confirm_current and not self._confirm_current_navigation(screen_index):
            self._update_navigation_actions()
            return False
        if screen_index == self.SCREEN_COURSES:
            self._get_course_screen()
        elif screen_index == self.SCREEN_QUESTION_BANK:
            self._get_question_bank_screen()
        elif screen_index == self.SCREEN_PAST_EXAMS:
            self._get_past_exam_screen()
        self.navigation_router.navigate(screen_index, remember=remember)
        # Refresh data on certain screens
        if screen_index == self.SCREEN_TOPIC_SELECTION:
            self._sync_topic_screen_course()
            self.topic_screen.refresh()
        elif screen_index == self.SCREEN_PROGRESS:
            self._sync_progress_screen_course()
            self.progress_screen.refresh()
        elif screen_index == self.SCREEN_HOME:
            self._sync_home_screen_course()
            self.home_screen.refresh()
        elif screen_index == self.SCREEN_COURSES:
            self._get_course_screen().refresh()
        elif screen_index == self.SCREEN_QUESTION_BANK:
            self._sync_question_bank_screen_course()
            self._get_question_bank_screen().refresh()
        elif screen_index == self.SCREEN_PAST_EXAMS:
            self._get_past_exam_screen().refresh()
        self._update_navigation_actions()
        return True

    def navigate_back(self):
        """Return to the previous screen if navigation history exists."""
        previous = self.navigation_router.peek_back()
        if previous is None:
            self._update_navigation_actions()
            return
        if not self._confirm_current_navigation(previous):
            self._update_navigation_actions()
            return
        self.navigation_router.discard_back()
        self.navigate_to(previous, remember=False, confirm_current=False)

    def _confirm_current_navigation(self, target_screen: int) -> bool:
        """Return whether navigation away from the current screen may proceed."""
        if self.stack.currentIndex() == self.SCREEN_QUIZ and target_screen != self.SCREEN_QUIZ:
            return self.quiz_screen.confirm_exit()
        return True

    def _update_navigation_actions(self):
        """Keep shell navigation buttons in sync with current location."""
        if not hasattr(self, "context_back_btn"):
            return
        current = self.stack.currentIndex()
        workspace_button = {
            self.SCREEN_HOME: self.learning_nav_btn,
            self.SCREEN_TOPIC_SELECTION: self.learning_nav_btn,
            self.SCREEN_QUIZ: self.learning_nav_btn,
            self.SCREEN_RESULTS: self.learning_nav_btn,
            self.SCREEN_PROGRESS: self.learning_nav_btn,
            self.SCREEN_COURSES: self.courses_nav_btn,
            self.SCREEN_QUESTION_BANK: self.library_nav_btn,
            self.SCREEN_PAST_EXAMS: self.library_nav_btn,
        }.get(current)
        if workspace_button is not None:
            workspace_button.setChecked(True)

        learning = current in {
            self.SCREEN_TOPIC_SELECTION,
            self.SCREEN_PROGRESS,
            self.SCREEN_QUIZ,
            self.SCREEN_RESULTS,
        }
        library = current in {self.SCREEN_QUESTION_BANK, self.SCREEN_PAST_EXAMS}
        for button in (self.topics_tab_btn, self.progress_tab_btn):
            button.setVisible(learning and current not in {self.SCREEN_QUIZ, self.SCREEN_RESULTS})
        self.incorrect_review_btn.setVisible(
            learning and current not in {self.SCREEN_QUIZ, self.SCREEN_RESULTS}
        )
        for button in (self.bank_tab_btn, self.past_exams_tab_btn):
            button.setVisible(library)
        self.topics_tab_btn.setChecked(current == self.SCREEN_TOPIC_SELECTION)
        self.progress_tab_btn.setChecked(current == self.SCREEN_PROGRESS)
        self.bank_tab_btn.setChecked(current == self.SCREEN_QUESTION_BANK)
        self.past_exams_tab_btn.setChecked(current == self.SCREEN_PAST_EXAMS)

        page_titles = {
            self.SCREEN_HOME: ("学习", "Study"),
            self.SCREEN_TOPIC_SELECTION: ("学习", "Study"),
            self.SCREEN_QUIZ: ("答题", "Quiz"),
            self.SCREEN_RESULTS: ("练习结果", "Results"),
            self.SCREEN_PROGRESS: ("学习", "Study"),
            self.SCREEN_COURSES: ("课程", "Courses"),
            self.SCREEN_QUESTION_BANK: ("题库", "Question Bank"),
            self.SCREEN_PAST_EXAMS: ("题库", "Question Bank"),
        }
        zh, en = page_titles.get(current, ("", ""))
        self.context_title.setText(self.lang_manager.get_text(zh, en))
        is_focus_flow = current in {self.SCREEN_QUIZ, self.SCREEN_RESULTS}
        self.navigation_sidebar.setVisible(not is_focus_flow)
        self.context_back_btn.setVisible(is_focus_flow and self.navigation_router.can_go_back)
        self.context_back_btn.setEnabled(self.navigation_router.can_go_back)
        self._refresh_task_center_action()

    def open_settings(self, section: str = "") -> None:
        """Open settings as a utility window without leaving the workspace."""
        self.settings_window.show_settings(section)

    def _refresh_task_center_action(self) -> None:
        """Keep the global task entry visible and surface tasks needing attention."""
        if not hasattr(self, "task_center_btn"):
            return
        view = build_task_center_view(
            self.task_center.snapshots(),
            language=self.lang_manager.current,
            attention_only=True,
        )
        self.task_center_btn.setText(
            task_toolbar_text(view.attention_count, self.lang_manager.current)
        )
        self.task_center_btn.setProperty("needsAttention", bool(view.attention_count))
        self.task_center_btn.style().unpolish(self.task_center_btn)
        self.task_center_btn.style().polish(self.task_center_btn)

    def _open_task_center(self) -> None:
        dialog = BackgroundTaskDialog(
            self.task_center,
            language=self.lang_manager.current,
            parent=self,
        )
        dialog.exec()
        requested_task_id = str(getattr(dialog, "requested_task_id", "") or "")
        if requested_task_id:
            action = str(getattr(dialog, "requested_action", "") or "")
            if action == "retry":
                self.task_recovery.retry(requested_task_id)
            else:
                self.task_recovery.open_page(requested_task_id)
        self._refresh_task_center_action()

    def _first_run_ai_error(self) -> str:
        settings = self.settings_screen.settings_snapshot()
        api_key = ""
        if _provider_requires_api_key(settings):
            from core.secrets_manager import SecretsManager

            api_key = SecretsManager.instance().get_key()
        return _ai_generation_settings_error(settings, api_key)

    def _first_run_practice_candidates(self):
        course_id = self._current_course_id()
        if not course_id:
            return []
        candidates = []
        for question_set in self.set_manager.load_all():
            set_course_id = str(
                (getattr(question_set, "metadata", {}) or {}).get(
                    "course_id",
                    "",
                )
                or ""
            )
            if set_course_id and set_course_id != course_id:
                continue
            question_ids = [
                question.question_id
                for question in self.question_bank.get_many(
                    question_set.questions,
                    course_id=course_id,
                )
            ]
            if question_ids:
                candidates.append((question_set, question_ids))
        return candidates

    def _first_run_question_count(self) -> int:
        return sum(
            len(question_ids)
            for _question_set, question_ids in self._first_run_practice_candidates()
        )

    def _first_run_has_completed_practice(self) -> bool:
        return any(
            getattr(record, "status", "") == "completed"
            for record in self.progress_manager.load_all()
        )

    def _first_run_required(self) -> bool:
        if self._first_run_operation:
            return True
        if not self._current_course_id():
            return True
        if self._first_run_question_count() <= 0:
            return True
        return not self._first_run_has_completed_practice()

    def _refresh_first_run(self) -> None:
        if not hasattr(self, "first_run_screen"):
            return
        progress = self._first_run_progress
        has_course = bool(self._current_course_id())
        question_count = self._first_run_question_count()
        first_run_required = (
            bool(self._first_run_operation)
            or not has_course
            or question_count <= 0
            or not self._first_run_has_completed_practice()
        )
        state = resolve_first_run_state(
            ai_error=self._first_run_ai_error(),
            has_course=has_course,
            question_count=question_count,
            operation=self._first_run_operation,
            error=self._first_run_error,
            progress_text=str(getattr(progress, "detail", "") or ""),
            progress_current=int(getattr(progress, "current", 0) or 0),
            progress_total=int(getattr(progress, "total", 0) or 0),
        )
        self.first_run_screen.set_state(state)
        self.home_workspace.setCurrentWidget(
            self.first_run_screen
            if first_run_required
            else self.home_screen
        )

    def _on_first_run_choose_materials(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            self.lang_manager.get_text(
                "选择课程资料文件夹",
                "Choose Course Materials Folder",
            ),
        )
        if not folder:
            return
        course_screen = self._get_course_screen()
        self._first_run_operation = "importing"
        self._first_run_error = ""
        self._first_run_progress = None
        self._refresh_first_run()
        if not course_screen.start_import(
            folder,
            "",
            present_result=False,
        ):
            self._first_run_operation = ""
            self._first_run_error = self.lang_manager.get_text(
                "课程导入任务未能启动，请检查当前后台任务。",
                "The course import could not start. Check the current background task.",
            )
            self._refresh_first_run()

    def _on_first_run_import_started(self) -> None:
        self._first_run_operation = "importing"
        self._first_run_error = ""
        self._first_run_progress = None
        self._refresh_first_run()

    def _on_first_run_import_progress(self, progress) -> None:
        self._first_run_progress = progress
        self._refresh_first_run()

    def _on_first_run_import_completed(self, _project) -> None:
        self._first_run_operation = ""
        self._first_run_error = ""
        self._first_run_progress = None
        self._refresh_first_run()

    def _on_first_run_import_failed(self, message: str) -> None:
        self._first_run_operation = ""
        self._first_run_error = str(message or "")
        self._first_run_progress = None
        self._refresh_first_run()

    def _on_first_run_import_cancelled(self) -> None:
        self._first_run_operation = ""
        self._first_run_error = self.lang_manager.get_text(
            "课程导入已停止，未完成内容没有保存。",
            "Course import stopped; incomplete content was not saved.",
        )
        self._first_run_progress = None
        self._refresh_first_run()

    def _on_first_run_generate(self) -> None:
        course_project = self.course_manager.current()
        if course_project is None:
            self._first_run_error = self.lang_manager.get_text(
                "当前课程已不存在，请重新导入课程资料。",
                "The current course no longer exists. Import the materials again.",
            )
            self._refresh_first_run()
            return
        try:
            plan = build_first_run_exam_plan(course_project)
        except ValueError:
            self._first_run_error = self.lang_manager.get_text(
                "课程中没有可用于出题的知识点，请重新解析课程资料。",
                "The course has no topics available for generation. Parse the materials again.",
            )
            self._refresh_first_run()
            return
        title = self.lang_manager.get_text(
            f"{course_project.title}快速复习",
            f"{course_project.title} Quick Review",
        )
        self._first_run_operation = "generating"
        self._first_run_error = ""
        self._refresh_first_run()
        try:
            self._on_ai_generate(
                course_override=course_project,
                initial_plan=plan,
                auto_start=True,
                start_after_save=True,
                review_warnings_only=True,
                question_set_title=title,
            )
        finally:
            self._first_run_operation = ""
            self._first_run_progress = None
            self._refresh_first_run()

    def _on_first_run_start(self) -> None:
        candidates = self._first_run_practice_candidates()
        if not candidates:
            self._first_run_error = self.lang_manager.get_text(
                "尚未找到可开始的题目集，请先生成快速复习题。",
                "No ready question set was found. Generate quick-review questions first.",
            )
            self._refresh_first_run()
            return
        question_set, question_ids = candidates[0]
        self._on_quiz_start(question_set.set_id, question_ids)

    def _on_first_run_cancel(self) -> None:
        if self._course_screen is not None:
            self._course_screen.cancel_active_task()

    # --- Slot handlers ---

    def _handle_study_intent(self, intent: StudyIntent) -> None:
        """Route a user intent and keep legacy result data aligned."""
        self.study_flow.handle_intent(intent)
        if self.study_flow.active_intent is intent:
            self.quiz_screen.set_study_intent(intent)
        if (
            isinstance(intent, StudyIntent)
            and intent.action is StudyAction.DAILY_QUEUE
        ):
            self._active_questions = dict(self.study_flow.active_questions)

    def _on_start_practice(self):
        self.study_flow.clear_setup()
        self.navigate_to(self.SCREEN_TOPIC_SELECTION)

    def _on_study_quiz_start(
        self,
        intent: StudyIntent,
        question_ids: list[str],
    ) -> None:
        """Start the prefilled practice without asking for scope again."""
        self._active_questions = self.study_flow.start_prefilled(
            intent,
            question_ids,
        )
        self.quiz_screen.set_study_intent(intent)

    def _resume_abandoned_draft(self):
        """Return the latest resumable abandoned draft details, or None."""
        draft = self.progress_manager.get_latest_abandoned_record()
        if not draft:
            return None
        question_set = self.set_manager.get(draft.set_id)
        if not question_set:
            return None
        questions = self.question_bank.get_many(
            question_set.questions,
            course_id=self._current_course_id(),
        )
        answered_ids = {answer.question_id for answer in draft.answers}
        remaining = [question for question in questions if question.question_id not in answered_ids]
        if not remaining:
            return None
        return draft, question_set, remaining

    def _resume_snapshot_draft(self):
        """Return the latest full quiz snapshot details, or None."""
        snapshot_manager = getattr(self, "snapshot_manager", None)
        self._resume_snapshot_error = ""
        if snapshot_manager is None:
            return None
        snapshot = snapshot_manager.load_latest()
        if not snapshot:
            return None
        question_set = self.set_manager.get(snapshot.set_id)
        if question_set is None and snapshot.question_set_data:
            try:
                restored_set = QuestionSet.from_dict(
                    snapshot.question_set_data
                )
            except (TypeError, ValueError):
                restored_set = None
            if (
                restored_set is not None
                and restored_set.set_id == snapshot.set_id
            ):
                question_set = restored_set
        if not question_set:
            snapshot_manager.delete(snapshot.snapshot_id)
            self._resume_snapshot_error = self.lang_manager.get_text(
                "练习草稿引用的题目集已不存在，无法恢复，已清理该草稿。",
                "The draft's question set no longer exists, so it cannot be restored. The draft was removed.",
            )
            return None
        try:
            study_intent = (
                StudyIntent.from_dict(snapshot.study_intent_data)
                if snapshot.study_intent_data
                else None
            )
        except (TypeError, ValueError):
            study_intent = None
        course_id = (
            study_intent.course_id
            if study_intent is not None and study_intent.course_id
            else self._current_course_id()
        )
        questions = self.question_bank.get_many(
            snapshot.question_order,
            course_id=course_id,
        )
        if len(questions) != len(snapshot.question_order):
            snapshot_manager.delete(snapshot.snapshot_id)
            self._resume_snapshot_error = self.lang_manager.get_text(
                "练习草稿中的部分题目已不存在，无法完整恢复，已清理该草稿。",
                "Some questions in the draft no longer exist, so it cannot be fully restored. The draft was removed.",
            )
            return None
        return snapshot, question_set, questions, study_intent

    def _update_home_resume_draft(self):
        """Reflect the latest abandoned draft on the home screen."""
        if not hasattr(self, "home_screen"):
            return
        snapshot_resume = MainWindow._resume_snapshot_draft(self)
        if snapshot_resume:
            snapshot, question_set, questions, _study_intent = snapshot_resume
            remaining_count = max(0, len(questions) - snapshot.current_index)
            self.home_screen.set_resume_draft(
                question_set.get_title(self.lang_manager.current),
                remaining_count,
                current_index=snapshot.current_index,
                total_count=len(questions),
                mode=snapshot.mode,
            )
            return
        resume = MainWindow._resume_abandoned_draft(self)
        if not resume:
            self.home_screen.clear_resume_draft()
            return
        _draft, question_set, remaining = resume
        self.home_screen.set_resume_draft(question_set.get_title(self.lang_manager.current), len(remaining))

    def _on_resume_abandoned(self):
        """Resume the latest quiz draft, preferring full snapshots over legacy abandoned records."""
        gm = self.lang_manager.get_text
        snapshot_resume = MainWindow._resume_snapshot_draft(self)
        if snapshot_resume:
            snapshot, question_set, questions, study_intent = snapshot_resume
            self._active_questions = {question.question_id: question for question in questions}
            self.quiz_screen.restore_snapshot(
                snapshot,
                questions,
                question_set,
                show_timer=self._show_timer_setting(),
            )
            if study_intent is not None:
                restore_intent = getattr(
                    self.study_flow,
                    "restore_active_intent",
                    None,
                )
                if callable(restore_intent):
                    restore_intent(study_intent, questions)
            if hasattr(self, "home_screen"):
                self.home_screen.clear_resume_draft()
            self.navigate_to(self.SCREEN_QUIZ)
            return

        resume = MainWindow._resume_abandoned_draft(self)
        if not resume:
            snapshot_error = getattr(self, "_resume_snapshot_error", "")
            parent = self if isinstance(self, QWidget) else None
            if snapshot_error:
                QMessageBox.warning(
                    parent,
                    gm("草稿无法恢复", "Draft Cannot Be Restored"),
                    snapshot_error,
                )
            else:
                QMessageBox.information(
                    parent,
                    gm("没有草稿", "No Draft"),
                    gm("当前没有可恢复的练习草稿。", "There is no resumable quiz draft."),
                )
            return
        draft, question_set, remaining = resume
        self._active_questions = {question.question_id: question for question in remaining}
        label = gm(
            f"继续草稿：{question_set.get_title('zh')}",
            f"Resume Draft: {question_set.get_title('en')}",
        )
        self.quiz_screen.start_quiz_custom(
            remaining,
            label,
            show_timer=self._show_timer_setting(),
        )
        self.progress_manager.delete(draft.progress_id)
        if hasattr(self, "home_screen"):
            self.home_screen.clear_resume_draft()
        self.navigate_to(self.SCREEN_QUIZ)

    def _on_quiz_start(self, set_id: str, question_ids: list[str]):
        """Start a quiz session with the given question set."""
        gm = self.lang_manager.get_text
        question_set = self.set_manager.get(set_id)
        if not question_set:
            QMessageBox.warning(self, gm("错误", "Error"), gm("未找到题目集。", "Question set not found."))
            return

        questions = self.question_bank.get_many(question_ids)
        if not questions:
            QMessageBox.warning(self, gm("错误", "Error"), gm("未找到该题目集的题目。", "No questions found for this set."))
            return

        submission_mode = "practice"

        self.study_flow.clear_active()
        self._active_questions = {q.question_id: q for q in questions}
        self.quiz_screen.start_quiz(
            question_set,
            questions,
            show_timer=self._show_timer_setting(),
            submission_mode=submission_mode,
        )
        self.navigate_to(self.SCREEN_QUIZ)

    def _on_export_mock_exam(self, set_id: str):
        """Export a selected question set as a Markdown mock exam."""
        gm = self.lang_manager.get_text
        question_set = self.set_manager.get(set_id)
        if not question_set:
            QMessageBox.warning(self, gm("错误", "Error"), gm("未找到题目集。", "Question set not found."))
            return

        questions = self.question_bank.get_many(question_set.questions)
        if not questions:
            QMessageBox.warning(self, gm("错误", "Error"), gm("未找到该题目集的题目。", "No questions found for this set."))
            return

        default_name = f"{question_set.set_id}_mock_exam.md"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            gm("导出模拟卷", "Export Mock Exam"),
            default_name,
            "Markdown Files (*.md);;All Files (*)",
        )
        if not filepath:
            return

        from core.mock_exam_exporter import MockExamExporter

        try:
            written = MockExamExporter.write_markdown(
                filepath,
                question_set,
                questions,
                lang=self.lang_manager.current,
                include_answers=True,
            )
        except OSError as exc:
            QMessageBox.critical(self, gm("导出失败", "Export Failed"), str(exc))
            return

        QMessageBox.information(
            self,
            gm("导出完成", "Export Complete"),
            gm(f"模拟卷已导出到:\n{written}", f"Mock exam exported to:\n{written}"),
        )

    def _on_export_mock_exams(self, set_ids: list[str]):
        """Export multiple selected question sets to one folder."""
        gm = self.lang_manager.get_text
        unique_set_ids = list(dict.fromkeys(set_ids))
        if not unique_set_ids:
            return
        if len(unique_set_ids) == 1:
            self._on_export_mock_exam(unique_set_ids[0])
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            gm("批量导出模拟卷", "Export Mock Exams"),
        )
        if not folder:
            return

        from core.mock_exam_exporter import MockExamExporter
        from utils.json_io import sanitize_filename_part

        output_dir = Path(folder)
        written: list[Path] = []
        failures: list[str] = []
        for set_id in unique_set_ids:
            question_set = self.set_manager.get(set_id)
            if not question_set:
                failures.append(gm(f"{set_id}: 未找到题目集", f"{set_id}: question set not found"))
                continue

            questions = self.question_bank.get_many(question_set.questions)
            if not questions:
                failures.append(gm(f"{set_id}: 未找到题目", f"{set_id}: no questions found"))
                continue

            output_path = output_dir / f"{sanitize_filename_part(question_set.set_id)}_mock_exam.md"
            try:
                written.append(
                    MockExamExporter.write_markdown(
                        output_path,
                        question_set,
                        questions,
                        lang=self.lang_manager.current,
                        include_answers=True,
                    )
                )
            except OSError as exc:
                failures.append(f"{set_id}: {exc}")

        if written:
            preview = "\n".join(str(path) for path in written[:5])
            extra = "" if len(written) <= 5 else gm(f"\n等 {len(written)} 份文件", f"\nand {len(written)} files total")
            QMessageBox.information(
                self,
                gm("导出完成", "Export Complete"),
                gm(f"已导出模拟卷:\n{preview}{extra}", f"Mock exams exported:\n{preview}{extra}"),
            )
        if failures:
            QMessageBox.warning(
                self,
                gm("部分导出失败", "Export Partially Failed"),
                "\n".join(failures),
            )

    def _on_quiz_finished(self, progress_record):
        """Show results screen after quiz completion."""
        # Save progress
        if progress_record:
            self.progress_manager.save(progress_record)
            snapshot_manager = getattr(self, "snapshot_manager", None)
            if snapshot_manager is not None:
                snapshot_manager.delete_for_set(progress_record.set_id)
        self._refresh_first_run()

        study_intent = self.study_flow.take_active_intent()
        if (
            progress_record is not None
            and isinstance(study_intent, StudyIntent)
            and study_intent.action is StudyAction.DAILY_QUEUE
            and getattr(self, "daily_plan_store", None) is not None
            and study_intent.plan_id
        ):
            try:
                daily_plan = self.daily_plan_store.record_completion(
                    study_intent.plan_id,
                    current_question_ids=study_intent.question_ids,
                    answers=progress_record.answers,
                )
                study_intent = StudyIntent(
                    course_id=study_intent.course_id,
                    action=study_intent.action,
                    topic_ids=study_intent.topic_ids,
                    question_ids=study_intent.question_ids,
                    remaining_question_ids=daily_plan.pending_ids,
                    question_count=study_intent.question_count,
                    source=study_intent.source,
                    plan_id=study_intent.plan_id,
                )
            except (KeyError, OSError, TypeError, ValueError):
                pass

        self.results_screen.set_results(
            progress_record,
            questions=self._active_questions,
            lang=self.lang_manager.current,
            study_intent=study_intent,
        )
        self.navigate_to(self.SCREEN_RESULTS)

    def _on_open_progress_record(self, progress_id: str) -> None:
        """Open one persisted result, using archived snapshots when assets are gone."""
        record = self.progress_manager.get(progress_id)
        if record is None:
            QMessageBox.warning(
                self if isinstance(self, QWidget) else None,
                self.lang_manager.get_text("记录不可用", "Record Unavailable"),
                self.lang_manager.get_text(
                    "该练习记录已不存在，请刷新进度页。",
                    "This practice record no longer exists. Refresh the progress page.",
                ),
            )
            return

        question_ids = list(dict.fromkeys(
            answer.question_id
            for answer in record.answers
            if answer.question_id
        ))
        questions = self.question_bank.get_many(question_ids)
        self._active_questions = {
            question.question_id: question for question in questions
        }
        self.results_screen.set_results(
            record,
            questions=self._active_questions,
            lang=self.lang_manager.current,
            study_intent=None,
        )
        self._refresh_results_retry_availability()
        self.navigate_to(self.SCREEN_RESULTS)

    def _on_retry_incorrect(self):
        """Retry only incorrectly answered questions."""
        MainWindow._retry_current_session(self, SessionRetryMode.INCORRECT)

    def _on_retry_unsure(self):
        """Retry questions the user marked as unsure in the completed session."""
        MainWindow._retry_current_session(self, SessionRetryMode.UNSURE)

    def _on_retry_review(self):
        """Retry questions the user marked for review in the completed session."""
        MainWindow._retry_current_session(self, SessionRetryMode.REVIEW)

    def _retry_current_session(self, mode: SessionRetryMode) -> None:
        """Start one retry subset from the current completed session."""
        gm = self.lang_manager.get_text
        record = self.results_screen.current_record
        if not record:
            return
        copy = session_retry_copy(mode)
        question_ids = session_retry_question_ids(record, mode)
        parent = self if isinstance(self, QWidget) else None
        if not question_ids:
            QMessageBox.information(
                parent,
                gm(copy.empty_title_zh, copy.empty_title_en),
                gm(copy.empty_detail_zh, copy.empty_detail_en),
            )
            return
        questions = self.question_bank.get_many(
            question_ids,
            course_id=self._current_course_id(),
        )
        if not questions:
            QMessageBox.warning(
                parent,
                gm("题目不可用", "Questions Unavailable"),
                gm(
                    "这些题目已被删除，或不属于当前课程。请返回结果页选择其他练习。",
                    "These questions were deleted or do not belong to the current course. Choose another practice action from Results.",
                ),
            )
            return
        self._active_questions = {question.question_id: question for question in questions}
        self.quiz_screen.start_quiz_custom(
            questions,
            gm(copy.session_title_zh, copy.session_title_en),
            show_timer=self._show_timer_setting(),
        )
        self.navigate_to(self.SCREEN_QUIZ)

    def _on_practice_incorrect(self, intent: StudyIntent | None = None):
        """Start a quiz session from all historical incorrect questions."""
        gm = self.lang_manager.get_text
        incorrect_ids = (
            list(intent.question_ids)
            if isinstance(intent, StudyIntent) and intent.question_ids
            else self.progress_manager.get_prioritized_review_question_ids()
        )
        if not incorrect_ids:
            QMessageBox.information(
                self,
                gm("没有错题", "No Incorrect Questions"),
                gm("还没有错题记录。", "No incorrect questions recorded yet."),
            )
            return

        questions = self.question_bank.get_many(
            incorrect_ids,
            course_id=self._current_course_id(),
        )
        course_id = self._current_course_id()
        mastery_overrides = getattr(self, "mastery_overrides", None)
        if mastery_overrides is not None:
            questions = [
                question for question in questions
                if not mastery_overrides.is_topic_mastered(course_id, question.topic)
            ]
        if isinstance(intent, StudyIntent) and intent.question_count > 0:
            questions = questions[:intent.question_count]
        if not questions:
            QMessageBox.warning(
                self,
                gm("没有题目", "No Questions"),
                gm(
                    "存在错题记录，但题目文件缺失，或相关主题已标记为已掌握。",
                    "Incorrect records exist, but question files are missing or their topics are marked mastered.",
                ),
            )
            return

        self._active_questions = {q.question_id: q for q in questions}
        label = gm("历史错题复习", "Incorrect Review")
        self.quiz_screen.start_quiz_custom(questions, label, show_timer=self._show_timer_setting())
        self.navigate_to(self.SCREEN_QUIZ)

    def _on_practice_progress_topic(self, topic_key: str):
        """Start a short practice session for the selected progress topic."""
        gm = self.lang_manager.get_text
        topic_key = topic_value(topic_key)
        questions = MainWindow._progress_topic_questions(self, topic_key)
        if not questions:
            QMessageBox.information(
                self,
                gm("没有题目", "No Questions"),
                gm("该主题下没有可练习的题目。", "No questions are available for this topic."),
            )
            return
        selected = questions[:10]
        topic_name = MainWindow._progress_topic_label(self, topic_key, selected)
        MainWindow._start_progress_topic_quiz(
            self,
            selected,
            gm(f"{topic_name}：主题练习", f"{topic_name}: Topic Practice"),
        )

    def _on_review_progress_topic(self, topic_key: str):
        """Start a practice session from incorrect questions in the selected topic."""
        gm = self.lang_manager.get_text
        topic_key = topic_value(topic_key)
        topic_questions = MainWindow._progress_topic_questions(self, topic_key)
        candidate_ids = {question.question_id for question in topic_questions}
        prioritized_ids = self.progress_manager.get_prioritized_review_question_ids(candidate_ids)
        questions = [
            question
            for question in self.question_bank.get_many(
                prioritized_ids,
                course_id=self._current_course_id(),
            )
            if topic_value(question.topic) == topic_key
        ]
        if not questions:
            QMessageBox.information(
                self,
                gm("没有该主题错题", "No Incorrect Questions"),
                gm("该主题下暂无需要复习的错题。", "This topic has no incorrect questions to review."),
            )
            return
        topic_name = MainWindow._progress_topic_label(self, topic_key, questions)
        MainWindow._start_progress_topic_quiz(
            self,
            questions,
            gm(f"{topic_name}：错题复习", f"{topic_name}: Incorrect Review"),
        )

    def _progress_topic_questions(self, topic_key: str):
        """Return current-course questions matching a progress topic key."""
        return self.question_bank.filter_by_topic(
            topic_key,
            course_id=self._current_course_id(),
        )

    def _progress_topic_label(self, topic_key: str, questions: list) -> str:
        """Return a readable topic label for progress-triggered sessions."""
        lang = self.lang_manager.current
        course_manager = getattr(self, "course_manager", None)
        course_project = (
            course_manager.get(self._current_course_id()) if course_manager else None
        )
        fallback_title = questions[0].topic_title() if questions else ""
        topic = questions[0].topic if questions else topic_key
        return topic_display_name(topic, course_project, lang, fallback_title)

    def _on_generate_progress_topic(self, topic_key: str):
        """Open generation review prefilled for exactly one progress topic."""
        topic_key = topic_value(topic_key)
        if not topic_key:
            return
        self._on_ai_generate(initial_plan=ExamGenerationPlan(
            question_count=10,
            selected_topics=(topic_key,),
            topic_weights={topic_key: 100},
        ))

    def _start_progress_topic_quiz(self, questions: list, label: str):
        """Open QuizScreen for a progress-topic action."""
        self._active_questions = {question.question_id: question for question in questions}
        self.quiz_screen.start_quiz_custom(
            questions,
            label,
            show_timer=self._show_timer_setting(),
            submission_mode="practice",
        )
        self.navigate_to(self.SCREEN_QUIZ)

    def _prepare_generation_dialog(
        self,
        *,
        course_override=None,
        material_pack=None,
        purpose: str = "create",
    ):
        """Prepare one validated generation dialog for create or regenerate."""
        gm = self.lang_manager.get_text
        context_provider = getattr(
            self,
            "_load_generation_context",
            lambda: ("", [], None),
        )
        controller = GenerationLaunchController(
            settings_provider=self.settings_screen.settings_snapshot,
            course_context_provider=context_provider,
            task_center=getattr(self, "task_center", None),
            api_key_required=_provider_requires_api_key,
            settings_validator=_ai_generation_settings_error,
        )
        preparation = controller.prepare(
            self,
            course_override=course_override,
            material_pack=material_pack,
        )
        if preparation.ok:
            return preparation
        copy = generation_launch_copy(preparation.issue, purpose=purpose)
        detail = preparation.message or gm(copy.detail_zh, copy.detail_en)
        QMessageBox.warning(
            self,
            gm(copy.title_zh, copy.title_en),
            detail,
        )
        return None

    def _on_ai_generate(
        self,
        *,
        course_override=None,
        initial_plan=None,
        prediction=None,
        material_pack=None,
        recovery_context=None,
        auto_start: bool = False,
        start_after_save: bool = False,
        review_warnings_only: bool = False,
        question_set_title: str = "",
    ):
        """Open the AI question generation dialog."""
        gm = self.lang_manager.get_text
        preparation = MainWindow._prepare_generation_dialog(
            self,
            course_override=course_override,
            material_pack=material_pack,
            purpose="create",
        )
        if preparation is None:
            return
        dialog = preparation.dialog
        course_project = preparation.course_project
        if initial_plan is not None:
            try:
                dialog.apply_exam_plan(initial_plan)
            except ValueError as exc:
                QMessageBox.warning(
                    self,
                    gm("预测配置不可用", "Prediction Plan Unavailable"),
                    str(exc),
                )

                return
            if prediction is not None and hasattr(dialog, "set_title_input"):
                course_title = str(getattr(course_project, "title", "") or "").strip()
                dialog.set_title_input.setText(gm(
                    f"{course_title}预测模拟卷" if course_title else "预测模拟卷",
                    f"{course_title} Predicted Mock Exam" if course_title else "Predicted Mock Exam",
                ))
            if prediction is not None and hasattr(dialog, "status_label"):
                dialog.status_label.setText(
                    prediction_prefill_status(prediction, gm)
                )
        if question_set_title and hasattr(dialog, "set_title_input"):
            dialog.set_title_input.setText(str(question_set_title).strip())
        if isinstance(recovery_context, dict):
            if hasattr(dialog, "set_title_input"):
                title = str(recovery_context.get("question_set_title", "") or "").strip()
                if title:
                    dialog.set_title_input.setText(title)
            if hasattr(dialog, "runtime_instruction_input"):
                instruction = str(recovery_context.get("runtime_instruction", "") or "").strip()
                dialog.runtime_instruction_input.setPlainText(instruction)
        if review_warnings_only:
            dialog.set_review_warnings_only(True)
        if auto_start:
            dialog.start_generation_when_shown()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            questions = dialog.generated_questions
            if questions:
                lang = self.lang_manager.current
                qset = build_ai_question_set(
                    questions,
                    selected_difficulty=dialog.diff_combo.currentData(),
                    generation_config=dialog._build_generation_config(),
                    lang=lang,
                    course_project=course_project,
                    custom_title=dialog.question_set_title(),
                    material_pack=material_pack,
                )
                try:
                    qset, saved = persist_new_question_set(
                        self.question_bank,
                        self.set_manager,
                        qset,
                        questions,
                    )
                except RuntimeError as exc:
                    QMessageBox.critical(
                        self if isinstance(self, QWidget) else None,
                        gm("保存失败", "Save Failed"),
                        str(exc),
                    )
                    return
                refresh_question_bank = getattr(
                    self,
                    "_on_question_bank_changed",
                    None,
                )
                if callable(refresh_question_bank):
                    refresh_question_bank()
                if start_after_save:
                    self._on_quiz_start(qset.set_id, list(qset.questions))
                    return
                QMessageBox.information(
                    self,
                    gm("已保存", "Saved"),
                    gm(f"已保存 {saved} 道题目并创建了题目集：\n{qset.get_title(lang)}",
                       f"Saved {saved} questions and created a question set:\n{qset.get_title(lang)}"),
                )
                self.navigate_to(self.SCREEN_TOPIC_SELECTION)

    def _on_current_event_generation(self, course_id: str, material_pack) -> None:
        """Generate against the reviewed material pack for its selected course."""
        project = self.course_manager.get(course_id)
        if project is None or material_pack is None:
            return
        self._on_ai_generate(course_override=project, material_pack=material_pack)

    def _on_generate_predicted_exam(self, course_id: str, prediction):
        """Open the normal generation review flow with a historical profile plan."""
        course = self.course_manager.get(course_id)
        if course is None:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("课程不存在", "Course Not Found"),
                self.lang_manager.get_text(
                    "该真题关联的课程已不存在，请重新选择课程。",
                    "The course linked to this exam no longer exists. Choose another course.",
                ),
            )
            return
        self._on_ai_generate(
            course_override=course,
            initial_plan=prediction.plan,
            prediction=prediction,
        )

    def _on_regenerate_question_set(self, set_id: str):
        """Regenerate questions for an existing question set in place."""
        if (
            self._history_protection_blocked
            and not self._confirm_history_sensitive_navigation(
                self.SCREEN_QUESTION_BANK
            )
        ):
            return
        gm = self.lang_manager.get_text
        qset = self.set_manager.get(set_id)
        if not qset:
            QMessageBox.warning(self, gm("错误", "Error"), gm("未找到题目集。", "Question set not found."))
            return

        preparation = MainWindow._prepare_generation_dialog(
            self,
            purpose="regenerate",
        )
        if preparation is None:
            return
        dialog = preparation.dialog
        course_project = preparation.course_project
        dialog.configure_from_question_set(qset)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        questions = dialog.generated_questions
        if not questions:
            QMessageBox.warning(self, gm("没有题目", "No Questions"), gm("未生成可保存的题目。", "No generated questions to save."))
            return

        selected_diff = dialog.diff_combo.currentData()
        difficulty = qset.difficulty
        if selected_diff in {d.value for d in Difficulty}:
            difficulty = Difficulty(selected_diff)
        try:
            qset, saved, deleted = persist_regenerated_question_set(
                self.question_bank,
                self.set_manager,
                self.progress_manager,
                qset,
                questions,
                difficulty=difficulty,
                course_project=course_project,
            )
        except RuntimeError as exc:
            QMessageBox.critical(
                self,
                gm("保存失败", "Save Failed"),
                str(exc),
            )
            return
        self.topic_screen.refresh()
        cleanup_note = gm(
            f"\n已清理 {len(deleted)} 道无引用旧 AI 题目。" if deleted else "",
            f"\nCleaned up {len(deleted)} unreferenced old AI question(s)." if deleted else "",
        )
        QMessageBox.information(
            self,
            gm("已重新生成", "Regenerated"),
            gm(f"已保存 {saved} 道新题，并更新题目集：\n{qset.get_title(self.lang_manager.current)}{cleanup_note}",
               f"Saved {saved} new questions and updated question set:\n{qset.get_title(self.lang_manager.current)}{cleanup_note}"),
        )
        self.navigate_to(self.SCREEN_TOPIC_SELECTION)

    def _on_retry_all(self):
        """Retry the entire question set."""
        record = self.results_screen.current_record
        if not record or not record.set_id:
            return

        question_set = self.set_manager.get(record.set_id)
        if question_set is None:
            gm = self.lang_manager.get_text
            parent = self if isinstance(self, QWidget) else None
            QMessageBox.warning(
                parent,
                gm("原题不可用", "Original Questions Unavailable"),
                gm(
                    "原题集已被删除。当前历史记录仍可查看，但无法重新练习。",
                    "The original question set was deleted. The archived result remains "
                    "viewable, but it cannot be retried.",
                ),
            )
            return
        questions = self.question_bank.get_many(question_set.questions)
        if not questions:
            gm = self.lang_manager.get_text
            parent = self if isinstance(self, QWidget) else None
            QMessageBox.warning(
                parent,
                gm("原题不可用", "Original Questions Unavailable"),
                gm(
                    "原题已被删除。当前历史记录仍可查看，但无法重新练习。",
                    "The original questions were deleted. The archived result remains "
                    "viewable, but it cannot be retried.",
                ),
            )
            return
        self._active_questions = {q.question_id: q for q in questions}
        self.quiz_screen.start_quiz(
            question_set,
            questions,
            show_timer=self._show_timer_setting(),
            submission_mode="practice",
        )
        self.navigate_to(self.SCREEN_QUIZ)

    def _show_timer_setting(self) -> bool:
        return bool(self.settings_screen.get_setting("show_timer", False))

    def _on_course_changed(self):
        """Refresh app state after switching/importing course projects."""
        self._sync_home_screen_course()
        self._sync_topic_screen_course()
        self._sync_question_bank_screen_course()
        self._sync_progress_screen_course()
        self._refresh_results_retry_availability()
        self._refresh_first_run()
        self._on_language_changed()

    def _on_question_bank_changed(self):
        """Refresh views affected by question CRUD."""
        self.question_bank.clear_cache()
        self.home_screen.refresh()
        self.topic_screen.refresh()
        self._refresh_results_retry_availability()
        self._refresh_first_run()

    def _refresh_results_retry_availability(self) -> None:
        record = getattr(self.results_screen, "current_record", None)
        if record is None:
            return
        answer_ids = [answer.question_id for answer in record.answers]
        available = self.question_bank.get_many(
            answer_ids,
            course_id=self._current_course_id(),
        )
        question_set = self.set_manager.get(record.set_id) if record.set_id else None
        set_questions = (
            self.question_bank.get_many(question_set.questions)
            if question_set is not None
            else []
        )
        self.results_screen.set_retry_availability(
            [question.question_id for question in available],
            can_retry_all=bool(question_set is not None and set_questions),
        )

    def _load_generation_context(self) -> tuple[str, list, object]:
        """Load active course summary and topics for AI generation.
        Returns (content, topics, project). Caller should check for empty content
        and show a message if needed."""
        gm = self.lang_manager.get_text
        course = self.course_manager.current()
        if course:
            scoped_topics = getattr(course, "exam_topics", None)
            topics = list(
                scoped_topics()
                if callable(scoped_topics)
                else getattr(course, "topics", []) or []
            )
            if not topics and getattr(course, "exam_scope_mode", "all") != "selected":
                topics = [gm("综合", "General")]
            return course.summary_markdown, topics, course
        return "", [], None

    def _sync_topic_screen_course(self):
        course = self.course_manager.current()
        self.topic_screen.set_current_course(
            course.course_id if course else "",
            course.title if course else "",
        )

    def _sync_question_bank_screen_course(self):
        if self._question_bank_screen is None:
            return
        self._question_bank_screen.set_current_course(self._current_course_id())

    def _sync_home_screen_course(self):
        course = self.course_manager.current()
        exam_topic_ids = None
        exam_scope_weights = {}
        if course and getattr(course, "exam_scope_mode", "all") == "selected":
            scoped_topics = getattr(course, "exam_topics", None)
            topics = scoped_topics() if callable(scoped_topics) else getattr(course, "topics", [])
            exam_topic_ids = {topic.topic_id for topic in topics}
        if course:
            allowed_topics = {
                topic.topic_id
                for topic in (
                    course.exam_topics()
                    if callable(getattr(course, "exam_topics", None))
                    else getattr(course, "topics", [])
                )
            }
            profile = getattr(course, "generation_profile", {}) or {}
            raw_weights = (
                profile.get("topic_weights", {})
                if isinstance(profile, dict)
                else {}
            )
            if isinstance(raw_weights, dict):
                exam_scope_weights = {
                    str(topic_id): weight
                    for topic_id, weight in raw_weights.items()
                    if str(topic_id) in allowed_topics
                }
        self.home_screen.set_current_course(
            course.course_id if course else "",
            course.title if course else "",
            exam_topic_ids,
            exam_scope_weights=exam_scope_weights,
        )
        self._update_home_resume_draft()

    def _sync_progress_screen_course(self):
        self.progress_screen.set_current_course(self._current_course_id())

    def _current_course_id(self) -> str:
        course = self.course_manager.current()
        return course.course_id if course else ""

    def _show_about(self):
        """Show the About dialog."""
        gm = self.lang_manager.get_text
        QMessageBox.about(
            self,
            gm("关于", "About"),
            f"<b>{APP_NAME}</b><br><br>"
            f"{gm('一个基于PyQt的课件导入与刷题工具。', 'A PyQt-based course-material ingestion and quiz practice tool.')}<br><br>"
            f"{gm('功能特性：', 'Features:')}<br>"
            f"{gm('• 导入PPTX/PDF/DOCX/TXT/Markdown课件', '• Import PPTX/PDF/DOCX/TXT/Markdown course materials')}<br>"
            f"{gm('• 导入文本或OCR历史真题', '• Import text or OCR historical exams')}<br>"
            f"{gm('• 生成可复用的课件摘要', '• Generate reusable course summaries')}<br>"
            f"{gm('• AI生成双语题目', '• AI-generated bilingual questions')}<br>"
            f"{gm('• 选择题/判断题自动评分', '• Auto-grading for multiple choice / true-false')}<br>"
            f"{gm('• 进度追踪', '• Progress tracking')}<br>"
            f"{gm('• 可复用的本地JSON题目集', '• Reusable local JSON question sets')}"
        )

    def closeEvent(self, event):
        """Confirm active quiz exit before closing, then save settings."""
        if self.stack.currentIndex() == self.SCREEN_QUIZ and not self.quiz_screen.confirm_exit():
            event.ignore()
            return
        if self._course_screen is not None and not self._course_screen.request_shutdown():
            event.ignore()
            return
        if self._past_exam_screen is not None and not self._past_exam_screen.request_shutdown():
            event.ignore()
            return
        self.settings_screen.save_settings(silent=True)
        super().closeEvent(event)
