"""Library workspace separating question records from question-set assets."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.language_manager import LanguageManager
from core.library_scope import LibraryAssetScope
from models.course_project import CourseProjectManager
from models.question import QuestionBank
from models.question_set import SetManager
from ui.components import PageHeader
from ui.screens.question_bank_screen import QuestionBankScreen
from ui.widgets.question_set_library_panel import QuestionSetLibraryPanel
from ui.widgets.generation_draft_library_panel import (
    GenerationDraftLibraryPanel,
)
from ui.widgets.wheel_safe_controls import WheelSafeComboBox


class LibraryScreen(QWidget):
    """Own the two asset-management views under one library route."""

    question_bank_changed = pyqtSignal()
    export_mock_exam = pyqtSignal(str)
    export_mock_exams = pyqtSignal(list)
    regenerate_questions = pyqtSignal(str)
    sets_changed = pyqtSignal()
    resume_generation_draft = pyqtSignal(str, str, str)

    def __init__(
        self,
        question_bank: QuestionBank,
        *,
        set_manager: SetManager,
        course_manager: CourseProjectManager,
        progress_manager=None,
        task_center=None,
        generation_draft_store=None,
        parent=None,
    ):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        self.course_manager = course_manager
        self._scope_kind = "active"
        self._scope_course_id = ""
        self.current_scope = LibraryAssetScope.empty()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.page_header = PageHeader(
            self.lang_manager.get_text("资料库", "Library")
        )
        layout.addWidget(self.page_header)

        self.scope_row = QHBoxLayout()
        self.scope_row.setSpacing(8)
        self.scope_label = QLabel()
        self.scope_label.setObjectName("secondaryText")
        self.scope_row.addWidget(self.scope_label)
        self.scope_group = QButtonGroup(self)
        self.scope_group.setExclusive(True)
        self.active_scope_btn = self._scope_button()
        self.archived_scope_btn = self._scope_button()
        self.unassigned_scope_btn = self._scope_button()
        for button in (
            self.active_scope_btn,
            self.archived_scope_btn,
            self.unassigned_scope_btn,
        ):
            self.scope_row.addWidget(button)
        self.course_scope_combo = WheelSafeComboBox()
        self.course_scope_combo.setMinimumWidth(220)
        self.course_scope_combo.currentIndexChanged.connect(
            self._on_course_scope_changed
        )
        self.scope_row.addWidget(self.course_scope_combo, 1)
        layout.addLayout(self.scope_row)

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setObjectName("libraryWorkspaceTabs")
        self.question_screen = QuestionBankScreen(
            question_bank,
            set_manager=set_manager,
            course_manager=course_manager,
            task_center=task_center,
            embedded=True,
        )
        self.question_screen.setObjectName("question_records")
        self.set_panel = QuestionSetLibraryPanel(
            set_manager,
            progress_manager=progress_manager,
        )
        self.set_panel.setObjectName("question_sets")
        self.draft_panel = GenerationDraftLibraryPanel(
            generation_draft_store,
            course_manager,
        )
        self.draft_panel.setObjectName("generation_drafts")
        self.workspace_tabs.addTab(self.question_screen, "")
        self.workspace_tabs.addTab(self.set_panel, "")
        self.workspace_tabs.addTab(self.draft_panel, "")
        self.workspace_tabs.tabBar().hide()
        layout.addWidget(self.workspace_tabs, 1)

        self.question_screen.question_bank_changed.connect(
            self.question_bank_changed.emit
        )
        self.set_panel.export_mock_exam.connect(self.export_mock_exam.emit)
        self.set_panel.export_mock_exams.connect(self.export_mock_exams.emit)
        self.set_panel.regenerate_questions.connect(
            self.regenerate_questions.emit
        )
        self.set_panel.sets_changed.connect(self.sets_changed.emit)
        self.draft_panel.resume_requested.connect(
            self.resume_generation_draft.emit
        )
        self.active_scope_btn.clicked.connect(
            lambda: self._set_scope_kind("active")
        )
        self.archived_scope_btn.clicked.connect(
            lambda: self._set_scope_kind("archived")
        )
        self.unassigned_scope_btn.clicked.connect(
            lambda: self._set_scope_kind("unassigned")
        )
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self._on_language_changed()
        current = self.course_manager.current()
        self.set_current_course(current.course_id if current else "")

    def _scope_button(self) -> QPushButton:
        button = QPushButton()
        button.setObjectName("quizModeOption")
        button.setCheckable(True)
        button.setMinimumHeight(34)
        self.scope_group.addButton(button)
        return button

    def _on_language_changed(self, _lang=None) -> None:
        self.page_header.set_title(
            self.lang_manager.get_text("资料库", "Library")
        )
        self.workspace_tabs.setTabText(
            0,
            self.lang_manager.get_text("题目", "Questions"),
        )
        self.workspace_tabs.setTabText(
            1,
            self.lang_manager.get_text("题目集", "Question Sets"),
        )
        self.workspace_tabs.setTabText(
            2,
            self.lang_manager.get_text("生成草稿", "Generation Drafts"),
        )
        self.scope_label.setText(
            self.lang_manager.get_text("资料范围", "Asset Scope")
        )
        self._refresh_scope_controls()

    def set_current_course(self, course_id: str | None) -> None:
        course_id = str(course_id or "").strip()
        project = self.course_manager.get(course_id) if course_id else None
        if project is not None:
            self._scope_kind = (
                "archived"
                if getattr(project, "is_archived", False)
                else "active"
            )
            self._scope_course_id = project.course_id
        else:
            active = self._courses_for_scope("active")
            archived = self._courses_for_scope("archived")
            if active:
                self._scope_kind = "active"
                current = self.course_manager.current()
                active_ids = {course.course_id for course in active}
                self._scope_course_id = (
                    current.course_id
                    if current is not None
                    and current.course_id in active_ids
                    else active[0].course_id
                )
            elif archived:
                self._scope_kind = "archived"
                self._scope_course_id = archived[0].course_id
            else:
                self._scope_kind = "unassigned"
                self._scope_course_id = ""
        self._refresh_scope_controls()

    def show_course_assets(
        self,
        course_id: str,
        *,
        question_sets: bool = False,
    ) -> None:
        project = self.course_manager.get(str(course_id or "").strip())
        if project is None:
            return
        self._scope_kind = (
            "archived"
            if getattr(project, "is_archived", False)
            else "active"
        )
        self._scope_course_id = project.course_id
        self._refresh_scope_controls()
        self.workspace_tabs.setCurrentWidget(
            self.set_panel if question_sets else self.question_screen
        )

    def _set_scope_kind(self, kind: str) -> None:
        self._scope_kind = (
            kind if kind in {"active", "archived", "unassigned"} else "active"
        )
        self._scope_course_id = ""
        self._refresh_scope_controls()

    def _all_courses(self):
        return list(self.course_manager.load_all(include_archived=True))

    def _courses_for_scope(self, kind: str):
        archived = kind == "archived"
        return [
            course
            for course in self._all_courses()
            if bool(getattr(course, "is_archived", False)) == archived
        ]

    def _refresh_scope_controls(self) -> None:
        if not hasattr(self, "active_scope_btn"):
            return
        gm = self.lang_manager.get_text
        active_courses = self._courses_for_scope("active")
        archived_courses = self._courses_for_scope("archived")
        self.active_scope_btn.setText(
            gm(f"进行中 ({len(active_courses)})", f"Active ({len(active_courses)})")
        )
        self.archived_scope_btn.setText(
            gm(f"已归档 ({len(archived_courses)})", f"Archived ({len(archived_courses)})")
        )
        self.unassigned_scope_btn.setText(gm("未归属", "Unassigned"))
        self.active_scope_btn.setChecked(self._scope_kind == "active")
        self.archived_scope_btn.setChecked(self._scope_kind == "archived")
        self.unassigned_scope_btn.setChecked(self._scope_kind == "unassigned")

        courses = (
            archived_courses
            if self._scope_kind == "archived"
            else active_courses
        )
        self.course_scope_combo.blockSignals(True)
        self.course_scope_combo.clear()
        if self._scope_kind == "unassigned":
            self._scope_course_id = ""
            self.course_scope_combo.setVisible(False)
            self.course_scope_combo.setEnabled(False)
        else:
            self.course_scope_combo.setVisible(True)
            for course in courses:
                self.course_scope_combo.addItem(course.title, course.course_id)
            available_ids = {course.course_id for course in courses}
            if self._scope_course_id not in available_ids:
                self._scope_course_id = courses[0].course_id if courses else ""
            if courses:
                index = self.course_scope_combo.findData(self._scope_course_id)
                self.course_scope_combo.setCurrentIndex(max(0, index))
                self.course_scope_combo.setEnabled(True)
            else:
                self.course_scope_combo.addItem(
                    gm(
                        "暂无进行中的课程"
                        if self._scope_kind == "active"
                        else "暂无已归档课程",
                        "No active courses"
                        if self._scope_kind == "active"
                        else "No archived courses",
                    ),
                    "",
                )
                self.course_scope_combo.setEnabled(False)
        self.course_scope_combo.blockSignals(False)
        self._apply_current_scope()

    def _on_course_scope_changed(self, _index: int) -> None:
        self._scope_course_id = str(
            self.course_scope_combo.currentData() or ""
        )
        self._apply_current_scope()

    def _apply_current_scope(self) -> None:
        if self._scope_kind == "unassigned":
            scope = LibraryAssetScope.unassigned()
        elif self._scope_course_id:
            scope = LibraryAssetScope.course(self._scope_course_id)
        else:
            scope = LibraryAssetScope.empty()
        self.current_scope = scope
        self.question_screen.set_asset_scope(scope)
        self.set_panel.set_asset_scope(scope)
        self.draft_panel.set_asset_scope(scope)

    def refresh(self) -> None:
        self._refresh_scope_controls()
        self.question_screen.refresh()
        self.set_panel.refresh()

    def show_question_sets(self) -> None:
        self.workspace_tabs.setCurrentWidget(self.set_panel)

    def show_questions(self) -> None:
        self.workspace_tabs.setCurrentWidget(self.question_screen)

    def show_generation_drafts(self) -> None:
        self.workspace_tabs.setCurrentWidget(self.draft_panel)
