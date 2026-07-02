"""Main window — application shell with QStackedWidget navigation."""

from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QDialog,
    QToolBar, QMessageBox, QWidget, QVBoxLayout, QPushButton, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.language_manager import LanguageManager
from models.question import QuestionBank
from models.question_set import SetManager
from core.question_set_regenerator import persist_new_question_set, persist_regenerated_question_set
from core.question_set_builder import build_ai_question_set
from core.progress_tracker import ProgressManager
from core.quiz_snapshot_manager import QuizSnapshotManager
from core.mastery_overrides import MasteryOverrideStore
from models.course_project import CourseProjectManager
from config import QUESTIONS_DIR, QUESTION_SETS_DIR, PROGRESS_DIR, QUIZ_SNAPSHOTS_DIR, APP_NAME

from ui.screens.home_screen import HomeScreen
from ui.screens.topic_selection_screen import TopicSelectionScreen
from ui.screens.quiz_screen import QuizScreen
from ui.screens.results_screen import ResultsScreen
from ui.screens.progress_dashboard import ProgressDashboard
from ui.screens.settings_screen import SettingsScreen
from utils.constants import Difficulty
from ai.course_summary_factory import provider_requires_api_key
from ai.provider_presets import detect_local_agents
from ai.settings_validation import validate_ai_settings


def _provider_requires_api_key(settings: dict) -> bool:
    """Return whether the selected AI provider needs a configured API key."""
    return provider_requires_api_key(settings)


def _ai_generation_settings_error(
    settings: dict,
    api_key: str,
    detected_agents: list[str] | None = None,
) -> str:
    """Return a blocking AI settings error for generation, or an empty string."""
    result = validate_ai_settings(
        settings,
        api_key=api_key,
        detected_agents=detect_local_agents() if detected_agents is None else detected_agents,
    )
    return "" if result.ok else result.message


