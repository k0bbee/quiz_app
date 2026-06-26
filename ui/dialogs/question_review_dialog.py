"""Question review dialog — preview, edit, accept, or reject generated questions."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QSplitter,
    QMessageBox, QWidget
)
from PyQt6.QtCore import Qt

from models.question import Question
from core.language_manager import LanguageManager
from utils.constants import topic_value


class QuestionReviewDialog(QDialog):
    """Review and approve/reject AI-generated questions before saving."""

    def __init__(self, questions: list[Question], parent=None):
        super().__init__(parent)
        self.questions = list(questions)
        self._accepted: set[int] = set(range(len(questions)))  # indices
        self._current_index: int = -1
        self.lang_manager = LanguageManager.instance()

        self.setWindowTitle(self.lang_manager.get_text("审查生成的题目", "Review Generated Questions"))
        self.resize(900, 600)
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

        if self.questions:
            self.question_list.setCurrentRow(0)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        self.header = QLabel(
            self.lang_manager.get_text(
                f"已生成 {len(self.questions)} 道题目，请审查并接受或拒绝。",
                f"Generated {len(self.questions)} questions. Review and accept/reject each one."
            )
        )
        self.header.setObjectName("dialogHeader")
        layout.addWidget(self.header)

        # Splitter: list on left, preview on right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: question list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.questions_label = QLabel(self.lang_manager.get_text("题目列表:", "Questions:"))
        left_layout.addWidget(self.questions_label)

        self.question_list = QListWidget()
        self.question_list.setMinimumWidth(250)
        for i, q in enumerate(self.questions):
            lang = self.lang_manager.current
            stem = q.get_stem(lang)
            short = stem[:80] + "..." if len(stem) > 80 else stem
            item = QListWidgetItem(f"Q{i + 1}: {short}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.question_list.addItem(item)
        self.question_list.currentRowChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.question_list)

        # Accept all / reject all buttons
        bulk_layout = QHBoxLayout()
        self.accept_all_btn = QPushButton(self.lang_manager.get_text("✓ 全部接受", "✓ Accept All"))
        self.accept_all_btn.setObjectName("secondaryButton")
        self.accept_all_btn.clicked.connect(self._accept_all)
        self.reject_all_btn = QPushButton(self.lang_manager.get_text("✗ 全部拒绝", "✗ Reject All"))
        self.reject_all_btn.setObjectName("dangerButton")
        self.reject_all_btn.clicked.connect(self._reject_all)
        bulk_layout.addWidget(self.accept_all_btn)
        bulk_layout.addWidget(self.reject_all_btn)
        left_layout.addLayout(bulk_layout)

        splitter.addWidget(left_widget)

        # Right: question preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.preview_label = QLabel(self.lang_manager.get_text("选择题目以预览", "Select a question to preview"))
        self.preview_label.setObjectName("dialogPreviewLabel")
        right_layout.addWidget(self.preview_label)

        self.detail_editor = QTextEdit()
        self.detail_editor.setReadOnly(True)
        self.detail_editor.setObjectName("dialogDetailEditor")
        right_layout.addWidget(self.detail_editor, 1)

        # Accept/reject for current question
        action_layout = QHBoxLayout()
        self.accept_btn = QPushButton(self.lang_manager.get_text("✓ 接受", "✓ Accept"))
        self.accept_btn.setObjectName("secondaryButton")
        self.accept_btn.clicked.connect(self._accept_current)
        action_layout.addWidget(self.accept_btn)

        self.reject_btn = QPushButton(self.lang_manager.get_text("✗ 拒绝", "✗ Reject"))
        self.reject_btn.setObjectName("dangerButton")
        self.reject_btn.clicked.connect(self._reject_current)
        action_layout.addWidget(self.reject_btn)

        action_layout.addStretch()
        right_layout.addLayout(action_layout)

        splitter.addWidget(right_widget)
        splitter.setSizes([300, 550])
        layout.addWidget(splitter, 1)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton(self.lang_manager.get_text("取消", "Cancel"))
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton(self.lang_manager.get_text("保存已接受的题目", "Save Accepted Questions"))
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setMinimumHeight(36)
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _on_language_changed(self, lang):
        """Update all UI strings when language changes."""
        self.setWindowTitle(self.lang_manager.get_text("审查生成的题目", "Review Generated Questions"))
        self.header.setText(
            self.lang_manager.get_text(
                f"已生成 {len(self.questions)} 道题目，请审查并接受或拒绝。",
                f"Generated {len(self.questions)} questions. Review and accept/reject each one."
            )
        )
        self.questions_label.setText(self.lang_manager.get_text("题目列表:", "Questions:"))
        self.accept_all_btn.setText(self.lang_manager.get_text("✓ 全部接受", "✓ Accept All"))
        self.reject_all_btn.setText(self.lang_manager.get_text("✗ 全部拒绝", "✗ Reject All"))
        self.preview_label.setText(self.lang_manager.get_text("选择题目以预览", "Select a question to preview"))
        self.accept_btn.setText(self.lang_manager.get_text("✓ 接受", "✓ Accept"))
        self.reject_btn.setText(self.lang_manager.get_text("✗ 拒绝", "✗ Reject"))
        self.cancel_btn.setText(self.lang_manager.get_text("取消", "Cancel"))
        self.save_btn.setText(self.lang_manager.get_text("保存已接受的题目", "Save Accepted Questions"))

        # Update list item stems (may change with language)
        for i in range(len(self.questions)):
            self._update_list_item(i)

        # Refresh preview if a question is currently selected
        if self._current_index >= 0:
            self._on_selection_changed(self._current_index)

    def _on_selection_changed(self, row: int):
        """Display question details in the preview panel."""
        if row < 0 or row >= len(self.questions):
            return

        self._current_index = row
        q = self.questions[row]
        is_accepted = row in self._accepted

        if is_accepted:
            status = self.lang_manager.get_text("已接受", "ACCEPTED")
        else:
            status = self.lang_manager.get_text("已拒绝", "REJECTED")
        self.preview_label.setText(f"Q{row + 1} — [{status}]")

        # Build detail text
        lang = self.lang_manager.current
        details = f"Type: {q.type.value}\n"
        details += f"Difficulty: {q.difficulty.value}\n"
        details += f"Topic: {topic_value(q.topic)}\n"
        details += f"Subtopic: {q.subtopic}\n"
        details += f"Correct Answer: {q.correct_answer}\n"
        details += f"\n--- ZH Stem ---\n{q.get_stem('zh')}\n"
        if q.get_options('zh'):
            details += f"\nOptions:\n" + "\n".join(q.get_options('zh'))
        details += f"\n--- EN Stem ---\n{q.get_stem('en')}\n"
        if q.get_options('en'):
            details += f"\nOptions:\n" + "\n".join(q.get_options('en'))
        details += f"\n--- Explanation (ZH) ---\n{q.get_explanation('zh')}"
        details += f"\n--- Explanation (EN) ---\n{q.get_explanation('en')}"

        self.detail_editor.setPlainText(details)

    def _accept_current(self):
        """Accept the currently viewed question."""
        if self._current_index >= 0:
            self._accepted.add(self._current_index)
            self._update_list_item(self._current_index)

    def _reject_current(self):
        """Reject the currently viewed question."""
        if self._current_index >= 0:
            self._accepted.discard(self._current_index)
            self._update_list_item(self._current_index)

    def _accept_all(self):
        """Accept all questions."""
        for i in range(len(self.questions)):
            self._accepted.add(i)
            self._update_list_item(i)

    def _reject_all(self):
        """Reject all questions."""
        self._accepted.clear()
        for i in range(len(self.questions)):
            self._update_list_item(i)

    def _update_list_item(self, index: int):
        """Update the visual indicator on a list item."""
        item = self.question_list.item(index)
        if item is None:
            return
        q = self.questions[index]
        lang = self.lang_manager.current
        stem = q.get_stem(lang)
        short = stem[:80] + "..." if len(stem) > 80 else stem
        prefix = "✓ " if index in self._accepted else "✗ "
        item.setText(f"{prefix}Q{index + 1}: {short}")

    def _on_save(self):
        """Validate and save accepted questions."""
        accepted_count = len(self._accepted)
        if accepted_count == 0:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("没有接受的题目", "No Questions"),
                self.lang_manager.get_text("请至少接受一道题目。", "Please accept at least one question.")
            )
            return

        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("保存题目?", "Save Questions?"),
            self.lang_manager.get_text(
                f"保存 {accepted_count} 道已接受的题目？\n它们将被添加到题库中。",
                f"Save {accepted_count} accepted question(s)?\nThey will be added to the question bank."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.accept()

    def get_accepted_questions(self) -> list[Question]:
        """Return only the accepted questions."""
        return [self.questions[i] for i in sorted(self._accepted)]
