"""Question bank CRUD screen with search and pagination."""

from __future__ import annotations

import json
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QTextEdit, QMessageBox, QSplitter,
    QAbstractItemView, QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from core.language_manager import LanguageManager
from core.question_bank_maintenance import backfill_source_refs_from_course, remove_question_from_sets
from core.question_validation import validate_question_quality
from models.course_project import CourseProjectManager
from models.question import Question, QuestionBank
from models.question_set import SetManager
from ui.widgets.source_refs_panel import SourceRefsPanel
from ui.widgets.question_form_editor import QuestionFormEditor
from ui.widgets.wheel_safe_controls import WheelSafeComboBox
from utils.constants import Difficulty, QuestionType, topic_value


class QuestionBankScreen(QWidget):
    """Manage question JSON records."""

    question_bank_changed = pyqtSignal()

    def __init__(
        self,
        question_bank: QuestionBank,
        set_manager: SetManager | None = None,
        course_manager: CourseProjectManager | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.course_manager = course_manager or CourseProjectManager()
        self.lang_manager = LanguageManager.instance()
        self.page_size = 25
        self.page = 0
        self.total = 0
        self.current_question_id = ""
        self._current_course_id = ""
        self._list_title_limit = 96
        self._refreshing_set_filter = False
        self.search_debounce_timer = QTimer(self)
        self.search_debounce_timer.setSingleShot(True)
        self.search_debounce_timer.setInterval(250)
        self.search_debounce_timer.timeout.connect(self._reset_and_refresh)
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
        self.search_input.textChanged.connect(self._schedule_search_refresh)
        filter_row.addWidget(self.search_input, 2)

        self.set_filter = WheelSafeComboBox()
        self.set_filter.currentIndexChanged.connect(self._reset_and_refresh)
        filter_row.addWidget(self.set_filter, 1)

        self.difficulty_filter = WheelSafeComboBox()
        self.difficulty_filter.addItem(self.lang_manager.get_text("全部难度", "All difficulty"), None)
        for difficulty in Difficulty:
            self.difficulty_filter.addItem(difficulty.value, difficulty.value)
        self.difficulty_filter.currentIndexChanged.connect(self._reset_and_refresh)
        filter_row.addWidget(self.difficulty_filter)

        self.quality_filter = WheelSafeComboBox()
        self._populate_quality_filter()
        self.quality_filter.currentIndexChanged.connect(self._reset_and_refresh)
        filter_row.addWidget(self.quality_filter)

        self.backfill_source_refs_btn = QPushButton(
            self.lang_manager.get_text("关联课程原文", "Link to Course Materials")
        )
        self.backfill_source_refs_btn.setObjectName("secondaryButton")
        self.backfill_source_refs_btn.setToolTip(
            self.lang_manager.get_text(
                "用当前课程资料补全题目来源片段",
                "Enrich question source snippets from the current course",
            )
        )
        self.backfill_source_refs_btn.clicked.connect(self._backfill_source_refs)
        filter_row.addWidget(self.backfill_source_refs_btn)
        layout.addLayout(filter_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.question_list = QListWidget()
        self.question_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.question_list.itemSelectionChanged.connect(self._on_selection_changed)
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
        self.source_refs_panel = SourceRefsPanel()
        self.source_refs_panel.setObjectName("questionBankSourceRefs")
        self.source_refs_panel.setVisible(False)
        self.source_refs_label = self.source_refs_panel
        right_layout.addWidget(self.source_refs_panel)

        editor_header = QHBoxLayout()
        self.json_label = QLabel(self.lang_manager.get_text("题目编辑", "Question Editor"))
        editor_header.addWidget(self.json_label, 1)
        self.editor_mode_btn = QPushButton()
        self.editor_mode_btn.setObjectName("secondaryButton")
        self.editor_mode_btn.clicked.connect(self._toggle_editor_mode)
        editor_header.addWidget(self.editor_mode_btn)
        right_layout.addLayout(editor_header)
        self.detail_stack = QStackedWidget()
        self.form_editor = QuestionFormEditor()
        self.detail_stack.addWidget(self.form_editor)
        self.editor = QTextEdit()
        self.editor.setObjectName("questionBankEditor")
        self.detail_stack.addWidget(self.editor)
        right_layout.addWidget(self.detail_stack, 1)
        self._update_editor_mode_button()

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
        self._refresh_set_filter()

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

        self._populate_quality_filter()
        self.prev_btn.setText(self.lang_manager.get_text("上一页", "Prev"))
        self.next_btn.setText(self.lang_manager.get_text("下一页", "Next"))
        self.json_label.setText(self.lang_manager.get_text("题目编辑", "Question Editor"))
        self.new_btn.setText(self.lang_manager.get_text("新建", "New"))
        self.save_btn.setText(self.lang_manager.get_text("保存", "Save"))
        self.delete_btn.setText(self.lang_manager.get_text("删除", "Delete"))
        self.backfill_source_refs_btn.setText(
            self.lang_manager.get_text("关联课程原文", "Link to Course Materials")
        )
        self.backfill_source_refs_btn.setToolTip(
            self.lang_manager.get_text(
                "用当前课程资料补全题目来源片段",
                "Enrich question source snippets from the current course",
            )
        )
        self._update_editor_mode_button()

    def refresh(self):
        """Reload current page."""
        query = self.search_input.text()
        difficulty = self.difficulty_filter.currentData()
        quality_filter = self.quality_filter.currentData()
        metadata_filter = self._quality_filter_predicate(quality_filter)
        self._refresh_set_filter()
        selected_set_id = self._selected_set_id()
        if selected_set_id:
            all_items = self._questions_for_set(
                selected_set_id,
                query=query,
                difficulty=difficulty,
                quality_filter=quality_filter,
            )
            self.total = len(all_items)
            start = self.page * self.page_size
            items = all_items[start:start + self.page_size]
        else:
            items, self.total = self.question_bank.search(
                query=query,
                difficulty=difficulty,
                course_id=self._current_course_id,
                metadata_filter=metadata_filter,
                offset=self.page * self.page_size,
                limit=self.page_size,
            )
        selected_ids = set(self._selected_question_ids())
        if not selected_ids and self.current_question_id:
            selected_ids.add(self.current_question_id)
        self.question_list.blockSignals(True)
        self.question_list.clear()
        for q in items:
            item = QListWidgetItem(self._question_list_title(q))
            item.setData(Qt.ItemDataRole.UserRole, q.question_id)
            item.setToolTip(self._question_list_tooltip(q))
            self.question_list.addItem(item)
            if q.question_id in selected_ids:
                item.setSelected(True)
        self.question_list.blockSignals(False)
        if not self._selected_question_ids() and self.question_list.count() > 0:
            self.question_list.setCurrentRow(0)
        else:
            self._on_selection_changed()

        max_page = max(1, (self.total + self.page_size - 1) // self.page_size)
        page_pattern = self.lang_manager.get_text(
            "第 {page}/{max} 页（共 {total} 题）",
            "Page {page}/{max} ({total} questions)"
        )
        self.page_label.setText(page_pattern.format(page=self.page + 1, max=max_page, total=self.total))
        self.prev_btn.setEnabled(self.page > 0)
        self.next_btn.setEnabled((self.page + 1) * self.page_size < self.total)
        self.delete_btn.setEnabled(bool(self._selected_question_ids()) or bool(self.current_question_id))

    def set_current_course(self, course_id: str | None):
        """Restrict generated questions to the active course."""
        course_id = course_id or ""
        if course_id == self._current_course_id:
            return
        self._current_course_id = course_id
        self.form_editor.set_topics(self._current_course_topics())
        self.page = 0
        self.current_question_id = ""
        if hasattr(self, "question_list"):
            self.refresh()

    def _reset_and_refresh(self):
        self.page = 0
        self.refresh()

    def _schedule_search_refresh(self):
        """Debounce free-text search to avoid reloading on every keystroke."""
        self.search_debounce_timer.start()

    def _prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.refresh()

    def _next_page(self):
        if (self.page + 1) * self.page_size < self.total:
            self.page += 1
            self.refresh()

    def _on_selection_changed(self):
        selected_ids = self._selected_question_ids()
        if not selected_ids:
            self.current_question_id = ""
            self._set_source_refs_summary(None)
            self._show_empty_state()
            self.delete_btn.setEnabled(False)
            return
        if len(selected_ids) > 1:
            self.current_question_id = ""
            self._set_source_refs_summary(None)
            self.editor.setReadOnly(True)
            self.editor.setPlainText(
                self.lang_manager.get_text(
                    f"已选择 {len(selected_ids)} 道题。批量删除可用；编辑请只选择一道题。",
                    f"{len(selected_ids)} questions selected. Batch delete is available; select one question to edit.",
                )
            )
            self.detail_stack.setCurrentWidget(self.editor)
            self.editor_mode_btn.setEnabled(False)
            self._update_editor_mode_button()
            self.save_btn.setEnabled(False)
            self.delete_btn.setEnabled(True)
            return

        qid = selected_ids[0]
        q = self.question_bank.get(qid)
        if not q:
            return
        self.current_question_id = q.question_id
        self.editor.setReadOnly(False)
        self._set_source_refs_summary(q)
        payload = q.to_dict()
        self.form_editor.set_topics(self._current_course_topics())
        self.form_editor.load_payload(payload)
        self.editor.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self.detail_stack.setCurrentWidget(self.form_editor)
        self.editor_mode_btn.setEnabled(True)
        self._update_editor_mode_button()
        self.save_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _show_empty_state(self):
        """Show an explicit empty detail state instead of a blank editor."""
        self.editor.setReadOnly(True)
        self.editor.setPlainText(
            self.lang_manager.get_text(
                "没有匹配的题目。\n\n请调整搜索/筛选条件，或点击“新建”创建题目。",
                "No matching questions.\n\nAdjust search/filter options, or click New to create a question.",
            )
        )
        self.detail_stack.setCurrentWidget(self.editor)
        self.editor_mode_btn.setEnabled(False)
        self._update_editor_mode_button()
        self.save_btn.setEnabled(False)

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
        self.question_list.blockSignals(True)
        self.question_list.clearSelection()
        self.question_list.setCurrentItem(None)
        self.question_list.blockSignals(False)
        self.current_question_id = ""
        self._set_source_refs_summary(None)
        self.form_editor.set_topics(self._current_course_topics())
        self.form_editor.load_payload(template)
        self.editor.setReadOnly(False)
        self.editor.setPlainText(json.dumps(template, ensure_ascii=False, indent=2))
        self.detail_stack.setCurrentWidget(self.form_editor)
        self.editor_mode_btn.setEnabled(True)
        self._update_editor_mode_button()
        self.save_btn.setEnabled(True)
        self.delete_btn.setEnabled(False)

    def _save_question(self):
        try:
            if self.detail_stack.currentWidget() is self.form_editor:
                data = self.form_editor.to_payload()
            else:
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

    def _toggle_editor_mode(self):
        if self.detail_stack.currentWidget() is self.form_editor:
            payload = self.form_editor.to_payload()
            self.editor.setReadOnly(False)
            self.editor.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
            self.detail_stack.setCurrentWidget(self.editor)
        else:
            try:
                payload = json.loads(self.editor.toPlainText())
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    self.lang_manager.get_text("无效 JSON", "Invalid JSON"),
                    str(exc),
                )
                return
            self.form_editor.set_topics(self._current_course_topics())
            self.form_editor.load_payload(payload)
            self.detail_stack.setCurrentWidget(self.form_editor)
        self._update_editor_mode_button()

    def _update_editor_mode_button(self):
        if not hasattr(self, "editor_mode_btn"):
            return
        form_active = self.detail_stack.currentWidget() is self.form_editor
        self.editor_mode_btn.setText(self.lang_manager.get_text(
            "高级 JSON" if form_active else "返回表单",
            "Advanced JSON" if form_active else "Back to Form",
        ))

    def _current_course_topics(self):
        if not self._current_course_id:
            return []
        project = self.course_manager.get(self._current_course_id)
        return project.topics if project else []

    def _delete_question(self):
        selected_ids = self._selected_question_ids()
        if not selected_ids and self.current_question_id:
            selected_ids = [self.current_question_id]
        if not selected_ids:
            return
        count = len(selected_ids)
        message = self.lang_manager.get_text(
            f"确定要删除选中的 {count} 道题目吗？此操作会同时从题目集中移除引用。",
            f"Delete the selected {count} questions? References will also be removed from question sets.",
        ) if count > 1 else self.lang_manager.get_text(
            "确定要删除这道题目吗？此操作会同时从题目集中移除引用。",
            "Delete this question? References will also be removed from question sets.",
        )
        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("删除题目", "Delete Question"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for deleted_question_id in selected_ids:
            self.question_bank.delete(deleted_question_id)
            if self.set_manager is not None:
                remove_question_from_sets(self.set_manager, deleted_question_id, delete_empty=True)
        self.current_question_id = ""
        self._set_source_refs_summary(None)
        self.editor.setReadOnly(False)
        self.editor.clear()
        self.save_btn.setEnabled(True)
        self.question_bank_changed.emit()
        self.refresh()

    def _backfill_source_refs(self):
        course = self._active_course_project()
        if course is None:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("缺少课程", "No Course"),
                self.lang_manager.get_text(
                    "请先选择或导入课程，再关联课程原文。",
                    "Select or import a course before linking to course materials.",
                ),
            )
            return
        changed = backfill_source_refs_from_course(self.question_bank, course)
        if changed:
            self.question_bank_changed.emit()
            self.refresh()
        QMessageBox.information(
            self,
            self.lang_manager.get_text("来源证据补全", "Source Evidence Backfill"),
            self.lang_manager.get_text(
                f"已补全 {changed} 道题目的来源证据。",
                f"Backfilled source evidence for {changed} questions.",
            ) if changed else self.lang_manager.get_text(
                "没有需要补全的来源证据。",
                "No source evidence needed backfilling.",
            ),
        )

    def _active_course_project(self):
        if self._current_course_id:
            return self.course_manager.get(self._current_course_id)
        return self.course_manager.current()

    def _selected_question_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for item in self.question_list.selectedItems():
            qid = item.data(Qt.ItemDataRole.UserRole)
            if qid and qid not in seen:
                ids.append(qid)
                seen.add(qid)
        return ids

    def _refresh_set_filter(self) -> None:
        if self.set_manager is None or not hasattr(self, "set_filter") or self._refreshing_set_filter:
            return
        self._refreshing_set_filter = True
        try:
            current_data = self.set_filter.currentData()
            self.set_filter.blockSignals(True)
            self.set_filter.clear()
            self.set_filter.addItem(self.lang_manager.get_text("全部题集", "All sets"), None)
            lang = self.lang_manager.current
            for qset in self.set_manager.load_all():
                if not self._matches_current_course(qset):
                    continue
                label = (
                    f"{qset.get_title(lang)}"
                    f" ({qset.question_count} {self.lang_manager.get_text('题', 'questions')})"
                )
                self.set_filter.addItem(label, qset.set_id)
            idx = self.set_filter.findData(current_data)
            self.set_filter.setCurrentIndex(idx if idx >= 0 else 0)
            self.set_filter.blockSignals(False)
        finally:
            self._refreshing_set_filter = False

    def _selected_set_id(self) -> str:
        if self.set_manager is None or not hasattr(self, "set_filter"):
            return ""
        return self.set_filter.currentData() or ""

    def _questions_for_set(
        self,
        set_id: str,
        query: str = "",
        difficulty: str | None = None,
        quality_filter: str | None = None,
    ) -> list[Question]:
        if self.set_manager is None:
            return []
        qset = self.set_manager.get(set_id)
        if not qset:
            return []
        return [
            question
            for question in self.question_bank.get_many(qset.questions, course_id=self._current_course_id)
            if self._matches_question_filters(
                question,
                query=query,
                difficulty=difficulty,
                quality_filter=quality_filter,
            )
        ]

    def _matches_current_course(self, qset) -> bool:
        source_course_id = (qset.metadata or {}).get("course_id", "")
        if not source_course_id:
            return True
        if not self._current_course_id:
            return True
        return source_course_id == self._current_course_id

    def _matches_question_filters(
        self,
        question: Question,
        query: str = "",
        difficulty: str | None = None,
        quality_filter: str | None = None,
    ) -> bool:
        difficulty_filter = difficulty.value if isinstance(difficulty, Difficulty) else difficulty
        if difficulty_filter and question.difficulty.value != difficulty_filter:
            return False
        if not self._matches_quality_filter(question, quality_filter):
            return False
        query = (query or "").strip().lower()
        if not query:
            return True
        haystack = " ".join([
            question.get_stem("zh"),
            question.get_stem("en"),
            question.get_explanation("zh"),
            question.get_explanation("en"),
            question.subtopic,
            topic_value(question.topic),
            question.topic_title(),
        ]).lower()
        return query in haystack

    def _populate_quality_filter(self) -> None:
        if not hasattr(self, "quality_filter"):
            return
        current_data = self.quality_filter.currentData()
        self.quality_filter.blockSignals(True)
        self.quality_filter.clear()
        self.quality_filter.addItem(
            self.lang_manager.get_text("全部来源/质量", "All source/quality"),
            None,
        )
        self.quality_filter.addItem(
            self.lang_manager.get_text("有质量警告", "Has quality warnings"),
            "quality_warnings",
        )
        self.quality_filter.addItem(
            self.lang_manager.get_text("无来源证据", "No source evidence"),
            "missing_source",
        )
        self.quality_filter.addItem(
            self.lang_manager.get_text("来源为兜底", "Fallback source"),
            "fallback_source",
        )
        self.quality_filter.addItem(
            self.lang_manager.get_text("仅形状匹配计划", "Weak plan match"),
            "weak_plan",
        )
        idx = self.quality_filter.findData(current_data)
        self.quality_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.quality_filter.blockSignals(False)

    def _quality_filter_predicate(self, filter_key: str | None):
        if not filter_key:
            return None
        return lambda question: self._matches_quality_filter(question, filter_key)

    @classmethod
    def _matches_quality_filter(cls, question: Question, filter_key: str | None) -> bool:
        if not filter_key:
            return True
        if filter_key == "quality_warnings":
            return cls._has_quality_warning(question)
        if filter_key == "missing_source":
            return cls._has_missing_source(question)
        if filter_key == "fallback_source":
            return cls._source_ref_status(question) in {
                "fallback_plan_evidence",
                "fallback_global_evidence",
                "global_fallback",
            }
        if filter_key == "weak_plan":
            return cls._plan_match_status(question) == "matched_by_shape"
        return True

    @classmethod
    def _has_quality_warning(cls, question: Question) -> bool:
        metadata = question.metadata or {}
        for key in ("quality_warnings", "quality_issues", "validation_issues", "warnings"):
            value = metadata.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, str) and value.strip():
                return True
        if metadata.get("invalid_source_ref_ids"):
            return True
        return bool(validate_question_quality(question))

    @classmethod
    def _has_missing_source(cls, question: Question) -> bool:
        metadata = question.metadata or {}
        status = cls._source_ref_status(question)
        source_refs = metadata.get("source_refs")
        if status in {"missing", "invalid_model_ref"}:
            return True
        if isinstance(source_refs, list):
            return not any(isinstance(ref, dict) and ref for ref in source_refs)
        return True

    @staticmethod
    def _source_ref_status(question: Question) -> str:
        return str((question.metadata or {}).get("source_ref_status", "") or "").strip().lower()

    @staticmethod
    def _plan_match_status(question: Question) -> str:
        return str((question.metadata or {}).get("plan_match_status", "") or "").strip().lower()

    def _question_list_title(self, question: Question) -> str:
        difficulty = self._compact_text(question.difficulty.value, 12)
        topic = self._compact_text(question.topic_title(), 24)
        stem = self._compact_text(self._stem_preview(question), 56)
        return self._compact_text(f"{difficulty} · {topic} · {stem}", self._list_title_limit)

    def _question_list_tooltip(self, question: Question) -> str:
        stem = question.get_stem("zh") or question.get_stem("en") or ""
        topic = question.topic_title()
        return f"{question.difficulty.value} · {topic}\n{stem}"

    def _set_source_refs_summary(self, question: Question | None) -> None:
        if question is None:
            self.source_refs_panel.set_source_refs([])
            return
        metadata = question.metadata or {}
        self.source_refs_panel.set_source_refs(
            metadata.get("source_refs", []),
            course_project=self._active_course_project(),
            label=self.lang_manager.get_text("来源", "Source Evidence"),
            status=metadata.get("source_ref_status"),
            language=self.lang_manager.current,
        )

    def _stem_preview(self, question: Question) -> str:
        stem = question.get_stem("zh") or question.get_stem("en") or ""
        lines: list[str] = []
        for raw_line in str(stem).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if self._looks_like_secondary_content(line):
                if lines:
                    break
                continue
            lines.append(line)
        preview = " ".join(lines) if lines else str(stem)
        return self._normalize_inline_text(preview)

    @staticmethod
    def _looks_like_secondary_content(line: str) -> bool:
        return bool(
            re.match(r"^([A-Ha-h][\.\)、)]|[①②③④⑤⑥⑦⑧])\s+", line)
            or re.match(r"^(解析|答案|正确答案|解释|选项|options?|answer|explanation)\s*[:：]", line, re.IGNORECASE)
        )

    @classmethod
    def _compact_text(cls, text: object, limit: int) -> str:
        normalized = cls._normalize_inline_text(str(text or ""))
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 1)].rstrip() + "…"

    @staticmethod
    def _normalize_inline_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
