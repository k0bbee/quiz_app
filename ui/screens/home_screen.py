"""Home screen — welcome view with quick actions."""

from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import pyqtSignal, Qt

from core.language_manager import LanguageManager
from core.learning_dashboard import (
    LearningDashboardViewModel,
    build_learning_dashboard,
)
from core.study_intent import StudyAction, StudyIntent
from core.study_queue import build_daily_study_queue
from core.today_learning_plan import (
    DraftLearningState,
    LearningPlanAction,
    TodayLearningPlan,
    build_today_learning_plan,
)
from ui.components import PageHeader
from utils.logger import warning


class HomeScreen(QWidget):
    """Welcome screen with navigation to main features."""

    start_practice = pyqtSignal()
    resume_practice = pyqtSignal()
    practice_incorrect = pyqtSignal()
    ai_generate = pyqtSignal()
    view_progress = pyqtSignal()
    open_settings = pyqtSignal()
    manage_courses = pyqtSignal()
    study_requested = pyqtSignal(object)

    def __init__(
        self,
        progress_manager=None,
        question_bank=None,
        parent=None,
        *,
        mastery_overrides=None,
        daily_plan_store=None,
    ):
        super().__init__(parent)
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.mastery_overrides = mastery_overrides
        self.daily_plan_store = daily_plan_store
        self.lang_manager = LanguageManager.instance()
        self._current_course_id = ""
        self._current_course_title = ""
        self._exam_topic_ids: set[str] | None = None
        self._exam_scope_weights: dict[str, float] = {}
        self._resume_title = ""
        self._resume_remaining_count = 0
        self._resume_current_index: int | None = None
        self._resume_total_count: int | None = None
        self._resume_mode: str | None = None
        self._today_plan = TodayLearningPlan(LearningPlanAction.IMPORT_COURSE)
        self._learning_dashboard = LearningDashboardViewModel()
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(36, 28, 36, 28)
        main_layout.setSpacing(16)

        self.page_header = PageHeader(
            self.lang_manager.get_text("今天的学习", "Today's Learning"),
            self.lang_manager.get_text(
                "完成今日计划，再处理最需要关注的内容",
                "Finish today's plan, then address the highest-priority topics",
            ),
        )
        self.title = self.page_header.title_label
        self.subtitle = self.page_header.subtitle_label
        main_layout.addWidget(self.page_header)

        # The visual center is a recommendation plus its course context, not a
        # grid of competing navigation actions.
        self.hero_layout = QHBoxLayout()
        self.hero_layout.setContentsMargins(0, 8, 0, 0)
        self.hero_layout.setSpacing(16)
        self.today_plan_frame = QWidget()
        self.today_plan_frame.setObjectName("homeFocusPanel")
        today_layout = QVBoxLayout(self.today_plan_frame)
        today_layout.setContentsMargins(22, 20, 22, 20)
        today_layout.setSpacing(10)
        self.today_plan_title = QLabel(self.lang_manager.get_text("今日建议", "Today's Plan"))
        self.today_plan_title.setObjectName("homeTodayPlanTitle")
        today_layout.addWidget(self.today_plan_title)
        self.today_plan_detail = QLabel()
        self.today_plan_detail.setObjectName("homeTodayPlanDetail")
        self.today_plan_detail.setWordWrap(True)
        today_layout.addWidget(self.today_plan_detail)
        today_layout.addStretch(1)

        self.start_btn = QPushButton()
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setProperty("homeAction", "primary")
        self.start_btn.setMinimumHeight(44)
        self.start_btn.clicked.connect(self._activate_today_plan)
        today_layout.addWidget(self.start_btn)

        self.context_frame = QWidget()
        self.context_frame.setObjectName("homeContextPanel")
        context_layout = QVBoxLayout(self.context_frame)
        context_layout.setContentsMargins(20, 20, 20, 20)
        context_layout.setSpacing(10)
        self.context_title = QLabel(self.lang_manager.get_text("当前学习范围", "Current Scope"))
        self.context_title.setObjectName("homeContextTitle")
        context_layout.addWidget(self.context_title)

        self.course_context_label = QLabel()
        self.course_context_label.setObjectName("homeCourseContextLabel")
        self.course_context_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.course_context_label.setWordWrap(True)
        context_layout.addWidget(self.course_context_label)
        self.scope_context_label = QLabel()
        self.scope_context_label.setObjectName("homeScopeContextLabel")
        self.scope_context_label.setWordWrap(True)
        context_layout.addWidget(self.scope_context_label)
        self.question_context_label = QLabel()
        self.question_context_label.setObjectName("homeQuestionContextLabel")
        self.question_context_label.setText(self.lang_manager.get_text("题目：0 题", "Questions: 0"))
        context_layout.addWidget(self.question_context_label)
        context_layout.addStretch(1)
        self._update_course_context_label()

        self.hero_layout.addWidget(self.today_plan_frame, 13)
        self.hero_layout.addWidget(self.context_frame, 7)
        main_layout.addLayout(self.hero_layout)

        self.overview_frame = QWidget()
        self.overview_frame.setObjectName("homeOverviewPanel")
        overview_layout = QVBoxLayout(self.overview_frame)
        overview_layout.setContentsMargins(20, 16, 20, 16)
        overview_layout.setSpacing(8)
        self.overview_title = QLabel(self.lang_manager.get_text("需要关注", "Needs Attention"))
        self.overview_title.setObjectName("homeOverviewTitle")
        overview_layout.addWidget(self.overview_title)

        self.diagnosis_title = QLabel()
        self.diagnosis_title.setObjectName("homeDiagnosisTitle")
        overview_layout.addWidget(self.diagnosis_title)
        self.diagnosis_label = QLabel()
        self.diagnosis_label.setObjectName("homeDiagnosisLabel")
        self.diagnosis_label.setWordWrap(True)
        overview_layout.addWidget(self.diagnosis_label)

        self.focus_action_layout = QHBoxLayout()
        self.focus_action_buttons = []
        for index in range(2):
            button = QPushButton()
            button.setObjectName("secondaryButton")
            button.clicked.connect(
                lambda _checked=False, position=index:
                self._request_focus_topic(position)
            )
            button.hide()
            self.focus_action_layout.addWidget(button)
            self.focus_action_buttons.append(button)
        self.focus_action_layout.addStretch()
        overview_layout.addLayout(self.focus_action_layout)

        self.stats_label = QLabel()
        self.stats_label.setObjectName("homeStatsLabel")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.stats_label.setWordWrap(True)
        self.stats_label.setText(self.lang_manager.get_text(
            "完成练习后，这里会显示本周摘要。",
            "Your weekly summary will appear here after practice.",
        ))
        overview_layout.addWidget(self.stats_label)

        self.next_step_title = QLabel(self.lang_manager.get_text("接下来", "Next"))
        self.next_step_title.setObjectName("homeNextStepTitle")
        overview_layout.addWidget(self.next_step_title)
        self.next_step_label = QLabel()
        self.next_step_label.setObjectName("homeNextStepLabel")
        self.next_step_label.setWordWrap(True)
        overview_layout.addWidget(self.next_step_label)
        main_layout.addWidget(self.overview_frame)
        main_layout.addStretch(1)

        # Compatibility signal targets remain hidden; navigation now lives in
        # the application shell and the recommendation is the sole home action.
        self.resume_btn = QPushButton(self)
        self.resume_btn.setObjectName("secondaryButton")
        self.resume_btn.setProperty("homeAction", "secondary")
        self.resume_btn.hide()

        self.free_practice_btn = QPushButton(
            self.lang_manager.get_text("自由练习", "Free Practice"),
            self,
        )
        self.free_practice_btn.setObjectName("secondaryButton")
        self.free_practice_btn.setProperty("homeAction", "secondary")
        self.free_practice_btn.setMinimumHeight(40)
        self.free_practice_btn.clicked.connect(self.start_practice.emit)
        self.free_practice_btn.hide()

        self.incorrect_btn = QPushButton(self.lang_manager.get_text("练习历史错题", "Practice Incorrect"), self)
        self.incorrect_btn.setObjectName("secondaryButton")
        self.incorrect_btn.setProperty("homeAction", "secondary")
        self.incorrect_btn.setMinimumHeight(40)
        self.incorrect_btn.clicked.connect(self.practice_incorrect.emit)
        self.incorrect_btn.hide()

        self.ai_btn = QPushButton(self.lang_manager.get_text("AI 生成题目", "Generate Questions"), self)
        self.ai_btn.setObjectName("secondaryButton")
        self.ai_btn.setProperty("homeAction", "secondary")
        self.ai_btn.setMinimumHeight(40)
        self.ai_btn.clicked.connect(self.ai_generate.emit)
        self.ai_btn.hide()

        self.progress_btn = QPushButton(self.lang_manager.get_text("查看进度", "View Progress"), self)
        self.progress_btn.setObjectName("secondaryButton")
        self.progress_btn.setProperty("homeAction", "secondary")
        self.progress_btn.setMinimumHeight(40)
        self.progress_btn.clicked.connect(self.view_progress.emit)
        self.progress_btn.hide()

        # Settings already has a persistent top-level navigation entry.
        self.settings_btn = QPushButton(self.lang_manager.get_text("设置", "Settings"), self)
        self.settings_btn.setObjectName("secondaryButton")
        self.settings_btn.setProperty("homeAction", "secondary")
        self.settings_btn.clicked.connect(self.open_settings.emit)
        self.settings_btn.hide()

        self.first_use_label = QLabel()
        self.first_use_label.setObjectName("homeFirstUseGuide")
        self.first_use_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.first_use_label.setWordWrap(True)
        self.first_use_label.hide()

        self._render_learning_diagnosis()
        self._render_today_plan()

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self.title.setText(self.lang_manager.get_text("今天的学习", "Today's Learning"))
        self.subtitle.setText(self.lang_manager.get_text(
            "完成今日计划，再处理最需要关注的内容",
            "Finish today's plan, then address the highest-priority topics",
        ))
        self._update_course_context_label()
        self.today_plan_title.setText(self.lang_manager.get_text("今日计划", "Today's Plan"))
        self.context_title.setText(self.lang_manager.get_text("当前学习范围", "Current Scope"))
        self.overview_title.setText(self.lang_manager.get_text("需要关注", "Needs Attention"))
        self.next_step_title.setText(self.lang_manager.get_text("接下来", "Next"))
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
            self._learning_dashboard = LearningDashboardViewModel()
            self.stats_label.show()
            self.stats_label.setText(self.lang_manager.get_text(
                "暂无可用的学习数据。",
                "No learning data is available yet.",
            ))
            self.question_context_label.setText(self.lang_manager.get_text("题目：0 题", "Questions: 0"))
            self.incorrect_btn.setEnabled(False)
            self._set_incorrect_empty_state(True)
            self._refresh_today_plan()
            return

        all_course_question_ids = (
            set(self.question_bank.question_ids(course_id=self._current_course_id))
            if self._current_course_id
            else set()
        )
        visible_question_ids = self._visible_question_ids()
        total_questions = (
            self.question_bank.count(course_id=self._current_course_id)
            if self._current_course_id
            else 0
        )
        progress_records = self.progress_manager.load_all()
        self.question_context_label.setText(self.lang_manager.get_text(
            f"题目：{len(visible_question_ids)} 题",
            f"Questions: {len(visible_question_ids)}",
        ))
        stats_filter = all_course_question_ids
        stats = self.progress_manager.get_aggregated_stats(
            stats_filter,
            records=progress_records,
        )
        incorrect_ids = self._incorrect_question_ids(progress_records)
        if self._current_course_id:
            incorrect_ids = [
                question_id
                for question_id in incorrect_ids
                if question_id in visible_question_ids
            ]
        else:
            incorrect_ids = []
        incorrect_count = len(incorrect_ids)
        self._refresh_today_plan(
            len(visible_question_ids),
            incorrect_ids,
            progress_records=progress_records,
        )
        self.incorrect_btn.setEnabled(True)
        self._set_incorrect_empty_state(incorrect_count <= 0)

        if stats["total_sessions"] == 0:
            self.first_use_label.hide()
            self.stats_label.show()
            self.stats_label.setText(self.lang_manager.get_text(
                "尚无练习记录。完成第一次练习后，这里会显示正确率和错题情况。",
                "No practice history yet. Accuracy and incorrect-question trends will appear after your first session.",
            ))
            return

        self.first_use_label.hide()
        self.stats_label.show()
        weekly = self._learning_dashboard.weekly_summary
        self.stats_label.setText(self.lang_manager.get_text(
            f"本周学习 {weekly.study_days} 天 · 完成 "
            f"{weekly.completed_questions} 题 · 正确率 {weekly.accuracy:.1%}",
            f"This week: {weekly.study_days} day(s) · "
            f"{weekly.completed_questions} answered · "
            f"{weekly.accuracy:.1%} accuracy",
        ))

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

    def set_current_course(
        self,
        course_id: str | None,
        course_title: str | None = None,
        exam_topic_ids: set[str] | list[str] | tuple[str, ...] | None = None,
        *,
        exam_scope_weights: dict | None = None,
    ):
        """Restrict home quick stats to the active course."""
        course_id = course_id or ""
        course_title = (course_title or "").strip()
        normalized_scope = (
            None
            if exam_topic_ids is None
            else {
                str(topic_id or "").strip()
                for topic_id in exam_topic_ids
                if str(topic_id or "").strip()
            }
        )
        normalized_weights = {}
        for topic_id, weight in (exam_scope_weights or {}).items():
            key = str(topic_id or "").strip()
            try:
                numeric = float(weight)
            except (TypeError, ValueError):
                continue
            if key and numeric > 0:
                normalized_weights[key] = numeric
        if (
            course_id == self._current_course_id
            and course_title == self._current_course_title
            and normalized_scope == self._exam_topic_ids
            and normalized_weights == self._exam_scope_weights
        ):
            return
        self._current_course_id = course_id
        self._current_course_title = course_title
        self._exam_topic_ids = normalized_scope
        self._exam_scope_weights = normalized_weights
        self._update_course_context_label()
        self.refresh()

    def _render_learning_diagnosis(self) -> None:
        """Render at most two actionable weaknesses beside the daily plan."""
        focus_topics = self._learning_dashboard.focus_topics
        if not focus_topics:
            self.diagnosis_title.setText(
                self.lang_manager.get_text("学习重点", "Learning Focus")
            )
            self.diagnosis_label.hide()
            for button in self.focus_action_buttons:
                button.hide()
            return
        self.diagnosis_title.setText(
            self.lang_manager.get_text("当前需要巩固", "Focus Next")
        )
        zh_lines = []
        en_lines = []
        for topic in focus_topics:
            zh_signals = [f"错误 {topic.incorrect_count}"]
            en_signals = [f"{topic.incorrect_count} incorrect"]
            if topic.unsure_count:
                zh_signals.append(f"不确定 {topic.unsure_count}")
                en_signals.append(f"{topic.unsure_count} unsure")
            zh_signals.append(f"正确率 {topic.accuracy:.0%}")
            en_signals.append(f"{topic.accuracy:.0%} accuracy")
            zh_lines.append(f"{topic.title}：{' · '.join(zh_signals)}")
            en_lines.append(f"{topic.title}: {' · '.join(en_signals)}")
        self.diagnosis_label.setText(
            self.lang_manager.get_text("\n".join(zh_lines), "\n".join(en_lines))
        )
        self.diagnosis_label.show()
        for index, button in enumerate(self.focus_action_buttons):
            if index < len(focus_topics):
                topic = focus_topics[index]
                button.setText(self.lang_manager.get_text(
                    f"强化 {topic.title}",
                    f"Practice {topic.title}",
                ))
                button.show()
            else:
                button.hide()

    def _request_focus_topic(self, index: int) -> None:
        topics = self._learning_dashboard.focus_topics
        if not 0 <= index < len(topics):
            return
        topic = topics[index]
        self.study_requested.emit(StudyIntent(
            course_id=self._current_course_id,
            action=StudyAction.PRACTICE_TOPIC,
            topic_ids=(topic.topic_id,),
            question_count=10,
            source="home_focus",
        ))

    def _visible_question_ids(self) -> set[str]:
        """Return current-course question IDs inside the selected exam scope."""
        if self.question_bank is None or not self._current_course_id:
            return set()
        course_ids = set(
            self.question_bank.question_ids(course_id=self._current_course_id)
        )
        topic_index = self.question_bank.topic_index(course_id=self._current_course_id)
        if self._exam_topic_ids is not None:
            course_ids = {
                question_id
                for question_id in course_ids
                if str((topic_index.get(question_id) or ("", ""))[0])
                in self._exam_topic_ids
            }
        if self.mastery_overrides is not None:
            mastered_topics = self.mastery_overrides.mastered_topics(
                self._current_course_id,
            )
            course_ids = {
                question_id
                for question_id in course_ids
                if str((topic_index.get(question_id) or ("", ""))[0])
                not in mastered_topics
            }
        return course_ids

    def _visible_topic_index(self) -> dict[str, tuple[str, str]]:
        """Return topic labels restricted to the selected exam scope."""
        if self.question_bank is None or not self._current_course_id:
            return {}
        topic_index = self.question_bank.topic_index(course_id=self._current_course_id)
        if self._exam_topic_ids is None:
            return topic_index
        return {
            question_id: topic
            for question_id, topic in topic_index.items()
            if str((topic or ("", ""))[0]) in self._exam_topic_ids
        }

    def _visible_scheduling_index(
        self,
    ) -> dict[str, tuple[str, str, str]]:
        if self.question_bank is None or not self._current_course_id:
            return {}
        scheduling_index = getattr(
            self.question_bank,
            "scheduling_index",
            None,
        )
        if callable(scheduling_index):
            rows = scheduling_index(course_id=self._current_course_id)
        else:
            rows = {
                question_id: (topic_id, topic_title, "medium")
                for question_id, (topic_id, topic_title)
                in self.question_bank.topic_index(
                    course_id=self._current_course_id
                ).items()
            }
        mastered_topics = (
            self.mastery_overrides.mastered_topics(self._current_course_id)
            if self.mastery_overrides is not None
            else set()
        )
        return {
            question_id: row
            for question_id, row in rows.items()
            if (
                isinstance(row, (tuple, list))
                and len(row) >= 3
                and (
                    self._exam_topic_ids is None
                    or str(row[0] or "") in self._exam_topic_ids
                )
                and str(row[0] or "") not in mastered_topics
            )
        }

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
                self.lang_manager.get_text(
                    "当前课程：尚未选择",
                    "Current course: None selected",
                )
            )
        if hasattr(self, "scope_context_label"):
            if not self._current_course_id:
                self.scope_context_label.setText(self.lang_manager.get_text(
                    "考试范围：等待选择课程",
                    "Exam scope: Select a course first",
                ))
            elif self._exam_topic_ids is None:
                self.scope_context_label.setText(self.lang_manager.get_text(
                    "考试范围：全部知识点",
                    "Exam scope: All topics",
                ))
            else:
                count = len(self._exam_topic_ids)
                self.scope_context_label.setText(self.lang_manager.get_text(
                    f"考试范围：{count} 个知识点",
                    f"Exam scope: {count} topics",
                ))

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

    @staticmethod
    def _incorrect_question_ids(progress_records) -> list[str]:
        return sorted({
            answer.question_id
            for record in (progress_records or ())
            if getattr(record, "status", "") == "completed"
            for answer in (getattr(record, "answers", ()) or ())
            if (
                not getattr(answer, "skipped", False)
                and not getattr(answer, "is_correct", False)
                and getattr(answer, "question_id", "")
            )
        })

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
        *,
        progress_records=None,
    ):
        draft = None
        if self._resume_title and self._resume_remaining_count > 0:
            draft = DraftLearningState(
                self._resume_title,
                self._resume_remaining_count,
                self._resume_mode or "practice",
            )

        if total_questions is None:
            total_questions = len(self._visible_question_ids())
        self.question_context_label.setText(self.lang_manager.get_text(
            f"题目：{total_questions} 题",
            f"Questions: {total_questions}",
        ))
        if progress_records is None:
            progress_records = (
                self.progress_manager.load_all()
                if draft is None and total_questions > 0
                else []
            )
        if incorrect_ids is None:
            incorrect_ids = []
            if self.question_bank is not None:
                visible_ids = self._visible_question_ids()
                incorrect_ids = [
                    question_id
                    for question_id in self._incorrect_question_ids(progress_records)
                    if question_id in visible_ids
                ]

        scheduling_index = (
            self._visible_scheduling_index()
            if total_questions > 0
            else {}
        )
        if scheduling_index:
            visible_question_ids = set(scheduling_index)
            topic_index = {
                question_id: (row[0], row[1])
                for question_id, row in scheduling_index.items()
            }
            difficulty_index = {
                question_id: row[2]
                for question_id, row in scheduling_index.items()
            }
        else:
            visible_question_ids = self._visible_question_ids()
            topic_index = (
                self._visible_topic_index()
                if total_questions > 0
                else {}
            )
            difficulty_index = {}
        daily_queue = (
            build_daily_study_queue(
                visible_question_ids,
                progress_records,
                topic_index=topic_index,
                difficulty_index=difficulty_index,
                exam_scope_weights=self._exam_scope_weights,
            )
            if draft is None and total_questions > 0
            else None
        )
        plan_id = (
            f"{date.today().isoformat()}:{self._current_course_id or 'all'}"
            if daily_queue is not None
            else ""
        )
        daily_plan = None
        if daily_queue is not None and self.daily_plan_store is not None:
            try:
                daily_plan = self.daily_plan_store.get_or_create(
                    plan_id=plan_id,
                    plan_date=date.today().isoformat(),
                    course_id=self._current_course_id,
                    queue=daily_queue,
                    valid_question_ids=visible_question_ids,
                )
            except (OSError, TypeError, ValueError) as exc:
                warning(f"Failed to load today's study plan: {exc}")
        self._today_plan = build_today_learning_plan(
            total_questions=total_questions,
            incorrect_question_ids=incorrect_ids,
            topic_index=topic_index,
            progress_records=progress_records,
            draft=draft,
            has_course=bool(self._current_course_id),
            daily_queue=daily_queue,
            daily_plan=daily_plan,
            plan_id=plan_id,
        )
        self._learning_dashboard = build_learning_dashboard(
            topic_index,
            records=progress_records,
            daily_plan=self._today_plan,
        )
        self._render_learning_diagnosis()
        self._render_next_step()
        self._render_today_plan()

    def _render_today_plan(self):
        plan = self._today_plan
        self.today_plan_detail.setToolTip("")
        self.today_plan_title.setText(
            self.lang_manager.get_text("今日计划", "Today's Plan")
        )
        if plan.action is LearningPlanAction.RESUME_DRAFT:
            mode_zh = "模拟卷" if plan.draft_mode == "exam" else "练习"
            mode_en = "mock exam" if plan.draft_mode == "exam" else "practice"
            self.start_btn.setText(self.lang_manager.get_text(f"继续{mode_zh}", f"Resume {mode_en}"))
            self.today_plan_detail.setText(self.lang_manager.get_text(
                f"优先完成“{plan.draft_title}” · 剩余 {plan.target_question_count} 题 · 约 {plan.estimated_minutes} 分钟",
                f"Finish '{plan.draft_title}' first · {plan.target_question_count} left · about {plan.estimated_minutes} min",
            ))
        elif plan.action is LearningPlanAction.START_DAILY_QUEUE:
            self.today_plan_detail.setToolTip(
                self.lang_manager.get_text(
                    "调度依据：到期与错误优先 · 薄弱和未覆盖主题优先 · "
                    "主题轮换 · 难度循序混合",
                    "Scheduling: due and incorrect first · weak and uncovered "
                    "topics first · topic rotation · mixed difficulty gradient",
                )
            )
            progress = self._learning_dashboard.plan_progress
            if progress.completed_count:
                button_zh = f"继续剩余 {progress.remaining_count} 题"
                button_en = f"Continue Remaining {progress.remaining_count}"
                group_zh = f"本组 {progress.current_group_count} 题"
                group_en = f"Current group {progress.current_group_count}"
            else:
                button_zh = "开始第一组"
                button_en = "Start First Group"
                group_zh = f"第一组 {progress.current_group_count} 题"
                group_en = f"First group {progress.current_group_count}"
            self.start_btn.setText(
                self.lang_manager.get_text(button_zh, button_en)
            )
            zh_lines = [
                f"今日进度 {progress.completed_count} / {progress.total_count} 题",
                f"{group_zh} · 预计剩余 {plan.estimated_minutes} 分钟",
            ]
            en_lines = [
                f"Today's progress {progress.completed_count} / {progress.total_count}",
                f"{group_en} · about {plan.estimated_minutes} min remaining",
            ]
            if progress.remaining_after_current_group:
                zh_lines.append(
                    f"完成后还有 {progress.remaining_after_current_group} 题"
                )
                en_lines.append(
                    f"{progress.remaining_after_current_group} remain after this group"
                )
            self.today_plan_detail.setText(
                self.lang_manager.get_text(
                    "\n".join(zh_lines),
                    "\n".join(en_lines),
                )
            )
        elif plan.action is LearningPlanAction.DAILY_COMPLETE:
            self.today_plan_title.setText(
                self.lang_manager.get_text(
                    "今日任务完成",
                    "Today's Study Complete",
                )
            )
            self.start_btn.setText(
                self.lang_manager.get_text("自由练习", "Free Practice")
            )
            if plan.deferred_count:
                detail_zh = (
                    f"今日计划已完成；{plan.deferred_count} 道仍需巩固的题目"
                    "已安排到明日。"
                )
                detail_en = (
                    f"Today's plan is complete; {plan.deferred_count} item(s) "
                    "still needing work are deferred to tomorrow."
                )
            else:
                detail_zh = "当前没有待完成的今日计划题目。"
                detail_en = "No questions remain in today's plan."
            self.today_plan_detail.setText(
                self.lang_manager.get_text(detail_zh, detail_en)
            )
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

    def _render_next_step(self) -> None:
        preview = self._learning_dashboard.next_day_preview
        if preview.question_count:
            self.next_step_label.setText(self.lang_manager.get_text(
                f"明日预计 {preview.question_count} 题",
                f"About {preview.question_count} questions tomorrow",
            ))
        else:
            self.next_step_label.setText(self.lang_manager.get_text(
                "完成当前计划后，系统会根据结果安排下一步。",
                "After this plan, the next step will adapt to your results.",
            ))

    def _activate_today_plan(self):
        self.study_requested.emit(self._today_study_intent())

    def _today_study_intent(self) -> StudyIntent:
        """Translate the visible recommendation into an executable request."""
        action = self._today_plan.action
        if action is LearningPlanAction.RESUME_DRAFT:
            study_action = StudyAction.RESUME_SESSION
        elif action is LearningPlanAction.REVIEW_INCORRECT:
            study_action = StudyAction.REVIEW_QUESTIONS
        elif action is LearningPlanAction.START_DAILY_QUEUE:
            study_action = StudyAction.DAILY_QUEUE
        elif action is LearningPlanAction.DAILY_COMPLETE:
            study_action = StudyAction.CUSTOM_PRACTICE
        elif action is LearningPlanAction.START_PRACTICE:
            study_action = (
                StudyAction.PRACTICE_TOPIC
                if self._today_plan.weak_topic_id
                else StudyAction.CUSTOM_PRACTICE
            )
        elif action is LearningPlanAction.GENERATE_QUESTIONS:
            study_action = StudyAction.GENERATE_MISSING
        else:
            study_action = StudyAction.IMPORT_COURSE
        topic_ids = (
            (self._today_plan.weak_topic_id,)
            if self._today_plan.weak_topic_id
            else ()
        )
        question_count = self._today_plan.target_question_count
        if study_action is StudyAction.GENERATE_MISSING and question_count <= 0:
            question_count = 10
        return StudyIntent(
            course_id=self._current_course_id,
            action=study_action,
            topic_ids=topic_ids,
            question_ids=self._today_plan.question_ids,
            remaining_question_ids=self._today_plan.remaining_question_ids,
            question_count=question_count,
            source="today_plan",
            plan_id=self._today_plan.plan_id,
        )
