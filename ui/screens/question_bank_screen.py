"""Question bank CRUD screen with search and pagination."""

from __future__ import annotations

import json
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTextEdit, QMessageBox, QSplitter, QAbstractItemView, QStackedWidget,
    QHeaderView, QTableView,
)
from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    QItemSelectionModel,
    QModelIndex,
    QSignalBlocker,
    QTimer,
    QThread,
)

from core.background_task import BackgroundTaskCancelled, TaskControl, TaskProgress
from core.background_task_bridge import BackgroundTaskBridge
from core.language_manager import LanguageManager
from core.library_scope import LibraryAssetScope, LibraryScopeKind
from core.question_bank_maintenance import backfill_source_refs_from_course, remove_question_from_sets
from core.question_quality_scan import scan_question_bank_quality
from core.question_validation import validate_question_quality
from models.course_project import CourseProjectManager
from models.question import Question, QuestionBank
from models.question_set import SetManager
from ui.components import PageHeader
from ui.models.question_table_model import QuestionTableModel, QuestionTableRow
from ui.widgets.source_refs_panel import SourceRefsPanel
from ui.widgets.question_form_editor import QuestionFormEditor
from ui.widgets.wheel_safe_controls import WheelSafeComboBox
from utils.constants import Difficulty, QuestionType, topic_value


class QuestionQualityScanWorker(QThread):
    """Validate a question bank outside the UI thread."""

    progressed = pyqtSignal(object)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        question_bank,
        *,
        course_id: str = "",
        unassigned_only: bool = False,
        task_center=None,
        task_id: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.question_bank = question_bank
        self.course_id = str(course_id or "")
        self.unassigned_only = bool(unassigned_only)
        self.task_id = str(task_id or "")
        self._bridge = (
            BackgroundTaskBridge(task_center, self.task_id)
            if task_center is not None and self.task_id
            else None
        )
        self._control = TaskControl(self._report_progress)

    def cancel(self):
        self._control.cancel()

    def _report_progress(self, progress: TaskProgress):
        self.progressed.emit(progress)
        if self._bridge is not None:
            self._bridge.report(progress)

    def run(self):
        if self._bridge is not None and not self._bridge.start(self.cancel):
            self.cancelled.emit()
            return
        try:
            report = scan_question_bank_quality(
                self.question_bank,
                course_id=self.course_id,
                unassigned_only=self.unassigned_only,
                task=self._control,
            )
            if self._bridge is not None:
                self._bridge.complete(
                    result_summary=(
                        f"{report.issue_question_count}/{report.scanned_count} questions need review"
                    ),
                    result_count=report.scanned_count,
                )
            self.completed.emit(report)
        except BackgroundTaskCancelled:
            if self._bridge is not None:
                self._bridge.cancelled()
            self.cancelled.emit()
        except Exception as exc:
            if self._bridge is not None:
                self._bridge.fail(exc)
            self.failed.emit(str(exc))


