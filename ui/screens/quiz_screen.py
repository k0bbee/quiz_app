"""Quiz screen — question display, answer input, auto-grading, feedback."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QScrollArea, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from models.question import Question, QuestionBank
from models.question_set import QuestionSet
from models.progress import ProgressRecord
from core.quiz_engine import QuizSession
from core.language_manager import LanguageManager
from core.progress_tracker import ProgressManager
from utils.constants import QuestionType, QuizState
from ui.widgets.question_card import QuestionCard
from ui.widgets.answer_area import AnswerArea


class QuizScreen(QWidget):
    """Main quiz-taking screen with question, answer area, and feedback."""

    quiz_finished = pyqtSignal(object)  # ProgressRecord
    return_home = pyqtSignal()

    def __init__(self, question_bank: QuestionBank, progress_manager: ProgressManager, parent=None):
        super().__init__(parent)
        self.question_bank = question_bank
        self.progress_manager = progress_manager
        self.lang_manager = LanguageManager.instance()

        self.session = QuizSession()
        self._question_set: QuestionSet = None
        self._last_user_answer = None

        self._setup_ui()
        self._connect_session()
        self._setup_shortcuts()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # === Top bar (two rows: info + progress bar) ===
        info_row = QHBoxLayout()
        info_row.setSpacing(10)

        self.progress_label = QLabel(
            self.lang_manager.get_text("题目 1/20", "Question 1/20")
        )
        self.progress_label.setObjectName("quizProgressLabel")
        info_row.addWidget(self.progress_label)

        self.timer_label = QLabel("00:00")
        self.timer_label.setObjectName("quizTimerLabel")
        info_row.addWidget(self.timer_label)

        info_row.addStretch()

        self.lang_btn = QPushButton(
            "English" if self.lang_manager.current == "zh" else "中文"
        )
        self.lang_btn.setObjectName("secondaryButton")
        self.lang_btn.setMinimumWidth(80)
        self.lang_btn.clicked.connect(self._toggle_language)
        info_row.addWidget(self.lang_btn)

        self.back_btn = QPushButton(self.lang_manager.get_text("← 退出", "← Exit"))
        self.back_btn.setObjectName("secondaryButton")
        self.back_btn.clicked.connect(self._confirm_exit)
        info_row.addWidget(self.back_btn)

        layout.addLayout(info_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.session_timer = QTimer(self)
        self.session_timer.setInterval(1000)
        self.session_timer.timeout.connect(self._update_timer)

        # === Divider ===
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        # === Centered practice card ===
        self.practice_scroll = QScrollArea()
        self.practice_scroll.setWidgetResizable(True)
        self.practice_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.practice_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 8, 0, 8)

        self.practice_card = QFrame()
        self.practice_card.setObjectName("quizPracticeCard")
        self.practice_card.setMaximumWidth(860)
        practice_layout = QVBoxLayout(self.practice_card)
        practice_layout.setContentsMargins(16, 16, 16, 16)
        practice_layout.setSpacing(12)

        # Question card
        self.question_card = QuestionCard()
        practice_layout.addWidget(self.question_card)

        # Answer area
        self.answer_area = AnswerArea()
        self.answer_area.answer_submitted.connect(lambda _answer: self._update_submit_enabled())
        practice_layout.addWidget(self.answer_area)

        # === Action buttons ===
        action_layout = QHBoxLayout()

        self.skip_btn = QPushButton(self.lang_manager.get_text("跳过 ⏭", "Skip ⏭"))
        self.skip_btn.setObjectName("secondaryButton")
        self.skip_btn.clicked.connect(self._skip_question)
        self.skip_btn.setEnabled(False)
        action_layout.addWidget(self.skip_btn)

        action_layout.addStretch()

        self.submit_btn = QPushButton(
            self.lang_manager.get_text("提交答案 ✓", "Submit Answer ✓")
        )
        self.submit_btn.setObjectName("primaryButton")
        self.submit_btn.setMinimumHeight(40)
        self.submit_btn.clicked.connect(self._submit_answer)
        self.submit_btn.setEnabled(False)
        action_layout.addWidget(self.submit_btn)

        practice_layout.addLayout(action_layout)
        scroll_layout.addWidget(self.practice_card, 0, Qt.AlignmentFlag.AlignHCenter)
        scroll_layout.addStretch()

        self.practice_scroll.setWidget(scroll_content)
        layout.addWidget(self.practice_scroll, 1)

        # === Feedback frame (shown after submit) ===
        self.feedback_frame = QFrame()
        self.feedback_frame.setObjectName("feedbackFrame")
        self.feedback_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.feedback_frame.setMaximumWidth(750)
        fb_layout = QVBoxLayout(self.feedback_frame)

        self.correct_indicator = QLabel()
        self.correct_indicator.setObjectName("correctIndicator")
        self.correct_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.correct_indicator.setProperty("answerState", "")
        fb_layout.addWidget(self.correct_indicator)

        self.explanation_label = QLabel()
        self.explanation_label.setObjectName("quizExplanationLabel")
        self.explanation_label.setWordWrap(True)
        fb_layout.addWidget(self.explanation_label)

        next_btn_layout = QHBoxLayout()
        next_btn_layout.addStretch()
        self.next_btn = QPushButton(self.lang_manager.get_text("下一题 →", "Next →"))
        self.next_btn.setObjectName("primaryButton")
        self.next_btn.setMinimumHeight(36)
        self.next_btn.clicked.connect(self._next_question)
        next_btn_layout.addWidget(self.next_btn)
        fb_layout.addLayout(next_btn_layout)

        self.feedback_frame.hide()
        layout.addWidget(self.feedback_frame)

    def _setup_shortcuts(self):
        """Register keyboard shortcuts for fast practice."""
        QShortcut(QKeySequence("Return"), self, activated=self._submit_or_next)
        QShortcut(QKeySequence("Enter"), self, activated=self._submit_or_next)
        QShortcut(QKeySequence("Esc"), self, activated=self._confirm_exit)
        for i in range(1, 10):
            QShortcut(QKeySequence(str(i)), self, activated=lambda idx=i - 1: self._select_choice(idx))

    def _connect_session(self):
        """Connect quiz session signals to UI slots."""
        self.session.state_changed.connect(self._on_state_changed)
        self.session.question_changed.connect(self._on_question_changed)
        self.session.question_graded.connect(self._on_question_graded)
        self.session.session_completed.connect(self._on_session_completed)
        self.session.error_occurred.connect(
            lambda msg: QMessageBox.warning(
                self, self.lang_manager.get_text("错误", "Error"), msg
            )
        )

    # --- Public interface ---

    def start_quiz(self, question_set: QuestionSet, questions: list[Question], show_timer: bool = False):
        """Start a quiz session with a question set."""
        self._question_set = question_set
        lang = self.lang_manager.current
        self._last_user_answer = None
        self.answer_area.clear()
        self.feedback_frame.hide()
        self._set_correct_indicator_state("")
        self.timer_label.setVisible(show_timer)
        self.session.start(question_set, questions, lang)
        self.submit_btn.setText(self.lang_manager.get_text("提交答案 ✓", "Submit Answer ✓"))
        self.submit_btn.setEnabled(False)
        self.skip_btn.setEnabled(True)
        self._update_timer()
        if show_timer:
            self.session_timer.start()
        else:
            self.session_timer.stop()

    def start_quiz_custom(self, questions: list[Question], label: str = "Custom", show_timer: bool = False):
        """Start a custom quiz session (e.g., retry incorrect)."""
        from models.question_set import QuestionSet
        qs = QuestionSet.create_new(
            title={"zh": label, "en": label},
            description={"zh": "", "en": ""},
            topics=[], question_ids=[q.question_id for q in questions],
            source="retry"
        )
        self.start_quiz(qs, questions, show_timer=show_timer)

    # --- Internal UI logic ---

    def _display_current_question(self):
        """Render the current question in the selected language."""
        q = self.session.current_question
        if q is None:
            return

        lang = self.session.language
        stem = q.get_stem(lang)
        options = q.get_options(lang)

        # Type labels
        type_names = {
            QuestionType.MULTIPLE_CHOICE: self.lang_manager.get_text("单选题", "Single Choice"),
            QuestionType.SCENARIO_CHOICE: self.lang_manager.get_text("情景题", "Scenario Choice"),
            QuestionType.TRUE_FALSE: self.lang_manager.get_text("判断题", "True/False"),
            QuestionType.MATCHING: self.lang_manager.get_text("配对题", "Matching"),
            QuestionType.ORDERING: self.lang_manager.get_text("排序题", "Ordering"),
            QuestionType.FILL_IN_BLANK: self.lang_manager.get_text("填空题", "Fill in the Blank"),
            QuestionType.SHORT_ANSWER: self.lang_manager.get_text("简答题", "Short Answer"),
        }
        type_label = type_names.get(q.type, "")

        self.question_card.set_question(stem, type_label)
        self.answer_area.set_question_type(q.type, options)
        self.answer_area.set_enabled(True)
        self.feedback_frame.hide()
        self._set_correct_indicator_state("")
        self.submit_btn.setText(self.lang_manager.get_text("提交答案 ✓", "Submit Answer ✓"))
        self._update_submit_enabled()
        self.submit_btn.show()
        self.skip_btn.setEnabled(True)

        is_last = self.session.current_index == self.session.total_questions - 1
        self.next_btn.setText(
            self.lang_manager.get_text("完成 ✓", "Finish ✓") if is_last
            else self.lang_manager.get_text("下一题 →", "Next →")
        )

    def _submit_answer(self):
        """Grade the current answer and show feedback."""
        if self.session.state not in (QuizState.IN_PROGRESS,):
            return

        user_answer = self.answer_area.get_answer()
        if not self.answer_area.has_answer():
            QMessageBox.information(
                self,
                self.lang_manager.get_text("未作答", "No Answer"),
                self.lang_manager.get_text(
                    "请先选择或输入答案再提交。",
                    "Please choose or enter an answer before submitting."
                )
            )
            return
        self._last_user_answer = user_answer
        is_correct, normalized = self.session.submit_answer(user_answer)

    def _skip_question(self):
        """Skip the current question."""
        self.session.skip_question()

    def _next_question(self):
        """Move to the next question."""
        if not self.session.next_question():
            # Quiz completed
            pass

    def _toggle_language(self):
        """Switch between Chinese and English."""
        lang = self.lang_manager.current
        new_lang = "en" if lang == "zh" else "zh"
        self.lang_manager.set_language(new_lang)
        self.session.set_language(new_lang)

    def _confirm_exit(self):
        """Ask user to confirm leaving mid-quiz. Save partial progress if abandoning."""
        if self.session.state == QuizState.COMPLETED:
            self.return_home.emit()
            return

        answered = self.session.answered_count
        msg = self.lang_manager.get_text(
            f"你已答完 {answered}/{self.session.total_questions} 题。\n\n确定要退出吗？已答题目将被保存为草稿。",
            f"You've completed {answered}/{self.session.total_questions} questions.\n\nExit quiz? Answered questions will be saved as draft."
        )

        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("退出练习", "Exit Quiz?"),
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Save partial progress as abandoned without showing completed results.
            record = self.session.abandon()
            if record:
                self.progress_manager.save(record)
            self.return_home.emit()

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self.lang_btn.setText("English" if lang == "zh" else "中文")
        self.back_btn.setText(self.lang_manager.get_text("← 退出", "← Exit"))
        self.skip_btn.setText(self.lang_manager.get_text("跳过 ⏭", "Skip ⏭"))
        self.submit_btn.setText(self.lang_manager.get_text("提交答案 ✓", "Submit Answer ✓"))
        self.next_btn.setText(self.lang_manager.get_text("下一题 →", "Next →"))

        if self.session.state in (
            QuizState.IN_PROGRESS,
            QuizState.ANSWERED,
            QuizState.SHOWING_FEEDBACK,
        ):
            current = self.session.current_index + 1
            total = self.session.total_questions
            self.progress_label.setText(
                self.lang_manager.get_text(
                    f"题目 {current}/{total}", f"Question {current}/{total}"
                )
            )
            self._display_current_question()

    # --- Session signal handlers ---

    def _on_state_changed(self, state: str):
        """Handle quiz state transitions."""
        # No-op for most transitions; handled by specific signals
        pass

    def _on_question_changed(self, current: int, total: int):
        """Update UI for a new question."""
        self.progress_label.setText(
            self.lang_manager.get_text(
                f"题目 {current}/{total}", f"Question {current}/{total}"
            )
        )
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

        q = self.session.current_question
        if q:
            self._last_user_answer = None
            self.answer_area.clear()
            self._display_current_question()

    def _on_question_graded(self, question_id: str, is_correct: bool):
        """Show feedback after grading."""
        q = self.session.current_question
        if q is None:
            return

        lang = self.session.language

        # Update progress bar
        self.progress_bar.setValue(self.session.answered_count)

        # Feedback
        if is_correct:
            self.correct_indicator.setText(
                self.lang_manager.get_text("✅ 正确！", "✅ Correct!")
            )
            self._set_correct_indicator_state("correct")
        else:
            self.correct_indicator.setText(
                self.lang_manager.get_text("❌ 错误", "❌ Incorrect")
            )
            self._set_correct_indicator_state("incorrect")

        user_answer = self._format_answer(self._last_user_answer, q)
        correct_answer = self._format_answer(q.correct_answer, q)

        your_answer_text = self.lang_manager.get_text("你的答案", "Your answer")
        correct_answer_text = self.lang_manager.get_text("正确答案", "Correct answer")
        self.explanation_label.setText(
            f"<b>{your_answer_text}:</b> {user_answer}<br>"
            f"<b>{correct_answer_text}:</b> {correct_answer}<br><br>"
            f"💡 {q.get_explanation(lang)}"
        )

        self.feedback_frame.show()
        self.answer_area.set_enabled(False)
        self.submit_btn.hide()
        self.skip_btn.setEnabled(False)

    def _on_session_completed(self, progress_id: str):
        """Handle quiz completion."""
        record = self.session.get_progress_record()
        if record and self._question_set:
            record.set_id = self._question_set.set_id

        self.progress_bar.setValue(self.session.total_questions)
        self.session_timer.stop()
        self.quiz_finished.emit(record)

    def _submit_or_next(self):
        """Enter key behavior: submit during answering, advance during feedback."""
        if self.session.state == QuizState.IN_PROGRESS:
            if self.submit_btn.isEnabled() and self.submit_btn.isVisible():
                self._submit_answer()
        elif self.session.state == QuizState.SHOWING_FEEDBACK:
            self._next_question()

    def _select_choice(self, index: int):
        """Select a choice option with number keys."""
        if self.session.state != QuizState.IN_PROGRESS:
            return
        widget = self.answer_area.stack.currentWidget()
        buttons = getattr(widget, "buttons", None)
        if buttons and 0 <= index < len(buttons):
            buttons[index].setChecked(True)
            self._update_submit_enabled()
            return
        if hasattr(widget, "true_btn") and index in (0, 1):
            (widget.true_btn if index == 0 else widget.false_btn).setChecked(True)
            self._update_submit_enabled()

    def _update_submit_enabled(self):
        """Enable Submit only when the current answer input is non-empty."""
        if self.session.state == QuizState.IN_PROGRESS:
            self.submit_btn.setEnabled(self.answer_area.has_answer())

    def _update_timer(self):
        """Update elapsed session timer."""
        seconds = int(self.session.elapsed_seconds)
        minutes, seconds = divmod(seconds, 60)
        self.timer_label.setText(f"{minutes:02d}:{seconds:02d}")

    def _set_correct_indicator_state(self, state: str):
        """Update feedback color through themeable dynamic properties."""
        self.correct_indicator.setProperty("answerState", state)
        self.correct_indicator.style().unpolish(self.correct_indicator)
        self.correct_indicator.style().polish(self.correct_indicator)

    def _format_answer(self, answer, question: Question = None) -> str:
        """Convert stored answers to readable text for feedback/review."""
        if answer is None or answer == "":
            return self.lang_manager.get_text("(空)", "(empty)")
        if isinstance(answer, list):
            return " → ".join(str(x) for x in answer)
        if question is not None:
            answer_text = str(answer)
            options = question.get_options(self.session.language)
            if len(answer_text) == 1 and answer_text.isalpha() and options:
                idx = ord(answer_text.upper()) - ord("A")
                if 0 <= idx < len(options):
                    return options[idx]
        return str(answer)
