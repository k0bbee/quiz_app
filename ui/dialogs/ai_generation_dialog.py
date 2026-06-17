"""AI question generation dialog — wizard for selecting topics and generating."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QSpinBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox, QCheckBox,
    QAbstractItemView, QScrollArea, QFrame, QWidget
)
from PyQt6.QtCore import Qt

from utils.constants import topic_label, topic_value
from core.language_manager import LanguageManager
from ai.llm_client import LLMClient
from ai.batch_generator import GenerationWorker
from models.question import Question
from ui.dialogs.question_review_dialog import QuestionReviewDialog
from ai.course_context import extract_relevant_course_context
from core.course_index import retrieve_course_context


class AIGenerationDialog(QDialog):
    """Dialog for generating questions via AI."""

    def __init__(self, course_content: str, settings: dict, parent=None, available_topics: list = None, course_project=None):
        super().__init__(parent)
        self.course_content = course_content
        self.settings = settings
        self.available_topics = available_topics or []
        self.course_project = course_project
        self.lang_manager = LanguageManager.instance()
        self.generated_questions: list[Question] = []
        self.worker: GenerationWorker = None

        self.setWindowTitle(self.lang_manager.get_text("AI 出题", "AI Question Generation"))
        self.resize(700, 550)
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        # Outer layout: scroll area + fixed bottom bar
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 12, 16, 4)

        # Topic selection
        self.topic_group = QGroupBox(self.lang_manager.get_text("选择主题", "Select Topics"))
        topic_layout = QVBoxLayout(self.topic_group)

        # Select all / deselect all
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton(self.lang_manager.get_text("全选", "Select All"))
        self.select_all_btn.clicked.connect(lambda: self._toggle_all(True))
        self.deselect_btn = QPushButton(self.lang_manager.get_text("取消全选", "Deselect All"))
        self.deselect_btn.clicked.connect(lambda: self._toggle_all(False))
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.deselect_btn)
        btn_row.addStretch()
        topic_layout.addLayout(btn_row)

        self.topic_list = QListWidget()
        lang = self.lang_manager.current
        for topic in self.available_topics:
            label = topic_label(topic, lang)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, topic)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.topic_list.addItem(item)
        # Use standard selection with checkboxes; don't disable selection
        self.topic_list.itemChanged.connect(lambda _item: self._update_preview())
        topic_layout.addWidget(self.topic_list)

        layout.addWidget(self.topic_group)

        # Configuration row
        config_layout = QHBoxLayout()

        self.count_label = QLabel(self.lang_manager.get_text("数量:", "Count:"))
        config_layout.addWidget(self.count_label)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(3, 60)
        self.count_spin.setValue(15)
        config_layout.addWidget(self.count_spin)

        self.diff_label = QLabel(self.lang_manager.get_text("难度:", "Difficulty:"))
        config_layout.addWidget(self.diff_label)
        self.diff_combo = QComboBox()
        difficulties = [
            (self.lang_manager.get_text("简单", "easy"), "easy"),
            (self.lang_manager.get_text("中等", "medium"), "medium"),
            (self.lang_manager.get_text("困难", "hard"), "hard"),
            (self.lang_manager.get_text("混合", "mixed"), "mixed"),
        ]
        for display, value in difficulties:
            self.diff_combo.addItem(display, value)
        # Default to medium
        for i in range(self.diff_combo.count()):
            if self.diff_combo.itemData(i) == "medium":
                self.diff_combo.setCurrentIndex(i)
                break
        config_layout.addWidget(self.diff_combo)

        config_layout.addStretch()
        layout.addLayout(config_layout)

        # Prompt preview (optional)
        self.prompt_group = QGroupBox(self.lang_manager.get_text("课程内容预览", "Course Content Preview"))
        prompt_layout = QVBoxLayout(self.prompt_group)
        self.prompt_preview = QTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setMaximumHeight(120)
        prompt_layout.addWidget(self.prompt_preview)
        layout.addWidget(self.prompt_group)

        self._update_preview()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # Fixed bottom bar (always visible)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 4, 16, 12)
        bottom_layout.setSpacing(8)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        bottom_layout.addWidget(self.progress_bar)

        self.status_label = QLabel()
        bottom_layout.addWidget(self.status_label)

        # Action buttons
        btn_layout = QHBoxLayout()

        self.cancel_btn = QPushButton(self.lang_manager.get_text("取消", "Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        btn_layout.addStretch()

        self.generate_btn = QPushButton(self.lang_manager.get_text("生成题目 🚀", "Generate Questions 🚀"))
        self.generate_btn.setMinimumHeight(40)
        self.generate_btn.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.generate_btn.clicked.connect(self._start_generation)
        btn_layout.addWidget(self.generate_btn)

        bottom_layout.addLayout(btn_layout)
        outer.addWidget(bottom)

    def _on_language_changed(self, lang):
        """Update all UI strings when language changes."""
        self.setWindowTitle(self.lang_manager.get_text("AI 出题", "AI Question Generation"))
        self.topic_group.setTitle(self.lang_manager.get_text("选择主题", "Select Topics"))
        self.select_all_btn.setText(self.lang_manager.get_text("全选", "Select All"))
        self.deselect_btn.setText(self.lang_manager.get_text("取消全选", "Deselect All"))

        # Update topic list items
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            topic = item.data(Qt.ItemDataRole.UserRole)
            item.setText(topic_label(topic, lang))

        self.count_label.setText(self.lang_manager.get_text("数量:", "Count:"))
        self.diff_label.setText(self.lang_manager.get_text("难度:", "Difficulty:"))

        # Rebuild difficulty combo items preserving the selected value
        current_diff = self.diff_combo.currentData()
        self.diff_combo.clear()
        difficulties = [
            (self.lang_manager.get_text("简单", "easy"), "easy"),
            (self.lang_manager.get_text("中等", "medium"), "medium"),
            (self.lang_manager.get_text("困难", "hard"), "hard"),
            (self.lang_manager.get_text("混合", "mixed"), "mixed"),
        ]
        for display, value in difficulties:
            self.diff_combo.addItem(display, value)
        for i in range(self.diff_combo.count()):
            if self.diff_combo.itemData(i) == current_diff:
                self.diff_combo.setCurrentIndex(i)
                break

        self.prompt_group.setTitle(self.lang_manager.get_text("课程内容预览", "Course Content Preview"))
        self._update_preview()

        self.cancel_btn.setText(self.lang_manager.get_text("取消", "Cancel"))
        self.generate_btn.setText(self.lang_manager.get_text("生成题目 🚀", "Generate Questions 🚀"))

    def _toggle_all(self, selected: bool):
        """Select/deselect all topics."""
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def _get_selected_topics(self) -> list:
        """Get list of selected Topic enums."""
        topics = []
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                topics.append(item.data(Qt.ItemDataRole.UserRole))
        return topics

    def _update_preview(self):
        """Show a brief preview of relevant course content."""
        topics = self._get_selected_topics()
        if not topics:
            self.prompt_preview.setPlainText(
                self.lang_manager.get_text(
                    "选择主题以查看相关课程内容...",
                    "Select topics to see relevant course content..."
                )
            )
            return

        topic_names = [
            topic_label(t, self.lang_manager.current) for t in topics
        ]
        if self.course_project is not None:
            context = retrieve_course_context(
                self.course_project,
                [topic_value(t) for t in topics],
                max_chars=1800,
            )
        else:
            context = extract_relevant_course_context(self.course_content, topics, max_chars=1800)

        if self.lang_manager.current == "zh":
            preview = (
                f"已选择 {len(topics)} 个主题: {', '.join(topic_names)}\n"
                f"提示上下文预览:\n\n{context[:1800]}"
            )
        else:
            preview = (
                f"Selected {len(topics)} topic(s): {', '.join(topic_names)}\n"
                f"Prompt context preview:\n\n{context[:1800]}"
            )
        self.prompt_preview.setPlainText(preview)

    def _start_generation(self):
        """Start the background generation process."""
        topics = self._get_selected_topics()
        if not topics:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("未选择主题", "No Topics"),
                self.lang_manager.get_text("请至少选择一个主题。", "Please select at least one topic.")
            )
            return

        provider = self.settings.get("ai_provider", "")
        from core.secrets_manager import SecretsManager
        api_key = SecretsManager.instance().get_key()
        if provider != "local_agent" and not api_key:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("未配置 API Key", "No API Key"),
                self.lang_manager.get_text("请在设置中配置 API Key。", "Please configure your API key in Settings.")
            )
            return

        base_url = self.settings.get("ai_base_url", "https://api.anthropic.com/v1")
        model = self.settings.get("ai_model", "claude-sonnet-4-6")
        count = self.count_spin.value()
        difficulty = self.diff_combo.currentData()

        # Disable UI during generation
        self.generate_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate

        # Create client and worker
        client = LLMClient(api_key=api_key, base_url=base_url, model=model)
        self.worker = GenerationWorker(
            client, self.course_content, topics, count, difficulty, course_project=self.course_project
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.batch_done.connect(self._on_batch_done)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, message: str):
        self.status_label.setText(message)

    def _on_batch_done(self, questions: list[Question]):
        self.generated_questions = questions

    def _on_error(self, message: str):
        if self.lang_manager.current == "zh":
            self.status_label.setText(f"错误: {message}")
        else:
            self.status_label.setText(f"Error: {message}")
        QMessageBox.critical(self, self.lang_manager.get_text("生成错误", "Generation Error"), message)
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    def _on_finished(self):
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)

        if self.generated_questions:
            if self.lang_manager.current == "zh":
                self.status_label.setText(f"已生成 {len(self.generated_questions)} 道题目。正在打开预览...")
            else:
                self.status_label.setText(f"Generated {len(self.generated_questions)} questions. Opening review...")
            # Open review dialog
            review_dialog = QuestionReviewDialog(self.generated_questions, self)
            if review_dialog.exec() == QDialog.DialogCode.Accepted:
                accepted = review_dialog.get_accepted_questions()
                if not accepted:
                    QMessageBox.warning(
                        self,
                        self.lang_manager.get_text("没有接受的题目", "No Questions Accepted"),
                        self.lang_manager.get_text(
                            "没有题目被接受，请至少接受一道题目或取消操作。",
                            "No questions were accepted. Please accept at least one or cancel."
                        )
                    )
                    self.generate_btn.setEnabled(True)
                    self.progress_bar.setVisible(False)
                    return
                self.generated_questions = accepted
                self.accept()
        else:
            self.status_label.setText(self.lang_manager.get_text("未生成任何题目。", "No questions were generated."))

        # Clean up worker thread
        if self.worker:
            self.worker.wait(2000)
        else:
            self.status_label.setText(self.lang_manager.get_text("未生成任何题目。", "No questions were generated."))

    def reject(self):
        """Cancel generation if the dialog is closed while a worker is running."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            # Wait up to 5s for clean shutdown, then force-terminate
            if not self.worker.wait(5000):
                self.worker.terminate()
                self.worker.wait(1000)
        super().reject()
