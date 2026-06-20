"""Main window — application shell with QStackedWidget navigation."""

from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QMenuBar, QMenu, QDialog,
    QToolBar, QMessageBox, QWidget, QVBoxLayout, QPushButton, QFileDialog
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, pyqtSignal

from core.language_manager import LanguageManager
from models.question import QuestionBank
from models.question_set import SetManager
from core.question_set_regenerator import apply_regenerated_questions
from core.question_set_builder import build_ai_question_set
from core.progress_tracker import ProgressManager
from models.course_project import CourseProjectManager
from config import QUESTIONS_DIR, QUESTION_SETS_DIR, PROGRESS_DIR, APP_NAME

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
        self.course_manager = CourseProjectManager()
        self.lang_manager = LanguageManager.instance()

        # Central stacked widget
        self.stack = QStackedWidget()

        # Create screens
        self.home_screen = HomeScreen(self.progress_manager, self.question_bank)
        self.topic_screen = TopicSelectionScreen(self.set_manager, self.progress_manager)
        self.quiz_screen = QuizScreen(self.question_bank, self.progress_manager)
        self.results_screen = ResultsScreen()
        self.progress_screen = ProgressDashboard(self.progress_manager, self.question_bank)
        self.settings_screen = SettingsScreen()
        self._course_screen = None
        self._question_bank_screen = None
        self._active_questions: dict = {}

        # Screens 6-7 are lazily created on first access (see properties below)
        self.stack.addWidget(self.home_screen)       # 0
        self.stack.addWidget(self.topic_screen)       # 1
        self.stack.addWidget(self.quiz_screen)        # 2
        self.stack.addWidget(self.results_screen)     # 3
        self.stack.addWidget(self.progress_screen)    # 4
        self.stack.addWidget(self.settings_screen)    # 5

        self.setCentralWidget(self.stack)

        # Menu bar
        self._create_menus()

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

    def _get_course_screen(self):
        """Lazy-init the course screen on first access."""
        if self._course_screen is None:
            from ui.screens.course_screen import CourseScreen
            self._course_screen = CourseScreen(self.course_manager)
            self.stack.insertWidget(self.SCREEN_COURSES, self._course_screen)
        return self._course_screen

    def _get_question_bank_screen(self):
        """Lazy-init the question bank screen on first access."""
        if self._question_bank_screen is None:
            from ui.screens.question_bank_screen import QuestionBankScreen
            self._question_bank_screen = QuestionBankScreen(self.question_bank, set_manager=self.set_manager)
            self._sync_question_bank_screen_course()
            self.stack.insertWidget(self.SCREEN_QUESTION_BANK, self._question_bank_screen)
        return self._question_bank_screen

    def _create_menus(self):
        menubar = self.menuBar()

        # File menu
        self.file_menu = menubar.addMenu("")
        self.home_action = QAction("", self)
        self.home_action.triggered.connect(lambda: self.navigate_to(self.SCREEN_HOME))
        self.file_menu.addAction(self.home_action)
        self.file_menu.addSeparator()
        self.exit_action = QAction("", self)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        # Tools menu
        self.tools_menu = menubar.addMenu("")
        self.topics_action = QAction("", self)
        self.topics_action.triggered.connect(lambda: self.navigate_to(self.SCREEN_TOPIC_SELECTION))
        self.tools_menu.addAction(self.topics_action)
        self.progress_action = QAction("", self)
        self.progress_action.triggered.connect(lambda: self.navigate_to(self.SCREEN_PROGRESS))
        self.tools_menu.addAction(self.progress_action)
        self.settings_action = QAction("", self)
        self.settings_action.triggered.connect(lambda: self.navigate_to(self.SCREEN_SETTINGS))
        self.tools_menu.addAction(self.settings_action)
        self.courses_action = QAction("", self)
        self.courses_action.triggered.connect(lambda: self.navigate_to(self.SCREEN_COURSES))
        self.tools_menu.addAction(self.courses_action)
        self.bank_action = QAction("", self)
        self.bank_action.triggered.connect(lambda: self.navigate_to(self.SCREEN_QUESTION_BANK))
        self.tools_menu.addAction(self.bank_action)

        # Help menu
        self.help_menu = menubar.addMenu("")
        self.about_action = QAction("", self)
        self.about_action.triggered.connect(self._show_about)
        self.help_menu.addAction(self.about_action)

    def _create_toolbar(self):
        self.toolbar = QToolBar("")
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        self.topics_btn = QPushButton("")
        self.topics_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_TOPIC_SELECTION))
        self.progress_btn = QPushButton("")
        self.progress_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_PROGRESS))
        self.courses_btn = QPushButton("")
        self.courses_btn.clicked.connect(lambda: self.navigate_to(self.SCREEN_COURSES))

        self.toolbar.addWidget(self.topics_btn)
        self.toolbar.addWidget(self.progress_btn)
        self.toolbar.addWidget(self.courses_btn)

    def _connect_signals(self):
        # Home screen
        self.home_screen.start_practice.connect(self._on_start_practice)
        self.home_screen.practice_incorrect.connect(self._on_practice_incorrect)
        self.home_screen.ai_generate.connect(self._on_ai_generate)
        self.home_screen.view_progress.connect(lambda: self.navigate_to(self.SCREEN_PROGRESS))
        self.home_screen.open_settings.connect(lambda: self.navigate_to(self.SCREEN_SETTINGS))
        self._get_course_screen().current_course_changed.connect(self._on_course_changed)
        self._get_question_bank_screen().question_bank_changed.connect(self._on_question_bank_changed)

        # Topic selection
        self.topic_screen.quiz_start.connect(self._on_quiz_start)
        self.topic_screen.export_mock_exam.connect(self._on_export_mock_exam)
        self.topic_screen.regenerate_questions.connect(self._on_regenerate_question_set)
        self.topic_screen.back_to_home.connect(lambda: self.navigate_to(self.SCREEN_HOME))

        # Quiz screen
        self.quiz_screen.quiz_finished.connect(self._on_quiz_finished)
        self.quiz_screen.return_home.connect(lambda: self.navigate_to(self.SCREEN_HOME))

        # Results screen
        self.results_screen.retry_incorrect.connect(self._on_retry_incorrect)
        self.results_screen.retry_all.connect(self._on_retry_all)
        self.results_screen.back_to_topics.connect(
            lambda: self.navigate_to(self.SCREEN_TOPIC_SELECTION)
        )

        # Language manager
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, lang: str = None):
        """Update all UI text based on current language."""
        lang = lang or self.lang_manager.current
        gm = self.lang_manager.get_text

        # Update menu titles
        self.file_menu.setTitle(gm("文件", "File"))
        self.tools_menu.setTitle(gm("工具", "Tools"))
        self.help_menu.setTitle(gm("帮助", "Help"))

        # Update menu action texts
        self.home_action.setText(gm("首页", "Home"))
        self.exit_action.setText(gm("退出", "Exit"))
        self.topics_action.setText(gm("题目集", "Question Sets"))
        self.progress_action.setText(gm("进度", "Progress"))
        self.settings_action.setText(gm("设置", "Settings"))
        self.courses_action.setText(gm("课件管理", "Course Materials"))
        self.bank_action.setText(gm("题库", "Question Bank"))
        self.about_action.setText(gm("关于", "About"))

        # Update toolbar title
        self.toolbar.setWindowTitle(gm("快捷导航", "Quick Nav"))

        # Update toolbar button texts (core 3 only)
        self.topics_btn.setText(gm("📋 题目集", "📋 Topics"))
        self.progress_btn.setText(gm("📊 进度", "📊 Progress"))
        self.courses_btn.setText(gm("📚 课件", "📚 Course"))

    def navigate_to(self, screen_index: int):
        """Switch to a screen by index."""
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

    # --- Slot handlers ---

    def _on_start_practice(self):
        self.navigate_to(self.SCREEN_TOPIC_SELECTION)

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

        self._active_questions = {q.question_id: q for q in questions}
        self.quiz_screen.start_quiz(question_set, questions)
        self.navigate_to(self.SCREEN_QUIZ)

    def _on_export_mock_exam(self, set_id: str):
        """Export a selected question set as a Markdown mock exam."""
        gm = self.lang_manager.get_text
        question_set = self.set_manager.get(set_id)
        if not question_set:
            QMessageBox.warning(self, gm("Error", "Error"), gm("Question set not found.", "Question set not found."))
            return

        questions = self.question_bank.get_many(question_set.questions)
        if not questions:
            QMessageBox.warning(self, gm("Error", "Error"), gm("No questions found for this set.", "No questions found for this set."))
            return

        default_name = f"{question_set.set_id}_mock_exam.md"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            gm("Export Mock Exam", "Export Mock Exam"),
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
            QMessageBox.critical(self, gm("Export Failed", "Export Failed"), str(exc))
            return

        QMessageBox.information(
            self,
            gm("Export Complete", "Export Complete"),
            gm(f"Mock exam exported to:\n{written}", f"Mock exam exported to:\n{written}"),
        )

    def _on_quiz_finished(self, progress_record):
        """Show results screen after quiz completion."""
        # Save progress
        if progress_record:
            self.progress_manager.save(progress_record)

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
            self.quiz_screen.start_quiz_custom(questions, gm("重做：错题", "Retry: Incorrect Questions"))
            self.navigate_to(self.SCREEN_QUIZ)

    def _on_practice_incorrect(self):
        """Start a quiz session from all historical incorrect questions."""
        gm = self.lang_manager.get_text
        incorrect_ids = self.progress_manager.get_incorrect_question_ids()
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
        if not questions:
            QMessageBox.warning(
                self,
                gm("没有题目", "No Questions"),
                gm("存在错题记录，但题目文件缺失。", "Incorrect records exist, but the question files are missing."),
            )
            return

        self._active_questions = {q.question_id: q for q in questions}
        label = gm("历史错题复习", "Incorrect Review")
        self.quiz_screen.start_quiz_custom(questions, label)
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
        api_key = SecretsManager.instance().get_key()
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
        if dialog.exec() == QDialog.DialogCode.Accepted:
            questions = dialog.generated_questions
            if questions:
                saved = self.question_bank.save_many(questions)
                lang = self.lang_manager.current
                qset = build_ai_question_set(
                    questions,
                    selected_difficulty=dialog.diff_combo.currentData(),
                    generation_config=dialog._build_generation_config(),
                    lang=lang,
                    course_project=course_project,
                )
                self.set_manager.save(qset)
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
        api_key = SecretsManager.instance().get_key()
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
        dialog.configure_from_question_set(qset)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        questions = dialog.generated_questions
        if not questions:
            QMessageBox.warning(self, gm("没有题目", "No Questions"), gm("未生成可保存的题目。", "No generated questions to save."))
            return

        saved = self.question_bank.save_many(questions)
        selected_diff = dialog.diff_combo.currentData()
        difficulty = qset.difficulty
        if selected_diff in {d.value for d in Difficulty}:
            difficulty = Difficulty(selected_diff)
        apply_regenerated_questions(qset, questions, difficulty=difficulty, course_project=course_project)
        self.set_manager.save(qset)
        self.topic_screen.refresh()
        QMessageBox.information(
            self,
            gm("已重新生成", "Regenerated"),
            gm(f"已保存 {saved} 道新题，并更新题目集：\n{qset.get_title(self.lang_manager.current)}",
               f"Saved {saved} new questions and updated question set:\n{qset.get_title(self.lang_manager.current)}"),
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
                self.quiz_screen.start_quiz(question_set, questions)
                self.navigate_to(self.SCREEN_QUIZ)

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
            topics = [topic.title for topic in course.topics] or [gm("综合", "General")]
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
