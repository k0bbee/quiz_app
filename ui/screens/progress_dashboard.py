"""Progress dashboard — aggregated stats, history, per-topic breakdown."""

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem,
    QGroupBox, QHeaderView, QAbstractItemView, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.progress_tracker import ProgressManager
from core.learning_dashboard import build_learning_dashboard
from core.mastery import build_topic_mastery
from core.mastery_overrides import MasteryOverrideStore
from models.question import QuestionBank
from models.question_set import SetManager
from models.course_project import CourseProjectManager
from core.topic_display import topic_display_name
from ui.components import PageHeader
from ui.widgets.source_refs_panel import SourceRefsPanel
from utils.constants import topic_value
from core.language_manager import LanguageManager
from core.today_learning_plan import build_topic_learning
from ui.archive_status_presenter import build_archive_status_view


class ProgressDashboard(QWidget):
    """Aggregated progress statistics and session history."""

    practice_topic_requested = pyqtSignal(str)
    review_topic_requested = pyqtSignal(str)
    generate_topic_requested = pyqtSignal(str)
    history_requested = pyqtSignal(str)

    def __init__(
        self,
        progress_manager: ProgressManager,
        question_bank: QuestionBank,
        parent=None,
        *,
        set_manager: SetManager,
        mastery_overrides: MasteryOverrideStore,
        course_manager: CourseProjectManager,
    ):
        super().__init__(parent)
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.lang_manager = LanguageManager.instance()
        self.mastery_overrides = mastery_overrides
        self.course_manager = course_manager
        self._current_course_id = ""
        self._current_project = None
        self._recent_history_expanded = False
        self._recommended_topic_ids: list[str] = []
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.page_header = PageHeader()
        self.title = self.page_header.title_label
        layout.addWidget(self.page_header)

        # Overall summary
        self.summary_group = QGroupBox()
        summary_layout = QVBoxLayout(self.summary_group)

        self.overall_label = QLabel()
        self.overall_label.setObjectName("dashboardOverallLabel")
        summary_layout.addWidget(self.overall_label)

        self.detail_label = QLabel()
        summary_layout.addWidget(self.detail_label)

        self.recommendation_label = QLabel()
        self.recommendation_label.setObjectName("dashboardRecommendationLabel")
        self.recommendation_label.setWordWrap(True)
        summary_layout.addWidget(self.recommendation_label)

        self.focus_action_layout = QHBoxLayout()
        self.focus_action_buttons = []
        for index in range(3):
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
        summary_layout.addLayout(self.focus_action_layout)

        self.source_refs_panel = SourceRefsPanel()
        self.source_refs_panel.setObjectName("dashboardSourceRefsLabel")
        self.source_refs_panel.setHidden(True)
        self.source_refs_label = self.source_refs_panel
        summary_layout.addWidget(self.source_refs_panel)

        layout.addWidget(self.summary_group)

        # Per-topic breakdown
        self.topic_group = QGroupBox()
        topic_layout = QVBoxLayout(self.topic_group)

        self.topic_table = QTableWidget()
        self.topic_table.setColumnCount(5)
        self.topic_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.topic_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.topic_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.topic_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.topic_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.topic_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.topic_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.topic_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.topic_table.verticalHeader().setVisible(False)
        self.topic_table.itemSelectionChanged.connect(self._update_mastery_action_state)
        topic_layout.addWidget(self.topic_table)

        self.topic_action_layout = QHBoxLayout()
        self.topic_action_hint = QLabel()
        self.topic_action_hint.setObjectName("dashboardTopicActionHint")
        self.topic_action_layout.addWidget(self.topic_action_hint)
        self.topic_action_layout.addStretch()

        self.practice_topic_btn = QPushButton()
        self.practice_topic_btn.setObjectName("secondaryButton")
        self.practice_topic_btn.clicked.connect(self._request_selected_topic_practice)
        self.topic_action_layout.addWidget(self.practice_topic_btn)

        self.review_topic_btn = QPushButton()
        self.review_topic_btn.setObjectName("secondaryButton")
        self.review_topic_btn.clicked.connect(self._request_selected_topic_review)
        self.topic_action_layout.addWidget(self.review_topic_btn)

        self.more_topic_actions_menu = QMenu(self)
        self.generate_topic_action = QAction(self)
        self.generate_topic_action.triggered.connect(self._request_selected_topic_generation)
        self.more_topic_actions_menu.addAction(self.generate_topic_action)
        self.view_topic_source_action = QAction(self)
        self.view_topic_source_action.triggered.connect(self._show_selected_topic_sources)
        self.more_topic_actions_menu.addAction(self.view_topic_source_action)
        self.mark_mastered_action = QAction(self)
        self.mark_mastered_action.triggered.connect(self._toggle_selected_topic_mastery)
        self.more_topic_actions_menu.addAction(self.mark_mastered_action)

        self.more_topic_actions_btn = QPushButton()
        self.more_topic_actions_btn.setObjectName("secondaryButton")
        self.more_topic_actions_btn.clicked.connect(self._show_more_topic_actions)
        self.topic_action_layout.addWidget(self.more_topic_actions_btn)
        topic_layout.addLayout(self.topic_action_layout)

        layout.addWidget(self.topic_group, 1)
        self.topic_group.hide()

        # Recent sessions
        self.recent_group = QGroupBox()
        recent_layout = QVBoxLayout(self.recent_group)

        recent_header = QHBoxLayout()
        recent_header.addStretch()
        self.recent_toggle_btn = QPushButton()
        self.recent_toggle_btn.setObjectName("secondaryButton")
        self.recent_toggle_btn.clicked.connect(self._toggle_recent_history)
        self.recent_toggle_btn.hide()
        recent_header.addWidget(self.recent_toggle_btn)
        recent_layout.addLayout(recent_header)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("dashboardRecentList")
        self.recent_list.itemActivated.connect(self._open_recent_session)
        recent_layout.addWidget(self.recent_list)

        layout.addWidget(self.recent_group)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("secondaryButton")
        self.refresh_btn.clicked.connect(self.refresh)
        btn_layout.addWidget(self.refresh_btn)

        self.details_toggle_btn = QPushButton()
        self.details_toggle_btn.setObjectName("secondaryButton")
        self.details_toggle_btn.clicked.connect(self._toggle_topic_details)
        btn_layout.addWidget(self.details_toggle_btn)

        layout.addLayout(btn_layout)

        self._update_ui_strings()

    def _update_ui_strings(self):
        """Update all static UI text based on current language."""
        self.title.setText(self.lang_manager.get_text("学习分析", "Learning Analysis"))
        self.summary_group.setTitle(self.lang_manager.get_text("本周与重点", "This Week and Focus"))
        self.topic_group.setTitle(self.lang_manager.get_text("知识点详情", "Topic Details"))
        self.recent_group.setTitle(self.lang_manager.get_text("最近练习", "Recent Practice"))
        self.refresh_btn.setText(self.lang_manager.get_text("刷新", "Refresh"))
        self._update_details_toggle_text()
        self.topic_action_hint.setText(self.lang_manager.get_text("选中主题后可继续练习：", "Select a topic to continue:"))
        self.practice_topic_btn.setText(self.lang_manager.get_text("练 10 题", "Practice 10"))
        self.review_topic_btn.setText(self.lang_manager.get_text("复习错题", "Review Incorrect"))
        self.more_topic_actions_btn.setText(self.lang_manager.get_text("更多操作", "More Actions"))
        self.generate_topic_action.setText(self.lang_manager.get_text("生成新题", "Generate Questions"))
        self.view_topic_source_action.setText(self.lang_manager.get_text("查看来源", "View Sources"))
        self._update_mastery_action_state()
        self.topic_table.setHorizontalHeaderLabels([
            self.lang_manager.get_text("主题", "Topic"),
            self.lang_manager.get_text("练习次数", "Sessions"),
            self.lang_manager.get_text("正确率", "Accuracy"),
            self.lang_manager.get_text("掌握度", "Mastery"),
            self.lang_manager.get_text("题目数", "Questions"),
        ])

    def _on_language_changed(self, lang):
        """Handle language change event - update all UI text and reload data."""
        self._update_ui_strings()
        self.refresh()

    def refresh(self):
        """Reload and display progress data."""
        self._current_project = (
            self.course_manager.get(self._current_course_id)
            if self._current_course_id
            else None
        )
        visible_questions = self._visible_questions()
        visible_question_ids = (
            None
            if visible_questions is None
            else {question.question_id for question in visible_questions}
        )
        stats = self.progress_manager.get_aggregated_stats(visible_question_ids)
        records = self.progress_manager.load_all()
        lang = self.lang_manager.current
        questions = (
            list(visible_questions)
            if visible_questions is not None
            else self.question_bank.load_all()
        )
        topic_index = {
            question.question_id: (
                topic_value(question.topic),
                topic_display_name(
                    question.topic,
                    self._current_course_project(),
                    lang,
                    question.topic_title(),
                ),
            )
            for question in questions
        }
        self._learning_dashboard = build_learning_dashboard(
            topic_index,
            records=records,
            max_focus_topics=10,
        )

        # Overall
        if stats["total_sessions"] == 0:
            self.overall_label.setText(self.lang_manager.get_text(
                "暂无练习记录。开始答题以追踪进度！",
                "No progress yet. Start a quiz to begin tracking!"
            ))
            self.detail_label.clear()
            self.recommendation_label.clear()
            self.recommendation_label.hide()
            self._show_focus_actions(())
            self._set_source_refs([])
        else:
            weekly = self._learning_dashboard.weekly_summary
            self.overall_label.setText(self.lang_manager.get_text(
                f"本周：学习 {weekly.study_days} 天",
                f"This week: {weekly.study_days} day"
                f"{'' if weekly.study_days == 1 else 's'}",
            ))
            zh_detail = (
                f"完成 {weekly.completed_questions} 题 · "
                f"正确率 {weekly.accuracy:.1%}"
            )
            en_detail = (
                f"{weekly.completed_questions} answered · "
                f"{weekly.accuracy:.1%} accuracy"
            )
            self.detail_label.setText(
                self.lang_manager.get_text(zh_detail, en_detail)
            )
            self._update_recommendations()

        # Per-topic breakdown
        self._populate_topic_table(
            lang,
            visible_question_ids,
            questions,
            records=records,
        )

        # Recent sessions
        self.recent_list.clear()
        set_names = {
            qs.set_id: qs.get_title(lang)
            for qs in self.set_manager.load_all()
        }
        for session in stats.get("recent_sessions", []):
            score = session.get("score", 0)
            icon = "🟢" if score >= 80 else ("🟡" if score >= 60 else "🔴")
            archive_view = build_archive_status_view(
                session.get("archive_status", ""),
                missing_fields=session.get("archive_missing_fields", ()),
                snapshot_count=session.get("snapshot_question_count", 0),
                answer_count=session.get("answer_count", 0),
                language=lang,
            )
            set_id = session.get("set_id", "")
            set_name = (
                session.get("set_title_snapshot")
                or set_names.get(set_id)
                or self.lang_manager.get_text("历史练习", "Archived Practice")
            )
            course_name = str(session.get("course_title_snapshot", "") or "").strip()
            title = f"{course_name} · {set_name}" if course_name else set_name
            scope_hint = ""
            if session.get("is_partial"):
                scope_hint = self.lang_manager.get_text(
                    f" | 命中 {session.get('matched_total', 0)}/{session.get('session_total', 0)}",
                    f" | in scope {session.get('matched_total', 0)}/{session.get('session_total', 0)}",
                )
            item = QListWidgetItem(
                f"{icon} {archive_view.badge + ' ' if archive_view.badge else ''}"
                f"{session.get('started_at', '')[:10]} — "
                f"{title} — "
                f"{self.lang_manager.get_text('得分', 'Score')}: {score:.0f}% "
                f"({session.get('correct', 0)}/{session.get('total', 0)})"
                f"{scope_hint}"
            )
            item.setData(Qt.ItemDataRole.UserRole, session.get("progress_id", ""))
            review_hint = self.lang_manager.get_text(
                "双击或按回车复盘本次练习",
                "Double-click or press Enter to review this session",
            )
            item.setToolTip(
                "\n".join(
                    part
                    for part in (archive_view.tooltip, review_hint)
                    if part
                )
            )
            self.recent_list.addItem(item)
        self._update_recent_history_visibility()

    def _open_recent_session(self, item: QListWidgetItem) -> None:
        progress_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if progress_id:
            self.history_requested.emit(progress_id)

    def _toggle_recent_history(self) -> None:
        """Respect the user's choice to reveal or hide a long session history."""
        self._recent_history_expanded = not self._recent_history_expanded
        self._update_recent_history_visibility()

    def _update_recent_history_visibility(self) -> None:
        """Keep short history visible and collapse long history by default."""
        count = self.recent_list.count()
        is_long_history = count > 5
        self.recent_toggle_btn.setVisible(is_long_history)
        self.recent_list.setVisible(not is_long_history or self._recent_history_expanded)
        action_zh = "收起" if self._recent_history_expanded else "展开"
        action_en = "Collapse" if self._recent_history_expanded else "Show"
        self.recent_toggle_btn.setText(self.lang_manager.get_text(
            f"{action_zh}最近记录（{count}）",
            f"{action_en} Recent Sessions ({count})",
        ))

    def set_current_course(self, course_id: str | None):
        """Scope displayed progress to the active course when one is selected."""
        self._current_course_id = (course_id or "").strip()

    def _visible_question_ids(self) -> set[str] | None:
        """Return question IDs visible for the current course, or None for global mode."""
        questions = self._visible_questions()
        if questions is None:
            return None
        return {question.question_id for question in questions}

    def _visible_questions(self) -> list | None:
        """Return questions visible for the current course, or None for global mode."""
        if not self._current_course_id:
            return None
        questions, _total = self.question_bank.search(
            course_id=self._current_course_id,
            limit=1_000_000,
        )
        return questions

    def _populate_topic_table(
        self,
        lang: str,
        visible_question_ids: set[str] | None,
        visible_questions: list | None = None,
        *,
        records=None,
    ):
        """Fill the per-topic breakdown table."""
        # Build per-topic stats from all completed sessions
        all_records = (
            list(records)
            if records is not None
            else self.progress_manager.load_all()
        )
        completed = [r for r in all_records if r.status == "completed" and r.summary]

        # Map question_id -> normalized topic metadata once for all views.
        qid_to_topic = {}
        topic_index = {}
        topic_titles = {}
        if visible_questions is None:
            questions = self.question_bank.load_all()
            if visible_question_ids is not None:
                questions = [q for q in questions if q.question_id in visible_question_ids]
        else:
            questions = list(visible_questions)
        topic_mastery = build_topic_mastery(completed, questions)
        for q in questions:
            topic_id = topic_value(q.topic)
            qid_to_topic[q.question_id] = topic_id
            topic_index[q.question_id] = (topic_id, q.topic_title())
            topic_titles.setdefault(topic_id, q.topic_title())

        # Reuse the same answered-question rules as home and today's plan.
        topic_learning = build_topic_learning(topic_index, completed)
        topic_stats = {
            topic_id: {
                "total": int(values["attempts"]),
                "correct": int(values["correct"]),
                "sessions": set(),
            }
            for topic_id, values in topic_learning.items()
            if int(values["attempts"]) > 0
        }
        for r in completed:
            for ans in r.answers:
                if ans.skipped:
                    continue
                topic = qid_to_topic.get(ans.question_id)
                if topic:
                    topic_stats[topic]["sessions"].add(r.progress_id)

        # Populate table
        self.topic_table.setRowCount(len(topic_stats))
        for row, (topic, stats) in enumerate(sorted(topic_stats.items(), key=lambda x: topic_value(x[0]))):
            label = topic_display_name(
                topic,
                self._current_course_project(),
                lang,
                topic_titles.get(topic_value(topic), ""),
            )
            accuracy = (stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0
            mastery = topic_mastery.get(topic_value(topic))
            is_mastered = self.mastery_overrides.is_topic_mastered(self._current_course_id, topic)
            mastery_text = self.lang_manager.get_text("已掌握", "Mastered") if is_mastered else (
                f"{mastery.mastery_score * 100:.0f}%" if mastery else "0%"
            )

            topic_item = QTableWidgetItem(label)
            topic_item.setData(Qt.ItemDataRole.UserRole, topic_value(topic))
            self.topic_table.setItem(row, 0, topic_item)
            self.topic_table.setItem(row, 1, QTableWidgetItem(str(len(stats["sessions"]))))
            self.topic_table.setItem(row, 2, QTableWidgetItem(f"{accuracy:.0f}%"))
            self.topic_table.setItem(row, 3, QTableWidgetItem(mastery_text))
            self.topic_table.setItem(row, 4, QTableWidgetItem(f"{stats['correct']}/{stats['total']}"))
        self._update_mastery_action_state()

    def _update_recommendations(self):
        """Show at most three diagnosis-first actions without auto-opening sources."""
        topics = []
        for topic in self._learning_dashboard.focus_topics:
            if self.mastery_overrides.is_topic_mastered(
                self._current_course_id,
                topic.topic_id,
            ):
                continue
            topics.append(topic)
            if len(topics) >= 3:
                break

        if not topics:
            self.recommendation_label.clear()
            self.recommendation_label.hide()
            self._show_focus_actions(())
            self._set_source_refs([])
            return

        zh_lines = [
            f"{index}. {topic.title} · 正确率 {topic.accuracy:.0%}"
            for index, topic in enumerate(topics, start=1)
        ]
        en_lines = [
            f"{index}. {topic.title} · {topic.accuracy:.0%} accuracy"
            for index, topic in enumerate(topics, start=1)
        ]
        self.recommendation_label.setText(self.lang_manager.get_text(
            "最需要关注 · 建议复习\n" + "\n".join(zh_lines),
            "Needs the most attention · Suggested review\n"
            + "\n".join(en_lines),
        ))
        self.recommendation_label.show()
        self._show_focus_actions(topics)
        self._set_source_refs([])

    def _show_focus_actions(self, topics) -> None:
        self._recommended_topic_ids = [
            topic.topic_id for topic in topics
        ]
        for index, button in enumerate(self.focus_action_buttons):
            if index < len(topics):
                topic = topics[index]
                button.setText(self.lang_manager.get_text(
                    f"强化 {topic.title}",
                    f"Practice {topic.title}",
                ))
                button.show()
            else:
                button.hide()

    def _request_focus_topic(self, index: int) -> None:
        if 0 <= index < len(self._recommended_topic_ids):
            self.practice_topic_requested.emit(
                self._recommended_topic_ids[index]
            )

    def _toggle_topic_details(self) -> None:
        self.topic_group.setVisible(self.topic_group.isHidden())
        self._update_details_toggle_text()

    def _update_details_toggle_text(self) -> None:
        visible = (
            hasattr(self, "topic_group")
            and not self.topic_group.isHidden()
        )
        self.details_toggle_btn.setText(self.lang_manager.get_text(
            "收起知识点详情" if visible else "查看知识点详情",
            "Hide Topic Details" if visible else "View Topic Details",
        ))

    def _set_source_refs(
        self,
        source_refs: list[dict],
        *,
        label: str | None = None,
        status: str | None = None,
    ) -> None:
        """Show source refs only when they add useful information."""
        self.source_refs_panel.set_source_refs(
            source_refs,
            course_project=self._current_course_project(),
            label=label or self.lang_manager.get_text("相关来源", "Related sources"),
            status=status,
            language=self.lang_manager.current,
        )

    def _source_refs_for_topics(self, questions: list, topic_values: set[str]) -> list[dict]:
        """Return de-duplicated source refs for the currently recommended topics."""
        refs = []
        seen = set()
        for question in questions:
            if topic_value(question.topic) not in topic_values:
                continue
            for ref in (question.metadata or {}).get("source_refs", []):
                if not isinstance(ref, dict):
                    continue
                key = (
                    str(ref.get("source_file", "") or ""),
                    str(ref.get("page_or_slide", "") or ""),
                    str(ref.get("chunk_id", "") or ""),
                    str(ref.get("heading", "") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                refs.append(ref)
                if len(refs) >= 5:
                    return refs
        return refs

    def _selected_topic_key(self) -> str:
        selected = self.topic_table.selectedItems()
        if not selected:
            return ""
        row = selected[0].row()
        item = self.topic_table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _current_course_project(self):
        return self._current_project

    def _update_mastery_action_state(self):
        """Update the selected-topic mastery toggle button."""
        if not hasattr(self, "mark_mastered_action"):
            return
        topic_key = self._selected_topic_key()
        has_topic = bool(topic_key)
        if hasattr(self, "practice_topic_btn"):
            self.practice_topic_btn.setEnabled(has_topic)
        if hasattr(self, "review_topic_btn"):
            self.review_topic_btn.setEnabled(has_topic)
        self.generate_topic_action.setEnabled(has_topic)
        self.view_topic_source_action.setEnabled(has_topic)
        self.mark_mastered_action.setEnabled(has_topic)
        if topic_key and self.mastery_overrides.is_topic_mastered(self._current_course_id, topic_key):
            self.mark_mastered_action.setText(self.lang_manager.get_text("取消已掌握", "Unmark Mastered"))
        else:
            self.mark_mastered_action.setText(self.lang_manager.get_text("标记已掌握", "Mark Mastered"))

    def _show_more_topic_actions(self) -> None:
        self.more_topic_actions_menu.popup(
            self.more_topic_actions_btn.mapToGlobal(
                self.more_topic_actions_btn.rect().bottomLeft()
            )
        )

    def _request_selected_topic_practice(self):
        topic_key = self._selected_topic_key()
        if topic_key:
            self.practice_topic_requested.emit(topic_key)

    def _request_selected_topic_review(self):
        topic_key = self._selected_topic_key()
        if topic_key:
            self.review_topic_requested.emit(topic_key)

    def _request_selected_topic_generation(self):
        topic_key = self._selected_topic_key()
        if topic_key:
            self.generate_topic_requested.emit(topic_key)

    def _show_selected_topic_sources(self):
        topic_key = self._selected_topic_key()
        if not topic_key:
            return
        questions = self._visible_questions()
        if questions is None:
            questions = self.question_bank.load_all()
        selected = [
            question for question in questions
            if topic_value(question.topic) == topic_key
        ]
        refs = self._source_refs_for_topics(selected, {topic_key})
        status = None if refs else self.lang_manager.get_text(
            "该主题暂无可定位的课件来源。",
            "No navigable course source is available for this topic.",
        )
        self._set_source_refs(
            refs,
            label=self.lang_manager.get_text("主题来源", "Topic Sources"),
            status=status,
        )

    def _toggle_selected_topic_mastery(self):
        """Toggle the selected topic's user-managed mastered state."""
        topic_key = self._selected_topic_key()
        if not topic_key:
            return
        if self.mastery_overrides.is_topic_mastered(self._current_course_id, topic_key):
            self.mastery_overrides.unmark_topic_mastered(self._current_course_id, topic_key)
        else:
            self.mastery_overrides.mark_topic_mastered(self._current_course_id, topic_key)
        self.refresh()
