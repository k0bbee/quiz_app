"""Topic selection screen — choose topics, difficulty, and question count."""

from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QLineEdit,
    QMessageBox, QAbstractItemView, QInputDialog
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer

from utils.constants import topic_label, topic_value
from core.language_manager import LanguageManager
from models.question_set import SetManager
from ui.widgets.wheel_safe_controls import WheelSafeComboBox


class TopicSelectionScreen(QWidget):
    """Screen for selecting a question set and configuring quiz parameters."""

    quiz_start = pyqtSignal(str, list)  # set_id, question_ids
    export_mock_exam = pyqtSignal(str)  # set_id
    export_mock_exams = pyqtSignal(list)  # set_ids
    regenerate_questions = pyqtSignal(str)  # set_id
    def __init__(self, set_manager: SetManager, progress_manager=None, parent=None):
        super().__init__(parent)
        self.set_manager = set_manager
        self.progress_manager = progress_manager
        self.lang_manager = LanguageManager.instance()
        self._all_sets = []
        self._current_course_id = ""
        self._current_course_title = ""
        self._updating_topic_filter = False
        self.search_debounce_timer = QTimer(self)
        self.search_debounce_timer.setSingleShot(True)
        self.search_debounce_timer.setInterval(250)
        self.search_debounce_timer.timeout.connect(self._render_sets)
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        # Title
        self.title_label = QLabel(self.lang_manager.get_text("选择题目集", "Select Question Set"))
        self.title_label.setObjectName("screenTitle")
        layout.addWidget(self.title_label)

        self.course_context_label = QLabel()
        self.course_context_label.setObjectName("topicCourseContextLabel")
        self.course_context_label.setWordWrap(True)
        layout.addWidget(self.course_context_label)
        self._update_course_context_label()

        # Filters
        filter_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.lang_manager.get_text("搜索...", "Search..."))
        self.search_input.textChanged.connect(self._schedule_search_render)
        filter_layout.addWidget(self.search_input, 2)

        self.topic_filter = WheelSafeComboBox()
        self.topic_filter.setEditable(True)
        self.topic_filter.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.topic_filter.lineEdit().setReadOnly(True)
        self.topic_filter.currentIndexChanged.connect(self._render_sets)
        self.topic_filter.model().itemChanged.connect(self._on_topic_filter_item_changed)
        filter_layout.addWidget(self.topic_filter, 1)

        self.difficulty_filter = WheelSafeComboBox()
        self.difficulty_filter.currentIndexChanged.connect(self._render_sets)
        filter_layout.addWidget(self.difficulty_filter)

        layout.addLayout(filter_layout)

        # Question set list
        self.list_label = QLabel(self.lang_manager.get_text("可用的题目集:", "Available question sets:"))
        layout.addWidget(self.list_label)
        self.set_list = QListWidget()
        self.set_list.setObjectName("topicSetList")
        self.set_list.setMinimumHeight(250)
        self.set_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.set_list.currentItemChanged.connect(self._on_set_selected)
        self.set_list.itemSelectionChanged.connect(self._on_set_selection_changed)
        layout.addWidget(self.set_list)

        # Set info
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # Start button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.export_btn = QPushButton(self.lang_manager.get_text("导出模拟卷", "Export Mock Exam"))
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.setMinimumHeight(40)
        self.export_btn.clicked.connect(self._export_selected_set)
        self.export_btn.setEnabled(False)
        btn_layout.addWidget(self.export_btn)

        self.regenerate_btn = QPushButton(self.lang_manager.get_text("重新生成题目", "Regenerate Questions"))
        self.regenerate_btn.setObjectName("secondaryButton")
        self.regenerate_btn.setMinimumHeight(40)
        self.regenerate_btn.clicked.connect(self._regenerate_selected_set)
        self.regenerate_btn.setEnabled(False)
        self.regenerate_btn.setHidden(True)
        btn_layout.addWidget(self.regenerate_btn)

        self.rename_btn = QPushButton(self.lang_manager.get_text("重命名", "Rename"))
        self.rename_btn.setObjectName("secondaryButton")
        self.rename_btn.setMinimumHeight(40)
        self.rename_btn.clicked.connect(self._rename_selected_set)
        self.rename_btn.setEnabled(False)
        btn_layout.addWidget(self.rename_btn)

        self.start_btn = QPushButton(self.lang_manager.get_text("开始答题", "Start Quiz"))
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self._start_quiz)
        self.start_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)

        layout.addLayout(btn_layout)

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self.title_label.setText(self.lang_manager.get_text("选择题目集", "Select Question Set"))
        self._update_course_context_label()
        self.search_input.setPlaceholderText(self.lang_manager.get_text("搜索...", "Search..."))
        self.list_label.setText(self.lang_manager.get_text("可用的题目集:", "Available question sets:"))
        self.export_btn.setText(self.lang_manager.get_text("导出模拟卷", "Export Mock Exam"))
        self.regenerate_btn.setText(self.lang_manager.get_text("重新生成题目", "Regenerate Questions"))
        self.rename_btn.setText(self.lang_manager.get_text("重命名", "Rename"))
        self.start_btn.setText(self.lang_manager.get_text("开始答题", "Start Quiz"))
        self.refresh()

    def _on_set_selected(self, current, previous):
        """Display info about the selected question set."""
        if current is None:
            self.info_label.clear()
            self.start_btn.setEnabled(False)
            self.export_btn.setEnabled(False)
            self.regenerate_btn.setEnabled(False)
            self.regenerate_btn.setHidden(True)
            self.rename_btn.setEnabled(False)
            return

        set_id = current.data(Qt.ItemDataRole.UserRole)
        qset = self.set_manager.get(set_id)
        if qset:
            lang = self.lang_manager.current
            topics_str = ", ".join(topic_label(t, lang) for t in qset.topics)
            attempts = self.progress_manager.load_for_set(set_id) if self.progress_manager else []
            completed = [r for r in attempts if r.status == "completed" and r.summary]
            recent_score = f"{completed[0].summary.score_percentage:.0f}%" if completed else "N/A"
            best_score = f"{max(r.summary.score_percentage for r in completed):.0f}%" if completed else "N/A"
            self.info_label.setText(
                f"<b>{qset.get_title(lang)}</b><br>"
                f"{qset.get_description(lang)}<br><br>"
                f"{self.lang_manager.get_text('题目数:', 'Questions:')} {qset.question_count} | "
                f"{self.lang_manager.get_text('难度:', 'Difficulty:')} {qset.difficulty.value} | "
                f"{self.lang_manager.get_text('预计时间:', 'Est. time:')} {qset.estimated_minutes} "
                f"{self.lang_manager.get_text('分钟', 'min')}<br>"
                f"{self.lang_manager.get_text('主题:', 'Topics:')} {topics_str}<br>"
                f"{self.lang_manager.get_text('练习次数:', 'Attempts:')} {len(completed)} | "
                f"{self.lang_manager.get_text('最近:', 'Recent:')} {recent_score} | "
                f"{self.lang_manager.get_text('最佳:', 'Best:')} {best_score}"
            )
            self._on_set_selection_changed()

    def _on_set_selection_changed(self):
        """Keep action availability aligned with single vs batch selection."""
        selected_ids = self._selected_set_ids()
        has_selection = bool(selected_ids)
        single_selection = len(selected_ids) == 1
        selected_set = self.set_manager.get(selected_ids[0]) if single_selection else None
        can_regenerate = single_selection and self._is_regeneratable_set(selected_set)
        self.export_btn.setEnabled(has_selection)
        self.start_btn.setEnabled(single_selection)
        self.regenerate_btn.setHidden(not can_regenerate)
        self.regenerate_btn.setEnabled(can_regenerate)
        self.rename_btn.setEnabled(single_selection)

    def _start_quiz(self):
        """Emit signal to start the quiz with selected set."""
        set_ids = self._selected_set_ids()
        if len(set_ids) != 1:
            return

        set_id = set_ids[0]
        qset = self.set_manager.get(set_id)
        if qset:
            self.quiz_start.emit(set_id, qset.questions)


    def _export_selected_set(self):
        """Emit signal to export selected question sets as mock exams."""
        set_ids = self._selected_set_ids()
        if len(set_ids) == 1:
            self.export_mock_exam.emit(set_ids[0])
        elif len(set_ids) > 1:
            self.export_mock_exams.emit(set_ids)

    def _regenerate_selected_set(self):
        """Emit signal to regenerate questions for the selected question set."""
        set_ids = self._selected_set_ids()
        if len(set_ids) != 1:
            return
        qset = self.set_manager.get(set_ids[0])
        if not self._is_regeneratable_set(qset):
            return
        self.regenerate_questions.emit(set_ids[0])

    def _rename_selected_set(self):
        """Let the user rename the selected question set."""
        set_ids = self._selected_set_ids()
        if len(set_ids) != 1:
            return
        qset = self.set_manager.get(set_ids[0])
        if not qset:
            return
        lang = self.lang_manager.current
        new_title, accepted = QInputDialog.getText(
            self,
            self.lang_manager.get_text("重命名题目集", "Rename Question Set"),
            self.lang_manager.get_text("题目集名称:", "Question set name:"),
            text=qset.get_title(lang),
        )
        new_title = new_title.strip()
        if not accepted or not new_title:
            return
        qset.title["zh"] = new_title
        qset.title["en"] = new_title
        qset.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
        qset.metadata["renamed_by_user"] = True
        self.set_manager.save(qset)
        self.refresh()
        for row in range(self.set_list.count()):
            item = self.set_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == qset.set_id:
                self.set_list.setCurrentRow(row)
                break

    def set_current_course(self, course_id: str | None, course_title: str | None = None):
        """Restrict generated question sets to the active course."""
        course_id = course_id or ""
        course_title = (course_title or "").strip()
        if course_id == self._current_course_id and course_title == self._current_course_title:
            return
        self._current_course_id = course_id
        self._current_course_title = course_title
        self._update_course_context_label()
        if hasattr(self, "set_list"):
            self.refresh()

    def _update_course_context_label(self):
        """Show which course scope the question set list currently uses."""
        title = self._current_course_title or self._current_course_id
        if title:
            self.course_context_label.setText(
                self.lang_manager.get_text(
                    f"当前课程：{title}",
                    f"Showing sets for: {title}",
                )
            )
        else:
            self.course_context_label.setText(
                self.lang_manager.get_text("当前课程：全部课程", "Showing sets for: All courses")
            )

    def refresh(self):
        """Reload the question set list."""
        lang = self.lang_manager.current
        self._all_sets = [
            qset for qset in self.set_manager.load_all()
            if self._matches_current_course(qset)
        ]

        self._updating_topic_filter = True
        self.topic_filter.blockSignals(True)
        self.topic_filter.model().blockSignals(True)
        current_topics = {topic_value(topic) for topic in self._selected_topic_filters()}
        self.topic_filter.clear()
        self.topic_filter.addItem(self.lang_manager.get_text("全部主题", "All topics"), None)
        self._configure_topic_filter_item(0, checked=not current_topics)
        seen_topics = []
        for qs in self._all_sets:
            for topic in qs.topics:
                if topic not in seen_topics:
                    seen_topics.append(topic)
        for topic in sorted(seen_topics, key=topic_value):
            self.topic_filter.addItem(topic_label(topic, lang), topic)
            self._configure_topic_filter_item(
                self.topic_filter.count() - 1,
                checked=topic_value(topic) in current_topics,
            )
        self.topic_filter.model().blockSignals(False)
        self.topic_filter.blockSignals(False)
        self._updating_topic_filter = False
        self._update_topic_filter_label()

        self.difficulty_filter.blockSignals(True)
        current_diff = self.difficulty_filter.currentData()
        self.difficulty_filter.clear()
        self.difficulty_filter.addItem(self.lang_manager.get_text("全部难度", "All"), None)
        for diff in ("easy", "medium", "hard"):
            self.difficulty_filter.addItem(diff, diff)
        if current_diff is not None:
            idx = self.difficulty_filter.findData(current_diff)
            if idx >= 0:
                self.difficulty_filter.setCurrentIndex(idx)
        self.difficulty_filter.blockSignals(False)

        self._render_sets()

        self.start_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.regenerate_btn.setEnabled(False)
        self.regenerate_btn.setHidden(True)
        self.rename_btn.setEnabled(False)
        self.info_label.clear()

    def _schedule_search_render(self):
        """Debounce free-text search to avoid rerendering on every keystroke."""
        self.search_debounce_timer.start()

    def _render_sets(self):
        """Render the filtered question-set list."""
        if not hasattr(self, "set_list"):
            return

        self.set_list.clear()
        lang = self.lang_manager.current
        query = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        topic_filters = self._selected_topic_filters() if hasattr(self, "topic_filter") else []
        diff_filter = self.difficulty_filter.currentData() if hasattr(self, "difficulty_filter") else None

        visible = [qs for qs in self._all_sets if self._matches_filters(qs, query, topic_filters, diff_filter, lang)]
        completed_by_set = self._completed_progress_by_set() if self.progress_manager else {}
        for qs in visible:
            completed = completed_by_set.get(qs.set_id, [])
            score_hint = ""
            if completed:
                score_hint = (
                    f" | {self.lang_manager.get_text('最近', 'recent')} "
                    f"{completed[0].summary.score_percentage:.0f}%"
                )
            item = QListWidgetItem(
                f"{qs.get_title(lang)}  [{qs.question_count} "
                f"{self.lang_manager.get_text('题', 'questions')}, "
                f"{qs.estimated_minutes} {self.lang_manager.get_text('分钟', 'min')}"
                f"{score_hint}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, qs.set_id)
            self.set_list.addItem(item)

        if not visible:
            self.info_label.setText(
                self.lang_manager.get_text(
                    "没有匹配的题目集。请调整搜索/筛选条件。",
                    "No matching question sets. Adjust search/filter."
                )
            )
            self.start_btn.setEnabled(False)
            self.export_btn.setEnabled(False)
            self.regenerate_btn.setEnabled(False)
            self.regenerate_btn.setHidden(True)
            self.rename_btn.setEnabled(False)

    def _completed_progress_by_set(self) -> dict[str, list]:
        """Return completed progress records grouped by set id using one bulk load."""
        grouped: dict[str, list] = {}
        if not self.progress_manager:
            return grouped
        for record in self.progress_manager.load_all():
            if record.status != "completed" or not record.summary:
                continue
            grouped.setdefault(record.set_id, []).append(record)
        return grouped

    def _matches_filters(self, qset, query: str, topic_filters, diff_filter, lang: str) -> bool:
        """Return True if a question set should be shown."""
        selected_topic_values = {topic_value(topic) for topic in topic_filters}
        if selected_topic_values and not any(topic_value(topic) in selected_topic_values for topic in qset.topics):
            return False
        if diff_filter is not None and qset.difficulty.value != diff_filter:
            return False
        if not query:
            return True

        topic_text = " ".join(
            f"{topic_value(t)} {topic_label(t, 'zh')} {topic_label(t, 'en')}"
            for t in qset.topics
        )
        haystack = " ".join([
            qset.get_title("zh"),
            qset.get_title("en"),
            qset.get_description("zh"),
            qset.get_description("en"),
            topic_text,
        ]).lower()
        return query in haystack

    def _configure_topic_filter_item(self, row: int, checked: bool = False):
        """Make a topic filter row checkable."""
        item = self.topic_filter.model().item(row)
        if item is None:
            return
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _selected_topic_filters(self) -> list[object]:
        """Return checked topic filter values; empty means all topics."""
        if not hasattr(self, "topic_filter"):
            return []
        selected = []
        model = self.topic_filter.model()
        for row in range(self.topic_filter.count()):
            topic = self.topic_filter.itemData(row)
            if topic is None:
                continue
            item = model.item(row)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected.append(topic)
        return selected

    def _on_topic_filter_item_changed(self, item):
        """Apply multi-topic filter changes from checkable combo rows."""
        if self._updating_topic_filter:
            return
        self._updating_topic_filter = True
        try:
            changed_topic = item.data(Qt.ItemDataRole.UserRole)
            model = self.topic_filter.model()
            all_item = model.item(0)
            if changed_topic is None and item.checkState() == Qt.CheckState.Checked:
                for row in range(1, self.topic_filter.count()):
                    topic_item = model.item(row)
                    if topic_item:
                        topic_item.setCheckState(Qt.CheckState.Unchecked)
            elif changed_topic is not None and item.checkState() == Qt.CheckState.Checked and all_item:
                all_item.setCheckState(Qt.CheckState.Unchecked)
            if all_item and not self._selected_topic_filters():
                all_item.setCheckState(Qt.CheckState.Checked)
        finally:
            self._updating_topic_filter = False

        self._update_topic_filter_label()
        self._render_sets()

    def _update_topic_filter_label(self):
        """Show a compact label for the current multi-topic filter."""
        if not hasattr(self, "topic_filter") or not self.topic_filter.isEditable():
            return
        count = len(self._selected_topic_filters())
        if count == 0:
            text = self.lang_manager.get_text("全部主题", "All topics")
        else:
            text = self.lang_manager.get_text(f"已选 {count} 个主题", f"{count} topics selected")
        self.topic_filter.lineEdit().setText(text)

    def _selected_set_ids(self) -> list[str]:
        """Return selected question-set ids without duplicates."""
        items = self.set_list.selectedItems() if hasattr(self, "set_list") else []
        set_ids = []
        seen = set()
        for item in items:
            set_id = item.data(Qt.ItemDataRole.UserRole)
            if set_id and set_id not in seen:
                seen.add(set_id)
                set_ids.append(set_id)
        return set_ids

    def _matches_current_course(self, qset) -> bool:
        source_course_id = (qset.metadata or {}).get("course_id", "")
        if not source_course_id:
            return True
        if not self._current_course_id:
            return True
        return source_course_id == self._current_course_id

    @staticmethod
    def _is_regeneratable_set(qset) -> bool:
        if not qset:
            return False
        source = str((qset.metadata or {}).get("source", "") or "").strip().lower()
        return source in {"ai_generated", "ai_regenerated"}
