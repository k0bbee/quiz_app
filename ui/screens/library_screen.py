"""Library workspace separating question records from question-set assets."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
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


class LibraryScreen(QWidget):
    """Own the two asset-management views under one library route."""

    question_bank_changed = pyqtSignal()
    export_mock_exam = pyqtSignal(str)
    export_mock_exams = pyqtSignal(list)
    regenerate_questions = pyqtSignal(str)
    sets_changed = pyqtSignal()

    def __init__(
        self,
        question_bank: QuestionBank,
        *,
        set_manager: SetManager,
        course_manager: CourseProjectManager,
        progress_manager=None,
        task_center=None,
        parent=None,
    ):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        self.course_manager = course_manager
        self._scope_course_id = ""
        self.current_scope = LibraryAssetScope.empty()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.page_header = PageHeader(
            self.lang_manager.get_text("资料库", "Library")
        )
        layout.addWidget(self.page_header)

        self.scope_label = QLabel()
        self.scope_label.setObjectName("secondaryText")
        self.scope_label.setWordWrap(True)
        layout.addWidget(self.scope_label)

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
        layout.addWidget(self.question_screen, 1)
        layout.addWidget(self.set_panel, 1)
        self.set_panel.hide()

        self.question_screen.question_bank_changed.connect(
            self.question_bank_changed.emit
        )
        self.set_panel.export_mock_exam.connect(self.export_mock_exam.emit)
        self.set_panel.export_mock_exams.connect(self.export_mock_exams.emit)
        self.set_panel.regenerate_questions.connect(
            self.regenerate_questions.emit
        )
        self.set_panel.sets_changed.connect(self.sets_changed.emit)
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self._on_language_changed()
        current = self.course_manager.current()
        self.set_current_course(current.course_id if current else "")

    def _on_language_changed(self, _lang=None) -> None:
        self.page_header.set_title(
            self.lang_manager.get_text("资料库", "Library")
        )
        self._update_scope_label()

    def set_current_course(self, course_id: str | None) -> None:
        course_id = str(course_id or "").strip()
        project = self.course_manager.get(course_id) if course_id else None
        self._scope_course_id = project.course_id if project is not None else ""
        self._update_scope_label()
        self._apply_current_scope()

    def show_course_assets(
        self,
        course_id: str,
        *,
        question_sets: bool = False,
    ) -> None:
        project = self.course_manager.get(str(course_id or "").strip())
        if project is None:
            return
        self._scope_course_id = project.course_id
        self._update_scope_label()
        self._apply_current_scope()
        if question_sets:
            self.show_question_sets()
        else:
            self.show_questions()

    def _update_scope_label(self) -> None:
        project = (
            self.course_manager.get(self._scope_course_id)
            if self._scope_course_id
            else None
        )
        if project is None:
            text = self.lang_manager.get_text(
                "尚未选择课程",
                "No course selected",
            )
            self.scope_label.setToolTip("")
        else:
            state = self.lang_manager.get_text(
                "已归档课程" if getattr(project, "is_archived", False) else "当前课程",
                "Archived course" if getattr(project, "is_archived", False) else "Current course",
            )
            text = f"{state}：{project.title}"
            self.scope_label.setToolTip(str(project.title or ""))
        self.scope_label.setText(text)

    def _apply_current_scope(self) -> None:
        if self._scope_course_id:
            scope = LibraryAssetScope.course(self._scope_course_id)
        else:
            scope = LibraryAssetScope.empty()
        self.current_scope = scope
        self.question_screen.set_asset_scope(scope)
        self.set_panel.set_asset_scope(scope)

    def refresh(self) -> None:
        self.question_screen.refresh()
        self.set_panel.refresh()

    def show_question_sets(self) -> None:
        self.question_screen.hide()
        self.set_panel.show()

    def show_questions(self) -> None:
        self.set_panel.hide()
        self.question_screen.show()
