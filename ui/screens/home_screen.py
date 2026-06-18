"""Home screen — welcome view with quick actions."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont

from core.language_manager import LanguageManager


class HomeScreen(QWidget):
    """Welcome screen with navigation to main features."""

    start_practice = pyqtSignal()
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
        self.title.setObjectName("homeTitle")
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

        # Action buttons (max-width + centered for elastic layout)
        btn_frame = QWidget()
        btn_frame.setMaximumWidth(500)
        btn_layout = QVBoxLayout(btn_frame)
        btn_layout.setSpacing(12)

        self.start_btn = QPushButton(self.lang_manager.get_text("📝 开始练习", "📝 Start Practice"))
        self.start_btn.setMinimumHeight(50)
        self.start_btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.start_btn.clicked.connect(self.start_practice.emit)
        btn_layout.addWidget(self.start_btn)

        self.incorrect_btn = QPushButton(self.lang_manager.get_text("🎯 练习历史错题", "🎯 Practice Incorrect"))
        self.incorrect_btn.setMinimumHeight(45)
        self.incorrect_btn.setStyleSheet("font-size: 14px;")
        self.incorrect_btn.clicked.connect(self.practice_incorrect.emit)
        btn_layout.addWidget(self.incorrect_btn)

        self.ai_btn = QPushButton(self.lang_manager.get_text("🤖 AI生成题目", "🤖 Generate Questions"))
        self.ai_btn.setMinimumHeight(45)
        self.ai_btn.setStyleSheet("font-size: 14px;")
        self.ai_btn.clicked.connect(self.ai_generate.emit)
        btn_layout.addWidget(self.ai_btn)

        self.progress_btn = QPushButton(self.lang_manager.get_text("📊 查看进度", "📊 View Progress"))
        self.progress_btn.setMinimumHeight(45)
        self.progress_btn.setStyleSheet("font-size: 14px;")
        self.progress_btn.clicked.connect(self.view_progress.emit)
        btn_layout.addWidget(self.progress_btn)

        self.settings_btn = QPushButton(self.lang_manager.get_text("⚙ 设置", "⚙ Settings"))
        self.settings_btn.setMinimumHeight(45)
        self.settings_btn.setStyleSheet("font-size: 14px;")
        self.settings_btn.clicked.connect(self.open_settings.emit)
        btn_layout.addWidget(self.settings_btn)

        # Center the button frame horizontally
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_frame)
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
        self.start_btn.setText(self.lang_manager.get_text("📝 开始练习", "📝 Start Practice"))
        self.incorrect_btn.setText(self.lang_manager.get_text("🎯 练习历史错题", "🎯 Practice Incorrect"))
        self.ai_btn.setText(self.lang_manager.get_text("🤖 AI生成题目", "🤖 Generate Questions"))
        self.progress_btn.setText(self.lang_manager.get_text("📊 查看进度", "📊 View Progress"))
        self.settings_btn.setText(self.lang_manager.get_text("⚙ 设置", "⚙ Settings"))
        # Refresh stats text in the new language
        self.refresh()

    def refresh(self):
        """Called when navigating back to home. Update stats."""
        if not self.progress_manager or not self.question_bank:
            self.stats_label.hide()
            self.incorrect_btn.setEnabled(False)
            return

        stats = self.progress_manager.get_aggregated_stats()
        _visible_questions, total_questions = self.question_bank.search(course_id=self._current_course_id, limit=0)
        incorrect_count = len(self.question_bank.get_many(
            self.progress_manager.get_incorrect_question_ids(),
            course_id=self._current_course_id,
        ))
        self.incorrect_btn.setEnabled(incorrect_count > 0)

        if stats["total_sessions"] == 0:
            self.stats_label.hide()
            self.incorrect_btn.setEnabled(incorrect_count > 0)
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

    def set_current_course(self, course_id: str | None):
        """Restrict home quick stats to the active course."""
        course_id = course_id or ""
        if course_id == self._current_course_id:
            return
        self._current_course_id = course_id
        self.refresh()
