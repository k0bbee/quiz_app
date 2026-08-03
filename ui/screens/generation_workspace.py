"""Persistent course-owned workspace for AI generation and review."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from core.language_manager import LanguageManager
from core.generation_session_state import GenerationStage


class GenerationWorkspace(QWidget):
    """Host one generation surface without starting a nested modal loop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("generationWorkspace")
        self.lang_manager = LanguageManager.instance()
        self.course_id = ""
        self.course_title = ""
        self._shutting_down = False

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

        self.stage_layout = QHBoxLayout()
        self.stage_layout.setSpacing(8)
        self.stage_labels = []
        for index in range(4):
            label = QLabel()
            label.setObjectName("generationStage")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stage_layout.addWidget(label, 1)
            self.stage_labels.append(label)
        header_layout.addLayout(self.stage_layout)
        layout.addWidget(self.header)

        self.generation_host = QStackedWidget()
        self.generation_host.setObjectName("generationWorkspaceHost")
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
        """Attach the one active generation surface for the workspace."""
        current = self.generation_widget()
        if current is not None and current is not widget:
            self._remove_generation_widget(current)
        if self.generation_host.indexOf(widget) < 0:
            widget.setParent(self.generation_host)
            widget.setWindowFlags(Qt.WindowType.Widget)
            widget.setMinimumSize(0, 0)
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            self.generation_host.addWidget(widget)
            draft_changed = getattr(widget, "draft_changed", None)
            connect = getattr(draft_changed, "connect", None)
            if callable(connect):
                connect(self.refresh_stage)
        self.generation_host.setCurrentWidget(widget)
        self.course_id = str(course_id or "").strip()
        self.course_title = str(course_title or "").strip()
        self._render()
        self.refresh_stage()
        widget.show()

    def clear_generation_widget(self, widget: QWidget | None = None):
        """Detach the active surface only when it matches the caller."""
        current = self.generation_widget()
        target = widget or current
        if target is None:
            return None
        if self.generation_host.indexOf(target) < 0:
            return None
        self._remove_generation_widget(target)
        self.course_id = ""
        self.course_title = ""
        self._render()
        return target

    def generation_widget(self):
        return self.generation_host.currentWidget()

    def request_shutdown(self) -> bool:
        """Request cooperative shutdown without blocking the UI thread."""
        current = self.generation_widget()
        if current is None:
            self._shutting_down = False
            return True
        self._shutting_down = True
        reject = getattr(current, "reject", None)
        if callable(reject):
            reject()
        worker = getattr(current, "worker", None)
        is_running = getattr(worker, "isRunning", None)
        all_stopped = not (callable(is_running) and is_running())
        return all_stopped

    def _remove_generation_widget(self, widget: QWidget) -> None:
        if self.generation_host.indexOf(widget) >= 0:
            self.generation_host.removeWidget(widget)
        widget.hide()
        widget.setParent(None)

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
        labels = (
            gm("1 计划", "1 Plan"),
            gm("2 生成", "2 Generate"),
            gm("3 审核", "3 Review"),
            gm("4 保存", "4 Save"),
        )
        for label, text in zip(self.stage_labels, labels):
            label.setText(text)
        self.refresh_stage()

    def refresh_stage(self) -> None:
        """Reflect the hosted generation lifecycle as four user-facing steps."""
        stage = getattr(
            self.generation_widget(),
            "generation_stage",
            GenerationStage.CONFIGURING,
        )
        active_index = {
            GenerationStage.CONFIGURING: 0,
            GenerationStage.RUNNING: 1,
            GenerationStage.PARTIAL: 1,
            GenerationStage.FAILED: 1,
            GenerationStage.CANCELLED: 1,
            GenerationStage.REVIEW_PENDING: 2,
            GenerationStage.SAVED: 3,
        }.get(stage, 0)
        for index, label in enumerate(self.stage_labels):
            active = index == active_index
            if label.property("activeStage") != active:
                label.setProperty("activeStage", active)
                label.style().unpolish(label)
                label.style().polish(label)
