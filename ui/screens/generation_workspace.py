"""Persistent course-owned workspace for AI generation and review."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.language_manager import LanguageManager


class GenerationWorkspace(QWidget):
    """Host one generation surface without starting a nested modal loop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("generationWorkspace")
        self.lang_manager = LanguageManager.instance()
        self.course_id = ""
        self.course_title = ""
        self._generation_widget = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)

        self.header = QFrame()
        self.header.setObjectName("generationWorkspaceHeader")
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(3)

        self.title_label = QLabel()
        self.title_label.setObjectName("pageTitle")
        header_layout.addWidget(self.title_label)

        self.context_label = QLabel()
        self.context_label.setObjectName("secondaryText")
        self.context_label.setWordWrap(True)
        header_layout.addWidget(self.context_label)
        layout.addWidget(self.header)

        self.generation_host = QWidget()
        self.generation_host.setObjectName("generationWorkspaceHost")
        self.generation_host_layout = QVBoxLayout(self.generation_host)
        self.generation_host_layout.setContentsMargins(0, 0, 0, 0)
        self.generation_host_layout.setSpacing(0)
        layout.addWidget(self.generation_host, 1)

        self.lang_manager.language_changed.connect(self._render)
        self._render()

    def show_generation_widget(
        self,
        widget: QWidget,
        *,
        course_id: str,
        course_title: str,
    ) -> None:
        """Attach a generation surface and retain it across navigation."""
        if widget is not self._generation_widget:
            self.clear_generation_widget()
            widget.setParent(self.generation_host)
            widget.setWindowFlags(Qt.WindowType.Widget)
            widget.setMinimumSize(0, 0)
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            self.generation_host_layout.addWidget(widget)
            self._generation_widget = widget
        self.course_id = str(course_id or "").strip()
        self.course_title = str(course_title or "").strip()
        self._render()
        widget.show()

    def clear_generation_widget(self, widget: QWidget | None = None):
        """Detach the active surface only when it matches the caller."""
        current = self._generation_widget
        if current is None or (widget is not None and widget is not current):
            return None
        self.generation_host_layout.removeWidget(current)
        current.hide()
        current.setParent(None)
        self._generation_widget = None
        self.course_id = ""
        self.course_title = ""
        self._render()
        return current

    def generation_widget(self):
        return self._generation_widget

    def request_shutdown(self) -> bool:
        """Request cooperative shutdown without blocking the UI thread."""
        current = self._generation_widget
        if current is None:
            return True
        reject = getattr(current, "reject", None)
        if not callable(reject):
            return True
        reject()
        worker = getattr(current, "worker", None)
        is_running = getattr(worker, "isRunning", None)
        return not (callable(is_running) and is_running())

    def _render(self, *_args) -> None:
        gm = self.lang_manager.get_text
        self.title_label.setText(gm("生成与审核", "Generate and Review"))
        if self.course_title:
            self.context_label.setText(gm(
                f"课程：{self.course_title} · 离开本页不会中断当前任务",
                f"Course: {self.course_title} · Leaving this page will not stop the task",
            ))
        else:
            self.context_label.setText(gm(
                "从课程页开始生成，任务与待审核草稿会保留在这里。",
                "Start from a course. The active task and review draft remain here.",
            ))
