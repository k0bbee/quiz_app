"""Question bank CRUD screen with search and pagination."""

from __future__ import annotations

import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QTextEdit, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.language_manager import LanguageManager
from core.question_bank_maintenance import remove_question_from_sets
from models.question import Question, QuestionBank
from models.question_set import SetManager
from ui.widgets.wheel_safe_controls import WheelSafeComboBox
from utils.constants import Difficulty, QuestionType, topic_value


class QuestionBankScreen(QWidget):
    """Manage question JSON records."""

    question_bank_changed = pyqtSignal()

    def __init__(self, question_bank: QuestionBank, set_manager: SetManager | None = None, parent=None):
        super().__init__(parent)
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.lang_manager = LanguageManager.instance()
        self.page_size = 25
        self.page = 0
        self.total = 0
        self.current_question_id = ""
        self._current_course_id = ""
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        self.title = QLabel(self.lang_manager.get_text("题库管理", "Question Bank"))
        self.title.setObjectName("screenTitle")
        layout.addWidget(self.title)

        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            self.lang_manager.get_text("搜索题干、解析、主题", "Search stem, explanation, topic")
        )
        self.search_input.textChanged.connect(self._reset_and_refresh)
        filter_row.addWidget(self.search_input, 2)

        self.difficulty_filter = WheelSafeComboBox()
        self.difficulty_filter.addItem(self.lang_manager.get_text("全部难度", "All difficulty"), None)
        for difficulty in Difficulty:
            self.difficulty_filter.addItem(difficulty.value, difficulty.value)
        self.difficulty_filter.currentIndexChanged.connect(self._reset_and_refresh)
        filter_row.addWidget(self.difficulty_filter)
        layout.addLayout(filter_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.question_list = QListWidget()
        self.question_list.currentItemChanged.connect(self._on_question_selected)
        left_layout.addWidget(self.question_list, 1)

        page_row = QHBoxLayout()
        self.prev_btn = QPushButton(self.lang_manager.get_text("上一页", "Prev"))
        self.prev_btn.setObjectName("secondaryButton")
        self.prev_btn.clicked.connect(self._prev_page)
        page_row.addWidget(self.prev_btn)
        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_row.addWidget(self.page_label, 1)
        self.next_btn = QPushButton(self.lang_manager.get_text("下一页", "Next"))
        self.next_btn.setObjectName("secondaryButton")
        self.next_btn.clicked.connect(self._next_page)
        page_row.addWidget(self.next_btn)
        left_layout.addLayout(page_row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.json_label = QLabel(self.lang_manager.get_text("题目 JSON:", "Question JSON:"))
        right_layout.addWidget(self.json_label)
        self.editor = QTextEdit()
        self.editor.setObjectName("questionBankEditor")
        right_layout.addWidget(self.editor, 1)

        action_row = QHBoxLayout()
        self.new_btn = QPushButton(self.lang_manager.get_text("新建", "New"))
        self.new_btn.setObjectName("secondaryButton")
        self.new_btn.clicked.connect(self._new_question)
        action_row.addWidget(self.new_btn)
        self.save_btn = QPushButton(self.lang_manager.get_text("保存", "Save"))
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._save_question)
        action_row.addWidget(self.save_btn)
        self.delete_btn = QPushButton(self.lang_manager.get_text("删除", "Delete"))
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._delete_question)
        action_row.addWidget(self.delete_btn)
        right_layout.addLayout(action_row)
        splitter.addWidget(right)
        splitter.setSizes([360, 640])

        layout.addWidget(splitter, 1)

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self._update_ui_texts()
        self.refresh()

    def _update_ui_texts(self):
        """Refresh all static UI strings after language switch."""
        self.title.setText(self.lang_manager.get_text("题库管理", "Question Bank"))
        self.search_input.setPlaceholderText(
            self.lang_manager.get_text("搜索题干、解析、主题", "Search stem, explanation, topic")
        )

        # Rebuild difficulty filter, preserving current selection
        current_data = self.difficulty_filter.currentData()
        self.difficulty_filter.blockSignals(True)
        self.difficulty_filter.clear()
        self.difficulty_filter.addItem(self.lang_manager.get_text("全部难度", "All difficulty"), None)
        for difficulty in Difficulty:
            self.difficulty_filter.addItem(difficulty.value, difficulty.value)
        idx = self.difficulty_filter.findData(current_data)
        if idx >= 0:
            self.difficulty_filter.setCurrentIndex(idx)
        self.difficulty_filter.blockSignals(False)

        self.prev_btn.setText(self.lang_manager.get_text("上一页", "Prev"))
        self.next_btn.setText(self.lang_manager.get_text("下一页", "Next"))
        self.json_label.setText(self.lang_manager.get_text("题目 JSON:", "Question JSON:"))
        self.new_btn.setText(self.lang_manager.get_text("新建", "New"))
        self.save_btn.setText(self.lang_manager.get_text("保存", "Save"))
        self.delete_btn.setText(self.lang_manager.get_text("删除", "Delete"))

    def refresh(self):
        """Reload current page."""
        query = self.search_input.text()
        difficulty = self.difficulty_filter.currentData()
        items, self.total = self.question_bank.search(
            query=query,
            difficulty=difficulty,
            course_id=self._current_course_id,
            offset=self.page * self.page_size,
            limit=self.page_size,
        )
        self.question_list.clear()
        for q in items:
            stem = q.get_stem("zh") or q.get_stem("en")
            short = stem[:90] + "..." if len(stem) > 90 else stem
            item = QListWidgetItem(f"{q.difficulty.value} | {topic_value(q.topic)} | {short}")
            item.setData(Qt.ItemDataRole.UserRole, q.question_id)
            self.question_list.addItem(item)

        max_page = max(1, (self.total + self.page_size - 1) // self.page_size)
        page_pattern = self.lang_manager.get_text(
            "第 {page}/{max} 页（共 {total} 题）",
            "Page {page}/{max} ({total} questions)"
        )
        self.page_label.setText(page_pattern.format(page=self.page + 1, max=max_page, total=self.total))
        self.prev_btn.setEnabled(self.page > 0)
        self.next_btn.setEnabled((self.page + 1) * self.page_size < self.total)
        self.delete_btn.setEnabled(bool(self.current_question_id))

    def set_current_course(self, course_id: str | None):
        """Restrict generated questions to the active course."""
        course_id = course_id or ""
        if course_id == self._current_course_id:
            return
        self._current_course_id = course_id
        self.page = 0
        self.current_question_id = ""
        if hasattr(self, "question_list"):
            self.refresh()

    def _reset_and_refresh(self):
        self.page = 0
        self.refresh()

    def _prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.refresh()

    def _next_page(self):
        if (self.page + 1) * self.page_size < self.total:
            self.page += 1
            self.refresh()

    def _on_question_selected(self, current, previous):
        if current is None:
            return
        qid = current.data(Qt.ItemDataRole.UserRole)
        q = self.question_bank.get(qid)
        if not q:
            return
        self.current_question_id = q.question_id
        self.editor.setPlainText(json.dumps(q.to_dict(), ensure_ascii=False, indent=2))
        self.delete_btn.setEnabled(True)

    def _new_question(self):
        template = {
            "question_id": "",
            "type": QuestionType.MULTIPLE_CHOICE.value,
            "difficulty": Difficulty.MEDIUM.value,
            "topic": "general",
            "subtopic": "",
            "correct_answer": "A",
            "bilingual": {
                "zh": {
                    "stem": "",
                    "options": ["A. ", "B. ", "C. ", "D. "],
                    "explanation": "",
                },
                "en": {
                    "stem": "",
                    "options": ["A. ", "B. ", "C. ", "D. "],
                    "explanation": "",
                },
            },
            "metadata": {"source": "manual", "version": 1},
        }
        self.current_question_id = ""
        self.editor.setPlainText(json.dumps(template, ensure_ascii=False, indent=2))
        self.delete_btn.setEnabled(False)

    def _save_question(self):
        try:
            data = json.loads(self.editor.toPlainText())
            if not data.get("question_id"):
                q = Question.create_new(
                    qtype=QuestionType(data.get("type", "multiple_choice")),
                    difficulty=Difficulty(data.get("difficulty", "medium")),
                    bilingual=data.get("bilingual", {}),
                    correct_answer=data.get("correct_answer"),
                    topic=data.get("topic", "general"),
                    subtopic=data.get("subtopic", ""),
                    source=data.get("metadata", {}).get("source", "manual"),
                )
                q.metadata.update(data.get("metadata") or {})
                if self._current_course_id:
                    q.metadata["course_id"] = self._current_course_id
            else:
                q = Question.from_dict(data)
        except Exception as exc:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("无效JSON", "Invalid JSON"),
                str(exc)
            )
            return

        errors = q.validate()
        if errors:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("验证失败", "Validation Failed"),
                "\n".join(errors)
            )
            return
        self.question_bank.save(q)
        self.current_question_id = q.question_id
        self.question_bank_changed.emit()
        self.refresh()
        QMessageBox.information(
            self,
            self.lang_manager.get_text("保存成功", "Saved"),
            self.lang_manager.get_text("题目已保存。", "Question saved.")
        )

    def _delete_question(self):
        if not self.current_question_id:
            return
        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("删除题目", "Delete Question"),
            self.lang_manager.get_text(
                "确定要删除这道题目吗？",
                "Delete this question?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted_question_id = self.current_question_id
        self.question_bank.delete(deleted_question_id)
        if self.set_manager is not None:
            remove_question_from_sets(self.set_manager, deleted_question_id)
        self.current_question_id = ""
        self.editor.clear()
        self.question_bank_changed.emit()
        self.refresh()
