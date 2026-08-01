"""Question review dialog — preview, edit, accept, or reject generated questions."""

import json
from collections.abc import Mapping

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QSplitter,
    QMessageBox, QWidget, QTabWidget,
)
from PyQt6.QtCore import Qt

from models.question import Question
from core.language_manager import LanguageManager
from core.question_validation import validate_question_quality
from ui.widgets.source_refs import format_source_refs
from ui.widgets.source_refs_panel import SourceRefsPanel
from ui.widgets.question_form_editor import QuestionFormEditor
from utils.constants import Difficulty, QuestionType


_TYPE_LABELS = {
    QuestionType.MULTIPLE_CHOICE: ("单选题", "Single Choice"),
    QuestionType.TRUE_FALSE: ("判断题", "True / False"),
    QuestionType.MATCHING: ("配对题", "Matching"),
    QuestionType.ORDERING: ("排序题", "Ordering"),
    QuestionType.SCENARIO_CHOICE: ("情景选择题", "Scenario Choice"),
    QuestionType.FILL_IN_BLANK: ("填空题", "Fill in the Blank"),
    QuestionType.SHORT_ANSWER: ("简答题", "Short Answer"),
}

_DIFFICULTY_LABELS = {
    Difficulty.EASY: ("简单", "Easy"),
    Difficulty.MEDIUM: ("中等", "Medium"),
    Difficulty.HARD: ("困难", "Hard"),
}


