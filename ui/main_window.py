"""Main window — application shell with QStackedWidget navigation."""

from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget,
    QMessageBox, QWidget, QPushButton,
)
from PyQt6.QtCore import QTimer, Qt

from core.application_services import ApplicationServices
from core.language_manager import LanguageManager
from core.background_task_presenter import build_task_center_view, task_toolbar_text
from core.topic_display import topic_display_name
from core.study_intent import StudyAction, StudyIntent
from ui.dialogs.background_task_dialog import BackgroundTaskDialog
from ui.course_context_controller import CourseContextController
from ui.generation_workspace_controller import GenerationWorkspaceController
from ui.first_run_controller import FirstRunController
from ui.history_protection_controller import HistoryProtectionController
from ui.question_set_action_controller import QuestionSetActionController
from ui.result_flow_controller import ResultFlowController
from ui.study_flow_controller import StudyFlowController
from ui.task_recovery_controller import TaskRecoveryController
from ui.workspace_navigation_controller import WorkspaceNavigationController
from ui.navigation import (
    NavigationRouter,
    Route,
    ScreenKey,
    Workspace,
)
from ui.shell import AppShell
from config import APP_NAME, APP_NAME_EN

from ui.screens.home_screen import HomeScreen
from ui.screens.first_run_workspace import FirstRunWorkspace
from ui.screens.generation_workspace import GenerationWorkspace
from ui.screens.topic_selection_screen import TopicSelectionScreen
from ui.screens.quiz_screen import QuizScreen
from ui.screens.results_screen import ResultsScreen
from ui.screens.progress_dashboard import ProgressDashboard
from ui.settings_window import SettingsWindow
from utils.constants import topic_value
from ai.exam_plan import ExamGenerationPlan
from models.question_set import QuestionSet
from models.remediation import RemediationRequest


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
    SCREEN_GENERATION = 8
    SCREEN_INDEX_BY_KEY = {
        ScreenKey.HOME: SCREEN_HOME,
        ScreenKey.TOPIC_SELECTION: SCREEN_TOPIC_SELECTION,
        ScreenKey.QUIZ: SCREEN_QUIZ,
        ScreenKey.RESULTS: SCREEN_RESULTS,
        ScreenKey.PROGRESS: SCREEN_PROGRESS,
        ScreenKey.COURSES: SCREEN_COURSES,
        ScreenKey.QUESTION_BANK: SCREEN_QUESTION_BANK,
        ScreenKey.PAST_EXAMS: SCREEN_PAST_EXAMS,
        ScreenKey.GENERATION: SCREEN_GENERATION,
    }

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
        self.generation_draft_store = getattr(
            services,
            "generation_draft_store",
            None,
        )
        self.exam_goal_store = getattr(services, "exam_goal_store", None)
        self._ensure_default_current_course()
        self.lang_manager = LanguageManager.instance()
        self.startup_migration_report = startup_migration_report
        self._first_run_operation = ""
        self._first_run_error = ""
        self._first_run_progress = None
        self._last_generation_launch_error = ""
        self._generation_close_pending = False
        self._generation_workspace = None
        self._history_protection_blocked = bool(
            getattr(startup_migration_report, "has_failures", False)
        )
        self.history_protection = HistoryProtectionController(self)
        self.first_run = FirstRunController(self)
        self.course_context = CourseContextController(self)
        self.workspace_navigation = WorkspaceNavigationController(self)
        self.result_flow = ResultFlowController(self)
        self.generation_flow = GenerationWorkspaceController(
            self,
            workspace_provider=lambda: self._get_generation_workspace(),
        )
        self.question_set_actions = QuestionSetActionController(self)

        # Central stacked widget
        self.stack = QStackedWidget()
        self.navigation_router = NavigationRouter(
            self.stack,
            skip_history_from={self.SCREEN_QUIZ},
            resolve_destination=self._screen_index_for_route,
            initial_destination=Route.study("today"),
        )

        # Create screens
        self.home_screen = HomeScreen(
            self.progress_manager,
            self.question_bank,
            course_manager=self.course_manager,
            mastery_overrides=self.mastery_overrides,
            daily_plan_store=self.daily_plan_store,
            exam_goal_store=self.exam_goal_store,
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

        # Secondary workspaces are lazily created on first access.
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
            (self.SCREEN_GENERATION, "generation"),
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
            current_course_id=self.course_context.current_course_id,
            course_changed=self.course_context.course_changed,
            resume_session=self._on_resume_abandoned,
            review_questions=self.result_flow.practice_incorrect,
            generate_questions=self.generation_flow.open,
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
            course_changed=self.course_context.course_changed,
            get_course_screen=self._get_course_screen,
            get_past_exam_screen=self._get_past_exam_screen,
            generate_questions=self.generation_flow.open,
            courses_screen_index=self.SCREEN_COURSES,
            past_exams_screen_index=self.SCREEN_PAST_EXAMS,
            question_bank_screen_index=self.SCREEN_QUESTION_BANK,
        )

        # Keep the shell free of duplicate menu navigation.
        self.menuBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Connect screen navigation signals
        self._connect_signals()
        self.course_context.sync_home()
        self.course_context.sync_topic_screen()
        self.course_context.sync_progress()
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
        self.history_protection.show_startup_warning()

    def _ensure_default_current_course(self) -> None:
        """Restore a usable course context when persisted data has no selection."""
        try:
            if self.course_manager.current() is not None:
                return
            courses = self.course_manager.load_all()
            if courses:
                self.course_manager.set_current(courses[0].course_id)
        except (OSError, TypeError, ValueError):
            # Startup remains usable even when course metadata needs repair.
            return

    def _history_protection_message(self) -> str:
        return self.history_protection.message()

    def _confirm_history_sensitive_navigation(self, screen_index: int) -> bool:
        return self.history_protection.confirm_navigation(screen_index)

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
                generation_draft_store=self.generation_draft_store,
                exam_goal_store=self.exam_goal_store,
                task_center=self.task_center,
            )
            self._course_screen.current_course_changed.connect(
                self.course_context.course_changed
            )
            self._course_screen.generate_questions_requested.connect(
                lambda _course_id: self.generation_flow.open()
            )
            self._course_screen.course_topic_action_requested.connect(
                self._on_course_topic_action
            )
            self._course_screen.view_course_library_requested.connect(
                self._open_course_library
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
            from ui.screens.library_screen import LibraryScreen
            self._question_bank_screen = LibraryScreen(
                self.question_bank,
                set_manager=self.set_manager,
                course_manager=self.course_manager,
                progress_manager=self.progress_manager,
                task_center=self.task_center,
                generation_draft_store=self.generation_draft_store,
            )
            self.course_context.sync_question_bank()
            self._question_bank_screen.question_bank_changed.connect(
                self.course_context.question_bank_changed
            )
            self._question_bank_screen.sets_changed.connect(
                self.topic_screen.refresh
            )
            self._question_bank_screen.export_mock_exam.connect(
                self.question_set_actions.export_mock_exam
            )
            self._question_bank_screen.export_mock_exams.connect(
                self.question_set_actions.export_mock_exams
            )
            self._question_bank_screen.regenerate_questions.connect(
                self.question_set_actions.regenerate
            )
            self._question_bank_screen.resume_generation_draft.connect(
                self.generation_flow.resume_draft
            )
            self._install_workspace(
                self.SCREEN_QUESTION_BANK,
                self._question_bank_screen,
            )
        return self._question_bank_screen

    def _open_course_library(self, course_id: str) -> None:
        """Open one active or archived course's assets without changing status."""
        if not self.navigate_to(
            self.SCREEN_QUESTION_BANK,
            allow_first_run_redirect=False,
        ):
            return
        self._get_question_bank_screen().show_course_assets(course_id)

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

    def _get_generation_workspace(self):
        """Lazy-init the persistent course-owned generation workspace."""
        if self._generation_workspace is None:
            self._generation_workspace = GenerationWorkspace()
            self._install_workspace(
                self.SCREEN_GENERATION,
                self._generation_workspace,
            )
        return self._generation_workspace

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
                (
                    "learning_nav_btn",
                    Workspace.STUDY,
                    Route.study("today"),
                ),
                (
                    "courses_nav_btn",
                    Workspace.COURSE,
                    Route.course(),
                ),
                (
                    "library_nav_btn",
                    Workspace.LIBRARY,
                    Route.library("questions"),
                ),
            ),
            context_routes=(
                ("today_tab_btn", Route.study("today")),
                ("topics_tab_btn", Route.study("practice")),
                ("progress_tab_btn", Route.study("analysis")),
                ("course_overview_tab_btn", Route.course(tab="overview")),
                ("course_sources_tab_btn", Route.course(tab="sources")),
                ("course_knowledge_tab_btn", Route.course(tab="knowledge")),
                ("course_generation_tab_btn", Route.course(tab="generation")),
                ("course_qa_tab_btn", Route.course(tab="qa")),
                ("bank_tab_btn", Route.library("questions")),
                ("sets_tab_btn", Route.library("sets")),
                ("past_exams_tab_btn", Route.library("past_exams")),
                ("drafts_tab_btn", Route.library("drafts")),
            ),
            navigate=self.navigate_route,
            open_settings=self.open_settings,
            navigate_back=self.navigate_back,
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
            "task_center_btn",
            "learning_nav_btn",
            "courses_nav_btn",
            "library_nav_btn",
            "today_tab_btn",
            "topics_tab_btn",
            "progress_tab_btn",
            "course_overview_tab_btn",
            "course_sources_tab_btn",
            "course_knowledge_tab_btn",
            "course_generation_tab_btn",
            "course_qa_tab_btn",
            "bank_tab_btn",
            "sets_tab_btn",
            "past_exams_tab_btn",
            "drafts_tab_btn",
        ):
            setattr(self, attribute, getattr(self.app_shell, attribute))
        self.setCentralWidget(self.app_shell)

    def navigation_buttons(self) -> tuple[QPushButton, ...]:
        return self.app_shell.navigation_buttons()

    def context_tabs(self) -> tuple[QPushButton, ...]:
        return self.app_shell.context_tabs()

    def _connect_signals(self):
        # Home screen
        self.home_screen.start_practice.connect(self._on_start_practice)
        self.home_screen.study_requested.connect(self._handle_study_intent)
        self.home_screen.resume_practice.connect(self._on_resume_abandoned)
        self.home_screen.practice_incorrect.connect(
            self.result_flow.practice_incorrect
        )
        self.home_screen.ai_generate.connect(self.generation_flow.open)
        self.home_screen.view_progress.connect(lambda: self.navigate_to(self.SCREEN_PROGRESS))
        self.home_screen.open_settings.connect(self.open_settings)
        self.home_screen.manage_courses.connect(lambda: self.navigate_to(self.SCREEN_COURSES))
        self.home_screen.open_course_requested.connect(
            self._on_home_course_requested
        )
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
        self.first_run_screen.restore_courses_requested.connect(
            self._open_archived_courses
        )
        self.settings_screen.settings_saved.connect(
            self._on_first_run_settings_saved
        )

        # Topic selection
        self.topic_screen.study_start.connect(self._on_study_quiz_start)
        self.topic_screen.generate_missing.connect(self.study_flow.generate_missing)
        self.topic_screen.today_mode_requested.connect(
            lambda: self.navigate_to(self.SCREEN_HOME)
        )

        # Quiz screen
        self.quiz_screen.quiz_finished.connect(self.result_flow.quiz_finished)
        self.quiz_screen.return_home.connect(
            lambda: self.navigate_to(self.SCREEN_HOME, confirm_current=False)
        )

        # Results screen
        self.results_screen.retry_incorrect.connect(
            self.result_flow.retry_incorrect
        )
        self.results_screen.retry_unsure.connect(
            self.result_flow.retry_unsure
        )
        self.results_screen.retry_review.connect(
            self.result_flow.retry_review
        )
        self.results_screen.retry_all.connect(self.result_flow.retry_all)
        self.results_screen.study_requested.connect(self._handle_study_intent)
        self.results_screen.practice_topic_requested.connect(self._on_practice_progress_topic)
        self.results_screen.review_topic_requested.connect(self._on_review_progress_topic)
        self.results_screen.generate_reinforcement_requested.connect(
            self._on_generate_result_reinforcement
        )
        self.progress_screen.practice_topic_requested.connect(self._on_practice_progress_topic)
        self.progress_screen.review_topic_requested.connect(self._on_review_progress_topic)
        self.progress_screen.generate_topic_requested.connect(self._on_generate_progress_topic)
        self.progress_screen.history_requested.connect(
            self.result_flow.open_progress_record
        )
        # Language manager
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang: str = None):
        """Update all UI text based on current language."""
        lang = lang or self.lang_manager.current
        gm = self.lang_manager.get_text

        self.sidebar_title.setText(gm(APP_NAME, APP_NAME_EN))
        self.app_shell.render_language(gm)
        self._refresh_task_center_action()
        self._update_navigation_actions()

    def _on_home_course_requested(self, course_id: str) -> None:
        """Switch the active course from the compact home agenda."""
        course_id = str(course_id or "").strip()
        if not course_id or not self.course_manager.set_current(course_id):
            return
        self.course_context.course_changed()

    def navigate_to(
        self,
        screen_index: int,
        remember: bool = True,
        confirm_current: bool = True,
        *,
        allow_first_run_redirect: bool = True,
    ) -> bool:
        """Compatibility boundary for callers that still hold a stack index."""
        return self.workspace_navigation.navigate_index(
            screen_index,
            remember=remember,
            confirm_current=confirm_current,
            allow_first_run_redirect=allow_first_run_redirect,
        )

    @property
    def current_route(self) -> Route:
        return self.workspace_navigation.current_route()

    def _screen_index_for_route(self, route) -> int:
        return self.workspace_navigation.screen_index(route)

    def navigate_route(
        self,
        route: Route,
        remember: bool = True,
        confirm_current: bool = True,
        *,
        allow_first_run_redirect: bool = True,
    ) -> bool:
        """Navigate by product semantics instead of numeric widget position."""
        return self.workspace_navigation.navigate(
            route,
            remember=remember,
            confirm_current=confirm_current,
            allow_first_run_redirect=allow_first_run_redirect,
        )

    def navigate_back(self):
        """Return to the previous screen if navigation history exists."""
        self.workspace_navigation.back()

    def _update_navigation_actions(self):
        """Keep shell navigation buttons in sync with current location."""
        self.workspace_navigation.update_actions()

    def open_settings(self, section: str = "") -> None:
        """Open settings as a utility window without leaving the workspace."""
        self.settings_window.show_settings(section)

    def _on_first_run_settings_saved(self) -> None:
        self.first_run.settings_saved()

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
        return self.first_run.ai_error()

    def _first_run_required(self) -> bool:
        return self.first_run.required()

    def _archived_course_count(self) -> int:
        return self.first_run.archived_course_count()

    def _open_archived_courses(self) -> None:
        self.first_run.open_archived_courses()

    def _refresh_first_run(self) -> None:
        self.first_run.refresh()

    def _on_first_run_choose_materials(self) -> None:
        self.first_run.choose_materials()

    def _on_first_run_import_started(self) -> None:
        self.first_run.import_started()

    def _on_first_run_import_progress(self, progress) -> None:
        self.first_run.import_progress(progress)

    def _on_first_run_import_completed(self, _project) -> None:
        self.first_run.import_completed(_project)

    def _on_first_run_import_failed(self, message: str) -> None:
        self.first_run.import_failed(message)

    def _on_first_run_import_cancelled(self) -> None:
        self.first_run.import_cancelled()

    def _on_first_run_generate(self) -> None:
        self.first_run.generate()

    def _on_first_run_start(self) -> None:
        self.first_run.start()

    def _on_first_run_cancel(self) -> None:
        self.first_run.cancel()

    # --- Slot handlers ---

    def _handle_study_intent(self, intent: StudyIntent) -> None:
        """Route one typed user intent through the study controller."""
        self.study_flow.handle_intent(intent)

    def _on_start_practice(self):
        self.study_flow.clear_setup()
        self.navigate_to(self.SCREEN_TOPIC_SELECTION)

    def _on_study_quiz_start(
        self,
        intent: StudyIntent,
        question_ids: list[str],
    ) -> None:
        """Start the prefilled practice without asking for scope again."""
        self.study_flow.start_prefilled(intent, question_ids)

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
            course_id=self.course_context.current_course_id(),
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
            else self.course_context.current_course_id()
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
            self.quiz_screen.restore_snapshot(
                snapshot,
                questions,
                question_set,
                show_timer=self._show_timer_setting(),
            )
            if study_intent is None:
                study_intent = StudyIntent(
                    course_id=self.course_context.current_course_id(),
                    action=StudyAction.CUSTOM_PRACTICE,
                    set_id=question_set.set_id,
                    question_ids=tuple(snapshot.question_order),
                    question_count=len(snapshot.question_order),
                    submission_mode=snapshot.mode,
                    source="snapshot_resume",
                )
            self.study_flow.restore_active_intent(study_intent, questions)
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
        label = gm(
            f"继续草稿：{question_set.get_title('zh')}",
            f"Resume Draft: {question_set.get_title('en')}",
        )
        intent = StudyIntent(
            course_id=self.course_context.current_course_id(),
            action=StudyAction.CUSTOM_PRACTICE,
            set_id=question_set.set_id,
            question_ids=tuple(
                question.question_id for question in remaining
            ),
            question_count=len(remaining),
            submission_mode="practice",
            source="legacy_resume",
        )
        self.study_flow.start_questions(
            intent,
            remaining,
            label=label,
        )
        self.progress_manager.delete(draft.progress_id)
        if hasattr(self, "home_screen"):
            self.home_screen.clear_resume_draft()

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
                course_id=self.course_context.current_course_id(),
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
            course_id=self.course_context.current_course_id(),
        )

    def _progress_topic_label(self, topic_key: str, questions: list) -> str:
        """Return a readable topic label for progress-triggered sessions."""
        lang = self.lang_manager.current
        course_manager = getattr(self, "course_manager", None)
        course_project = (
            course_manager.get(self.course_context.current_course_id())
            if course_manager
            else None
        )
        fallback_title = questions[0].topic_title() if questions else ""
        topic = questions[0].topic if questions else topic_key
        return topic_display_name(topic, course_project, lang, fallback_title)

    def _on_generate_progress_topic(self, topic_key: str):
        """Open generation review prefilled for exactly one progress topic."""
        topic_key = topic_value(topic_key)
        if not topic_key:
            return
        self.generation_flow.open(
            initial_plan=ExamGenerationPlan(
                question_count=10,
                selected_topics=(topic_key,),
                topic_weights={topic_key: 100},
            ),
            draft_source="progress_topic",
        )

    def _on_course_topic_action(
        self,
        course_id: str,
        topic_id: str,
        action: str,
    ) -> None:
        course_id = str(course_id or "").strip()
        topic_id = topic_value(topic_id)
        if not course_id or not topic_id:
            return
        if self.course_context.current_course_id() != course_id:
            if not self.course_manager.set_current(course_id):
                return
            self.course_context.course_changed()
        if action == "generate":
            self.generation_flow.open(
                initial_plan=ExamGenerationPlan(
                    question_count=10,
                    selected_topics=(topic_id,),
                    topic_weights={topic_id: 100},
                ),
                draft_source="course_hub_gap",
            )
        elif action == "practice":
            self._on_practice_progress_topic(topic_id)
        elif action == "view":
            if self.navigate_route(
                Route.course(course_id, tab="knowledge"),
                allow_first_run_redirect=False,
            ):
                self._get_course_screen().focus_knowledge_topic(topic_id)

    def _on_generate_result_reinforcement(self, request) -> None:
        """Open a source-aware generation plan for concrete answer signals."""
        request = RemediationRequest.from_mapping(request)
        if request is None:
            return
        course_id = request.course_id
        topics = tuple(dict.fromkeys(request.topic_ids))[:3]
        if not course_id or not topics:
            return
        if self.course_context.current_course_id() != course_id:
            if not self.course_manager.set_current(course_id):
                return
            self.course_context.course_changed()
        count = min(8, max(1, request.max_questions))
        base = 100 // len(topics)
        weights = {topic_id: base for topic_id in topics}
        weights[topics[-1]] += 100 - sum(weights.values())
        self.generation_flow.open(
            initial_plan=ExamGenerationPlan(
                question_count=count,
                selected_topics=topics,
                topic_weights=weights,
            ),
            draft_source="result_reinforcement",
            recovery_context={
                "runtime_instruction": request.instruction(
                    self.lang_manager.current
                ),
            },
            start_after_save=request.destination == "practice_now",
        )

    def _start_progress_topic_quiz(self, questions: list, label: str):
        """Open QuizScreen for a progress-topic action."""
        intent = StudyIntent(
            course_id=self.course_context.current_course_id(),
            action=StudyAction.PRACTICE_TOPIC,
            topic_ids=tuple(dict.fromkeys(
                topic_value(question.topic)
                for question in questions
                if topic_value(question.topic)
            )),
            question_ids=tuple(
                question.question_id for question in questions
            ),
            question_count=len(questions),
            submission_mode="practice",
            source="progress_topic",
        )
        self.study_flow.start_questions(
            intent,
            questions,
            label=label,
        )

    def _on_current_event_generation(self, course_id: str, material_pack) -> None:
        """Generate against the reviewed material pack for its selected course."""
        project = self.course_manager.get(course_id)
        if project is None or material_pack is None:
            return
        self.generation_flow.open(
            course_override=project,
            material_pack=material_pack,
        )

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
        self.generation_flow.open(
            course_override=course,
            initial_plan=prediction.plan,
            prediction=prediction,
            draft_source="predicted_exam",
        )

    def _show_timer_setting(self) -> bool:
        return bool(self.settings_screen.get_setting("show_timer", False))

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
        if (
            self._generation_workspace is not None
            and not self._generation_workspace.request_shutdown()
        ):
            self._generation_close_pending = True
            event.ignore()
            return
        self.settings_screen.save_settings(silent=True)
        super().closeEvent(event)
