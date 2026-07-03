"""Home screen — welcome view with quick actions."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont

from core.language_manager import LanguageManager


class HomeScreen(QWidget):
    """Welcome screen with navigation to main features."""

    start_practice = pyqtSignal()
    resume_practice = pyqtSignal()
    practice_incorrect = pyqtSignal()
    ai_generate = pyqtSignal()
    view_progress = pyqtSignal()
    open_settings = pyqtSignal()

    def __init__(self, progress_manager=None, question_bank=None, parent=None):
        super().__init__(parent)
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.lang_manager = LanguageManager.instance()
        self._current_course_id = ""
        self._resume_title = ""
        self._resume_remaining_count = 0
        self._resume_current_index: int | None = None
        self._resume_total_count: int | None = None
        self._resume_mode: str | None = None
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # ── Top stretch: pushes content to center ──
        main_layout.addStretch()

        # Title
        self.title = QLabel(self.lang_manager.get_text("课程刷题工具", "Course Quiz Studio"))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.title.setObjectName("screenTitle")
        main_layout.addWidget(self.title)

        # Subtitle
        self.subtitle = QLabel(self.lang_manager.get_text(
            "从课件生成总结、题库和自测练习",
            "Generate summaries, question banks and self-tests from courseware"
        ))
        self.subtitle.setObjectName("homeSubtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.subtitle)

        main_layout.addSpacing(20)

        # Action area: one primary action plus a balanced 2x2 secondary grid.
        self.action_frame = QWidget()
        self.action_frame.setMaximumWidth(640)
        self.action_layout = QGridLayout(self.action_frame)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setHorizontalSpacing(12)
        self.action_layout.setVerticalSpacing(12)
        self.action_layout.setColumnStretch(0, 1)
        self.action_layout.setColumnStretch(1, 1)

        self.start_btn = QPushButton(self.lang_manager.get_text("开始练习", "Start Practice"))
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setProperty("homeAction", "primary")
        self.start_btn.setMinimumHeight(44)
        self.start_btn.clicked.connect(self.start_practice.emit)
        self.action_layout.addWidget(self.start_btn, 0, 0, 1, 2)

        self.resume_btn = QPushButton()
        self.resume_btn.setObjectName("secondaryButton")
        self.resume_btn.setProperty("homeAction", "secondary")
        self.resume_btn.setMinimumHeight(40)
        self.resume_btn.clicked.connect(self.resume_practice.emit)
        self.resume_btn.hide()
        self.action_layout.addWidget(self.resume_btn, 1, 0, 1, 2)

        self.incorrect_btn = QPushButton(self.lang_manager.get_text("练习历史错题", "Practice Incorrect"))
        self.incorrect_btn.setObjectName("secondaryButton")
        self.incorrect_btn.setProperty("homeAction", "secondary")
        self.incorrect_btn.setMinimumHeight(40)
        self.incorrect_btn.clicked.connect(self.practice_incorrect.emit)
        self.action_layout.addWidget(self.incorrect_btn, 2, 0)

        self.ai_btn = QPushButton(self.lang_manager.get_text("AI 生成题目", "Generate Questions"))
        self.ai_btn.setObjectName("secondaryButton")
        self.ai_btn.setProperty("homeAction", "secondary")
        self.ai_btn.setMinimumHeight(40)
        self.ai_btn.clicked.connect(self.ai_generate.emit)
        self.action_layout.addWidget(self.ai_btn, 2, 1)

        self.progress_btn = QPushButton(self.lang_manager.get_text("查看进度", "View Progress"))
        self.progress_btn.setObjectName("secondaryButton")
        self.progress_btn.setProperty("homeAction", "secondary")
        self.progress_btn.setMinimumHeight(40)
        self.progress_btn.clicked.connect(self.view_progress.emit)
        self.action_layout.addWidget(self.progress_btn, 3, 0)

        self.settings_btn = QPushButton(self.lang_manager.get_text("设置", "Settings"))
        self.settings_btn.setObjectName("secondaryButton")
        self.settings_btn.setProperty("homeAction", "secondary")
        self.settings_btn.setMinimumHeight(40)
        self.settings_btn.clicked.connect(self.open_settings.emit)
        self.action_layout.addWidget(self.settings_btn, 3, 1)

        # Center the button frame horizontally
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.action_frame)
        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        main_layout.addSpacing(20)

        # Stats summary (hidden until refresh() populates it)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("homeStatsLabel")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setWordWrap(True)
        self.stats_label.hide()  # hidden until data is available
        main_layout.addWidget(self.stats_label)

        # ── Bottom stretch: balances top, content stays centered ──
        main_layout.addStretch()

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self.title.setText(self.lang_manager.get_text("课程刷题工具", "Course Quiz Studio"))
        self.subtitle.setText(self.lang_manager.get_text(
            "从课件生成总结、题库和自测练习",
            "Generate summaries, question banks and self-tests from courseware"
        ))
        self.start_btn.setText(self.lang_manager.get_text("开始练习", "Start Practice"))
        self._update_resume_text()
        self.incorrect_btn.setText(self.lang_manager.get_text("练习历史错题", "Practice Incorrect"))
        self.ai_btn.setText(self.lang_manager.get_text("AI 生成题目", "Generate Questions"))
        self.progress_btn.setText(self.lang_manager.get_text("查看进度", "View Progress"))
        self.settings_btn.setText(self.lang_manager.get_text("设置", "Settings"))
        # Refresh stats text in the new language
        self.refresh()

    def refresh(self):
        """Called when navigating back to home. Update stats."""
        if self.progress_manager is None or self.question_bank is None:
            self.stats_label.hide()
            self.incorrect_btn.setEnabled(False)
            self._set_incorrect_empty_state(True)
            return

        visible_question_ids = (
            set(self.question_bank.question_ids(course_id=self._current_course_id))
            if self._current_course_id else None
        )
        total_questions = self.question_bank.count(course_id=self._current_course_id)
        stats = self.progress_manager.get_aggregated_stats(visible_question_ids)
        incorrect_count = self.question_bank.count_existing(
            self.progress_manager.get_incorrect_question_ids(),
            course_id=self._current_course_id,
        )
        self.incorrect_btn.setEnabled(True)
        self._set_incorrect_empty_state(incorrect_count <= 0)

        if stats["total_sessions"] == 0:
            self.stats_label.hide()
            return

        self.stats_label.show()
        self.stats_label.setText(
            self.lang_manager.get_text(
                f"已完成 {stats['total_sessions']} 次练习 | "
                f"累计 {stats['total_questions']} 题 | "
                f"正确率 {stats['overall_accuracy']:.1f}% | "
                f"历史错题 {incorrect_count} 题 | "
                f"题库总量 {total_questions} 题",
                f"{stats['total_sessions']} sessions | "
                f"{stats['total_questions']} answered | "
                f"{stats['overall_accuracy']:.1f}% accuracy | "
                f"{incorrect_count} incorrect to retry | "
                f"{total_questions} total questions"
            )
        )

    def set_resume_draft(
        self,
        title: str,
        remaining_count: int,
        current_index: int | None = None,
        total_count: int | None = None,
        mode: str | None = None,
    ):
        """Show the resume draft action for an unfinished quiz."""
        self._resume_title = title
        self._resume_remaining_count = max(0, remaining_count)
        self._resume_current_index = current_index
        self._resume_total_count = total_count
        self._resume_mode = mode if mode in ("exam", "practice") else None
        self._update_resume_text()
        self.resume_btn.show()

    def clear_resume_draft(self):
        """Hide the resume draft action."""
        self._resume_title = ""
        self._resume_remaining_count = 0
        self._resume_current_index = None
        self._resume_total_count = None
        self._resume_mode = None
        self.resume_btn.hide()

    def set_current_course(self, course_id: str | None):
        """Restrict home quick stats to the active course."""
        course_id = course_id or ""
        if course_id == self._current_course_id:
            return
        self._current_course_id = course_id
        self.refresh()

    def _set_incorrect_empty_state(self, empty: bool):
        self.incorrect_btn.setProperty("emptyState", "true" if empty else "false")
        self.incorrect_btn.setToolTip(
            self.lang_manager.get_text(
                "当前没有错题；点击可查看提示。",
                "No incorrect questions yet; click for details.",
            )
            if empty
            else ""
        )
        self.incorrect_btn.style().unpolish(self.incorrect_btn)
        self.incorrect_btn.style().polish(self.incorrect_btn)

    def _update_resume_text(self):
        prefix_zh = "继续草稿"
        prefix_en = "Resume Draft"
        if self._resume_mode == "exam":
            prefix_zh = "继续模拟卷草稿"
            prefix_en = "Resume Mock Exam Draft"
        elif self._resume_mode == "practice":
            prefix_zh = "继续练习草稿"
            prefix_en = "Resume Practice Draft"

        if self._resume_current_index is not None and self._resume_total_count:
            current = min(max(0, self._resume_current_index), self._resume_total_count - 1) + 1
            label = self.lang_manager.get_text(
                f"{prefix_zh}：{self._resume_title}（第 {current}/{self._resume_total_count} 题）",
                f"{prefix_en}: {self._resume_title} (Question {current}/{self._resume_total_count})",
            )
        else:
            label = self.lang_manager.get_text(
                f"{prefix_zh}：{self._resume_title}（剩余 {self._resume_remaining_count} 题）",
                f"{prefix_en}: {self._resume_title} ({self._resume_remaining_count} left)",
            )
        self.resume_btn.setText(label)
