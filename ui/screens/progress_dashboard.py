"""Progress dashboard — aggregated stats, history, per-topic breakdown."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem,
    QGroupBox, QHeaderView, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt

from core.progress_tracker import ProgressManager
from core.mastery import build_topic_mastery
from core.mastery_overrides import MasteryOverrideStore
from models.question import QuestionBank
from models.question_set import SetManager
from utils.constants import topic_label, topic_value
from core.language_manager import LanguageManager
from config import QUESTION_SETS_DIR


class ProgressDashboard(QWidget):
    """Aggregated progress statistics and session history."""

    def __init__(
        self,
        progress_manager: ProgressManager,
        question_bank: QuestionBank,
        parent=None,
        mastery_overrides: MasteryOverrideStore | None = None,
    ):
        super().__init__(parent)
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.set_manager = SetManager(QUESTION_SETS_DIR)
        self.lang_manager = LanguageManager.instance()
        self.mastery_overrides = mastery_overrides or MasteryOverrideStore()
        self._current_course_id = ""
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.title = QLabel()
        self.title.setObjectName("screenTitle")
        layout.addWidget(self.title)

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

        layout.addWidget(self.topic_group, 1)

        # Recent sessions
        self.recent_group = QGroupBox()
        recent_layout = QVBoxLayout(self.recent_group)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("dashboardRecentList")
        recent_layout.addWidget(self.recent_list)

        layout.addWidget(self.recent_group)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("secondaryButton")
        self.refresh_btn.clicked.connect(self.refresh)
        btn_layout.addWidget(self.refresh_btn)

        self.mark_mastered_btn = QPushButton()
        self.mark_mastered_btn.setObjectName("secondaryButton")
        self.mark_mastered_btn.clicked.connect(self._toggle_selected_topic_mastery)
        btn_layout.addWidget(self.mark_mastered_btn)

        self.reset_btn = QPushButton()
        self.reset_btn.setObjectName("dangerButton")
        self.reset_btn.clicked.connect(self._reset_progress)
        btn_layout.addWidget(self.reset_btn)

        layout.addLayout(btn_layout)

        self._update_ui_strings()

    def _update_ui_strings(self):
        """Update all static UI text based on current language."""
        self.title.setText(self.lang_manager.get_text("进度面板", "Progress Dashboard"))
        self.summary_group.setTitle(self.lang_manager.get_text("总览", "Overall"))
        self.topic_group.setTitle(self.lang_manager.get_text("按主题", "By Topic"))
        self.recent_group.setTitle(self.lang_manager.get_text("最近记录", "Recent Sessions"))
        self.refresh_btn.setText(self.lang_manager.get_text("刷新", "Refresh"))
        self._update_mastery_action_state()
        self.reset_btn.setText(self.lang_manager.get_text("重置全部进度", "Reset All Progress"))
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
        visible_question_ids = self._visible_question_ids()
        stats = self.progress_manager.get_aggregated_stats(visible_question_ids)
        lang = self.lang_manager.current

        # Overall
        if stats["total_sessions"] == 0:
            self.overall_label.setText(self.lang_manager.get_text(
                "暂无练习记录。开始答题以追踪进度！",
                "No progress yet. Start a quiz to begin tracking!"
            ))
            self.detail_label.clear()
            self.recommendation_label.clear()
        else:
            self.overall_label.setText(self.lang_manager.get_text(
                f"练习: {stats['total_sessions']} 次 | 题目: {stats['total_questions']} 题 | 正确率: {stats['overall_accuracy']:.1f}%",
                f"Sessions: {stats['total_sessions']} | Questions: {stats['total_questions']} | Accuracy: {stats['overall_accuracy']:.1f}%"
            ))
            self.detail_label.setText(self.lang_manager.get_text(
                f"正确: {stats['total_correct']} / {stats['total_questions']}",
                f"Correct: {stats['total_correct']} / {stats['total_questions']}"
            ))
            self._update_recommendations(lang, visible_question_ids)

        # Per-topic breakdown
        self._populate_topic_table(lang, visible_question_ids)

        # Recent sessions
        self.recent_list.clear()
        set_names = {
            qs.set_id: qs.get_title(lang)
            for qs in self.set_manager.load_all()
        }
        for session in stats.get("recent_sessions", []):
            score = session.get("score", 0)
            icon = "🟢" if score >= 80 else ("🟡" if score >= 60 else "🔴")
            set_name = set_names.get(session.get("set_id", ""), session.get("set_id", "Custom"))
            item = QListWidgetItem(
                f"{icon} {session.get('started_at', '')[:10]} — "
                f"{set_name} — "
                f"Score: {score:.0f}% "
                f"({session.get('correct', 0)}/{session.get('total', 0)})"
            )
            self.recent_list.addItem(item)

    def set_current_course(self, course_id: str | None):
        """Scope displayed progress to the active course when one is selected."""
        self._current_course_id = (course_id or "").strip()

    def _visible_question_ids(self) -> set[str] | None:
        """Return question IDs visible for the current course, or None for global mode."""
        if not self._current_course_id:
            return None
        questions, _total = self.question_bank.search(
            course_id=self._current_course_id,
            limit=1_000_000,
        )
        return {question.question_id for question in questions}

    def _populate_topic_table(self, lang: str, visible_question_ids: set[str] | None):
        """Fill the per-topic breakdown table."""
        # Build per-topic stats from all completed sessions
        all_records = self.progress_manager.load_all()
        completed = [r for r in all_records if r.status == "completed" and r.summary]

        # Map question_id -> topic
        qid_to_topic = {}
        questions = self.question_bank.load_all()
        if visible_question_ids is not None:
            questions = [q for q in questions if q.question_id in visible_question_ids]
        topic_mastery = build_topic_mastery(completed, questions)
        for q in questions:
            qid_to_topic[q.question_id] = q.topic

        # Aggregate by topic
        topic_stats = {}
        for r in completed:
            for ans in r.answers:
                topic = qid_to_topic.get(ans.question_id)
                if topic:
                    if topic not in topic_stats:
                        topic_stats[topic] = {"total": 0, "correct": 0, "sessions": set()}
                    topic_stats[topic]["total"] += 1
                    if ans.is_correct:
                        topic_stats[topic]["correct"] += 1
                    topic_stats[topic]["sessions"].add(r.progress_id)

        # Populate table
        self.topic_table.setRowCount(len(topic_stats))
        for row, (topic, stats) in enumerate(sorted(topic_stats.items(), key=lambda x: topic_value(x[0]))):
            label = topic_label(topic, lang)
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

    def _update_recommendations(self, lang: str, visible_question_ids: set[str] | None):
        """Show compact next-review topic suggestions."""
        prioritized_ids = self.progress_manager.get_prioritized_review_question_ids(visible_question_ids)
        questions = self.question_bank.get_many(
            prioritized_ids,
            course_id=self._current_course_id,
        )

        labels = []
        seen_topics = set()
        for question in questions:
            if self.mastery_overrides.is_topic_mastered(self._current_course_id, question.topic):
                continue
            value = topic_value(question.topic)
            if value in seen_topics:
                continue
            seen_topics.add(value)
            labels.append(topic_label(question.topic, lang))
            if len(labels) >= 3:
                break

        if not labels:
            self.recommendation_label.clear()
            return

        topics = ", ".join(labels)
        self.recommendation_label.setText(self.lang_manager.get_text(
            f"建议复习: {topics}",
            f"Suggested review: {topics}",
        ))

    def _selected_topic_key(self) -> str:
        selected = self.topic_table.selectedItems()
        if not selected:
            return ""
        row = selected[0].row()
        item = self.topic_table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _update_mastery_action_state(self):
        """Update the selected-topic mastery toggle button."""
        if not hasattr(self, "mark_mastered_btn"):
            return
        topic_key = self._selected_topic_key()
        self.mark_mastered_btn.setEnabled(bool(topic_key))
        if topic_key and self.mastery_overrides.is_topic_mastered(self._current_course_id, topic_key):
            self.mark_mastered_btn.setText(self.lang_manager.get_text("取消已掌握", "Unmark Mastered"))
        else:
            self.mark_mastered_btn.setText(self.lang_manager.get_text("标记已掌握", "Mark Mastered"))

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

    def _reset_progress(self):
        """Confirm and reset all progress."""
        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("重置进度?", "Reset Progress?"),
            self.lang_manager.get_text(
                "确定要删除所有进度记录吗?",
                "Are you sure you want to delete ALL progress records?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.progress_manager.reset_all()
            self.mastery_overrides.clear()
            self.refresh()