class MainWindow(QMainWindow):
    """Main application window with QStackedWidget navigation."""

    # Screen indices
    SCREEN_HOME = 0
    SCREEN_TOPIC_SELECTION = 1
    SCREEN_QUIZ = 2
    SCREEN_RESULTS = 3
    SCREEN_PROGRESS = 4
    SCREEN_SETTINGS = 5
    SCREEN_COURSES = 6
    SCREEN_QUESTION_BANK = 7

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 680)

        # Data managers
        self.question_bank = QuestionBank(QUESTIONS_DIR)
        self.set_manager = SetManager(QUESTION_SETS_DIR)
        self.progress_manager = ProgressManager(PROGRESS_DIR)
        self.snapshot_manager = QuizSnapshotManager(QUIZ_SNAPSHOTS_DIR)
        self.mastery_overrides = MasteryOverrideStore()
        self.course_manager = CourseProjectManager()
        self.lang_manager = LanguageManager.instance()

        # Central stacked widget
        self.stack = QStackedWidget()

        # Create screens
        self.home_screen = HomeScreen(self.progress_manager, self.question_bank)
        self.topic_screen = TopicSelectionScreen(self.set_manager, self.progress_manager)
        self.quiz_screen = QuizScreen(
            self.question_bank,
            self.progress_manager,
            snapshot_manager=self.snapshot_manager,
        )
        self.results_screen = ResultsScreen()
        self.progress_screen = ProgressDashboard(
            self.progress_manager,
            self.question_bank,
            mastery_overrides=self.mastery_overrides,
        )
        self.settings_screen = SettingsScreen()
        self._course_screen = None
        self._question_bank_screen = None
        self._active_questions: dict = {}
        self._navigation_history: list[int] = []

        # Screens 6-7 are lazily created on first access (see properties below)
        self.stack.addWidget(self.home_screen)       # 0
        self.stack.addWidget(self.topic_screen)       # 1
        self.stack.addWidget(self.quiz_screen)        # 2
        self.stack.addWidget(self.results_screen)     # 3
        self.stack.addWidget(self.progress_screen)    # 4
        self.stack.addWidget(self.settings_screen)    # 5

        self.setCentralWidget(self.stack)

        # Keep the shell free of duplicate menu navigation; all app navigation
        # lives in the semantic top toolbar.
        self.menuBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Toolbar
        self._create_toolbar()

        # Connect screen navigation signals
        self._connect_signals()
        self._sync_home_screen_course()
        self._sync_topic_screen_course()
        self._sync_progress_screen_course()

        # Apply initial language
        self._on_language_changed()

        # Start on home screen
        self.stack.setCurrentIndex(self.SCREEN_HOME)
        self._update_navigation_actions()

    def _get_course_screen(self):
        """Lazy-init the course screen on first access."""
        if self._course_screen is None:
            from ui.screens.course_screen import CourseScreen
            self._course_screen = CourseScreen(self.course_manager, question_bank=self.question_bank)
            self.stack.insertWidget(self.SCREEN_COURSES, self._course_screen)
        return self._course_screen

    def _get_question_bank_screen(self):
        """Lazy-init the question bank screen on first access."""
        if self._question_bank_screen is None:
            from ui.screens.question_bank_screen import QuestionBankScreen
            self._question_bank_screen = QuestionBankScreen(
                self.question_bank,
                set_manager=self.set_manager,
                course_manager=self.course_manager,
            )
            self._sync_question_bank_screen_course()
            self.stack.insertWidget(self.SCREEN_QUESTION_BANK, self._question_bank_screen)
        return self._question_bank_screen

    def _create_toolbar(self):
        self.toolbar = QToolBar("")
        self.toolbar.setMovable(False)
        self.toolbar.setOrientation(Qt.Orientation.Horizontal)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.nav_back_btn = self._create_toolbar_button("navigation")
        self.nav_back_btn.clicked.connect(self.navigate_back)
        self.nav_home_btn = self._create_toolbar_button("navigation")
        self.nav_home_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_HOME))

        self.topics_btn = self._create_toolbar_button("practice")
        self.topics_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_TOPIC_SELECTION))
        self.progress_btn = self._create_toolbar_button("practice")
        self.progress_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_PROGRESS))
        self.courses_btn = self._create_toolbar_button("management")
        self.courses_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_COURSES))
        self.bank_btn = self._create_toolbar_button("management")
        self.bank_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_QUESTION_BANK))
        self.settings_btn = self._create_toolbar_button("management")
        self.settings_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_SETTINGS))
        self.about_btn = self._create_toolbar_button("support")
        self.about_btn.clicked.connect(self._show_about)

        self.toolbar.addWidget(self.nav_back_btn)
        self.toolbar.addWidget(self.nav_home_btn)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.topics_btn)
        self.toolbar.addWidget(self.progress_btn)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.courses_btn)
        self.toolbar.addWidget(self.bank_btn)
        self.toolbar.addWidget(self.settings_btn)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.about_btn)

    def _create_toolbar_button(self, group: str) -> QPushButton:
        button = QPushButton("")
        button.setObjectName("toolbarButton")
        button.setProperty("navGroup", group)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    def navigation_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.nav_back_btn,
            self.nav_home_btn,
            self.topics_btn,
            self.progress_btn,
            self.courses_btn,
            self.bank_btn,
            self.settings_btn,
            self.about_btn,
        )

    def _connect_signals(self):
        # Home screen
        self.home_screen.start_practice.connect(self._on_start_practice)
        self.home_screen.resume_practice.connect(self._on_resume_abandoned)
        self.home_screen.practice_incorrect.connect(self._on_practice_incorrect)
        self.home_screen.ai_generate.connect(self._on_ai_generate)
        self.home_screen.view_progress.connect(lambda: self.navigate_to(self.SCREEN_PROGRESS))
        self.home_screen.open_settings.connect(lambda: self.navigate_to(self.SCREEN_SETTINGS))
        self._get_course_screen().current_course_changed.connect(self._on_course_changed)
        self._get_question_bank_screen().question_bank_changed.connect(self._on_question_bank_changed)

        # Topic selection
        self.topic_screen.quiz_start.connect(self._on_quiz_start)
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
        # Language manager
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang: str = None):
        """Update all UI text based on current language."""
        lang = lang or self.lang_manager.current
        gm = self.lang_manager.get_text

        # Update toolbar title
        self.toolbar.setWindowTitle(gm("快捷导航", "Quick Nav"))

        # Update semantic toolbar button texts.
        self.nav_back_btn.setText(gm("返回", "Back"))
        self.nav_home_btn.setText(gm("首页", "Home"))
        self.topics_btn.setText(gm("题目集", "Question Sets"))
        self.progress_btn.setText(gm("进度", "Progress"))
        self.courses_btn.setText(gm("课程", "Courses"))
        self.bank_btn.setText(gm("题库", "Question Bank"))
        self.settings_btn.setText(gm("设置", "Settings"))
        self.about_btn.setText(gm("关于", "About"))

    def navigate_to(self, screen_index: int, remember: bool = True, confirm_current: bool = True) -> bool:
        """Switch to a screen by index."""
        current_index = self.stack.currentIndex()
        leaving_quiz = current_index == self.SCREEN_QUIZ and screen_index != self.SCREEN_QUIZ
        if confirm_current and not self._confirm_current_navigation(screen_index):
            self._update_navigation_actions()
            return False
        if remember and current_index >= 0 and current_index != screen_index:
            if not leaving_quiz:
                self._navigation_history.append(current_index)
            self._navigation_history = self._navigation_history[-50:]
        self.stack.setCurrentIndex(screen_index)
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
        self._update_navigation_actions()
        return True

    def navigate_back(self):
        """Return to the previous screen if navigation history exists."""
        if not self._navigation_history:
            self._update_navigation_actions()
            return
        previous = self._navigation_history[-1]
        if not self._confirm_current_navigation(previous):
            self._update_navigation_actions()
            return
        self._navigation_history.pop()
        self.navigate_to(previous, remember=False, confirm_current=False)

    def _confirm_current_navigation(self, target_screen: int) -> bool:
        """Return whether navigation away from the current screen may proceed."""
        if self.stack.currentIndex() == self.SCREEN_QUIZ and target_screen != self.SCREEN_QUIZ:
            return self.quiz_screen.confirm_exit()
        return True

    def _update_navigation_actions(self):
        """Keep shell navigation buttons in sync with current location."""
        if not hasattr(self, "nav_back_btn"):
            return
        self.nav_back_btn.setEnabled(bool(self._navigation_history))
        self.nav_home_btn.setEnabled(self.stack.currentIndex() != self.SCREEN_HOME)

    # --- Slot handlers ---

    def _on_start_practice(self):
        self.navigate_to(self.SCREEN_TOPIC_SELECTION)

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
        if not question_set:
            snapshot_manager.delete(snapshot.snapshot_id)
            self._resume_snapshot_error = self.lang_manager.get_text(
                "练习草稿引用的题目集已不存在，无法恢复，已清理该草稿。",
                "The draft's question set no longer exists, so it cannot be restored. The draft was removed.",
            )
            return None
        questions = self.question_bank.get_many(
            snapshot.question_order,
            course_id=self._current_course_id(),
        )
        if len(questions) != len(snapshot.question_order):
            snapshot_manager.delete(snapshot.snapshot_id)
            self._resume_snapshot_error = self.lang_manager.get_text(
                "练习草稿中的部分题目已不存在，无法完整恢复，已清理该草稿。",
                "Some questions in the draft no longer exist, so it cannot be fully restored. The draft was removed.",
            )
            return None
        return snapshot, question_set, questions

    def _update_home_resume_draft(self):
        """Reflect the latest abandoned draft on the home screen."""
        if not hasattr(self, "home_screen"):
            return
        snapshot_resume = MainWindow._resume_snapshot_draft(self)
        if snapshot_resume:
            snapshot, question_set, questions = snapshot_resume
            remaining_count = max(0, len(questions) - snapshot.current_index)
            self.home_screen.set_resume_draft(
                question_set.get_title(self.lang_manager.current),
                remaining_count,
                current_index=snapshot.current_index,
                total_count=len(questions),
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
            snapshot, question_set, questions = snapshot_resume
            self._active_questions = {question.question_id: question for question in questions}
            self.quiz_screen.restore_snapshot(
                snapshot,
                questions,
                question_set,
                show_timer=self._show_timer_setting(),
            )
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

        submission_mode = self._choose_quiz_submission_mode()
        if submission_mode is None:
            return

        self._active_questions = {q.question_id: q for q in questions}
        self.quiz_screen.start_quiz(
            question_set,
            questions,
            show_timer=self._show_timer_setting(),
            submission_mode=submission_mode,
        )
        self.navigate_to(self.SCREEN_QUIZ)

    def _choose_quiz_submission_mode(self) -> str | None:
        """Ask how this quiz should be submitted before entering the quiz screen."""
        gm = self.lang_manager.get_text
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(gm("选择练习模式", "Choose Practice Mode"))
        box.setText(
            gm(
                "请选择本次练习的提交方式。",
                "Choose how this session should be submitted.",
            )
        )
        exam_btn = box.addButton(gm("模拟模式", "Mock Exam"), QMessageBox.ButtonRole.AcceptRole)
        practice_btn = box.addButton(gm("例题模式", "Example Practice"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(exam_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == exam_btn:
            return "exam"
        if clicked == practice_btn:
            return "practice"
        return None

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

        self.results_screen.set_results(
            progress_record,
            questions=self._active_questions,
            lang=self.lang_manager.current,
        )
        self.navigate_to(self.SCREEN_RESULTS)

    def _on_retry_incorrect(self):
        """Retry only incorrectly answered questions."""
        gm = self.lang_manager.get_text
        record = self.results_screen.current_record
        if not record:
            return

        incorrect_ids = [a.question_id for a in record.answers if not a.is_correct]
        if not incorrect_ids:
            QMessageBox.information(
                self,
                gm("全部正确！", "All Correct!"),
                gm("你答对了所有题目！🎉", "You answered all questions correctly! 🎉"),
            )
            return

        questions = self.question_bank.get_many(incorrect_ids, course_id=self._current_course_id())
        if questions:
            self._active_questions = {q.question_id: q for q in questions}
            self.quiz_screen.start_quiz_custom(
                questions,
                gm("重做：错题", "Retry: Incorrect Questions"),
                show_timer=self._show_timer_setting(),
            )
            self.navigate_to(self.SCREEN_QUIZ)

    def _on_retry_unsure(self):
        """Retry questions the user marked as unsure in the completed session."""
        gm = self.lang_manager.get_text
        record = self.results_screen.current_record
        if not record:
            return

        unsure_ids = [
            answer.question_id
            for answer in record.answers
            if getattr(answer, "confidence", "sure") == "unsure"
        ]
        if not unsure_ids:
            QMessageBox.information(
                self,
                gm("没有不确定题", "No Unsure Questions"),
                gm("本次练习没有标记为不确定的题目。", "No questions were marked unsure in this session."),
            )
            return

        questions = self.question_bank.get_many(unsure_ids, course_id=self._current_course_id())
        if questions:
            self._active_questions = {q.question_id: q for q in questions}
            self.quiz_screen.start_quiz_custom(
                questions,
                gm("重做：不确定题", "Retry: Unsure Questions"),
                show_timer=self._show_timer_setting(),
            )
            self.navigate_to(self.SCREEN_QUIZ)

    def _on_retry_review(self):
        """Retry questions the user marked for review in the completed session."""
        gm = self.lang_manager.get_text
        record = self.results_screen.current_record
        if not record:
            return

        review_ids = list(dict.fromkeys(getattr(record, "marked_review_question_ids", [])))
        if not review_ids:
            QMessageBox.information(
                self if isinstance(self, QWidget) else None,
                gm("没有复查题", "No Review Questions"),
                gm("本次练习没有标记为复查的题目。", "No questions were marked for review in this session."),
            )
            return

        questions = self.question_bank.get_many(review_ids, course_id=self._current_course_id())
        if questions:
            self._active_questions = {q.question_id: q for q in questions}
            self.quiz_screen.start_quiz_custom(
                questions,
                gm("重做：复查题", "Retry: Review Questions"),
                show_timer=self._show_timer_setting(),
            )
            self.navigate_to(self.SCREEN_QUIZ)

    def _on_practice_incorrect(self):
        """Start a quiz session from all historical incorrect questions."""
        gm = self.lang_manager.get_text
        incorrect_ids = self.progress_manager.get_prioritized_review_question_ids()
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

    def _on_ai_generate(self):
        """Open the AI question generation dialog."""
        gm = self.lang_manager.get_text

        # Read settings directly — don't trigger save dialog
        settings = self.settings_screen._settings

        # Check course content first
        course_content, available_topics, course_project = self._load_generation_context()
        if not course_content:
            QMessageBox.warning(
                self,
                gm("缺少课程内容", "No Course Content"),
                gm("尚未导入任何课程资料。请先通过「课程资料」页面导入课件文件夹（支持 pptx/pdf/docx/md/txt），\n系统将自动解析并生成课程摘要，之后即可使用 AI 出题功能。",
                   "No course materials imported yet. Please go to Course Materials to import a folder\n(pptx/pdf/docx/md/txt). The system will parse and generate a summary for AI generation."),
            )
            return

        # Check API key unless a local CLI agent is selected.
        from core.secrets_manager import SecretsManager
        api_key = SecretsManager.instance().get_key() if _provider_requires_api_key(settings) else ""
        settings_error = _ai_generation_settings_error(settings, api_key)
        if settings_error:
            QMessageBox.warning(
                self,
                gm("AI 设置需要处理", "AI Settings Need Attention"),
                settings_error,
            )
            return

        # Lazy import — avoid loading AI deps until actually needed
        from ui.dialogs.ai_generation_dialog import AIGenerationDialog
        dialog = AIGenerationDialog(
            course_content,
            settings,
            self,
            available_topics=available_topics,
            course_project=course_project,
        )
        dialog.configure_from_course_profile(course_project)
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
                QMessageBox.information(
                    self,
                    gm("已保存", "Saved"),
                    gm(f"已保存 {saved} 道题目并创建了题目集：\n{qset.get_title(lang)}",
                       f"Saved {saved} questions and created a question set:\n{qset.get_title(lang)}"),
                )
                self.navigate_to(self.SCREEN_TOPIC_SELECTION)

    def _on_regenerate_question_set(self, set_id: str):
        """Regenerate questions for an existing question set in place."""
        gm = self.lang_manager.get_text
        qset = self.set_manager.get(set_id)
        if not qset:
            QMessageBox.warning(self, gm("错误", "Error"), gm("未找到题目集。", "Question set not found."))
            return

        settings = self.settings_screen._settings
        course_content, available_topics, course_project = self._load_generation_context()
        if not course_content:
            QMessageBox.warning(
                self,
                gm("缺少课程内容", "No Course Content"),
                gm("请先导入课程资料并生成课程总结，然后再重新生成题目。",
                   "Import course materials and generate a course summary before regenerating questions."),
            )
            return

        from core.secrets_manager import SecretsManager
        api_key = SecretsManager.instance().get_key() if _provider_requires_api_key(settings) else ""
        settings_error = _ai_generation_settings_error(settings, api_key)
        if settings_error:
            QMessageBox.warning(
                self,
                gm("AI 设置需要处理", "AI Settings Need Attention"),
                settings_error,
            )
            return

        from ui.dialogs.ai_generation_dialog import AIGenerationDialog
        dialog = AIGenerationDialog(
            course_content,
            settings,
            self,
            available_topics=available_topics,
            course_project=course_project,
        )
        dialog.configure_from_course_profile(course_project)
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
        if question_set:
            questions = self.question_bank.get_many(question_set.questions)
            if questions:
                self._active_questions = {q.question_id: q for q in questions}
                self.quiz_screen.start_quiz(question_set, questions, show_timer=self._show_timer_setting())
                self.navigate_to(self.SCREEN_QUIZ)

    def _show_timer_setting(self) -> bool:
        return bool(self.settings_screen._settings.get("show_timer", False))

    def _on_course_changed(self):
        """Refresh app state after switching/importing course projects."""
        self._sync_home_screen_course()
        self._sync_topic_screen_course()
        self._sync_question_bank_screen_course()
        self._sync_progress_screen_course()
        self._on_language_changed()

    def _on_question_bank_changed(self):
        """Refresh views affected by question CRUD."""
        self.question_bank.clear_cache()
        self.home_screen.refresh()
        self.topic_screen.refresh()

    def _load_generation_context(self) -> tuple[str, list, object]:
        """Load active course summary and topics for AI generation.
        Returns (content, topics, project). Caller should check for empty content
        and show a message if needed."""
        gm = self.lang_manager.get_text
        course = self.course_manager.current()
        if course:
            topics = list(course.topics) or [gm("综合", "General")]
            return course.summary_markdown, topics, course
        return "", [], None

    def _sync_topic_screen_course(self):
        self.topic_screen.set_current_course(self._current_course_id())

    def _sync_question_bank_screen_course(self):
        if self._question_bank_screen is None:
            return
        self._question_bank_screen.set_current_course(self._current_course_id())

    def _sync_home_screen_course(self):
        self.home_screen.set_current_course(self._current_course_id())
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
            f"{gm('• 生成可复用的课件摘要', '• Generate reusable course summaries')}<br>"
            f"{gm('• AI生成双语题目', '• AI-generated bilingual questions')}<br>"
            f"{gm('• 选择题/判断题自动评分', '• Auto-grading for multiple choice / true-false')}<br>"
            f"{gm('• 进度追踪', '• Progress tracking')}<br>"
            f"{gm('• 可复用的本地JSON题目集', '• Reusable local JSON question sets')}"
        )

    def closeEvent(self, event):
        """Save settings before closing."""
        self.settings_screen.save_settings(silent=True)
        super().closeEvent(event)
