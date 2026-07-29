"""Library workspace separating question records from question-set assets."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from core.language_manager import LanguageManager
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.page_header = PageHeader(
            self.lang_manager.get_text("资料库", "Library")
        )
        layout.addWidget(self.page_header)

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
        self.workspace_tabs.addTab(self.question_screen, "")
        self.workspace_tabs.addTab(self.set_panel, "")
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
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self._on_language_changed()

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

    def set_current_course(self, course_id: str | None) -> None:
        self.question_screen.set_current_course(course_id)
        self.set_panel.set_current_course(course_id)

    def refresh(self) -> None:
        self.question_screen.refresh()
        self.set_panel.refresh()

    def show_question_sets(self) -> None:
        self.set_panel.refresh()
        self.workspace_tabs.setCurrentWidget(self.set_panel)
