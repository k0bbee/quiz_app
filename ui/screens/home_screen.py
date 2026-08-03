"""Home screen — welcome view with quick actions."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import pyqtSignal, Qt

from core.language_manager import LanguageManager
from core.study_intent import StudyAction, StudyIntent
from core.study_queue import build_daily_study_queue
from core.today_learning_plan import (
    DraftLearningState,
    LearningPlanAction,
    TodayLearningPlan,
    build_today_learning_plan,
)
from ui.components import PageHeader


class HomeScreen(QWidget):
    """Welcome screen with navigation to main features."""

    study_requested = pyqtSignal(object)

    def __init__(
        self,
        progress_manager=None,
        question_bank=None,
        parent=None,
        *,
        course_manager=None,
        mastery_overrides=None,
    ):
        super().__init__(parent)
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.course_manager = course_manager
        self.mastery_overrides = mastery_overrides
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
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(36, 28, 36, 28)
        main_layout.setSpacing(16)

        self.page_header = PageHeader(
            self.lang_manager.get_text("今天的学习", "Today's Learning"),
            self.lang_manager.get_text(
                "回到当前课程，继续最重要的一步",
                "Return to the current course and continue the next useful step",
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
        self.today_plan_title = QLabel(self.lang_manager.get_text("当前建议", "Current Recommendation"))
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

        self.quick_links = QHBoxLayout()
        self.quick_links.setSpacing(14)
        self.generate_link = self._make_text_link(
            "生成新题",
            "Generate questions",
            self._request_generate_questions,
        )
        self.switch_course_link = self._make_text_link(
            "切换课程",
            "Switch course",
            self._request_switch_course,
        )
        self.quick_links.addWidget(self.generate_link)
        self.quick_links.addWidget(self.switch_course_link)
        self.quick_links.addStretch(1)
        today_layout.addLayout(self.quick_links)

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

        main_layout.addStretch(1)
        self._render_today_plan()

    def _make_text_link(self, zh: str, en: str, callback) -> QPushButton:
        button = QPushButton(self.lang_manager.get_text(zh, en))
        button.setObjectName("textLinkButton")
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self.title.setText(self.lang_manager.get_text("今天的学习", "Today's Learning"))
        self.subtitle.setText(self.lang_manager.get_text(
            "回到当前课程，继续最重要的一步",
            "Return to the current course and continue the next useful step",
        ))
        self._update_course_context_label()
        self.today_plan_title.setText(self.lang_manager.get_text("当前建议", "Current Recommendation"))
        self.context_title.setText(self.lang_manager.get_text("当前学习范围", "Current Scope"))
        self.generate_link.setText(self.lang_manager.get_text("生成新题", "Generate questions"))
        self.switch_course_link.setText(self.lang_manager.get_text("切换课程", "Switch course"))
        self.refresh()

    def refresh(self):
        """Called when navigating back to home. Update stats."""
        if self.progress_manager is None or self.question_bank is None:
            self.question_context_label.setText(self.lang_manager.get_text("题目：0 题", "Questions: 0"))
            self._refresh_today_plan()
            return

        visible_question_ids = self._visible_question_ids()
        progress_records = self.progress_manager.load_all()
        self.question_context_label.setText(self.lang_manager.get_text(
            f"题目：{len(visible_question_ids)} 题",
            f"Questions: {len(visible_question_ids)}",
        ))
        incorrect_ids = self._incorrect_question_ids(progress_records)
        if self._current_course_id:
            incorrect_ids = [
                question_id
                for question_id in incorrect_ids
                if question_id in visible_question_ids
            ]
        else:
            incorrect_ids = []
        self._refresh_today_plan(
            len(visible_question_ids),
            incorrect_ids,
            progress_records=progress_records,
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
        self._refresh_today_plan()

    def clear_resume_draft(self):
        """Hide the resume draft action."""
        self._resume_title = ""
        self._resume_remaining_count = 0
        self._resume_current_index = None
        self._resume_total_count = None
        self._resume_mode = None
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

    def _request_generate_questions(self) -> None:
        if not self._current_course_id:
            self._request_switch_course()
            return
        self.study_requested.emit(StudyIntent(
            course_id=self._current_course_id,
            action=StudyAction.GENERATE_MISSING,
            question_count=10,
            source="home_generate",
        ))

    def _request_switch_course(self) -> None:
        self.study_requested.emit(StudyIntent(
            course_id=self._current_course_id,
            action=StudyAction.IMPORT_COURSE,
            source="home_switch_course",
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
        self._today_plan = build_today_learning_plan(
            total_questions=total_questions,
            incorrect_question_ids=incorrect_ids,
            topic_index=topic_index,
            progress_records=progress_records,
            draft=draft,
            has_course=bool(self._current_course_id),
            daily_queue=daily_queue,
        )
        self._render_today_plan()

    def _render_today_plan(self):
        plan = self._today_plan
        self.today_plan_detail.setToolTip("")
        self.today_plan_title.setText(
            self.lang_manager.get_text("当前建议", "Current Recommendation")
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
            current_count = plan.target_question_count
            remaining_count = len(plan.remaining_question_ids)
            total_count = current_count + remaining_count
            button_zh = "开始练习"
            button_en = "Start Practice"
            self.start_btn.setText(
                self.lang_manager.get_text(button_zh, button_en)
            )
            zh_lines = [
                f"本次练习 {total_count} 题 · 先完成 {current_count} 题",
                f"预计 {plan.estimated_minutes} 分钟",
            ]
            en_lines = [
                f"{total_count} questions · start with {current_count}",
                f"about {plan.estimated_minutes} min",
            ]
            if remaining_count:
                zh_lines.append(
                    f"完成后还有 {remaining_count} 题"
                )
                en_lines.append(
                    f"{remaining_count} remain after this group"
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
                    "当前练习已完成",
                    "Current Practice Complete",
                )
            )
            self.start_btn.setText(
                self.lang_manager.get_text("开始练习", "Start Practice")
            )
            detail_zh = "当前没有待完成的复习题目。"
            detail_en = "No review questions remain right now."
            self.today_plan_detail.setText(
                self.lang_manager.get_text(detail_zh, detail_en)
            )
        elif plan.action is LearningPlanAction.REVIEW_INCORRECT:
            self.start_btn.setText(self.lang_manager.get_text("开始错题复习", "Start Review"))
            self.today_plan_detail.setText(self.lang_manager.get_text(
                f"共有 {plan.review_question_count} 道错题 · 先练 {plan.target_question_count} 题 · 约 {plan.estimated_minutes} 分钟",
                f"{plan.review_question_count} incorrect questions · review {plan.target_question_count} first · about {plan.estimated_minutes} min",
            ))
        elif plan.action is LearningPlanAction.START_PRACTICE:
            self.start_btn.setText(self.lang_manager.get_text("开始练习", "Start Practice"))
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
        )
