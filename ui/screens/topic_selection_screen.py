"""Topic selection screen — choose topics, difficulty, and question count."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QLineEdit,
    QMessageBox
)
from PyQt6.QtCore import pyqtSignal, Qt

from utils.constants import topic_label, topic_value
from core.language_manager import LanguageManager
from models.question_set import SetManager


class TopicSelectionScreen(QWidget):
    """Screen for selecting a question set and configuring quiz parameters."""

    quiz_start = pyqtSignal(str, list)  # set_id, question_ids
    export_mock_exam = pyqtSignal(str)  # set_id
    regenerate_questions = pyqtSignal(str)  # set_id
    back_to_home = pyqtSignal()

    def __init__(self, set_manager: SetManager, progress_manager=None, parent=None):
        super().__init__(parent)
        self.set_manager = set_manager
        self.progress_manager = progress_manager
        self.lang_manager = LanguageManager.instance()
        self._all_sets = []
        self._current_course_id = ""
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        # Title
        self.title_label = QLabel(self.lang_manager.get_text("选择题目集", "Select Question Set"))
        self.title_label.setObjectName("screenTitle")
        layout.addWidget(self.title_label)

        # Filters
        filter_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.lang_manager.get_text("搜索...", "Search..."))
        self.search_input.textChanged.connect(self._render_sets)
        filter_layout.addWidget(self.search_input, 2)

        self.topic_filter = QComboBox()
        self.topic_filter.setEditable(True)
        self.topic_filter.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.topic_filter.currentIndexChanged.connect(self._render_sets)
        filter_layout.addWidget(self.topic_filter, 1)

        self.difficulty_filter = QComboBox()
        self.difficulty_filter.currentIndexChanged.connect(self._render_sets)
        filter_layout.addWidget(self.difficulty_filter)

        layout.addLayout(filter_layout)

        # Question set list
        self.list_label = QLabel(self.lang_manager.get_text("可用的题目集:", "Available question sets:"))
        layout.addWidget(self.list_label)
        self.set_list = QListWidget()
        self.set_list.setObjectName("topicSetList")
        self.set_list.setMinimumHeight(250)
        self.set_list.currentItemChanged.connect(self._on_set_selected)
        layout.addWidget(self.set_list)

        # Set info
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # Start button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.back_btn = QPushButton(self.lang_manager.get_text("← 返回", "← Back"))
        self.back_btn.setObjectName("secondaryButton")
        self.back_btn.clicked.connect(self.back_to_home.emit)
        btn_layout.addWidget(self.back_btn)

        self.export_btn = QPushButton(self.lang_manager.get_text("Export Mock Exam", "Export Mock Exam"))
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.setMinimumHeight(40)
        self.export_btn.clicked.connect(self._export_selected_set)
        self.export_btn.setEnabled(False)
        btn_layout.addWidget(self.export_btn)

        self.regenerate_btn = QPushButton(self.lang_manager.get_text("Regenerate Questions", "Regenerate Questions"))
        self.regenerate_btn.setObjectName("secondaryButton")
        self.regenerate_btn.setMinimumHeight(40)
        self.regenerate_btn.clicked.connect(self._regenerate_selected_set)
        self.regenerate_btn.setEnabled(False)
        btn_layout.addWidget(self.regenerate_btn)

        self.start_btn = QPushButton(self.lang_manager.get_text("▶ 开始答题", "▶ Start Quiz"))
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
        self.search_input.setPlaceholderText(self.lang_manager.get_text("搜索...", "Search..."))
        self.list_label.setText(self.lang_manager.get_text("可用的题目集:", "Available question sets:"))
        self.back_btn.setText(self.lang_manager.get_text("← 返回", "← Back"))
        self.export_btn.setText(self.lang_manager.get_text("Export Mock Exam", "Export Mock Exam"))
        self.regenerate_btn.setText(self.lang_manager.get_text("Regenerate Questions", "Regenerate Questions"))
        self.start_btn.setText(self.lang_manager.get_text("▶ 开始答题", "▶ Start Quiz"))
        self.refresh()

    def _on_set_selected(self, current, previous):
        """Display info about the selected question set."""
        if current is None:
            self.info_label.clear()
            self.start_btn.setEnabled(False)
            self.export_btn.setEnabled(False)
            self.regenerate_btn.setEnabled(False)
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
            self.start_btn.setEnabled(True)
            self.export_btn.setEnabled(True)
            self.regenerate_btn.setEnabled(True)

    def _start_quiz(self):
        """Emit signal to start the quiz with selected set."""
        current = self.set_list.currentItem()
        if not current:
            return

        set_id = current.data(Qt.ItemDataRole.UserRole)
        qset = self.set_manager.get(set_id)
        if qset:
            self.quiz_start.emit(set_id, qset.questions)


    def _export_selected_set(self):
        """Emit signal to export the selected question set as a mock exam."""
        current = self.set_list.currentItem()
        if not current:
            return
        self.export_mock_exam.emit(current.data(Qt.ItemDataRole.UserRole))

    def _regenerate_selected_set(self):
        """Emit signal to regenerate questions for the selected question set."""
        current = self.set_list.currentItem()
        if not current:
            return
        self.regenerate_questions.emit(current.data(Qt.ItemDataRole.UserRole))

    def set_current_course(self, course_id: str | None):
        """Restrict generated question sets to the active course."""
        course_id = course_id or ""
        if course_id == self._current_course_id:
            return
        self._current_course_id = course_id
        if hasattr(self, "set_list"):
            self.refresh()

    def refresh(self):
        """Reload the question set list."""
        lang = self.lang_manager.current
        self._all_sets = [
            qset for qset in self.set_manager.load_all()
            if self._matches_current_course(qset)
        ]

        self.topic_filter.blockSignals(True)
        current_topic = self.topic_filter.currentData()
        self.topic_filter.clear()
        self.topic_filter.addItem(self.lang_manager.get_text("全部主题", "All topics"), None)
        seen_topics = []
        for qs in self._all_sets:
            for topic in qs.topics:
                if topic not in seen_topics:
                    seen_topics.append(topic)
        for topic in sorted(seen_topics, key=topic_value):
            self.topic_filter.addItem(topic_label(topic, lang), topic)
        if current_topic is not None:
            idx = self.topic_filter.findData(current_topic)
            if idx >= 0:
                self.topic_filter.setCurrentIndex(idx)
        self.topic_filter.blockSignals(False)

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
        self.info_label.clear()

    def _render_sets(self):
        """Render the filtered question-set list."""
        if not hasattr(self, "set_list"):
            return

        self.set_list.clear()
        lang = self.lang_manager.current
        query = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        topic_filter = self.topic_filter.currentData() if hasattr(self, "topic_filter") else None
        diff_filter = self.difficulty_filter.currentData() if hasattr(self, "difficulty_filter") else None

        visible = [qs for qs in self._all_sets if self._matches_filters(qs, query, topic_filter, diff_filter, lang)]
        for qs in visible:
            completed = []
            if self.progress_manager:
                completed = [
                    r for r in self.progress_manager.load_for_set(qs.set_id)
                    if r.status == "completed" and r.summary
                ]
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

    def _matches_filters(self, qset, query: str, topic_filter, diff_filter, lang: str) -> bool:
        """Return True if a question set should be shown."""
        if topic_filter is not None and topic_filter not in qset.topics:
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

    def _matches_current_course(self, qset) -> bool:
        source_course_id = (qset.metadata or {}).get("course_id", "")
        if not source_course_id:
            return True
        if not self._current_course_id:
            return True
        return source_course_id == self._current_course_id
