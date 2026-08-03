"""Persistent course-owned workspace for AI generation and review."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
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
        self._sessions: dict[str, tuple[QWidget, str, str]] = {}
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

        self.session_row = QHBoxLayout()
        self.session_row.setSpacing(8)
        self.session_label = QLabel()
        self.session_label.setObjectName("secondaryText")
        self.session_row.addWidget(self.session_label)
        self.session_selector = QComboBox()
        self.session_selector.setObjectName("generationSessionSelector")
        self.session_selector.currentIndexChanged.connect(
            self._select_session
        )
        self.session_row.addWidget(self.session_selector, 1)
        header_layout.addLayout(self.session_row)

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
        draft_id: str = "",
    ) -> None:
        """Attach a generation surface and retain it across navigation."""
        key = str(draft_id or "").strip() or f"widget-{id(widget)}"
        existing_key = next(
            (
                candidate
                for candidate, (current, _course_id, _title) in self._sessions.items()
                if current is widget
            ),
            None,
        )
        if existing_key is not None and existing_key != key:
            self._sessions.pop(existing_key, None)
        previous = self._sessions.get(key)
        if previous is not None and previous[0] is not widget:
            self._remove_session_widget(key)
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
        self._sessions[key] = (
            widget,
            str(course_id or "").strip(),
            str(course_title or "").strip(),
        )
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
        key = next(
            (
                candidate
                for candidate, (current_widget, _course_id, _title) in self._sessions.items()
                if current_widget is target
            ),
            None,
        )
        if key is None:
            return None
        self._remove_session_widget(key)
        active = self.generation_widget()
        if active is None:
            self.course_id = ""
            self.course_title = ""
        else:
            _key, (_widget, self.course_id, self.course_title) = next(
                (
                    (session_key, entry)
                    for session_key, entry in self._sessions.items()
                    if entry[0] is active
                ),
                ("", (active, "", "")),
            )
        self._render()
        return target

    def generation_widget(self):
        return self.generation_host.currentWidget()

    def session_course_id(self, draft_id: str) -> str:
        entry = self._sessions.get(str(draft_id or "").strip())
        return entry[1] if entry is not None else ""

    def select_session(self, draft_id: str) -> bool:
        wanted = str(draft_id or "").strip()
        if not wanted or wanted not in self._sessions:
            return False
        index = self.session_selector.findData(wanted)
        if index < 0:
            return False
        self.session_selector.setCurrentIndex(index)
        return self.generation_widget() is self._sessions[wanted][0]

    def request_shutdown(self) -> bool:
        """Request cooperative shutdown without blocking the UI thread."""
        sessions = list(self._sessions.values())
        if not sessions:
            self._shutting_down = False
            return True
        self._shutting_down = True
        all_stopped = True
        for current, _course_id, _course_title in sessions:
            reject = getattr(current, "reject", None)
            if callable(reject):
                reject()
            worker = getattr(current, "worker", None)
            is_running = getattr(worker, "isRunning", None)
            if callable(is_running) and is_running():
                all_stopped = False
        return all_stopped

    def _remove_session_widget(self, key: str) -> None:
        entry = self._sessions.pop(key, None)
        if entry is None:
            return
        widget = entry[0]
        if self.generation_host.indexOf(widget) >= 0:
            self.generation_host.removeWidget(widget)
        widget.hide()
        widget.setParent(None)

    def _select_session(self, index: int) -> None:
        if not 0 <= index < self.session_selector.count():
            return
        key = str(self.session_selector.itemData(index) or "").strip()
        entry = self._sessions.get(key)
        if entry is None:
            return
        widget, self.course_id, self.course_title = entry
        self.generation_host.setCurrentWidget(widget)
        self._render()
        self.refresh_stage()

    def _sync_session_selector(self) -> None:
        gm = self.lang_manager.get_text
        active = self.generation_widget()
        active_key = next(
            (
                key
                for key, (widget, _course_id, _title) in self._sessions.items()
                if widget is active
            ),
            "",
        )
        self.session_selector.blockSignals(True)
        self.session_selector.clear()
        for key, (widget, course_id, course_title) in self._sessions.items():
            title = course_title or course_id or gm("未命名课程", "Untitled course")
            source = str(getattr(widget, "_draft_source", "") or "").strip()
            source_label = {
                "first_run": gm("首次使用", "First Run"),
                "course_hub_gap": gm("补齐缺口", "Fill Gaps"),
                "result_reinforcement": gm("弱项补强", "Reinforcement"),
                "progress_topic": gm("按知识点生成", "By Topic"),
                "predicted_exam": gm("真题预测", "Exam Prediction"),
                "prediction": gm("真题预测", "Exam Prediction"),
                "manual": gm("手动生成", "Manual"),
            }.get(source, gm("生成任务", "Generation"))
            self.session_selector.addItem(
                f"{title} · {source_label}",
                key,
            )
        selected_index = self.session_selector.findData(active_key)
        if selected_index >= 0:
            self.session_selector.setCurrentIndex(selected_index)
        self.session_selector.blockSignals(False)
        multiple_sessions = len(self._sessions) > 1
        self.session_label.setVisible(multiple_sessions)
        self.session_selector.setVisible(multiple_sessions)
        self.session_label.setText(gm("当前任务", "Current task"))

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
        self._sync_session_selector()
        labels = (
            gm("1 计划", "1 Plan"),
            gm("2 生成", "2 Generate"),
            gm("3 审核", "3 Review"),
            gm("4 发布", "4 Publish"),
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
