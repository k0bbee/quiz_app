"""Quiz screen — question display, answer input, auto-grading, feedback."""

from html import escape as html_escape

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QScrollArea, QMessageBox,
    QListWidget, QListWidgetItem, QSplitter, QCheckBox, QDialog, QButtonGroup,
    QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from models.question import Question, QuestionBank
from models.question_set import QuestionSet
from models.quiz_snapshot import QuizSessionSnapshot
from core.quiz_engine import QuizSession
from core.study_intent import StudyIntent
from core.language_manager import LanguageManager
from core.progress_tracker import ProgressManager
from core.answer_display import format_answer_for_display
from utils.constants import QuestionType, QuizState
from ui.widgets.question_card import QuestionCard
from ui.widgets.answer_area import AnswerArea
from ui.widgets.source_refs_panel import SourceRefsPanel
from ui.widgets.wheel_safe_controls import WheelSafeComboBox
from ui.dialogs.short_answer_assessment_dialog import ShortAnswerAssessmentDialog


class QuizScreen(QWidget):
    """Main quiz-taking screen with question, answer area, and feedback."""

    _NARROW_LAYOUT_WIDTH = 1000

    quiz_finished = pyqtSignal(object)  # ProgressRecord
    return_home = pyqtSignal()

    def __init__(
        self,
        question_bank: QuestionBank,
        progress_manager: ProgressManager,
        parent=None,
        snapshot_manager=None,
        course_manager=None,
    ):
        super().__init__(parent)
        self.question_bank = question_bank
        self.progress_manager = progress_manager
        self.snapshot_manager = snapshot_manager
        self.course_manager = course_manager
        self.lang_manager = LanguageManager.instance()

        self.session = QuizSession()
        self._question_set: QuestionSet = None
        self._last_user_answer = None
        self._marked_question_ids: set[str] = set()
        self._unsure_question_ids: set[str] = set()
        self._draft_answers_by_question_id: dict[str, object] = {}
        self._displayed_question_id = ""
        self._refreshing_question_nav = False
        self._review_panel_visible = False
        self.submission_mode = "exam"
        self._study_intent: StudyIntent | None = None

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

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(0)
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.setExclusive(True)
        self.practice_mode_btn = QPushButton()
        self.practice_mode_btn.setObjectName("quizModeOption")
        self.practice_mode_btn.setCheckable(True)
        self.practice_mode_btn.clicked.connect(
            lambda checked: checked and self._set_submission_mode("practice")
        )
        self.exam_mode_btn = QPushButton()
        self.exam_mode_btn.setObjectName("quizModeOption")
        self.exam_mode_btn.setCheckable(True)
        self.exam_mode_btn.clicked.connect(
            lambda checked: checked and self._set_submission_mode("exam")
        )
        self.mode_button_group.addButton(self.practice_mode_btn)
        self.mode_button_group.addButton(self.exam_mode_btn)
        mode_layout.addWidget(self.practice_mode_btn)
        mode_layout.addWidget(self.exam_mode_btn)
        info_row.addLayout(mode_layout)

        self.mode_status_label = QLabel()
        self.mode_status_label.setObjectName("quizModeStatus")
        self.mode_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_status_label.hide()
        info_row.addWidget(self.mode_status_label)

        self.review_toggle_btn = QPushButton(
            self.lang_manager.get_text("整卷复查", "Review Paper")
        )
        self.review_toggle_btn.setObjectName("secondaryButton")
        self.review_toggle_btn.setMinimumWidth(96)
        self.review_toggle_btn.clicked.connect(self._toggle_review_panel)
        info_row.addWidget(self.review_toggle_btn)

        self.lang_btn = QPushButton(
            "English" if self.lang_manager.current == "zh" else "中文"
        )
        self.lang_btn.setObjectName("secondaryButton")
        self.lang_btn.setMinimumWidth(80)
        self.lang_btn.clicked.connect(self._toggle_language)
        info_row.addWidget(self.lang_btn)

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
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 8, 0, 8)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.practice_content_layout = scroll_layout

        self.practice_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.practice_splitter.setObjectName("quizPracticeSplitter")
        self.practice_splitter.setChildrenCollapsible(False)
        self.practice_splitter.setHandleWidth(8)

        self.preview_pane = QFrame()
        self.preview_pane.setObjectName("quizPreviewPane")
        self.preview_pane.setMinimumWidth(240)
        self.preview_pane.setMaximumWidth(340)
        preview_layout = QVBoxLayout(self.preview_pane)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(10)

        self.practice_card = QFrame()
        self.practice_card.setObjectName("quizPracticeCard")
        # Allow the card to shrink with the window; fixed desktop widths made
        # the question and answer panes overflow the default 900x680 window.
        self.practice_card.setMinimumWidth(0)
        self.practice_card.setMaximumWidth(16_777_215)
        practice_layout = QVBoxLayout(self.practice_card)
        self.practice_layout = practice_layout
        practice_layout.setContentsMargins(16, 16, 16, 16)
        practice_layout.setSpacing(12)

        # Compact full-paper preview and question-type filter.
        nav_header = QHBoxLayout()
        nav_header.setSpacing(8)
        self.question_preview_label = QLabel(
            self.lang_manager.get_text("整卷预览", "Paper Preview")
        )
        self.question_preview_label.setObjectName("sectionTitle")
        nav_header.addWidget(self.question_preview_label)

        self.question_filter_combo = WheelSafeComboBox()
        self.question_filter_combo.setObjectName("quizQuestionFilterCombo")
        self.question_filter_combo.setMinimumWidth(130)
        self.question_filter_combo.currentIndexChanged.connect(self._refresh_question_nav)
        nav_header.addWidget(self.question_filter_combo)
        preview_layout.addLayout(nav_header)

        self.question_nav_list = QListWidget()
        self.question_nav_list.setObjectName("quizQuestionNavList")
        self.question_nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.question_nav_list.currentItemChanged.connect(self._on_nav_item_selected)
        preview_layout.addWidget(self.question_nav_list, 1)

        self.question_answer_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.question_answer_splitter.setObjectName("quizQuestionAnswerSplitter")
        self.question_answer_splitter.setChildrenCollapsible(False)
        self.question_answer_splitter.setHandleWidth(8)

        self.question_pane = QWidget()
        question_layout = QVBoxLayout(self.question_pane)
        question_layout.setContentsMargins(0, 0, 4, 0)
        question_layout.setSpacing(10)

        self.question_card = QuestionCard()
        question_layout.addWidget(self.question_card)
        question_layout.addStretch()

        self.answer_pane = QWidget()
        answer_layout = QVBoxLayout(self.answer_pane)
        answer_layout.setContentsMargins(4, 0, 0, 0)
        answer_layout.setSpacing(10)

        self.answer_area = AnswerArea()
        self.answer_area.answer_submitted.connect(lambda _answer: self._refresh_navigation_button_state())
        answer_layout.addWidget(self.answer_area)
        answer_layout.addStretch()

        self.question_answer_splitter.addWidget(self.question_pane)
        self.question_answer_splitter.addWidget(self.answer_pane)
        self.question_answer_splitter.setStretchFactor(0, 1)
        self.question_answer_splitter.setStretchFactor(1, 1)
        self.question_answer_splitter.setSizes([560, 520])
        practice_layout.addWidget(self.question_answer_splitter)

        # === Feedback frame (shown after submit, inside the main scroll content) ===
        self.feedback_frame = QFrame()
        self.feedback_frame.setObjectName("feedbackFrame")
        self.feedback_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
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

        self.source_refs_panel = SourceRefsPanel()
        self.source_refs_panel.setObjectName("quizFeedbackSourceEvidence")
        self.source_refs_panel.hide()
        fb_layout.addWidget(self.source_refs_panel)

        self.feedback_frame.hide()

        # === Action buttons ===
        action_layout = QHBoxLayout()
        action_layout.setSpacing(12)

        self.prev_question_btn = QPushButton(
            self.lang_manager.get_text("上一题", "Previous")
        )
        self.prev_question_btn.setObjectName("secondaryButton")
        self.prev_question_btn.clicked.connect(self._previous_question_preview)
        self.prev_question_btn.setEnabled(False)
        action_layout.addWidget(self.prev_question_btn)

        action_layout.addStretch(1)

        self.uncertain_checkbox = QCheckBox(self.lang_manager.get_text("不确定", "Unsure"))
        self.uncertain_checkbox.setObjectName("quizUncertainCheck")
        self.uncertain_checkbox.clicked.connect(self._set_current_unsure_from_checkbox)
        self.uncertain_checkbox.setEnabled(False)

        self.review_checkbox = QCheckBox(self.lang_manager.get_text("复查", "Review"))
        self.review_checkbox.setObjectName("quizReviewCheck")
        self.review_checkbox.clicked.connect(self._set_current_review_from_checkbox)
        self.review_checkbox.setEnabled(False)

        self.marker_group = QFrame()
        self.marker_group.setObjectName("quizMarkerGroup")
        marker_layout = QHBoxLayout(self.marker_group)
        marker_layout.setContentsMargins(3, 2, 3, 2)
        marker_layout.setSpacing(6)
        marker_layout.addWidget(self.uncertain_checkbox)
        marker_layout.addWidget(self.review_checkbox)
        action_layout.addWidget(self.marker_group, 0, Qt.AlignmentFlag.AlignCenter)

        action_layout.addStretch(1)

        self.next_question_btn = QPushButton(
            self.lang_manager.get_text("下一题", "Next")
        )
        self.next_question_btn.setObjectName("primaryButton")
        self.next_question_btn.setMinimumHeight(40)
        self.next_question_btn.clicked.connect(self._primary_quiz_action)
        self.next_question_btn.setEnabled(False)
        action_layout.addWidget(self.next_question_btn)

        practice_layout.addLayout(action_layout)

        self.shortcut_hint_label = QLabel()
        self.shortcut_hint_label.setObjectName("quizShortcutHint")
        self.shortcut_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shortcut_hint_label.setWordWrap(False)
        practice_layout.addWidget(self.shortcut_hint_label)
        self._refresh_quiz_hints()
        # Keep feedback below the navigation controls so grading does not
        # move the primary previous/next actions while the user is reading.
        practice_layout.addWidget(self.feedback_frame)

        self.practice_splitter.addWidget(self.preview_pane)
        self.practice_splitter.addWidget(self.practice_card)
        self.practice_splitter.setStretchFactor(0, 0)
        self.practice_splitter.setStretchFactor(1, 1)
        self.practice_splitter.setSizes([280, 860])
        self.preview_pane.hide()
        scroll_layout.addWidget(self.practice_splitter)

        self.practice_scroll.setWidget(scroll_content)
        layout.addWidget(self.practice_scroll, 1)
        self._update_responsive_layout()

    def resizeEvent(self, event):
        """Keep the answer workspace usable when the window becomes narrow."""
        super().resizeEvent(event)
        self._update_responsive_layout()

    def _update_responsive_layout(self) -> None:
        """Stack answer panes when horizontal space is scarce."""
        is_narrow = self.width() < self._NARROW_LAYOUT_WIDTH
        content_requires_vertical = self._question_requires_vertical_layout()
        desired_orientation = (
            Qt.Orientation.Vertical if is_narrow else Qt.Orientation.Horizontal
        )
        if content_requires_vertical:
            desired_orientation = Qt.Orientation.Vertical
        if self.question_answer_splitter.orientation() != desired_orientation:
            self.question_answer_splitter.setOrientation(desired_orientation)
            self.practice_splitter.setOrientation(desired_orientation)
            if is_narrow or content_requires_vertical:
                self.question_answer_splitter.setSizes([1, 1])
                self.practice_splitter.setSizes([1, 1])
            else:
                self.question_answer_splitter.setSizes([560, 520])
                self.practice_splitter.setSizes([280, 860])

        if is_narrow:
            self.practice_card.setMinimumWidth(0)
            self.preview_pane.setMinimumWidth(0)
            self.preview_pane.setMaximumWidth(16_777_215)
            self.preview_pane.setMaximumHeight(260)
        else:
            self.preview_pane.setMinimumWidth(240)
            self.preview_pane.setMaximumWidth(340)
            self.preview_pane.setMaximumHeight(16_777_215)

        self.practice_splitter.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        self.question_answer_splitter.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )

    def _question_requires_vertical_layout(self) -> bool:
        """Use stacked panes when a long stem would dominate a split pane."""
        stem = self.question_card.stem_label.text().strip()
        if not stem:
            return False
        # Estimate wrapped lines using the desktop split width rather than
        # the current widget width, so switching orientation does not oscillate.
        available_width = max(360, min(560, self.width() // 2 - 48))
        metrics = self.question_card.stem_label.fontMetrics()
        estimated_lines = 0
        for line in stem.splitlines() or (stem,):
            line_width = metrics.horizontalAdvance(line)
            estimated_lines += max(
                1,
                (line_width + available_width - 1) // available_width,
            )
        return estimated_lines >= 8

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

    def start_quiz(
        self,
        question_set: QuestionSet,
        questions: list[Question],
        show_timer: bool = False,
        submission_mode: str = "exam",
    ):
        """Start a quiz session with a question set."""
        self._question_set = question_set
        self._study_intent = None
        self.submission_mode = submission_mode if submission_mode in ("exam", "practice") else "exam"
        lang = self.lang_manager.current
        self._last_user_answer = None
        self._marked_question_ids.clear()
        self._unsure_question_ids.clear()
        self._draft_answers_by_question_id.clear()
        self._displayed_question_id = ""
        self._refreshing_question_nav = False
        self._review_panel_visible = False
        self.preview_pane.hide()
        self.answer_area.clear()
        self.feedback_frame.hide()
        self._clear_source_evidence()
        self._set_correct_indicator_state("")
        self.timer_label.setVisible(show_timer)
        self.session.start(question_set, questions, lang)
        self._populate_question_filter()
        self._refresh_question_nav()
        self._display_current_question()
        self._refresh_navigation_button_state()
        self._refresh_unsure_state()
        self._refresh_review_state()
        self._update_timer()
        if show_timer:
            self.session_timer.start()
        else:
            self.session_timer.stop()

    def start_quiz_custom(
        self,
        questions: list[Question],
        label: str = "Custom",
        show_timer: bool = False,
        submission_mode: str = "practice",
    ):
        """Start a custom quiz session (e.g., retry incorrect)."""
        from models.question_set import QuestionSet
        qs = QuestionSet.create_new(
            title={"zh": label, "en": label},
            description={"zh": "", "en": ""},
            topics=[], question_ids=[q.question_id for q in questions],
            source="retry"
        )
        self.start_quiz(qs, questions, show_timer=show_timer, submission_mode=submission_mode)

    def set_study_intent(self, intent: StudyIntent | None) -> None:
        """Attach the active workflow context to future draft snapshots."""
        self._study_intent = intent if isinstance(intent, StudyIntent) else None

    def capture_snapshot(self) -> QuizSessionSnapshot:
        """Capture the full in-progress quiz UI/session state for draft recovery."""
        self._save_current_draft_answer()
        lang = self.session.language
        question_order = [question.question_id for question in self.session.questions]
        title = ""
        set_id = ""
        if self._question_set is not None:
            set_id = self._question_set.set_id
            title = self._question_set.get_title(lang) or self._question_set.get_title("zh")
        snapshot = QuizSessionSnapshot.create_new(
            set_id=set_id,
            title=title,
            question_order=question_order,
            language=lang,
            mode=self.submission_mode,
        )
        snapshot.current_index = self.session.current_index
        snapshot.submitted_answers = self.session.answers
        snapshot.draft_answers = dict(self._draft_answers_by_question_id)
        snapshot.unsure_question_ids = sorted(self._unsure_question_ids)
        snapshot.marked_review_question_ids = sorted(self._marked_question_ids)
        snapshot.started_at = self.session.started_at_iso
        snapshot.elapsed_seconds = self.session.elapsed_seconds
        snapshot.question_set_data = (
            self._question_set.to_dict()
            if self._question_set is not None
            else {}
        )
        snapshot.study_intent_data = (
            self._study_intent.to_dict()
            if self._study_intent is not None
            else {}
        )
        return snapshot

    def restore_snapshot(
        self,
        snapshot: QuizSessionSnapshot,
        questions: list[Question],
        question_set: QuestionSet,
        show_timer: bool = False,
    ):
        """Restore a full quiz UI/session state from a saved snapshot."""
        question_by_id = {question.question_id: question for question in questions}
        ordered_questions = [
            question_by_id[question_id]
            for question_id in snapshot.question_order
            if question_id in question_by_id
        ]
        self._question_set = question_set
        try:
            self._study_intent = StudyIntent.from_dict(
                snapshot.study_intent_data
            ) if snapshot.study_intent_data else None
        except (TypeError, ValueError):
            self._study_intent = None
        self._last_user_answer = None
        self.submission_mode = snapshot.mode if snapshot.mode in ("exam", "practice") else "practice"
        self._marked_question_ids = set(snapshot.marked_review_question_ids)
        self._unsure_question_ids = set(snapshot.unsure_question_ids)
        self._draft_answers_by_question_id = dict(snapshot.draft_answers)
        self.answer_area.clear()
        self.feedback_frame.hide()
        self._clear_source_evidence()
        self._set_correct_indicator_state("")
        self.timer_label.setVisible(show_timer)

        progress_id = snapshot.snapshot_id.replace("snapshot-", "progress-", 1)
        self.session.restore(
            question_set=question_set,
            questions=ordered_questions,
            current_index=snapshot.current_index,
            answers=snapshot.submitted_answers,
            language=snapshot.snapshot_language,
            progress_id=progress_id,
            elapsed_seconds=snapshot.elapsed_seconds,
        )
        self._populate_question_filter()
        self._refresh_question_nav()
        self._display_current_question()
        self._refresh_navigation_button_state()
        self._refresh_unsure_state()
        self._refresh_review_state()
        self._update_timer()
        if show_timer:
            self.session_timer.start()
        else:
            self.session_timer.stop()

    # --- Internal UI logic ---

    def _display_current_question(self, preserve_answer: bool = False):
        """Render the current question in the selected language."""
        q = self.session.current_question
        if q is None:
            return
        self._displayed_question_id = q.question_id

        lang = self.session.language
        stem = q.get_stem(lang)
        options = q.get_options(lang)

        type_label = self._type_label(q.type)
        self._refresh_feedback_next_text()

        self.question_card.set_question(stem, type_label)
        self.answer_area.set_question_type(q.type, options, preserve_answer=preserve_answer)
        self._update_responsive_layout()

        submitted_answer = self.session.answer_for_question_id(q.question_id)
        if self.submission_mode == "practice" and submitted_answer is not None:
            self.answer_area.set_answer(submitted_answer.user_answer)
            self._show_feedback_for_answer(submitted_answer, q)
            self._refresh_navigation_button_state()
            self._refresh_unsure_state()
            self._refresh_review_state()
            return

        draft_answer = self._draft_answers_by_question_id.get(q.question_id)
        if draft_answer is not None and not preserve_answer:
            restored = self.answer_area.set_answer(draft_answer)
            if not restored:
                self._draft_answers_by_question_id.pop(q.question_id, None)
                QMessageBox.warning(
                    self,
                    self.lang_manager.get_text("草稿已失效", "Draft No Longer Matches"),
                    self.lang_manager.get_text(
                        "这道题的选项已发生变化，旧的排序草稿无法安全恢复，已清除该题草稿。",
                        "This question's options changed, so its old ordering draft could not be restored safely and was cleared.",
                    ),
                )

        self.answer_area.set_enabled(True)
        self.feedback_frame.hide()
        self._clear_source_evidence()
        self._set_correct_indicator_state("")
        self._refresh_navigation_button_state()
        self._refresh_unsure_state()
        self._refresh_review_state()

        self._refresh_feedback_next_text()

    def _clear_source_evidence(self) -> None:
        """Hide feedback evidence before showing an unanswered question."""
        self.source_refs_panel.set_source_refs(
            [],
            language=self.lang_manager.current,
            label=self.lang_manager.get_text("来源", "Source Evidence"),
        )

    def _course_project_for_question(self, question: Question):
        """Resolve source navigation only within the question's own course."""
        if self.course_manager is None:
            return None
        metadata = question.metadata or {}
        course_id = str(metadata.get("course_id", "") or "").strip()
        return self.course_manager.get(course_id) if course_id else None

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
        if not self._confirm_default_ordering_answer():
            return
        self._last_user_answer = user_answer
        q = self.session.current_question
        manual_is_correct = None
        if q is not None and q.type == QuestionType.SHORT_ANSWER:
            manual_grades = self._assess_short_answers({q.question_id: user_answer})
            if manual_grades is None:
                return
            manual_is_correct = manual_grades[q.question_id]
        confidence = "sure"
        if q is not None:
            confidence = "unsure" if q.question_id in self._unsure_question_ids else "sure"
            self._draft_answers_by_question_id.pop(q.question_id, None)
        is_correct, normalized = self.session.submit_answer(
            user_answer,
            confidence=confidence,
            manual_is_correct=manual_is_correct,
        )
        self._refresh_navigation_button_state()

    def _confirm_default_ordering_answer(self) -> bool:
        """Ask before accepting an untouched ordering question's default order."""
        question = self.session.current_question
        if question is None or question.type != QuestionType.ORDERING:
            return True
        if self.answer_area.ordering_widget.has_user_reordered():
            return True

        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("确认排序答案", "Confirm Ordering Answer"),
            self.lang_manager.get_text(
                "你还没有调整排序。是否按当前顺序提交？",
                "You have not changed the order. Submit the current order?",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _set_current_unsure_from_checkbox(self):
        """Persist the current question's unsure marker from the center checkbox."""
        question = self.session.current_question
        displayed_id = self._displayed_question_id
        if question is None:
            return
        question_id = displayed_id or question.question_id
        if self.uncertain_checkbox.isChecked():
            self._unsure_question_ids.add(question_id)
            self.session.set_answer_confidence(question_id, "unsure")
        else:
            self._unsure_question_ids.discard(question_id)
            self.session.set_answer_confidence(question_id, "sure")
        self._refresh_question_nav()

    def _set_current_review_from_checkbox(self):
        """Persist the current question's independent review marker."""
        question = self.session.current_question
        displayed_id = self._displayed_question_id
        if question is None:
            return
        question_id = displayed_id or question.question_id
        if self.review_checkbox.isChecked():
            self._marked_question_ids.add(question_id)
        else:
            self._marked_question_ids.discard(question_id)
        self._refresh_question_nav()

    def _primary_quiz_action(self):
        """Run the current mode's single primary action."""
        if self.submission_mode == "practice":
            if self.session.state == QuizState.SHOWING_FEEDBACK:
                self._next_question()
            else:
                self._submit_answer()
            return
        self._advance_without_submitting()

    def _set_submission_mode(self, mode: str) -> None:
        """Select one inline mode without opening a separate start dialog."""
        if mode not in {"practice", "exam"}:
            return
        if mode != self.submission_mode and not self._can_switch_submission_mode():
            self._refresh_mode_switch_state()
            return
        self.submission_mode = mode
        self._refresh_navigation_button_state()

    def _can_switch_submission_mode(self) -> bool:
        """Prevent switching after answers or feedback could leak exam content."""
        return (
            self.session.state == QuizState.IN_PROGRESS
            and self.session.current_index == 0
            and self.session.answered_count == 0
            and not self._draft_answers_by_question_id
        )

    def _refresh_mode_switch_state(self) -> None:
        """Keep the inline mode selector localized and safe for the current state."""
        self.practice_mode_btn.setText(
            self.lang_manager.get_text("逐题练习", "Practice")
        )
        self.exam_mode_btn.setText(
            self.lang_manager.get_text("模拟考试", "Mock Exam")
        )
        self.practice_mode_btn.setToolTip(self.lang_manager.get_text(
            "每题提交后立即查看答案与解析。开始作答后模式锁定。",
            "See the answer and explanation after each submission. The mode locks after answering begins.",
        ))
        self.exam_mode_btn.setToolTip(self.lang_manager.get_text(
            "自由切换题目，最后统一交卷。开始作答后模式锁定。",
            "Navigate freely and submit the whole paper at the end. The mode locks after answering begins.",
        ))
        self.practice_mode_btn.blockSignals(True)
        self.exam_mode_btn.blockSignals(True)
        self.practice_mode_btn.setChecked(self.submission_mode == "practice")
        self.exam_mode_btn.setChecked(self.submission_mode == "exam")
        self.practice_mode_btn.blockSignals(False)
        self.exam_mode_btn.blockSignals(False)
        review_available = self.submission_mode == "exam"
        self.review_toggle_btn.setVisible(review_available)
        self.review_checkbox.setVisible(review_available)
        if not review_available and self._review_panel_visible:
            self._review_panel_visible = False
            self.preview_pane.hide()
            self._refresh_review_toggle_text()
        can_switch = self._can_switch_submission_mode()
        self.practice_mode_btn.setEnabled(can_switch)
        self.exam_mode_btn.setEnabled(can_switch)
        self.practice_mode_btn.setVisible(can_switch)
        self.exam_mode_btn.setVisible(can_switch)
        self.mode_status_label.setText(
            self.lang_manager.get_text(
                "模式：逐题练习" if self.submission_mode == "practice" else "模式：模拟考试",
                "Mode: Practice" if self.submission_mode == "practice" else "Mode: Mock Exam",
            )
        )
        self.mode_status_label.setVisible(not can_switch)

    def _refresh_unsure_state(self):
        """Keep the unsure marker aligned with the current question."""
        question = self.session.current_question
        if question is None:
            self.uncertain_checkbox.setEnabled(False)
            self.uncertain_checkbox.setChecked(False)
            return
        marked = question.question_id in self._unsure_question_ids
        self.uncertain_checkbox.blockSignals(True)
        self.uncertain_checkbox.setText(self.lang_manager.get_text("不确定", "Unsure"))
        self.uncertain_checkbox.setChecked(marked)
        self.uncertain_checkbox.setEnabled(True)
        self.uncertain_checkbox.blockSignals(False)

    def _refresh_review_state(self):
        """Keep the independent review marker aligned with the current question."""
        question = self.session.current_question
        if question is None:
            self.review_checkbox.setEnabled(False)
            self.review_checkbox.setChecked(False)
            return
        marked = question.question_id in self._marked_question_ids
        self.review_checkbox.blockSignals(True)
        self.review_checkbox.setText(self.lang_manager.get_text("复查", "Review"))
        self.review_checkbox.setChecked(marked)
        self.review_checkbox.setEnabled(True)
        self.review_checkbox.blockSignals(False)

    def _type_label(self, qtype: QuestionType) -> str:
        """Return the current-language label for a question type."""
        type_names = {
            QuestionType.MULTIPLE_CHOICE: self.lang_manager.get_text("单选题", "Single Choice"),
            QuestionType.SCENARIO_CHOICE: self.lang_manager.get_text("情景题", "Scenario Choice"),
            QuestionType.TRUE_FALSE: self.lang_manager.get_text("判断题", "True/False"),
            QuestionType.MATCHING: self.lang_manager.get_text("配对题", "Matching"),
            QuestionType.ORDERING: self.lang_manager.get_text("排序题", "Ordering"),
            QuestionType.FILL_IN_BLANK: self.lang_manager.get_text("填空题", "Fill in the Blank"),
            QuestionType.SHORT_ANSWER: self.lang_manager.get_text("简答题", "Short Answer"),
        }
        return type_names.get(qtype, "")

    def _populate_question_filter(self):
        """Populate the type filter from the current session question set."""
        self.question_filter_combo.blockSignals(True)
        self.question_filter_combo.clear()
        self.question_filter_combo.addItem(
            self.lang_manager.get_text("全部题型", "All Types"),
            None,
        )
        added_types = set()
        for question in self.session.questions:
            if question.type in added_types:
                continue
            added_types.add(question.type)
            self.question_filter_combo.addItem(self._type_label(question.type), question.type.value)
        self.question_filter_combo.blockSignals(False)

    def _refresh_question_nav(self, *args):
        """Refresh the full-paper preview list and keep current selection visible."""
        self._refreshing_question_nav = True
        self.question_nav_list.blockSignals(True)
        self.question_nav_list.clear()
        try:
            selected_type = self.question_filter_combo.currentData()
            current_row = None
            for index, question in enumerate(self.session.questions):
                if selected_type and question.type.value != selected_type:
                    continue
                status = self.lang_manager.get_text("未答", "Open")
                if self.session.answer_for_question_id(question.question_id):
                    status = self.lang_manager.get_text("已答", "Answered")
                if question.question_id in self._marked_question_ids:
                    status = self.lang_manager.get_text(f"{status} 复查", f"{status} Review")

                stem = question.get_stem(self.session.language).replace("\n", " ").strip()
                if len(stem) > 44:
                    stem = stem[:43] + "…"
                item = QListWidgetItem(
                    f"{index + 1}. {self._type_label(question.type)} · {status} · {stem}"
                )
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.question_nav_list.addItem(item)
                if index == self.session.current_index:
                    current_row = self.question_nav_list.count() - 1

            if current_row is not None:
                self.question_nav_list.setCurrentRow(current_row)
        finally:
            self.question_nav_list.blockSignals(False)
            self._refreshing_question_nav = False

    def _refresh_feedback_next_text(self):
        """Keep the feedback progression button aligned with the current position."""
        self._refresh_navigation_button_state()

    def _refresh_navigation_button_state(self):
        """Enable free-navigation buttons only when the target question exists."""
        self._refresh_mode_switch_state()
        has_questions = self.session.total_questions > 0
        self.prev_question_btn.setEnabled(has_questions and self.session.current_index > 0)
        is_last = has_questions and self.session.current_index >= self.session.total_questions - 1
        if self.submission_mode == "practice" and self.session.state == QuizState.IN_PROGRESS:
            self.next_question_btn.setText(self.lang_manager.get_text("提交本题", "Submit This"))
            self.next_question_btn.setEnabled(has_questions and self.answer_area.has_answer())
            return
        self.next_question_btn.setText(
            self.lang_manager.get_text("完成", "Finish") if is_last
            else self.lang_manager.get_text("下一题", "Next")
        )
        self.next_question_btn.setEnabled(has_questions)

    def _on_nav_item_selected(self, current: QListWidgetItem, previous: QListWidgetItem = None):
        """Jump to the selected preview item."""
        if self._refreshing_question_nav or not self._review_panel_visible or current is None:
            return
        index = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int):
            self._jump_to_question(index)

    def _save_current_draft_answer(self, question_index: int | None = None):
        """Preserve an unsubmitted answer before preview navigation."""
        if self.session.state != QuizState.IN_PROGRESS:
            return
        if question_index is None:
            question_index = self.session.current_index
        question_id = ""
        question = None
        if 0 <= question_index < len(self.session.questions):
            question = self.session.questions[question_index]
            question_id = question.question_id
        if not question_id:
            question_id = self._displayed_question_id
        if not question_id:
            return
        if (
            question is not None
            and question.type == QuestionType.ORDERING
            and not self.answer_area.ordering_widget.has_user_reordered()
        ):
            self._draft_answers_by_question_id.pop(question_id, None)
            return
        if self.answer_area.has_answer():
            self._draft_answers_by_question_id[question_id] = self.answer_area.get_answer()
        else:
            self._draft_answers_by_question_id.pop(question_id, None)

    def _jump_to_question(self, index: int):
        """Navigate freely without treating next/previous as quiz progression."""
        previous_question = self.session.current_question
        previous_index = self.session.current_index
        previous_id = previous_question.question_id if previous_question else self._displayed_question_id
        previous_drafts = dict(self._draft_answers_by_question_id)
        had_answer = self.answer_area.has_answer()
        previous_answer = self.answer_area.get_answer() if had_answer else None
        self._save_current_draft_answer(previous_index)
        if self.session.jump_to(index):
            if previous_id:
                if had_answer:
                    self._draft_answers_by_question_id[previous_id] = previous_answer
                else:
                    self._draft_answers_by_question_id.pop(previous_id, None)
            current = self.session.current_question
            current_id = current.question_id if current else ""
            if current_id and current_id != previous_id and current_id not in previous_drafts:
                self._draft_answers_by_question_id.pop(current_id, None)
            self._refresh_question_nav()

    def _previous_question_preview(self):
        """Navigate to the previous question without submitting."""
        self._jump_to_question(self.session.current_index - 1)

    def _next_question_preview(self):
        """Navigate to the next question without completing the quiz."""
        self._jump_to_question(self.session.current_index + 1)

    def _advance_without_submitting(self):
        """Save the draft and move forward; only the final action submits all drafts."""
        if self.session.current_index >= self.session.total_questions - 1:
            if self.submission_mode == "exam" and not self._confirm_incomplete_exam_submission():
                return
            self._finish_from_drafts()
            return
        self._next_question_preview()

    def _confirm_incomplete_exam_submission(self) -> bool:
        """Confirm final exam submission when some questions are still unanswered."""
        self._save_current_draft_answer(self.session.current_index)
        unanswered_count = sum(
            1
            for question in self.session.questions
            if not self._draft_has_answer(self._draft_answers_by_question_id.get(question.question_id))
            and self.session.answer_for_question_id(question.question_id) is None
        )
        if unanswered_count <= 0:
            return True

        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("确认交卷", "Submit Exam?"),
            self.lang_manager.get_text(
                f"还有 {unanswered_count} 题未作答。\n\n确定现在交卷吗？未作答题目将按跳过处理。",
                f"{unanswered_count} questions are still unanswered.\n\nSubmit now? Unanswered questions will be treated as skipped.",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    @staticmethod
    def _draft_has_answer(answer: object) -> bool:
        """Return whether a saved draft should count as answered."""
        if answer is None:
            return False
        if isinstance(answer, str):
            return bool(answer.strip())
        if isinstance(answer, (list, tuple, set, dict)):
            return bool(answer)
        return True

    def _finish_from_drafts(self):
        """Submit all saved drafts at the end of the navigation-first quiz flow."""
        self._save_current_draft_answer(self.session.current_index)
        drafts = dict(self._draft_answers_by_question_id)
        manual_grades = self._assess_short_answers(drafts)
        if manual_grades is None:
            return
        self.session.complete_with_drafts(
            drafts,
            set(self._unsure_question_ids),
            manual_grades=manual_grades,
        )

    def _assess_short_answers(self, answers: dict[str, object]) -> dict[str, bool] | None:
        """Collect transparent self-grades before short answers affect progress."""
        items = [
            (question, answers[question.question_id])
            for question in self.session.questions
            if question.type == QuestionType.SHORT_ANSWER
            and self._draft_has_answer(answers.get(question.question_id))
        ]
        if not items:
            return {}
        dialog = ShortAnswerAssessmentDialog(
            items,
            language=self.session.language,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        grades = dialog.grades()
        if len(grades) != len(items):
            return None
        return grades

    def _next_question(self):
        """Move to the next question."""
        if not self.session.next_question():
            # Quiz completed
            pass

    def _toggle_language(self):
        """Switch between Chinese and English."""
        lang = self.lang_manager.current
        new_lang = "en" if lang == "zh" else "zh"
        self.session.set_language(new_lang)
        self.lang_manager.set_language(new_lang)

    def _toggle_review_panel(self):
        """Show or hide the full-paper review panel on demand."""
        self._review_panel_visible = not self._review_panel_visible
        self.preview_pane.setVisible(self._review_panel_visible)
        self._refresh_review_toggle_text()

    def _refresh_review_toggle_text(self):
        """Keep the review toggle label aligned with panel state and language."""
        if self._review_panel_visible:
            self.review_toggle_btn.setText(self.lang_manager.get_text("收起复查", "Hide Review"))
        else:
            self.review_toggle_btn.setText(self.lang_manager.get_text("整卷复查", "Review Paper"))

    def _refresh_quiz_hints(self):
        """Keep keyboard and marker help text aligned with current language."""
        self.shortcut_hint_label.setText(
            self.lang_manager.get_text(
                "快捷键：1-9 选项 | Enter 主操作 | Esc 退出",
                "Shortcuts: 1-9 options | Enter primary action | Esc exit",
            )
        )
        self.uncertain_checkbox.setToolTip(
            self.lang_manager.get_text(
                "标记为不确定；结果页会单独统计，可用于重做不确定题。",
                "Mark as unsure; results track it separately for retrying unsure questions.",
            )
        )
        self.review_checkbox.setToolTip(
            self.lang_manager.get_text(
                "标记为复查；交卷后可集中回顾这些题。",
                "Mark for review; revisit these questions after submission.",
            )
        )

    def confirm_exit(self) -> bool:
        """Ask whether the current quiz can be left, saving partial progress if needed."""
        if self.session.state == QuizState.COMPLETED:
            return True

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
            if self.snapshot_manager is not None:
                snapshot = self.capture_snapshot()
                if not self.snapshot_manager.save(snapshot):
                    QMessageBox.warning(
                        self,
                        self.lang_manager.get_text("保存失败", "Save Failed"),
                        self.lang_manager.get_text(
                            "练习草稿保存失败，已留在当前练习。",
                            "Failed to save the quiz draft; staying in the current quiz.",
                        ),
                    )
                    return False
                self.session.abandon()
            else:
                # Compatibility path for tests/embedding without snapshot storage.
                record = self.session.abandon()
                if record:
                    self.progress_manager.save(record)
            self.session_timer.stop()
            return True
        return False

    def _confirm_exit(self):
        """Handle keyboard-triggered quiz exit."""
        if self.confirm_exit():
            self.return_home.emit()

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self.lang_btn.setText("English" if lang == "zh" else "中文")
        self._refresh_review_toggle_text()
        self._refresh_quiz_hints()
        self._refresh_unsure_state()
        self._refresh_review_state()
        self.prev_question_btn.setText(self.lang_manager.get_text("上一题", "Previous"))
        self.question_preview_label.setText(self.lang_manager.get_text("整卷预览", "Paper Preview"))
        self._refresh_navigation_button_state()
        self._populate_question_filter()
        self._refresh_question_nav()

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
            self._display_current_question(preserve_answer=True)

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
            self._refresh_question_nav()

    def _on_question_graded(self, question_id: str, is_correct: bool):
        """Show feedback after grading."""
        q = self.session.current_question
        if q is None:
            return

        # Update progress bar
        self.progress_bar.setValue(self.session.answered_count)

        record = self.session.answer_for_question_id(question_id)
        if record is not None:
            self._show_feedback_for_answer(record, q)
        self._refresh_question_nav()

    def _show_feedback_for_answer(self, record, question: Question):
        """Render feedback for a stored answer record."""
        lang = self.session.language

        is_manual = getattr(record, "grading_method", "automatic") == "manual_self_assessment"
        if record.is_correct:
            self.correct_indicator.setText(
                self.lang_manager.get_text(
                    "自评：基本正确" if is_manual else "正确",
                    "Self-assessed: Correct" if is_manual else "Correct",
                )
            )
            self._set_correct_indicator_state("correct")
        else:
            self.correct_indicator.setText(
                self.lang_manager.get_text(
                    "自评：仍需复习" if is_manual else "错误",
                    "Self-assessed: Review Needed" if is_manual else "Incorrect",
                )
            )
            self._set_correct_indicator_state("incorrect")

        user_answer = html_escape(self._format_answer(record.user_answer, question))
        correct_answer = html_escape(self._format_answer(question.correct_answer, question))
        explanation = html_escape(question.get_explanation(lang))

        your_answer_text = self.lang_manager.get_text("你的答案", "Your answer")
        correct_answer_text = self.lang_manager.get_text(
            "参考答案" if is_manual else "正确答案",
            "Reference answer" if is_manual else "Correct answer",
        )
        feedback = (
            f"<b>{your_answer_text}:</b> {user_answer}<br>"
            f"<b>{correct_answer_text}:</b> {correct_answer}<br><br>"
            f"{explanation}"
        )
        metadata = question.metadata or {}
        self.source_refs_panel.set_source_refs(
            metadata.get("source_refs", []),
            course_project=self._course_project_for_question(question),
            label=self.lang_manager.get_text("来源", "Source Evidence"),
            status=metadata.get("source_ref_status"),
            language=self.lang_manager.current,
        )
        self.explanation_label.setText(feedback)

        self.feedback_frame.show()
        self.answer_area.set_enabled(False)
        self.uncertain_checkbox.setEnabled(True)
        self.review_checkbox.setEnabled(True)
        self._refresh_navigation_button_state()

    def _on_session_completed(self, progress_id: str):
        """Handle quiz completion."""
        record = self.session.get_progress_record()
        if record and self._question_set:
            record.set_id = self._question_set.set_id
        if record:
            record.marked_review_question_ids = sorted(self._marked_question_ids)

        self.progress_bar.setValue(self.session.total_questions)
        self.session_timer.stop()
        self.quiz_finished.emit(record)

    def _submit_or_next(self):
        """Enter key follows the same mode-aware action as the visible primary button."""
        self._primary_quiz_action()

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
        """Legacy compatibility hook; navigation-first flow has no submit button."""
        self._refresh_navigation_button_state()

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
        if question is not None:
            return format_answer_for_display(
                question,
                answer,
                self.session.language,
                empty_text=self.lang_manager.get_text("(空)", "(empty)"),
            )
        if answer is None or answer == "":
            return self.lang_manager.get_text("(空)", "(empty)")
        return str(answer)