class QuestionReviewDialog(QDialog):
    """Review and approve/reject AI-generated questions before saving."""

    def __init__(
        self,
        questions: list[Question],
        parent=None,
        page_size: int = 50,
        course_project=None,
        allow_empty_accept: bool = False,
        review_state: Mapping[str, str] | None = None,
    ):
        super().__init__(parent)
        self.questions = list(questions)
        self.page_size = max(1, int(page_size or 50))
        self._current_page = 0
        self._current_index: int = -1
        self.lang_manager = LanguageManager.instance()
        self._accepted: set[int] = self._initial_accepted_indexes()
        self._rejected: set[int] = set()
        self._restore_review_state(review_state)
        self._loading_edit_fields = False
        self.course_project = course_project
        self.allow_empty_accept = bool(allow_empty_accept)

        self.setWindowTitle(self.lang_manager.get_text("审查生成的题目", "Review Generated Questions"))
        self.resize(900, 600)
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

        if self.questions:
            self._render_current_page()

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
        self.question_list.currentRowChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.question_list)

        page_layout = QHBoxLayout()
        self.prev_page_btn = QPushButton(self.lang_manager.get_text("上一页", "Previous"))
        self.prev_page_btn.setObjectName("secondaryButton")
        self.prev_page_btn.clicked.connect(self._previous_page)
        page_layout.addWidget(self.prev_page_btn)

        self.page_label = QLabel()
        self.page_label.setObjectName("dialogPageLabel")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_layout.addWidget(self.page_label, 1)

        self.next_page_btn = QPushButton(self.lang_manager.get_text("下一页", "Next"))
        self.next_page_btn.setObjectName("secondaryButton")
        self.next_page_btn.clicked.connect(self._next_page)
        page_layout.addWidget(self.next_page_btn)
        left_layout.addLayout(page_layout)

        # Accept all / reject all buttons
        bulk_layout = QHBoxLayout()
        self.accept_all_btn = QPushButton(self.lang_manager.get_text("接受无警告题", "Accept No-Warning"))
        self.accept_all_btn.setObjectName("secondaryButton")
        self.accept_all_btn.clicked.connect(self._accept_all)
        self.reject_all_btn = QPushButton(self.lang_manager.get_text("全部拒绝", "Reject All"))
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

        self.review_tabs = QTabWidget()
        self.review_tabs.setObjectName("reviewTabs")

        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        preview_layout.setContentsMargins(0, 8, 0, 0)
        self.detail_editor = QTextEdit()
        self.detail_editor.setReadOnly(True)
        self.detail_editor.setObjectName("dialogDetailEditor")
        preview_layout.addWidget(self.detail_editor)
        self.review_tabs.addTab(preview_page, self.lang_manager.get_text("预览", "Preview"))

        edit_page = QWidget()
        edit_layout = QVBoxLayout(edit_page)
        edit_layout.setContentsMargins(0, 8, 8, 0)
        self.edit_label = QLabel(self.lang_manager.get_text("编辑当前题目:", "Edit Current Question:"))
        self.edit_label.setObjectName("dialogEditLabel")
        edit_layout.addWidget(self.edit_label)
        self.form_editor = QuestionFormEditor(edit_page)
        if self.course_project is not None:
            self.form_editor.set_topics(getattr(self.course_project, "topics", []) or [])
        edit_layout.addWidget(self.form_editor, 1)

        self.apply_edit_btn = QPushButton(self.lang_manager.get_text("应用修改", "Apply Edits"))
        self.apply_edit_btn.setObjectName("secondaryButton")
        self.apply_edit_btn.clicked.connect(self._apply_current_edits)
        edit_layout.addWidget(self.apply_edit_btn)
        self.review_tabs.addTab(edit_page, self.lang_manager.get_text("编辑", "Edit"))

        source_page = QWidget()
        source_layout = QVBoxLayout(source_page)
        source_layout.setContentsMargins(0, 8, 0, 0)
        self.source_editor = QTextEdit()
        self.source_editor.setObjectName("reviewSourceEditor")
        self.source_editor.setReadOnly(True)
        source_layout.addWidget(self.source_editor)
        self.source_refs_panel = SourceRefsPanel()
        self.source_refs_panel.setVisible(False)
        source_layout.addWidget(self.source_refs_panel)
        self.review_tabs.addTab(source_page, self.lang_manager.get_text("来源", "Sources"))

        quality_page = QWidget()
        quality_layout = QVBoxLayout(quality_page)
        quality_layout.setContentsMargins(0, 8, 0, 0)
        self.quality_editor = QTextEdit()
        self.quality_editor.setObjectName("reviewQualityEditor")
        self.quality_editor.setReadOnly(True)
        quality_layout.addWidget(self.quality_editor)
        self.review_tabs.addTab(quality_page, self.lang_manager.get_text("质量问题", "Quality"))
        self.review_tabs.setCurrentIndex(0)
        right_layout.addWidget(self.review_tabs, 1)

        # Accept/reject for current question
        action_layout = QHBoxLayout()
        self.accept_btn = QPushButton(self.lang_manager.get_text("接受", "Accept"))
        self.accept_btn.setObjectName("secondaryButton")
        self.accept_btn.clicked.connect(self._accept_current)
        action_layout.addWidget(self.accept_btn)

        self.reject_btn = QPushButton(self.lang_manager.get_text("拒绝", "Reject"))
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

        self.save_btn = QPushButton(self._save_button_text())
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setMinimumHeight(36)
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _on_language_changed(self, lang):
        """Update all UI strings when language changes."""
        self._apply_current_edits(refresh=False)
        self.setWindowTitle(self.lang_manager.get_text("审查生成的题目", "Review Generated Questions"))
        self.header.setText(
            self.lang_manager.get_text(
                f"已生成 {len(self.questions)} 道题目，请审查并接受或拒绝。",
                f"Generated {len(self.questions)} questions. Review and accept/reject each one."
            )
        )
        self.questions_label.setText(self.lang_manager.get_text("题目列表:", "Questions:"))
        self.prev_page_btn.setText(self.lang_manager.get_text("上一页", "Previous"))
        self.next_page_btn.setText(self.lang_manager.get_text("下一页", "Next"))
        self.accept_all_btn.setText(self.lang_manager.get_text("接受无警告题", "Accept No-Warning"))
        self.reject_all_btn.setText(self.lang_manager.get_text("全部拒绝", "Reject All"))
        self.preview_label.setText(self.lang_manager.get_text("选择题目以预览", "Select a question to preview"))
        self.accept_btn.setText(self.lang_manager.get_text("接受", "Accept"))
        self.reject_btn.setText(self.lang_manager.get_text("拒绝", "Reject"))
        self.edit_label.setText(self.lang_manager.get_text("编辑当前题目:", "Edit Current Question:"))
        self.apply_edit_btn.setText(self.lang_manager.get_text("应用修改", "Apply Edits"))
        self.review_tabs.setTabText(0, self.lang_manager.get_text("预览", "Preview"))
        self.review_tabs.setTabText(1, self.lang_manager.get_text("编辑", "Edit"))
        self.review_tabs.setTabText(2, self.lang_manager.get_text("来源", "Sources"))
        self.review_tabs.setTabText(3, self.lang_manager.get_text("质量问题", "Quality"))
        self.cancel_btn.setText(self.lang_manager.get_text("取消", "Cancel"))
        self.save_btn.setText(self._save_button_text())

        # Update visible list item stems (may change with language)
        self._render_current_page(preserve_selection=True)

    def _on_selection_changed(self, row: int):
        """Display question details in the preview panel."""
        item = self.question_list.item(row)
        if item is None:
            return

        index = int(item.data(Qt.ItemDataRole.UserRole))
        if index < 0 or index >= len(self.questions):
            return
        if index != self._current_index:
            self._apply_current_edits(refresh=False)

        self._current_index = index
        q = self.questions[index]
        status_key = self._state_for_index(index)
        if status_key == "accepted":
            status = self.lang_manager.get_text("已接受", "ACCEPTED")
        elif status_key == "rejected":
            status = self.lang_manager.get_text("已拒绝", "REJECTED")
        else:
            status = self.lang_manager.get_text("待审核", "PENDING")
        self.preview_label.setText(f"Q{index + 1} — [{status}]")

        # Build detail text
        details = f"{self.lang_manager.get_text('题型', 'Type')}: {self.lang_manager.get_text(*_TYPE_LABELS[q.type])}\n"
        details += f"{self.lang_manager.get_text('难度', 'Difficulty')}: {self.lang_manager.get_text(*_DIFFICULTY_LABELS[q.difficulty])}\n"
        details += f"{self.lang_manager.get_text('知识点', 'Topic')}: {q.topic_title()}\n"
        details += f"{self.lang_manager.get_text('子主题', 'Subtopic')}: {q.subtopic}\n"
        details += f"{self.lang_manager.get_text('正确答案', 'Correct Answer')}: {q.correct_answer}\n"
        details += f"\n--- {self.lang_manager.get_text('中文题干', 'Chinese Stem')} ---\n{q.get_stem('zh')}\n"
        if q.get_options('zh'):
            details += f"\n{self.lang_manager.get_text('选项', 'Options')}:\n" + self._format_options_for_preview(q.get_options('zh'))
        details += f"\n--- {self.lang_manager.get_text('英文题干', 'English Stem')} ---\n{q.get_stem('en')}\n"
        if q.get_options('en'):
            details += f"\n{self.lang_manager.get_text('选项', 'Options')}:\n" + self._format_options_for_preview(q.get_options('en'))
        details += f"\n--- {self.lang_manager.get_text('中文解析', 'Chinese Explanation')} ---\n{q.get_explanation('zh')}"
        details += f"\n--- {self.lang_manager.get_text('英文解析', 'English Explanation')} ---\n{q.get_explanation('en')}"
        metadata = q.metadata or {}
        source_text = format_source_refs(
            metadata.get("source_refs", []),
            label=self.lang_manager.get_text("来源", "Source Evidence"),
            status=metadata.get("source_ref_status"),
            language=self.lang_manager.current,
        )
        warnings = self._review_warnings(q)

        self.detail_editor.setPlainText(details)
        self.source_editor.setPlainText(
            source_text
            or self.lang_manager.get_text(
                "暂无来源证据。",
                "No source evidence is available.",
            )
        )
        self.source_refs_panel.set_source_refs(
            metadata.get("source_refs", []),
            course_project=self.course_project,
            language=self.lang_manager.current,
            label=self.lang_manager.get_text("来源", "Source Evidence"),
            status=metadata.get("source_ref_status"),
        )
        self.source_editor.setVisible(not bool(metadata.get("source_refs")))
        self.quality_editor.setPlainText(
            "\n".join(f"• {warning}" for warning in warnings)
            if warnings
            else self.lang_manager.get_text(
                "未发现需要人工确认的质量问题。",
                "No quality issues require manual review.",
            )
        )
        self._populate_edit_fields(q)

    def _accept_current(self):
        """Accept the currently viewed question."""
        if self._current_index >= 0:
            self._accepted.add(self._current_index)
            self._rejected.discard(self._current_index)
            self._update_list_item(self._current_index)

    def _reject_current(self):
        """Reject the currently viewed question."""
        if self._current_index >= 0:
            self._accepted.discard(self._current_index)
            self._rejected.add(self._current_index)
            self._update_list_item(self._current_index)

    def _accept_all(self):
        """Accept all questions that do not require manual quality review."""
        for i in range(len(self.questions)):
            if not self._review_warnings(self.questions[i]):
                self._accepted.add(i)
                self._rejected.discard(i)
        self._render_current_page(preserve_selection=True)

    def _reject_all(self):
        """Reject all questions."""
        self._accepted.clear()
        self._rejected = set(range(len(self.questions)))
        self._render_current_page(preserve_selection=True)

    def _update_list_item(self, index: int):
        """Update the visual indicator on a list item."""
        item = self._visible_item_for_index(index)
        if item is None:
            return
        q = self.questions[index]
        lang = self.lang_manager.current
        stem = q.get_stem(lang)
        short = stem[:80] + "..." if len(stem) > 80 else stem
        warning_tags = self._review_warning_tags(q)
        warning_prefix = f"⚠ {' '.join(warning_tags)} " if warning_tags else ""
        prefix = {
            "accepted": "✓ ",
            "rejected": "✗ ",
            "pending": "… ",
        }[self._state_for_index(index)]
        item.setText(f"{warning_prefix}{prefix}Q{index + 1}: {short}")

    def _render_current_page(self, preserve_selection: bool = False):
        """Render only the current page to keep large review batches responsive."""
        selected_index = self._current_index if preserve_selection else -1
        self.question_list.blockSignals(True)
        self.question_list.clear()
        start, end = self._page_bounds()
        for index in range(start, end):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.question_list.addItem(item)
            self._update_list_item(index)
        self.question_list.blockSignals(False)
        self._update_pagination_controls()

        if self.question_list.count() == 0:
            self._current_index = -1
            return

        row_to_select = 0
        if start <= selected_index < end:
            row_to_select = selected_index - start
        self.question_list.setCurrentRow(row_to_select)

    def _page_bounds(self) -> tuple[int, int]:
        """Return start/end indexes for the current page."""
        start = self._current_page * self.page_size
        end = min(start + self.page_size, len(self.questions))
        return start, end

    def _page_count(self) -> int:
        """Return the number of pages needed for the review list."""
        if not self.questions:
            return 1
        return (len(self.questions) + self.page_size - 1) // self.page_size

    def _visible_item_for_index(self, index: int):
        """Return the visible QListWidgetItem for a global question index."""
        start, end = self._page_bounds()
        if index < start or index >= end:
            return None
        return self.question_list.item(index - start)

    def _update_pagination_controls(self):
        """Keep pagination controls in sync with the current page."""
        page_count = self._page_count()
        self._current_page = min(self._current_page, page_count - 1)
        self.page_label.setText(f"{self._current_page + 1} / {page_count}")
        self.prev_page_btn.setEnabled(self._current_page > 0)
        self.next_page_btn.setEnabled(self._current_page < page_count - 1)

    def _next_page(self):
        """Move to the next review page."""
        if self._current_page < self._page_count() - 1:
            self._apply_current_edits(refresh=False)
            self._current_page += 1
            self._render_current_page()

    def _previous_page(self):
        """Move to the previous review page."""
        if self._current_page > 0:
            self._apply_current_edits(refresh=False)
            self._current_page -= 1
            self._render_current_page()

    def _on_save(self):
        """Validate and save accepted questions."""
        self._apply_current_edits(refresh=False)
        accepted_count = len(self._accepted)
        if accepted_count == 0 and not self.allow_empty_accept:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("没有接受的题目", "No Questions"),
                self.lang_manager.get_text("请至少接受一道题目。", "Please accept at least one question.")
            )
            return

        if accepted_count:
            confirmation = self.lang_manager.get_text(
                f"保存 {accepted_count} 道已接受的题目？\n它们将被添加到题库中。",
                f"Save {accepted_count} accepted question(s)?\nThey will be added to the question bank.",
            )
        else:
            confirmation = self.lang_manager.get_text(
                "拒绝全部警告题并保存其余已自动接受的题目？",
                "Reject all flagged questions and save the remaining auto-accepted questions?",
            )
        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("保存题目?", "Save Questions?"),
            confirmation,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.accept()

    def _save_button_text(self) -> str:
        if self.allow_empty_accept:
            return self.lang_manager.get_text(
                "保存审查结果",
                "Save Review Result",
            )
        return self.lang_manager.get_text(
            "保存已接受的题目",
            "Save Accepted Questions",
        )

    def get_accepted_questions(self) -> list[Question]:
        """Return only the accepted questions."""
        return [self.questions[i] for i in sorted(self._accepted)]

    def get_review_state(self) -> dict[str, str]:
        """Return stable question-id decisions for draft persistence."""
        return {
            question.question_id: self._state_for_index(index)
            for index, question in enumerate(self.questions)
            if question.question_id
        }

    def _populate_edit_fields(self, question: Question):
        """Load the selected question into editable fields."""
        self._loading_edit_fields = True
        self.form_editor.load_payload(question.to_dict())
        self._loading_edit_fields = False

    def _apply_current_edits(self, checked: bool = False, refresh: bool = True):
        """Apply editable field values to the current question model."""
        if self._loading_edit_fields:
            return
        if self._current_index < 0 or self._current_index >= len(self.questions):
            return
        question = self.questions[self._current_index]
        updated = Question.from_dict(self.form_editor.to_payload())
        question.__dict__.update(updated.__dict__)
        self._update_list_item(self._current_index)
        if refresh:
            self._on_selection_changed(self.question_list.currentRow())

    @staticmethod
    def _format_options_for_preview(options: object) -> str:
        """Return readable options text for both flat and structured question types."""
        if isinstance(options, list) and all(isinstance(option, str) for option in options):
            return "\n".join(options)
        return json.dumps(options, ensure_ascii=False, indent=2)

    def _initial_accepted_indexes(self) -> set[int]:
        """Accept only questions that do not need manual confidence review."""
        return {
            index
            for index, question in enumerate(self.questions)
            if not self._review_warnings(question)
        }

    def _restore_review_state(self, review_state: Mapping[str, str] | None) -> None:
        """Apply persisted decisions while keeping unspecified questions reviewable."""
        if not isinstance(review_state, Mapping):
            return
        for index, question in enumerate(self.questions):
            decision = str(review_state.get(question.question_id, "") or "").strip()
            if decision == "accepted":
                self._accepted.add(index)
                self._rejected.discard(index)
            elif decision == "rejected":
                self._accepted.discard(index)
                self._rejected.add(index)
            elif decision == "pending":
                self._accepted.discard(index)
                self._rejected.discard(index)

    def _state_for_index(self, index: int) -> str:
        if index in self._accepted:
            return "accepted"
        if index in self._rejected:
            return "rejected"
        return "pending"

    def _review_warnings(self, question: Question) -> list[str]:
        """Return review warnings that should require explicit user acceptance."""
        language = self.lang_manager.current
        return [issue.message(language) for issue in validate_question_quality(question)]

    def _review_warning_tags(self, question: Question) -> list[str]:
        """Return compact warning labels for the review list."""
        language = self.lang_manager.current
        return [issue.tag(language) for issue in validate_question_quality(question)]


def _format_source_refs(source_refs, status: str | None = None) -> str:
    """Format stored source references for review without exposing raw JSON."""
    return format_source_refs(source_refs, status=status)
