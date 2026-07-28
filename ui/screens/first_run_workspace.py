"""Single onboarding workspace used until the first practice is ready."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.first_run_flow import FirstRunStage, FirstRunState
from core.language_manager import LanguageManager


class _FirstRunStep(QFrame):
    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self.setObjectName("firstRunStep")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(12)

        self.number_label = QLabel(str(number))
        self.number_label.setObjectName("firstRunStepNumber")
        self.number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number_label.setFixedSize(28, 28)
        layout.addWidget(self.number_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self.title_label = QLabel()
        self.title_label.setObjectName("firstRunStepTitle")
        text_layout.addWidget(self.title_label)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("secondaryText")
        self.detail_label.setWordWrap(True)
        text_layout.addWidget(self.detail_label)
        layout.addLayout(text_layout, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("firstRunStepStatus")
        layout.addWidget(self.status_label)

    def render(self, title: str, detail: str, status: str, status_text: str) -> None:
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.status_label.setText(status_text)
        self.setProperty("stepState", status)
        self.style().unpolish(self)
        self.style().polish(self)


class FirstRunWorkspace(QWidget):
    """Guide an empty installation through three explicit decisions."""

    configure_ai_requested = pyqtSignal()
    choose_materials_requested = pyqtSignal()
    generate_requested = pyqtSignal()
    start_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("firstRunWorkspace")
        self.lang_manager = LanguageManager.instance()
        self.state = FirstRunState(FirstRunStage.AI_SETUP)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.addStretch(1)

        self.card = QFrame()
        self.card.setObjectName("firstRunCard")
        self.card.setMaximumWidth(760)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(28, 26, 28, 26)
        card_layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("firstRunTitle")
        card_layout.addWidget(self.title_label)
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("secondaryText")
        self.subtitle_label.setWordWrap(True)
        card_layout.addWidget(self.subtitle_label)
        card_layout.addSpacing(6)

        self.ai_step = _FirstRunStep(1)
        self.materials_step = _FirstRunStep(2)
        self.generation_step = _FirstRunStep(3)
        for step in (self.ai_step, self.materials_step, self.generation_step):
            card_layout.addWidget(step)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("firstRunProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        card_layout.addWidget(self.progress_bar)
        self.status_label = QLabel()
        self.status_label.setObjectName("firstRunStatus")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        card_layout.addWidget(self.status_label)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.cancel_btn.hide()
        action_layout.addWidget(self.cancel_btn)
        self.primary_btn = QPushButton()
        self.primary_btn.setObjectName("primaryButton")
        self.primary_btn.setMinimumWidth(180)
        self.primary_btn.setMinimumHeight(38)
        self.primary_btn.clicked.connect(self._activate_primary)
        action_layout.addWidget(self.primary_btn)
        card_layout.addLayout(action_layout)

        outer.addWidget(self.card, 4)
        outer.addStretch(1)

        self.lang_manager.language_changed.connect(self._render)
        self._render()

    def set_state(self, state: FirstRunState) -> None:
        self.state = state
        self._render()

    def _render(self, *_args) -> None:
        gm = self.lang_manager.get_text
        self.title_label.setText(gm("创建第一门课程", "Create Your First Course"))
        self.subtitle_label.setText(gm(
            "完成下面三步即可直接开始第一次练习，无需先理解题库和题目集。",
            "Complete these three steps to start your first practice without "
            "learning the library structure first.",
        ))
        statuses = self._step_statuses()
        self.ai_step.render(
            gm("AI 设置", "AI setup"),
            gm("确认提供商、模型和密钥可以用于出题", "Verify provider, model, and credentials"),
            statuses[0],
            self._status_text(statuses[0]),
        )
        self.materials_step.render(
            gm("导入资料", "Import materials"),
            gm("选择包含 PDF、PPTX、DOCX、TXT 或 Markdown 的文件夹", "Choose a folder containing PDF, PPTX, DOCX, TXT, or Markdown"),
            statuses[1],
            self._status_text(statuses[1]),
        )
        self.generation_step.render(
            gm("生成练习", "Generate practice"),
            gm("根据课程知识点准备 10 道快速复习题", "Prepare 10 quick-review questions from course topics"),
            statuses[2],
            self._status_text(statuses[2]),
        )
        self._render_action()
        self._render_progress()

    def _step_statuses(self) -> tuple[str, str, str]:
        stage = self.state.stage
        if stage is FirstRunStage.AI_SETUP:
            return "active", "pending", "pending"
        if stage is FirstRunStage.MATERIALS:
            return "done", "active", "pending"
        if stage is FirstRunStage.IMPORTING:
            return "done", "active", "pending"
        if stage is FirstRunStage.GENERATE:
            return "done", "done", "active"
        if stage is FirstRunStage.GENERATING:
            return "done", "done", "active"
        return "done", "done", "done"

    def _status_text(self, status: str) -> str:
        return {
            "done": self.lang_manager.get_text("已就绪", "Ready"),
            "active": self.lang_manager.get_text("当前", "Current"),
            "pending": self.lang_manager.get_text("待完成", "Pending"),
        }[status]

    def _render_action(self) -> None:
        gm = self.lang_manager.get_text
        stage = self.state.stage
        labels = {
            FirstRunStage.AI_SETUP: gm("配置 AI", "Configure AI"),
            FirstRunStage.MATERIALS: gm("选择课程资料", "Choose Course Materials"),
            FirstRunStage.IMPORTING: gm("正在准备课程…", "Preparing Course…"),
            FirstRunStage.GENERATE: gm("生成 10 道快速复习题", "Generate 10 Quick-Review Questions"),
            FirstRunStage.GENERATING: gm("正在生成练习…", "Generating Practice…"),
            FirstRunStage.READY: gm("开始第一次练习", "Start First Practice"),
        }
        self.primary_btn.setText(labels[stage])
        busy = stage in {FirstRunStage.IMPORTING, FirstRunStage.GENERATING}
        self.primary_btn.setEnabled(not busy)
        self.cancel_btn.setText(gm("停止", "Stop"))
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)

    def _render_progress(self) -> None:
        busy = self.state.stage in {
            FirstRunStage.IMPORTING,
            FirstRunStage.GENERATING,
        }
        self.progress_bar.setVisible(busy)
        if busy and self.state.progress_total > 0:
            self.progress_bar.setRange(0, self.state.progress_total)
            self.progress_bar.setValue(self.state.progress_current)
        elif busy:
            self.progress_bar.setRange(0, 0)
        message = self.state.error or self.state.ai_error or self.state.progress_text
        self.status_label.setText(message)
        self.status_label.setProperty(
            "statusRole",
            "error" if self.state.error or self.state.ai_error else "info",
        )
        self.status_label.setVisible(bool(message))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _activate_primary(self) -> None:
        signal = {
            FirstRunStage.AI_SETUP: self.configure_ai_requested,
            FirstRunStage.MATERIALS: self.choose_materials_requested,
            FirstRunStage.GENERATE: self.generate_requested,
            FirstRunStage.READY: self.start_requested,
        }.get(self.state.stage)
        if signal is not None:
            signal.emit()
