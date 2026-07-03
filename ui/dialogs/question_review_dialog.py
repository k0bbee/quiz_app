"""Question review dialog — preview, edit, accept, or reject generated questions."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QSplitter,
    QMessageBox, QWidget, QFormLayout, QLineEdit, QComboBox
)
from PyQt6.QtCore import Qt

from models.question import Question
from core.language_manager import LanguageManager
from ui.widgets.source_refs import format_source_refs
from utils.constants import Difficulty


class QuestionReviewDialog(QDialog):
    """Review and approve/reject AI-generated questions before saving."""

    def __init__(self, questions: list[Question], parent=None, page_size: int = 50):
        super().__init__(parent)
        self.questions = list(questions)
        self.page_size = max(1, int(page_size or 50))
        self._current_page = 0
        self._current_index: int = -1
        self.lang_manager = LanguageManager.instance()
        self._accepted: set[int] = self._initial_accepted_indexes()

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
        self.accept_all_btn = QPushButton(self.lang_manager.get_text("全部接受", "Accept All"))
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

        self.detail_editor = QTextEdit()
        self.detail_editor.setReadOnly(True)
        self.detail_editor.setObjectName("dialogDetailEditor")
        right_layout.addWidget(self.detail_editor, 1)

        self.edit_label = QLabel(self.lang_manager.get_text("编辑当前题目:", "Edit Current Question:"))
        self.edit_label.setObjectName("dialogEditLabel")
        right_layout.addWidget(self.edit_label)

        edit_form = QFormLayout()
        self.zh_stem_editor = QTextEdit()
        self.zh_stem_editor.setObjectName("reviewZhStemEditor")
        self.zh_stem_editor.setMaximumHeight(52)
        edit_form.addRow(self.lang_manager.get_text("中文题干", "ZH Stem"), self.zh_stem_editor)

        self.en_stem_editor = QTextEdit()
        self.en_stem_editor.setObjectName("reviewEnStemEditor")
        self.en_stem_editor.setMaximumHeight(52)
        edit_form.addRow(self.lang_manager.get_text("英文题干", "EN Stem"), self.en_stem_editor)

        self.zh_options_editor = QTextEdit()
        self.zh_options_editor.setObjectName("reviewZhOptionsEditor")
        self.zh_options_editor.setMaximumHeight(70)
        edit_form.addRow(self.lang_manager.get_text("中文选项", "ZH Options"), self.zh_options_editor)

        self.en_options_editor = QTextEdit()
        self.en_options_editor.setObjectName("reviewEnOptionsEditor")
        self.en_options_editor.setMaximumHeight(70)
        edit_form.addRow(self.lang_manager.get_text("英文选项", "EN Options"), self.en_options_editor)

        self.topic_editor = QLineEdit()
        self.topic_editor.setObjectName("reviewTopicEditor")
        edit_form.addRow(self.lang_manager.get_text("主题", "Topic"), self.topic_editor)

        self.difficulty_editor = QComboBox()
        self.difficulty_editor.setObjectName("reviewDifficultyEditor")
        for difficulty in Difficulty:
            self.difficulty_editor.addItem(difficulty.value, difficulty.value)
        edit_form.addRow(self.lang_manager.get_text("难度", "Difficulty"), self.difficulty_editor)

        self.correct_answer_editor = QLineEdit()
        self.correct_answer_editor.setObjectName("reviewCorrectAnswerEditor")
        edit_form.addRow(self.lang_manager.get_text("正确答案", "Correct Answer"), self.correct_answer_editor)

        self.zh_explanation_editor = QTextEdit()
        self.zh_explanation_editor.setObjectName("reviewZhExplanationEditor")
        self.zh_explanation_editor.setMaximumHeight(70)
        edit_form.addRow(self.lang_manager.get_text("中文解析", "ZH Explanation"), self.zh_explanation_editor)

        self.en_explanation_editor = QTextEdit()
        self.en_explanation_editor.setObjectName("reviewEnExplanationEditor")
        self.en_explanation_editor.setMaximumHeight(70)
        edit_form.addRow(self.lang_manager.get_text("英文解析", "EN Explanation"), self.en_explanation_editor)
        right_layout.addLayout(edit_form)

        self.apply_edit_btn = QPushButton(self.lang_manager.get_text("应用修改", "Apply Edits"))
        self.apply_edit_btn.setObjectName("secondaryButton")
        self.apply_edit_btn.clicked.connect(self._apply_current_edits)
        right_layout.addWidget(self.apply_edit_btn)

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
        self.prev_page_btn.setText(self.lang_manager.get_text("上一页", "Previous"))
        self.next_page_btn.setText(self.lang_manager.get_text("下一页", "Next"))
        self.accept_all_btn.setText(self.lang_manager.get_text("全部接受", "Accept All"))
        self.reject_all_btn.setText(self.lang_manager.get_text("全部拒绝", "Reject All"))
        self.preview_label.setText(self.lang_manager.get_text("选择题目以预览", "Select a question to preview"))
        self.accept_btn.setText(self.lang_manager.get_text("接受", "Accept"))
        self.reject_btn.setText(self.lang_manager.get_text("拒绝", "Reject"))
        self.edit_label.setText(self.lang_manager.get_text("编辑当前题目:", "Edit Current Question:"))
        self.apply_edit_btn.setText(self.lang_manager.get_text("应用修改", "Apply Edits"))
        self.cancel_btn.setText(self.lang_manager.get_text("取消", "Cancel"))
        self.save_btn.setText(self.lang_manager.get_text("保存已接受的题目", "Save Accepted Questions"))

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

        self._current_index = index
        q = self.questions[index]
        is_accepted = index in self._accepted

        if is_accepted:
            status = self.lang_manager.get_text("已接受", "ACCEPTED")
        else:
            status = self.lang_manager.get_text("已拒绝", "REJECTED")
        self.preview_label.setText(f"Q{index + 1} — [{status}]")

        # Build detail text
        lang = self.lang_manager.current
        details = f"Type: {q.type.value}\n"
        details += f"Difficulty: {q.difficulty.value}\n"
        details += f"Topic: {q.topic_title()}\n"
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
        metadata = q.metadata or {}
        source_text = format_source_refs(
            metadata.get("source_refs", []),
            status=metadata.get("source_ref_status"),
        )
        if source_text:
            details += f"\n--- Source Evidence ---\n{source_text}"
        warnings = self._review_warnings(q)
        if warnings:
            details += "\n--- Review Warnings ---\n" + "\n".join(warnings)

        self.detail_editor.setPlainText(details)
        self._populate_edit_fields(q)

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
        self._render_current_page(preserve_selection=True)

    def _reject_all(self):
        """Reject all questions."""
        self._accepted.clear()
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
        warning_prefix = "⚠ " if self._review_warnings(q) else ""
        prefix = "✓ " if index in self._accepted else "✗ "
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
            self._current_page += 1
            self._render_current_page()

    def _previous_page(self):
        """Move to the previous review page."""
        if self._current_page > 0:
            self._current_page -= 1
            self._render_current_page()

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

    def _populate_edit_fields(self, question: Question):
        """Load the selected question into editable fields."""
        self.zh_stem_editor.setPlainText(question.get_stem("zh"))
        self.en_stem_editor.setPlainText(question.get_stem("en"))
        self.zh_options_editor.setPlainText("\n".join(question.get_options("zh")))
        self.en_options_editor.setPlainText("\n".join(question.get_options("en")))
        self.topic_editor.setText(question.topic_title())
        difficulty_index = self.difficulty_editor.findData(question.difficulty.value)
        if difficulty_index >= 0:
            self.difficulty_editor.setCurrentIndex(difficulty_index)
        self.correct_answer_editor.setText(str(question.correct_answer))
        self.zh_explanation_editor.setPlainText(question.get_explanation("zh"))
        self.en_explanation_editor.setPlainText(question.get_explanation("en"))

    def _apply_current_edits(self):
        """Apply editable field values to the current question model."""
        if self._current_index < 0 or self._current_index >= len(self.questions):
            return
        question = self.questions[self._current_index]
        question.bilingual.setdefault("zh", {})
        question.bilingual.setdefault("en", {})
        question.bilingual["zh"]["stem"] = self.zh_stem_editor.toPlainText().strip()
        question.bilingual["en"]["stem"] = self.en_stem_editor.toPlainText().strip()
        question.bilingual["zh"]["options"] = self._edited_options(self.zh_options_editor)
        question.bilingual["en"]["options"] = self._edited_options(self.en_options_editor)
        question.bilingual["zh"]["explanation"] = self.zh_explanation_editor.toPlainText().strip()
        question.bilingual["en"]["explanation"] = self.en_explanation_editor.toPlainText().strip()
        topic = self.topic_editor.text().strip()
        if topic:
            question.topic = topic
            if question.metadata.get("topic_title") and question.metadata.get("topic_title") != topic:
                question.metadata["topic_title"] = topic
        difficulty = self.difficulty_editor.currentData()
        if difficulty in {item.value for item in Difficulty}:
            question.difficulty = Difficulty(difficulty)
        question.correct_answer = self.correct_answer_editor.text().strip()
        self._accepted.add(self._current_index)
        self._update_list_item(self._current_index)
        self._on_selection_changed(self.question_list.currentRow())

    @staticmethod
    def _edited_options(editor: QTextEdit) -> list[str]:
        """Return non-empty edited options, one option per line."""
        return [line.strip() for line in editor.toPlainText().splitlines() if line.strip()]

    def _initial_accepted_indexes(self) -> set[int]:
        """Accept only questions that do not need manual confidence review."""
        return {
            index
            for index, question in enumerate(self.questions)
            if not self._review_warnings(question)
        }

    def _review_warnings(self, question: Question) -> list[str]:
        """Return review warnings that should require explicit user acceptance."""
        metadata = question.metadata or {}
        warnings: list[str] = []
        source_status = str(metadata.get("source_ref_status", "") or "").strip().lower()
        if source_status in {"invalid_model_ref", "missing"}:
            warnings.append(self.lang_manager.get_text("来源无效或缺失", "Source invalid or missing"))
        elif source_status in {"fallback_global_evidence", "global_fallback"}:
            warnings.append(self.lang_manager.get_text("来源来自全局兜底", "Source uses global fallback"))

        plan_status = str(metadata.get("plan_match_status", "") or "").strip().lower()
        if plan_status == "matched_by_shape":
            warnings.append(self.lang_manager.get_text("仅按形状匹配生成计划", "Plan matched by shape only"))

        zh_explanation = question.get_explanation("zh").strip()
        en_explanation = question.get_explanation("en").strip()
        if not zh_explanation and not en_explanation:
            warnings.append(self.lang_manager.get_text("缺少解析", "Missing explanation"))
        elif self._has_imbalanced_explanations(zh_explanation, en_explanation):
            warnings.append(self.lang_manager.get_text("中英文解析长度差异过大", "Bilingual explanation lengths differ greatly"))
        if self._has_overlong_correct_option(question):
            warnings.append(self.lang_manager.get_text("正确选项明显长于干扰项", "Correct option is much longer than distractors"))
        return warnings

    @staticmethod
    def _has_imbalanced_explanations(zh_explanation: str, en_explanation: str) -> bool:
        """Return whether bilingual explanations are suspiciously imbalanced."""
        zh_len = len(zh_explanation.strip())
        en_len = len(en_explanation.strip())
        if min(zh_len, en_len) == 0:
            return False
        return max(zh_len, en_len) >= max(60, min(zh_len, en_len) * 4)

    @staticmethod
    def _has_overlong_correct_option(question: Question) -> bool:
        """Return whether the correct option is much longer than all distractors."""
        answer = str(question.correct_answer).strip().upper()
        if len(answer) != 1 or not answer.isalpha():
            return False
        index = ord(answer) - ord("A")
        for lang in ("zh", "en"):
            options = question.get_options(lang)
            if not options or index < 0 or index >= len(options):
                continue
            lengths = [len(str(option).strip()) for option in options]
            correct_length = lengths[index]
            distractor_lengths = [length for idx, length in enumerate(lengths) if idx != index]
            if distractor_lengths and correct_length >= max(28, max(distractor_lengths) * 2):
                return True
        return False


def _format_source_refs(source_refs, status: str | None = None) -> str:
    """Format stored source references for review without exposing raw JSON."""
    return format_source_refs(source_refs, status=status)
