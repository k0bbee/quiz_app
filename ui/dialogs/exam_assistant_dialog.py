"""Reviewable natural-language assistant for exam generation settings."""

from __future__ import annotations

import html

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai.exam_plan import ExamGenerationPlan, PlanChange
from ai.exam_request_interpreter import (
    ExamRequestError,
    ExamRequestInterpreter,
    InterpretationResult,
)
from core.language_manager import LanguageManager


class ExamInterpretWorker(QThread):
    """Run a potentially remote interpretation without blocking the UI thread."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, interpreter, request: str, current: ExamGenerationPlan, parent=None):
        super().__init__(parent)
        self.interpreter = interpreter
        self.request = request
        self.current = current

    def run(self):
        try:
            result = self.interpreter.interpret(self.request, self.current)
        except ExamRequestError as exc:
            if self.isInterruptionRequested():
                return
            self.failed.emit(str(exc))
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            self.failed.emit(f"Unexpected interpretation error: {exc}")
        else:
            if self.isInterruptionRequested():
                return
            self.succeeded.emit(result)


class ExamAssistantDialog(QDialog):
    """Build a draft plan through dialogue, then explicitly confirm it."""

    def __init__(
        self,
        initial_plan: ExamGenerationPlan,
        available_topics: list[str],
        settings: dict | None = None,
        parent=None,
        interpreter=None,
    ):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        self.initial_plan = initial_plan
        self.draft_plan = initial_plan
        self.available_topics = list(available_topics)
        self.settings = settings or {}
        self.interpreter = interpreter or self._build_default_interpreter()
        self.confirmed_plan: ExamGenerationPlan | None = None
        self.worker: ExamInterpretWorker | None = None
        self._pending_request = ""
        self._last_changes: tuple[PlanChange, ...] = ()
        self._cancelled = False
        self._close_when_worker_stops = False

        self.setWindowTitle(self.lang_manager.get_text("试卷助手", "Exam Assistant"))
        self.resize(980, 680)
        self.setMinimumSize(820, 600)
        self._setup_ui()
        self._refresh_plan_preview()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _build_default_interpreter(self):
        from ai.llm_client import LLMClient
        from ai.course_summary_factory import provider_requires_api_key
        from core.secrets_manager import SecretsManager

        api_key = SecretsManager.instance().get_key() if provider_requires_api_key(self.settings) else ""
        client = LLMClient(
            api_key=api_key,
            base_url=self.settings.get("ai_base_url", "local-agent://auto"),
            model=self.settings.get("ai_model", "auto"),
            provider=self.settings.get("ai_provider", ""),
        )
        return ExamRequestInterpreter(self.available_topics, client)

    def _setup_ui(self):
        gm = self.lang_manager.get_text
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 12, 16, 8)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(8)

        self.left_pane = QWidget()
        left_layout = QVBoxLayout(self.left_pane)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(12)

        self.conversation_group = QGroupBox(gm("需求对话", "Requirements Conversation"))
        conversation_layout = QVBoxLayout(self.conversation_group)
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("conversationTranscript")
        self.transcript.setOpenExternalLinks(False)
        conversation_layout.addWidget(self.transcript, 1)
        self._append_assistant(
            gm(
                "描述你想要的试卷，例如：出 20 道期末模拟题，缓存和进程为主，困难题占 40%。",
                "Describe the exam you want, for example: Create 20 final-exam questions focused on cache and processes, with 40% hard questions.",
            )
        )

        self.request_input = QPlainTextEdit()
        self.request_input.setObjectName("examRequestInput")
        self.request_input.setMaximumHeight(100)
        self.request_input.setPlaceholderText(
            gm("输入新的要求或继续修改当前方案…", "Enter a requirement or refine the current plan…")
        )
        conversation_layout.addWidget(self.request_input)

        request_actions = QHBoxLayout()
        request_actions.addStretch()
        self.interpret_btn = QPushButton(gm("理解要求", "Interpret Request"))
        self.interpret_btn.setObjectName("secondaryButton")
        self.interpret_btn.clicked.connect(self._submit_request)
        request_actions.addWidget(self.interpret_btn)
        conversation_layout.addLayout(request_actions)
        left_layout.addWidget(self.conversation_group)

        self.content_splitter.addWidget(self.left_pane)

        self.right_pane = QWidget()
        right_layout = QVBoxLayout(self.right_pane)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(12)

        self.plan_group = QGroupBox(gm("当前方案", "Current Plan"))
        plan_layout = QVBoxLayout(self.plan_group)
        self.plan_preview = QTextEdit()
        self.plan_preview.setObjectName("examPlanPreview")
        self.plan_preview.setReadOnly(True)
        plan_layout.addWidget(self.plan_preview)
        right_layout.addWidget(self.plan_group, 3)

        self.changes_group = QGroupBox(gm("本轮变更", "Latest Changes"))
        changes_layout = QVBoxLayout(self.changes_group)
        self.changes_preview = QTextEdit()
        self.changes_preview.setObjectName("examChangesPreview")
        self.changes_preview.setReadOnly(True)
        changes_layout.addWidget(self.changes_preview)
        self.source_label = QLabel()
        self.source_label.setObjectName("mutedLabel")
        changes_layout.addWidget(self.source_label)
        right_layout.addWidget(self.changes_group, 2)

        self.content_splitter.addWidget(self.right_pane)
        self.content_splitter.setStretchFactor(0, 5)
        self.content_splitter.setStretchFactor(1, 4)
        self.content_splitter.setSizes([540, 440])
        body_layout.addWidget(self.content_splitter)
        outer.addWidget(body, 1)

        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(16, 4, 16, 12)
        footer_layout.setSpacing(8)
        self.status_label = QLabel()
        footer_layout.addWidget(self.status_label)

        self.footer_action_layout = QHBoxLayout()
        self.cancel_btn = QPushButton(gm("取消", "Cancel"))
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        self.footer_action_layout.addWidget(self.cancel_btn)
        self.footer_action_layout.addStretch()
        self.apply_btn = QPushButton(gm("应用配置", "Apply Configuration"))
        self.apply_btn.setObjectName("primaryButton")
        self.apply_btn.setMinimumHeight(34)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._confirm)
        self.footer_action_layout.addWidget(self.apply_btn)
        footer_layout.addLayout(self.footer_action_layout)
        outer.addWidget(footer)

    def _submit_request(self):
        request = self.request_input.toPlainText().strip()
        if not request:
            self._set_error(self.lang_manager.get_text("请输入具体要求。", "Enter a specific requirement."))
            return
        if self.worker and self.worker.isRunning():
            return

        self._cancelled = False
        self._pending_request = request
        self._append_user(request)
        self._set_busy(True)
        self._set_status(
            self.lang_manager.get_text("正在理解要求…", "Interpreting request…")
        )
        self.worker = ExamInterpretWorker(self.interpreter, request, self.draft_plan, self)
        self._connect_interpret_worker(self.worker)
        self.worker.start()

    def _connect_interpret_worker(self, worker) -> None:
        """Ignore queued results from an interpreter run that has been replaced."""
        worker.succeeded.connect(
            lambda result, source=worker: self._deliver_worker_signal(
                source, self._on_interpreted, result
            )
        )
        worker.failed.connect(
            lambda message, source=worker: self._deliver_worker_signal(
                source, self._on_interpretation_error, message
            )
        )
        worker.finished.connect(
            lambda source=worker: self._deliver_worker_signal(
                source, self._on_worker_finished
            )
        )

    def _deliver_worker_signal(self, source, handler, *args) -> None:
        if source is self.worker:
            handler(*args)

    def _on_interpreted(self, result: InterpretationResult):
        if self._cancelled:
            return
        self._apply_interpretation(self._pending_request, result, record_user=False)

    def _apply_interpretation(
        self,
        request: str,
        result: InterpretationResult,
        record_user: bool = True,
    ):
        """Apply a validated result to the draft only; confirmation stays explicit."""
        if record_user:
            self._append_user(request)
        self.draft_plan = result.plan
        self._last_changes = result.changes
        self._append_assistant(result.assistant_message)
        self.request_input.clear()
        self._refresh_plan_preview()
        self._refresh_changes_preview()
        self.source_label.setText(self._source_text(result.source))
        self._set_status(
            self.lang_manager.get_text("方案草案已更新，请检查变更。", "Draft updated. Review the changes before applying.")
        )
        self.apply_btn.setEnabled(self.draft_plan != self.initial_plan)

    def _on_interpretation_error(self, message: str):
        if self._cancelled:
            return
        self._append_assistant(
            self.lang_manager.get_text(f"未应用：{message}", f"Not applied: {message}")
        )
        self._set_error(message)

    def _on_worker_finished(self):
        if self._cancelled:
            if self._close_when_worker_stops:
                self._close_when_worker_stops = False
                super().reject()
            return
        self._set_busy(False)

    def _set_busy(self, busy: bool):
        self.request_input.setEnabled(not busy)
        self.interpret_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(True)

    def _set_error(self, message: str):
        self.status_label.setObjectName("errorLabel")
        self.status_label.setText(message)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _set_status(self, message: str):
        self.status_label.setObjectName("")
        self.status_label.setText(message)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _refresh_plan_preview(self):
        gm = self.lang_manager.get_text
        plan = self.draft_plan
        lines = [
            f"{gm('数量', 'Count')}: {plan.question_count}",
            f"{gm('整体难度', 'Overall difficulty')}: {plan.difficulty}",
            f"{gm('模板', 'Template')}: {plan.template}",
            f"{gm('知识点', 'Topics')}: {', '.join(plan.selected_topics) or gm('未选择', 'None selected')}",
            "",
            f"{gm('题型权重', 'Question type weights')}:",
            *[f"  {key}: {value}%" for key, value in plan.question_type_weights.items()],
            "",
            f"{gm('难度权重', 'Difficulty weights')}:",
            *[f"  {key}: {value}%" for key, value in plan.difficulty_weights.items()],
        ]
        if plan.topic_weights:
            lines.extend(
                [
                    "",
                    f"{gm('知识点权重', 'Topic weights')}:",
                    *[f"  {key}: {value}%" for key, value in plan.topic_weights.items()],
                ]
            )
        self.plan_preview.setPlainText("\n".join(lines))

    def _refresh_changes_preview(self):
        if not self._last_changes:
            self.changes_preview.setPlainText(
                self.lang_manager.get_text("本轮没有配置变化。", "No configuration changes in this turn.")
            )
            return
        lines = [
            f"{change.field}:\n  {self._format_value(change.before)}\n  → {self._format_value(change.after)}"
            for change in self._last_changes
        ]
        self.changes_preview.setPlainText("\n\n".join(lines))

    @staticmethod
    def _format_value(value: object) -> str:
        if isinstance(value, dict):
            return ", ".join(f"{key}={item}%" for key, item in value.items())
        if isinstance(value, tuple):
            return ", ".join(value) or "—"
        return str(value)

    def _source_text(self, source: str) -> str:
        if source == "llm":
            return self.lang_manager.get_text("来源：远程 LLM（已本地校验）", "Source: remote LLM (locally validated)")
        return self.lang_manager.get_text("来源：本地安全规则", "Source: safe local rules")

    def _append_user(self, text: str):
        label = self.lang_manager.get_text("你", "You")
        self.transcript.append(f"<p><b>{html.escape(label)}</b><br>{html.escape(text)}</p>")

    def _append_assistant(self, text: str):
        label = self.lang_manager.get_text("助手", "Assistant")
        self.transcript.append(f"<p><b>{html.escape(label)}</b><br>{html.escape(text)}</p>")

    def _confirm(self):
        if self.draft_plan == self.initial_plan:
            return
        self.confirmed_plan = self.draft_plan
        self.accept()

    def get_confirmed_plan(self) -> ExamGenerationPlan | None:
        return self.confirmed_plan

    def _on_language_changed(self, _lang):
        gm = self.lang_manager.get_text
        self.setWindowTitle(gm("试卷助手", "Exam Assistant"))
        self.conversation_group.setTitle(gm("需求对话", "Requirements Conversation"))
        self.plan_group.setTitle(gm("当前方案", "Current Plan"))
        self.changes_group.setTitle(gm("本轮变更", "Latest Changes"))
        self.request_input.setPlaceholderText(
            gm("输入新的要求或继续修改当前方案…", "Enter a requirement or refine the current plan…")
        )
        self.interpret_btn.setText(gm("理解要求", "Interpret Request"))
        self.cancel_btn.setText(gm("取消", "Cancel"))
        self.apply_btn.setText(gm("应用配置", "Apply Configuration"))
        self._refresh_plan_preview()
        self._refresh_changes_preview()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self._cancelled = True
            self.worker.requestInterruption()
            if not self.worker.wait(5000):
                self._close_when_worker_stops = True
                self._set_status(
                    self.lang_manager.get_text(
                        "正在取消理解任务…请等待当前请求结束。",
                        "Cancelling interpretation... waiting for the current request to finish.",
                    )
                )
                return
        super().reject()
