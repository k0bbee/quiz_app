"""Library projection for durable AI generation drafts."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.display_time import format_local_timestamp
from core.language_manager import LanguageManager
from core.library_scope import LibraryAssetScope, LibraryScopeKind


class GenerationDraftLibraryPanel(QWidget):
    """List and resume course-owned review drafts without owning their state."""

    resume_requested = pyqtSignal(str, str, str)

    def __init__(
        self,
        draft_store,
        course_manager,
        parent=None,
    ):
        super().__init__(parent)
        self.draft_store = draft_store
        self.course_manager = course_manager
        self.lang_manager = LanguageManager.instance()
        self.current_scope = LibraryAssetScope.empty()
        self._visible_drafts = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.status_label = QLabel()
        self.status_label.setObjectName("secondaryText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("generationDraftTable")
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 5):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        self.table.itemSelectionChanged.connect(
            self._update_resume_action
        )
        self.table.itemDoubleClicked.connect(
            lambda _item: self._resume_selected()
        )
        layout.addWidget(self.table, 1)

        action_row = QHBoxLayout()
        self.selection_note = QLabel()
        self.selection_note.setObjectName("secondaryText")
        self.selection_note.setWordWrap(True)
        action_row.addWidget(self.selection_note, 1)
        self.resume_btn = QPushButton()
        self.resume_btn.setObjectName("primaryButton")
        self.resume_btn.clicked.connect(self._resume_selected)
        action_row.addWidget(self.resume_btn)
        layout.addLayout(action_row)

        self.lang_manager.language_changed.connect(self._on_language_changed)
        self._on_language_changed()

    def set_asset_scope(self, scope: LibraryAssetScope) -> None:
        self.current_scope = scope
        self.refresh()

    def refresh(self) -> None:
        gm = self.lang_manager.get_text
        drafts = []
        if (
            self.draft_store is not None
            and self.current_scope.kind is LibraryScopeKind.COURSE
        ):
            try:
                drafts = [
                    draft
                    for draft in self.draft_store.list_all()
                    if draft.course_id == self.current_scope.course_id
                ]
            except (OSError, TypeError, ValueError):
                drafts = []
        self._visible_drafts = drafts
        self.table.setRowCount(len(drafts))
        for row, draft in enumerate(drafts):
            course = self.course_manager.get(draft.course_id)
            course_title = (
                course.title
                if course is not None
                else gm("课程已删除", "Course deleted")
            )
            source_label = _source_label(draft.source, gm)
            values = (
                course_title,
                draft.question_set_title
                or gm("未命名生成草稿", "Untitled generation draft"),
                str(len(draft.questions)),
                source_label,
                format_local_timestamp(draft.updated_at),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, draft.course_id)
                self.table.setItem(row, column, item)
        if drafts:
            self.table.selectRow(0)
            self.status_label.setText(gm(
                f"当前课程有 {len(drafts)} 份待审核草稿。",
                f"{len(drafts)} review draft(s) for this course.",
            ))
        else:
            self.status_label.setText(gm(
                "当前范围没有待审核的生成草稿。",
                "There are no review drafts in the current scope.",
            ))
        self._update_resume_action()

    def _on_language_changed(self, _lang=None) -> None:
        gm = self.lang_manager.get_text
        self.table.setHorizontalHeaderLabels([
            gm("课程", "Course"),
            gm("草稿", "Draft"),
            gm("题目", "Questions"),
            gm("来源", "Source"),
            gm("更新时间", "Updated"),
        ])
        self.resume_btn.setText(gm("继续审核", "Continue Review"))
        self.refresh()

    def _selected_draft(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._visible_drafts):
            return self._visible_drafts[row]
        return None

    def _update_resume_action(self) -> None:
        draft = self._selected_draft()
        course = (
            self.course_manager.get(draft.course_id)
            if draft is not None
            else None
        )
        available = (
            course is not None
            and not getattr(course, "is_archived", False)
        )
        self.resume_btn.setEnabled(available)
        gm = self.lang_manager.get_text
        if draft is None:
            note = gm(
                "选择草稿后可继续审核。",
                "Select a draft to continue review.",
            )
        elif course is None:
            note = gm(
                "所属课程已不存在，无法恢复此草稿。",
                "The owning course no longer exists, so this draft cannot resume.",
            )
        elif getattr(course, "is_archived", False):
            note = gm(
                "请先恢复所属课程，再继续审核。",
                "Restore the owning course before continuing review.",
            )
        else:
            note = gm(
                "继续后返回该课程的生成与审核工作区。",
                "Continue in the course Generate and Review workspace.",
            )
        self.selection_note.setText(note)

    def _resume_selected(self) -> None:
        if not self.resume_btn.isEnabled():
            return
        draft = self._selected_draft()
        if draft is not None:
            self.resume_requested.emit(
                draft.course_id,
                draft.source,
                draft.draft_id,
            )


def _source_label(source: str, get_text) -> str:
    return {
        "first_run": get_text("首次使用", "First Run"),
        "course_hub_gap": get_text("补齐缺口", "Fill Gaps"),
        "result_reinforcement": get_text("弱项补强", "Reinforcement"),
        "progress_topic": get_text("按知识点生成", "By Topic"),
        "manual": get_text("手动生成", "Manual"),
    }.get(str(source or "").strip(), get_text("其他", "Other"))
