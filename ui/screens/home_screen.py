"""Home screen — welcome view with quick actions."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton
)
from PyQt6.QtCore import pyqtSignal, Qt

from core.language_manager import LanguageManager
from core.today_learning_plan import (
    DraftLearningState,
    LearningPlanAction,
    TodayLearningPlan,
    build_today_learning_plan,
)


class HomeScreen(QWidget):
    """Welcome screen with navigation to main features."""

    start_practice = pyqtSignal()
    resume_practice = pyqtSignal()
    practice_incorrect = pyqtSignal()
    ai_generate = pyqtSignal()
    view_progress = pyqtSignal()
    open_settings = pyqtSignal()
    manage_courses = pyqtSignal()

    def __init__(self, progress_manager=None, question_bank=None, parent=None):
        super().__init__(parent)
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.lang_manager = LanguageManager.instance()
        self._current_course_id = ""
        self._current_course_title = ""
        self._resume_title = ""
        self._resume_remaining_count = 0
        self._resume_current_index: int | None = None
        self._resume_total_count: int | None = None
        self._resume_mode: str | None = None
        self._today_plan = TodayLearningPlan(LearningPlanAction.IMPORT_COURSE)
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

        self.course_context_label = QLabel()
        self.course_context_label.setObjectName("homeCourseContextLabel")
        self.course_context_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.course_context_label.setWordWrap(True)
        main_layout.addWidget(self.course_context_label)
        self._update_course_context_label()

        main_layout.addSpacing(20)

        # Action area: one recommendation card, one primary action, then 2x2 alternatives.
        self.action_frame = QWidget()
        self.action_frame.setMaximumWidth(640)
        self.action_layout = QGridLayout(self.action_frame)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setHorizontalSpacing(12)
        self.action_layout.setVerticalSpacing(12)
        self.action_layout.setColumnStretch(0, 1)
        self.action_layout.setColumnStretch(1, 1)

        self.today_plan_frame = QWidget()
        self.today_plan_frame.setObjectName("homeTodayPlan")
        today_layout = QVBoxLayout(self.today_plan_frame)
        today_layout.setContentsMargins(16, 14, 16, 14)
        today_layout.setSpacing(6)
        self.today_plan_title = QLabel(self.lang_manager.get_text("今日建议", "Today's Plan"))
        self.today_plan_title.setObjectName("homeTodayPlanTitle")
        today_layout.addWidget(self.today_plan_title)
        self.today_plan_detail = QLabel()
        self.today_plan_detail.setObjectName("homeTodayPlanDetail")
        self.today_plan_detail.setWordWrap(True)
        today_layout.addWidget(self.today_plan_detail)
        self.action_layout.addWidget(self.today_plan_frame, 0, 0, 1, 2)

        self.start_btn = QPushButton()
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setProperty("homeAction", "primary")
        self.start_btn.setMinimumHeight(44)
        self.start_btn.clicked.connect(self._activate_today_plan)
        self.action_layout.addWidget(self.start_btn, 1, 0, 1, 2)

        # Kept as a hidden compatibility mirror for older callers/tests. Drafts
        # now surface through the single primary action instead of another row.
        self.resume_btn = QPushButton(self.action_frame)
        self.resume_btn.setObjectName("secondaryButton")
        self.resume_btn.setProperty("homeAction", "secondary")
        self.resume_btn.hide()

        self.free_practice_btn = QPushButton(
            self.lang_manager.get_text("自由练习", "Free Practice")
        )
        self.free_practice_btn.setObjectName("secondaryButton")
        self.free_practice_btn.setProperty("homeAction", "secondary")
        self.free_practice_btn.setMinimumHeight(40)
        self.free_practice_btn.clicked.connect(self.start_practice.emit)
        self.action_layout.addWidget(self.free_practice_btn, 2, 0)

        self.incorrect_btn = QPushButton(self.lang_manager.get_text("练习历史错题", "Practice Incorrect"))
        self.incorrect_btn.setObjectName("secondaryButton")
        self.incorrect_btn.setProperty("homeAction", "secondary")
        self.incorrect_btn.setMinimumHeight(40)
        self.incorrect_btn.clicked.connect(self.practice_incorrect.emit)
        self.action_layout.addWidget(self.incorrect_btn, 2, 1)

        self.ai_btn = QPushButton(self.lang_manager.get_text("AI 生成题目", "Generate Questions"))
        self.ai_btn.setObjectName("secondaryButton")
        self.ai_btn.setProperty("homeAction", "secondary")
        self.ai_btn.setMinimumHeight(40)
        self.ai_btn.clicked.connect(self.ai_generate.emit)
        self.action_layout.addWidget(self.ai_btn, 3, 0)

        self.progress_btn = QPushButton(self.lang_manager.get_text("查看进度", "View Progress"))
        self.progress_btn.setObjectName("secondaryButton")
        self.progress_btn.setProperty("homeAction", "secondary")
        self.progress_btn.setMinimumHeight(40)
        self.progress_btn.clicked.connect(self.view_progress.emit)
        self.action_layout.addWidget(self.progress_btn, 3, 1)

        # Settings already has a persistent top-level navigation entry.
        self.settings_btn = QPushButton(self.lang_manager.get_text("设置", "Settings"), self.action_frame)
        self.settings_btn.setObjectName("secondaryButton")
        self.settings_btn.setProperty("homeAction", "secondary")
        self.settings_btn.clicked.connect(self.open_settings.emit)
        self.settings_btn.hide()

        self.first_use_label = QLabel()
        self.first_use_label.setObjectName("homeFirstUseGuide")
        self.first_use_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.first_use_label.setWordWrap(True)
        self.first_use_label.hide()

        # Center the button frame horizontally
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.action_frame)
        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        main_layout.addSpacing(20)
        main_layout.addWidget(self.first_use_label)

        # Stats summary (hidden until refresh() populates it)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("homeStatsLabel")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setWordWrap(True)
        self.stats_label.hide()  # hidden until data is available
        main_layout.addWidget(self.stats_label)

        # ── Bottom stretch: balances top, content stays centered ──
        main_layout.addStretch()
        self._render_today_plan()

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self.title.setText(self.lang_manager.get_text("课程刷题工具", "Course Quiz Studio"))
        self.subtitle.setText(self.lang_manager.get_text(
            "从课件生成总结、题库和自测练习",
            "Generate summaries, question banks and self-tests from courseware"
        ))
        self._update_course_context_label()
        self.today_plan_title.setText(self.lang_manager.get_text("今日建议", "Today's Plan"))
        self._update_resume_text()
        self.free_practice_btn.setText(self.lang_manager.get_text("自由练习", "Free Practice"))
        self.incorrect_btn.setText(self.lang_manager.get_text("练习历史错题", "Practice Incorrect"))
        self.ai_btn.setText(self.lang_manager.get_text("AI 生成题目", "Generate Questions"))
        self.progress_btn.setText(self.lang_manager.get_text("查看进度", "View Progress"))
        self.settings_btn.setText(self.lang_manager.get_text("设置", "Settings"))
        self._update_first_use_text()
        # Refresh stats text in the new language
        self.refresh()

    def refresh(self):
        """Called when navigating back to home. Update stats."""
        if self.progress_manager is None or self.question_bank is None:
            self.stats_label.hide()
            self.incorrect_btn.setEnabled(False)
            self._set_incorrect_empty_state(True)
            self._refresh_today_plan()
            return

        visible_question_ids = (
            set(self.question_bank.question_ids(course_id=self._current_course_id))
            if self._current_course_id else None
        )
        total_questions = self.question_bank.count(course_id=self._current_course_id)
        stats = self.progress_manager.get_aggregated_stats(visible_question_ids)
        incorrect_ids = self.progress_manager.get_incorrect_question_ids()
        if visible_question_ids is not None:
            incorrect_ids = [
                question_id
                for question_id in incorrect_ids
                if question_id in visible_question_ids
            ]
        else:
            existing_ids = set(self.question_bank.question_ids())
            incorrect_ids = [
                question_id
                for question_id in incorrect_ids
                if question_id in existing_ids
            ]
        incorrect_count = len(incorrect_ids)
        self._refresh_today_plan(total_questions, incorrect_ids)
        self.incorrect_btn.setEnabled(True)
        self._set_incorrect_empty_state(incorrect_count <= 0)

        if stats["total_sessions"] == 0:
            self.first_use_label.hide()
            self.stats_label.hide()
            return

        self.first_use_label.hide()
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

    def _update_first_use_text(self):
        """Show a compact onboarding path when no practice data exists yet."""
        self.first_use_label.setText(
            self.lang_manager.get_text(
                "欢迎！建议流程：先导入课程资料 → AI 生成题目 → 开始练习。",
                "Welcome! Suggested flow: import course materials → generate questions with AI → start practice.",
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
        self._refresh_today_plan()

    def clear_resume_draft(self):
        """Hide the resume draft action."""
        self._resume_title = ""
        self._resume_remaining_count = 0
        self._resume_current_index = None
        self._resume_total_count = None
        self._resume_mode = None
        self.resume_btn.hide()
        self._refresh_today_plan()

    def set_current_course(self, course_id: str | None, course_title: str | None = None):
        """Restrict home quick stats to the active course."""
        course_id = course_id or ""
        course_title = (course_title or "").strip()
        if course_id == self._current_course_id and course_title == self._current_course_title:
            return
        self._current_course_id = course_id
        self._current_course_title = course_title
        self._update_course_context_label()
        self.refresh()

    def _update_course_context_label(self):
        """Show which course scope the home actions and stats currently use."""
        title = self._current_course_title or self._current_course_id
        if title:
            self.course_context_label.setText(
                self.lang_manager.get_text(
                    f"当前课程：{title}",
                    f"Current course: {title}",
                )
            )
        else:
            self.course_context_label.setText(
                self.lang_manager.get_text("当前课程：全部课程", "Current course: All courses")
            )

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

    def _refresh_today_plan(
        self,
        total_questions: int | None = None,
        incorrect_ids: list[str] | None = None,
    ):
        draft = None
        if self._resume_title and self._resume_remaining_count > 0:
            draft = DraftLearningState(
                self._resume_title,
                self._resume_remaining_count,
                self._resume_mode or "practice",
            )

        if total_questions is None:
            total_questions = (
                self.question_bank.count(course_id=self._current_course_id)
                if self.question_bank is not None
                else 0
            )
        if incorrect_ids is None:
            incorrect_ids = []
            if self.progress_manager is not None and self.question_bank is not None:
                visible_ids = set(self.question_bank.question_ids(course_id=self._current_course_id))
                incorrect_ids = [
                    question_id
                    for question_id in self.progress_manager.get_incorrect_question_ids()
                    if question_id in visible_ids
                ]

        topic_index = {}
        progress_records = []
        if draft is None and not incorrect_ids and total_questions > 0:
            topic_index = self.question_bank.topic_index(course_id=self._current_course_id)
            progress_records = self.progress_manager.load_all()
        self._today_plan = build_today_learning_plan(
            total_questions=total_questions,
            incorrect_question_ids=incorrect_ids,
            topic_index=topic_index,
            progress_records=progress_records,
            draft=draft,
            has_course=bool(self._current_course_id),
        )
        self._render_today_plan()

    def _render_today_plan(self):
        plan = self._today_plan
        if plan.action is LearningPlanAction.RESUME_DRAFT:
            mode_zh = "模拟卷" if plan.draft_mode == "exam" else "练习"
            mode_en = "mock exam" if plan.draft_mode == "exam" else "practice"
            self.start_btn.setText(self.lang_manager.get_text(f"继续{mode_zh}", f"Resume {mode_en}"))
            self.today_plan_detail.setText(self.lang_manager.get_text(
                f"优先完成“{plan.draft_title}” · 剩余 {plan.target_question_count} 题 · 约 {plan.estimated_minutes} 分钟",
                f"Finish '{plan.draft_title}' first · {plan.target_question_count} left · about {plan.estimated_minutes} min",
            ))
        elif plan.action is LearningPlanAction.REVIEW_INCORRECT:
            self.start_btn.setText(self.lang_manager.get_text("开始今日错题复习", "Start Today's Review"))
            self.today_plan_detail.setText(self.lang_manager.get_text(
                f"共有 {plan.review_question_count} 道历史错题 · 今天先练 {plan.target_question_count} 题 · 约 {plan.estimated_minutes} 分钟",
                f"{plan.review_question_count} historical errors · review {plan.target_question_count} today · about {plan.estimated_minutes} min",
            ))
        elif plan.action is LearningPlanAction.START_PRACTICE:
            self.start_btn.setText(self.lang_manager.get_text("开始今日练习", "Start Today's Practice"))
            topic = plan.weak_topic_title
            if topic:
                detail_zh = f"建议巩固：{topic} · {plan.target_question_count} 题 · 约 {plan.estimated_minutes} 分钟"
                detail_en = f"Suggested focus: {topic} · {plan.target_question_count} questions · about {plan.estimated_minutes} min"
            else:
                detail_zh = f"建议完成 {plan.target_question_count} 题 · 约 {plan.estimated_minutes} 分钟"
                detail_en = f"Complete {plan.target_question_count} questions · about {plan.estimated_minutes} min"
            self.today_plan_detail.setText(self.lang_manager.get_text(detail_zh, detail_en))
        elif plan.action is LearningPlanAction.GENERATE_QUESTIONS:
            self.start_btn.setText(self.lang_manager.get_text("生成第一套题目", "Generate First Question Set"))
            self.today_plan_detail.setText(self.lang_manager.get_text(
                "当前课程还没有题目，先根据课程资料生成题库。",
                "This course has no questions yet. Generate a bank from its materials first.",
            ))
        else:
            self.start_btn.setText(self.lang_manager.get_text("导入第一门课程", "Import First Course"))
            self.today_plan_detail.setText(self.lang_manager.get_text(
                "先导入课件，系统会生成课程总结并准备后续出题。",
                "Import course materials first to build a summary and prepare generation.",
            ))

    def _activate_today_plan(self):
        action = self._today_plan.action
        if action is LearningPlanAction.RESUME_DRAFT:
            self.resume_practice.emit()
        elif action is LearningPlanAction.REVIEW_INCORRECT:
            self.practice_incorrect.emit()
        elif action is LearningPlanAction.START_PRACTICE:
            self.start_practice.emit()
        elif action is LearningPlanAction.GENERATE_QUESTIONS:
            self.ai_generate.emit()
        else:
            self.manage_courses.emit()