class QuestionBankScreen(QWidget):
    """Manage question JSON records."""

    question_bank_changed = pyqtSignal()

    def __init__(
        self,
        question_bank: QuestionBank,
        set_manager: SetManager | None = None,
        *,
        course_manager: CourseProjectManager,
        parent=None,
        task_center=None,
        embedded: bool = False,
    ):
        super().__init__(parent)
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.course_manager = course_manager
        self.task_center = task_center
        self.embedded = bool(embedded)
        self.lang_manager = LanguageManager.instance()
        self.page_size = 25
        self.page = 0
        self.total = 0
        self.current_question_id = ""
        self._current_course_id = ""
        self._asset_scope: LibraryAssetScope | None = None
        self._refreshing_set_filter = False
        self._quality_scan_worker = None
        self._quality_scan_task_id = ""
        self._quality_scan_results = {}
        self.search_debounce_timer = QTimer(self)
        self.search_debounce_timer.setSingleShot(True)
        self.search_debounce_timer.setInterval(250)
        self.search_debounce_timer.timeout.connect(self._reset_and_refresh)
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        if self.embedded:
            layout.setContentsMargins(0, 0, 0, 0)
        else:
            layout.setContentsMargins(24, 20, 24, 20)

        self.page_header = PageHeader(
            self.lang_manager.get_text("题库管理", "Question Bank")
        )
        self.title = self.page_header.title_label
        self.page_header.setVisible(not self.embedded)
        layout.addWidget(self.page_header)

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

        list_actions_row = QHBoxLayout()
        self.new_btn = QPushButton(
            self.lang_manager.get_text("新建题目", "New Question")
        )
        self.new_btn.setObjectName("secondaryButton")
        self.new_btn.clicked.connect(self._new_question)
        list_actions_row.addWidget(self.new_btn)
        list_actions_row.addStretch(1)
        layout.addLayout(list_actions_row)

        quality_scan_row = QHBoxLayout()
        self.quality_scan_status_label = QLabel("")
        self.quality_scan_status_label.setObjectName("secondaryText")
        self.quality_scan_status_label.setWordWrap(True)
        self.quality_scan_status_label.hide()
        quality_scan_row.addWidget(self.quality_scan_status_label, 1)
        self.scan_quality_btn = QPushButton(
            self.lang_manager.get_text("检查全部题目", "Check All Questions")
        )
        self.scan_quality_btn.setObjectName("secondaryButton")
        self.scan_quality_btn.clicked.connect(self._start_quality_scan)
        quality_scan_row.addWidget(self.scan_quality_btn)
        self.cancel_quality_scan_btn = QPushButton(
            self.lang_manager.get_text("停止", "Stop")
        )
        self.cancel_quality_scan_btn.setObjectName("secondaryButton")
        self.cancel_quality_scan_btn.clicked.connect(self._cancel_quality_scan)
        self.cancel_quality_scan_btn.hide()
        quality_scan_row.addWidget(self.cancel_quality_scan_btn)
        layout.addLayout(quality_scan_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter = splitter
        self._responsive_inspector_open = False

        left = QWidget()
        self.question_list_panel = left
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.question_table = QTableView()
        self.question_table.setObjectName("questionBankTable")
        self.question_table_model = QuestionTableModel(
            language=self.lang_manager.current,
            parent=self.question_table,
        )
        self.question_table.setModel(self.question_table_model)
        self.question_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.question_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.question_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.question_table.setAlternatingRowColors(True)
        self.question_table.setShowGrid(False)
        self.question_table.setWordWrap(False)
        self.question_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.question_table.verticalHeader().hide()
        self.question_table.verticalHeader().setDefaultSectionSize(34)
        header = self.question_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        for column in range(2, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.question_table.setColumnWidth(1, 140)
        self.question_table.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self.question_table.activated.connect(
            lambda _index: self._open_responsive_inspector()
        )
        self.question_table.doubleClicked.connect(
            lambda _index: self._open_responsive_inspector()
        )
        self.question_list_stack = QStackedWidget()
        self.question_list_stack.addWidget(self.question_table)
        self.empty_state_panel = QWidget()
        empty_state_layout = QVBoxLayout(self.empty_state_panel)
        empty_state_layout.addStretch(1)
        self.empty_state_label = QLabel(
            self.lang_manager.get_text(
                "题库中还没有题目。",
                "There are no questions in this bank yet.",
            )
        )
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        empty_state_layout.addWidget(self.empty_state_label)
        self.empty_create_btn = QPushButton(
            self.lang_manager.get_text("创建第一道题", "Create First Question")
        )
        self.empty_create_btn.setObjectName("primaryButton")
        self.empty_create_btn.clicked.connect(self._new_question)
        empty_state_layout.addWidget(
            self.empty_create_btn,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        empty_state_layout.addStretch(1)
        self.question_list_stack.addWidget(self.empty_state_panel)
        left_layout.addWidget(self.question_list_stack, 1)

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
        self.inspector_panel = right
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.source_refs_panel = SourceRefsPanel()
        self.source_refs_panel.setObjectName("questionBankSourceRefs")
        self.source_refs_panel.setVisible(False)
        self.source_refs_label = self.source_refs_panel
        right_layout.addWidget(self.source_refs_panel)

        editor_header = QHBoxLayout()
        self.inspector_back_btn = QPushButton(
            self.lang_manager.get_text("返回题目列表", "Back to Questions")
        )
        self.inspector_back_btn.setObjectName("secondaryButton")
        self.inspector_back_btn.clicked.connect(self._close_responsive_inspector)
        self.inspector_back_btn.hide()
        editor_header.addWidget(self.inspector_back_btn)
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
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([520, 640])

        layout.addWidget(splitter, 1)
        self._apply_responsive_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "content_splitter"):
            self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        narrow = self.width() < 1100
        if not narrow:
            self.question_list_panel.show()
            self.inspector_panel.show()
            self.inspector_back_btn.hide()
            self._responsive_inspector_open = False
            self.content_splitter.setSizes([520, 640])
            return
        self.inspector_back_btn.setVisible(self._responsive_inspector_open)
        self.question_list_panel.setVisible(not self._responsive_inspector_open)
        self.inspector_panel.setVisible(self._responsive_inspector_open)

    def _open_responsive_inspector(self) -> None:
        if self.width() >= 1100:
            return
        self._responsive_inspector_open = True
        self._apply_responsive_layout()

    def _close_responsive_inspector(self) -> None:
        self._responsive_inspector_open = False
        self._apply_responsive_layout()

    def _on_language_changed(self, lang):
        """Update all UI text when language changes."""
        self.question_table_model.set_language(lang)
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
        self.inspector_back_btn.setText(
            self.lang_manager.get_text("返回题目列表", "Back to Questions")
        )
        self.new_btn.setText(
            self.lang_manager.get_text("新建题目", "New Question")
        )
        self.empty_state_label.setText(
            self.lang_manager.get_text(
                "题库中还没有题目。",
                "There are no questions in this bank yet.",
            )
        )
        self.empty_create_btn.setText(
            self.lang_manager.get_text("创建第一道题", "Create First Question")
        )
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
        self.scan_quality_btn.setText(
            self.lang_manager.get_text("检查全部题目", "Check All Questions")
        )
        self.cancel_quality_scan_btn.setText(
            self.lang_manager.get_text("停止", "Stop")
        )
        self._update_editor_mode_button()

    def refresh(self):
        """Reload current page."""
        query = self.search_input.text()
        difficulty = self.difficulty_filter.currentData()
        quality_filter = self.quality_filter.currentData()
        metadata_filter = self._metadata_filter_predicate(quality_filter)
        self._refresh_set_filter()
        selected_set_id = self._selected_set_id()
        if (
            self._asset_scope is not None
            and self._asset_scope.kind is LibraryScopeKind.EMPTY
        ):
            items = []
            self.total = 0
        elif selected_set_id:
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
                unassigned_only=False,
                metadata_filter=metadata_filter,
                offset=self.page * self.page_size,
                limit=self.page_size,
            )
        selected_ids = set(self._selected_question_ids())
        if not selected_ids and self.current_question_id:
            selected_ids.add(self.current_question_id)
        selection_model = self.question_table.selectionModel()
        with QSignalBlocker(selection_model):
            self.question_table_model.set_rows(
                [self._question_table_row(question) for question in items]
            )
            self.question_list_stack.setCurrentWidget(
                self.question_table
                if self.question_table_model.rowCount() > 0
                else self.empty_state_panel
            )
            for question_id in selected_ids:
                row = self.question_table_model.row_for_question_id(question_id)
                if row < 0:
                    continue
                selection_model.select(
                    self.question_table_model.index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        if (
            not self._selected_question_ids()
            and self.question_table_model.rowCount() > 0
        ):
            first_index = self.question_table_model.index(0, 0)
            with QSignalBlocker(selection_model):
                selection_model.select(
                    first_index,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                self.question_table.setCurrentIndex(first_index)
            self._on_selection_changed()
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
        course_id = str(course_id or "").strip()
        scope = LibraryAssetScope.course(course_id) if course_id else None
        self.set_asset_scope(scope)

    def set_asset_scope(self, scope: LibraryAssetScope | None) -> None:
        """Apply the parent library's exact asset scope."""
        if scope == self._asset_scope:
            return
        self._asset_scope = scope
        self._current_course_id = (
            scope.course_id
            if scope is not None
            and scope.kind is LibraryScopeKind.COURSE
            else ""
        )
        self._invalidate_quality_scan()
        self.form_editor.set_topics(self._current_course_topics())
        self.page = 0
        self.current_question_id = ""
        if hasattr(self, "question_table"):
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

    def _on_selection_changed(self, *_args):
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
        selection_model = self.question_table.selectionModel()
        with QSignalBlocker(selection_model):
            self.question_table.clearSelection()
            self.question_table.setCurrentIndex(QModelIndex())
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
        if self.width() < 1100:
            self._open_responsive_inspector()

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
        self._invalidate_quality_scan()
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
        self._invalidate_quality_scan()
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
            self._invalidate_quality_scan()
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
        return [
            str(index.data(Qt.ItemDataRole.UserRole))
            for index in self.question_table.selectionModel().selectedRows(0)
            if index.data(Qt.ItemDataRole.UserRole)
        ]

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
            for question in self.question_bank.get_many(qset.questions)
            if self._matches_asset_scope(question)
            and self._matches_question_filters(
                question,
                query=query,
                difficulty=difficulty,
                quality_filter=quality_filter,
            )
        ]

    def _matches_current_course(self, qset) -> bool:
        if self._asset_scope is not None:
            return self._asset_scope.matches(qset)
        source_course_id = (qset.metadata or {}).get("course_id", "")
        if not source_course_id:
            return True
        if not self._current_course_id:
            return True
        return source_course_id == self._current_course_id

    def _matches_asset_scope(self, asset) -> bool:
        return (
            self._asset_scope.matches(asset)
            if self._asset_scope is not None
            else True
        )

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

    def _metadata_filter_predicate(self, filter_key: str | None):
        quality_predicate = self._quality_filter_predicate(filter_key)
        scope = self._asset_scope
        if scope is None or scope.kind is LibraryScopeKind.COURSE:
            return quality_predicate

        def matches(question: Question) -> bool:
            return scope.matches(question) and (
                quality_predicate(question)
                if quality_predicate is not None
                else True
            )

        return matches

    def _matches_quality_filter(self, question: Question, filter_key: str | None) -> bool:
        if not filter_key:
            return True
        if filter_key == "quality_warnings":
            return self._has_quality_warning(question)
        if filter_key == "missing_source":
            return self._has_missing_source(question)
        if filter_key == "fallback_source":
            return self._source_ref_status(question) in {
                "fallback_plan_evidence",
                "fallback_global_evidence",
                "global_fallback",
            }
        if filter_key == "weak_plan":
            return self._plan_match_status(question) == "matched_by_shape"
        return True

    def _has_quality_warning(self, question: Question) -> bool:
        scanned = self._quality_scan_results.get(question.question_id)
        if scanned is not None:
            return scanned.has_issues
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

    def _start_quality_scan(self):
        if self._quality_scan_worker is not None:
            return
        task_id = ""
        if self.task_center is not None:
            unassigned_only = False
            snapshot = self.task_center.create(
                kind="question_bank_validation",
                title=self.lang_manager.get_text("题库质量检查", "Question Bank Quality Check"),
                metadata={
                    "course_id": self._current_course_id,
                    "scope": (
                        "unassigned"
                        if unassigned_only
                        else "course"
                        if self._current_course_id
                        else "all"
                    ),
                },
            )
            task_id = snapshot.task_id
        else:
            unassigned_only = False
        self._quality_scan_task_id = task_id
        worker = QuestionQualityScanWorker(
            self.question_bank,
            course_id=self._current_course_id,
            unassigned_only=unassigned_only,
            task_center=self.task_center,
            task_id=task_id,
            parent=self,
        )
        self._quality_scan_worker = worker
        worker.progressed.connect(self._on_quality_scan_progress)
        worker.completed.connect(self._on_quality_scan_completed)
        worker.failed.connect(self._on_quality_scan_failed)
        worker.cancelled.connect(self._on_quality_scan_cancelled)
        self._set_quality_scan_busy(True)
        worker.start()

    def _set_quality_scan_busy(self, busy: bool):
        for widget in (
            self.search_input,
            self.set_filter,
            self.difficulty_filter,
            self.quality_filter,
            self.backfill_source_refs_btn,
            self.question_table,
            self.prev_btn,
            self.next_btn,
            self.new_btn,
            self.save_btn,
            self.delete_btn,
        ):
            widget.setEnabled(not busy)
        self.scan_quality_btn.setEnabled(not busy)
        self.cancel_quality_scan_btn.setVisible(busy)
        self.cancel_quality_scan_btn.setEnabled(busy)
        self.quality_scan_status_label.setVisible(True)
        if busy:
            self.quality_scan_status_label.setText(
                self.lang_manager.get_text("正在准备题库检查…", "Preparing quality check…")
            )

    def _on_quality_scan_progress(self, progress: TaskProgress):
        labels = {
            "discovering_questions": self.lang_manager.get_text("读取题库", "Reading question bank"),
            "loading_question": self.lang_manager.get_text("读取题目", "Loading questions"),
            "validating_question": self.lang_manager.get_text("检查题目", "Checking questions"),
            "validated": self.lang_manager.get_text("正在完成", "Finishing"),
        }
        label = labels.get(progress.stage, progress.stage)
        count = f" {progress.current}/{progress.total}" if progress.total else ""
        detail = f" · {progress.detail}" if progress.detail else ""
        self.quality_scan_status_label.setText(f"{label}{count}{detail}")

    def _on_quality_scan_completed(self, report):
        self._quality_scan_results = {
            result.question_id: result
            for result in report.results
        }
        self._finish_quality_scan()
        self.quality_scan_status_label.setText(self.lang_manager.get_text(
            f"检查完成：{report.issue_question_count}/{report.scanned_count} 道题需要处理。",
            f"Check complete: {report.issue_question_count}/{report.scanned_count} questions need review.",
        ))
        self.refresh()

    def _cancel_quality_scan(self):
        worker = self._quality_scan_worker
        if worker is None:
            return
        self.cancel_quality_scan_btn.setEnabled(False)
        self.quality_scan_status_label.setText(
            self.lang_manager.get_text("正在安全停止…", "Stopping safely…")
        )
        if self.task_center is not None and self._quality_scan_task_id:
            try:
                self.task_center.request_cancel(self._quality_scan_task_id)
            except (KeyError, ValueError):
                pass
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()

    def _on_quality_scan_cancelled(self):
        self._finish_quality_scan()
        self.quality_scan_status_label.setText(
            self.lang_manager.get_text("检查已停止。", "Check stopped.")
        )
        self.refresh()

    def _on_quality_scan_failed(self, message: str):
        self._finish_quality_scan()
        self.quality_scan_status_label.setText(
            self.lang_manager.get_text("检查失败。", "Check failed.")
        )
        self.refresh()
        QMessageBox.critical(
            self,
            self.lang_manager.get_text("题库检查失败", "Question Bank Check Failed"),
            message,
        )

    def _finish_quality_scan(self):
        self._set_quality_scan_busy(False)
        self.cancel_quality_scan_btn.hide()
        self._quality_scan_worker = None
        self._quality_scan_task_id = ""

    def _invalidate_quality_scan(self):
        self._quality_scan_results = {}
        if getattr(self, "_quality_scan_worker", None) is None and hasattr(
            self, "quality_scan_status_label"
        ):
            self.quality_scan_status_label.hide()

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

    def _question_table_row(self, question: Question) -> QuestionTableRow:
        return QuestionTableRow(
            question_id=question.question_id,
            stem=self._compact_text(self._stem_preview(question), 96),
            topic=self._compact_text(question.topic_title(), 32),
            question_type=self._question_type_label(question.type),
            difficulty=self._difficulty_label(question.difficulty),
            status=self._question_status_label(question),
            tooltip=self._question_tooltip(question),
        )

    def _question_tooltip(self, question: Question) -> str:
        stem = question.get_stem("zh") or question.get_stem("en") or ""
        topic = question.topic_title()
        return f"{question.difficulty.value} · {topic}\n{stem}"

    def _question_type_label(self, question_type: QuestionType) -> str:
        labels = {
            QuestionType.MULTIPLE_CHOICE: ("选择题", "Multiple choice"),
            QuestionType.SCENARIO_CHOICE: ("情境选择题", "Scenario choice"),
            QuestionType.TRUE_FALSE: ("判断题", "True / false"),
            QuestionType.FILL_IN_BLANK: ("填空题", "Fill in the blank"),
            QuestionType.MATCHING: ("配对题", "Matching"),
            QuestionType.ORDERING: ("排序题", "Ordering"),
            QuestionType.SHORT_ANSWER: ("简答题", "Short answer"),
        }
        zh, en = labels.get(question_type, (question_type.value, question_type.value))
        return self.lang_manager.get_text(zh, en)

    def _difficulty_label(self, difficulty: Difficulty) -> str:
        labels = {
            Difficulty.EASY: ("简单", "Easy"),
            Difficulty.MEDIUM: ("中等", "Medium"),
            Difficulty.HARD: ("困难", "Hard"),
        }
        zh, en = labels.get(difficulty, (difficulty.value, difficulty.value))
        return self.lang_manager.get_text(zh, en)

    def _question_status_label(self, question: Question) -> str:
        result = self._quality_scan_results.get(question.question_id)
        if result is not None:
            return self.lang_manager.get_text(
                "需检查" if result.has_issues else "通过",
                "Review" if result.has_issues else "Passed",
            )
        status = self._source_ref_status(question)
        if self._has_missing_source(question):
            return self.lang_manager.get_text("无来源", "No source")
        if status in {"fallback_global_evidence", "fallback_topic_evidence"}:
            return self.lang_manager.get_text("兜底来源", "Fallback")
        if self._plan_match_status(question) == "matched_by_shape":
            return self.lang_manager.get_text("弱匹配", "Weak match")
        return self.lang_manager.get_text("正常", "Ready")

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
