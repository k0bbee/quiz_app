"""Inline, non-blocking course consolidation Q&A workspace."""

from __future__ import annotations

import html
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ai.course_qa import CourseQAError, CourseQAResponse, CourseQATurn
from core.app_errors import AppError, format_app_error
from core.language_manager import LanguageManager
from ui.widgets.source_refs import format_source_refs


class CourseQAInput(QPlainTextEdit):
    submitted = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _CourseQARequest(QObject):
    succeeded = pyqtSignal(object, int)
    failed = pyqtSignal(object, int)

    def __init__(self, service, question, history, language, token):
        super().__init__()
        self.service = service
        self.question = question
        self.history = list(history)
        self.language = language
        self.token = token
        self._cancelled = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled.set()

    def _run(self) -> None:
        try:
            response = self.service.ask(
                self.question,
                history=self.history,
                language=self.language,
            )
        except Exception as exc:
            if not self._cancelled.is_set():
                self.failed.emit(exc, self.token)
            return
        if not self._cancelled.is_set():
            self.succeeded.emit(response, self.token)


class CourseQAPanel(QWidget):
    """A course-scoped conversation panel that never blocks the Qt event loop."""

    def __init__(self, service_factory, parent=None):
        super().__init__(parent)
        self.service_factory = service_factory
        self.lang_manager = LanguageManager.instance()
        self.course = None
        self._history_by_course: dict[str, list[CourseQATurn]] = {}
        self._active_request: _CourseQARequest | None = None
        self._request_token = 0
        self._setup_ui()
        self.retranslate()

    @property
    def turns(self) -> list[CourseQATurn]:
        if self.course is None:
            return []
        return self._history_by_course.setdefault(self.course.course_id, [])

    @property
    def is_busy(self) -> bool:
        return self._active_request is not None

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("courseQATranscript")
        self.transcript.setOpenExternalLinks(False)
        layout.addWidget(self.transcript, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("courseQAStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.input = CourseQAInput()
        self.input.setObjectName("courseQAInput")
        self.input.setMaximumHeight(96)
        self.input.submitted.connect(self._send_question)
        layout.addWidget(self.input)

        actions = QHBoxLayout()
        self.clear_btn = QPushButton()
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.clicked.connect(self.clear_history)
        actions.addWidget(self.clear_btn)
        actions.addStretch(1)
        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("secondaryButton")
        self.stop_btn.clicked.connect(self.stop_request)
        actions.addWidget(self.stop_btn)
        self.send_btn = QPushButton()
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.clicked.connect(self._send_question)
        actions.addWidget(self.send_btn)
        layout.addLayout(actions)

    def set_course(self, course) -> None:
        if self.course is not None and course is not None and self.course.course_id == course.course_id:
            self.course = course
            self._render_transcript()
            if not self.is_busy:
                self._set_idle_state()
            return
        self.stop_request(show_status=False)
        self.course = course
        if course is not None:
            self._history_by_course.setdefault(course.course_id, [])
        self._render_transcript()
        self._set_idle_state()

    def retranslate(self) -> None:
        gm = self.lang_manager.get_text
        self.input.setPlaceholderText(gm(
            "基于当前考试范围提问。Enter 发送，Shift+Enter 换行。",
            "Ask from the current exam scope. Enter to send; Shift+Enter for a new line.",
        ))
        self.input.setAccessibleName(gm("问答问题输入", "Course question input"))
        self.clear_btn.setText(gm("清空对话", "Clear"))
        self.stop_btn.setText(gm("停止", "Stop"))
        self.send_btn.setText(gm("发送", "Send"))
        self.transcript.setAccessibleName(gm("问答对话记录", "Course Q&A transcript"))
        self._render_transcript()
        if not self.is_busy:
            self._set_idle_state()

    def clear_history(self) -> None:
        if self.course is None or self.is_busy:
            return
        self._history_by_course[self.course.course_id] = []
        self._render_transcript()
        self._set_idle_state()

    def stop_request(self, *, show_status: bool = True) -> None:
        request = self._active_request
        if request is None:
            return
        self._request_token += 1
        request.cancel()
        self._active_request = None
        self._set_busy(False)
        if show_status:
            self.status_label.setText(self.lang_manager.get_text(
                "已停止本次回答，已输入的问题仍保留在对话中。",
                "This response was stopped. Your question remains in the conversation.",
            ))

    def _send_question(self) -> None:
        if self.course is None or self.is_busy:
            return
        question = self.input.toPlainText().strip()
        if not question:
            self.status_label.setText(self.lang_manager.get_text("请先输入问题。", "Enter a question first."))
            return
        try:
            service = self.service_factory(self.course)
        except CourseQAError as exc:
            self._show_error(exc.error)
            return
        except Exception as exc:
            self._show_error(_unexpected_error(exc))
            return

        history = list(self.turns)
        self.turns.append(CourseQATurn("user", question))
        self.input.clear()
        self._render_transcript()
        self._request_token += 1
        token = self._request_token
        request = _CourseQARequest(
            service,
            question,
            history,
            self.lang_manager.current,
            token,
        )
        request.succeeded.connect(self._on_response)
        request.failed.connect(self._on_failure)
        self._active_request = request
        self._set_busy(True)
        request.start()

    def _on_response(self, response, token: int) -> None:
        if token != self._request_token or self._active_request is None:
            return
        self._active_request = None
        if not isinstance(response, CourseQAResponse):
            self._show_error(_unexpected_error(TypeError("invalid course Q&A response")))
            self._set_busy(False)
            return
        self.turns.append(CourseQATurn("assistant", response.answer, response.source_refs))
        self._render_transcript()
        self._set_busy(False)
        self._set_idle_state()

    def _on_failure(self, error, token: int) -> None:
        if token != self._request_token or self._active_request is None:
            return
        failed_question = self._active_request.question
        self._active_request = None
        if self.turns and self.turns[-1].role == "user" and self.turns[-1].content == failed_question:
            self.turns.pop()
        if not self.input.toPlainText().strip():
            self.input.setPlainText(failed_question)
        self._render_transcript()
        app_error = error.error if isinstance(error, CourseQAError) else _unexpected_error(error)
        self._show_error(app_error)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.input.setEnabled(not busy and self.course is not None)
        self.send_btn.setEnabled(not busy and self.course is not None)
        self.clear_btn.setEnabled(not busy and bool(self.turns))
        self.stop_btn.setVisible(busy)
        if busy:
            self.status_label.setText(self.lang_manager.get_text(
                "正在依据课程资料整理回答…",
                "Building an answer from course materials…",
            ))

    def _set_idle_state(self) -> None:
        enabled = self.course is not None
        self.input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled and bool(self.turns))
        self.stop_btn.setVisible(False)
        if self.course is None:
            self.status_label.setText(self.lang_manager.get_text(
                "请先选择课程。", "Select a course first."
            ))
        elif not self.turns:
            self.status_label.setText(self.lang_manager.get_text(
                "回答仅使用当前考试范围内的课程总结和原始资料。",
                "Answers use only the course summary and sources inside the current exam scope.",
            ))
        elif not self.status_label.text().startswith(("已停止", "This response")):
            self.status_label.clear()

    def _show_error(self, error: AppError) -> None:
        self.status_label.setText(format_app_error(
            error,
            self.lang_manager.current,
            include_detail=False,
        ))

    def _render_transcript(self) -> None:
        if not self.turns:
            self.transcript.clear()
            return
        gm = self.lang_manager.get_text
        blocks = []
        for turn in self.turns:
            role = gm("你", "You") if turn.role == "user" else gm("助教", "Tutor")
            content = html.escape(turn.content).replace("\n", "<br>")
            source_text = ""
            if turn.source_refs:
                formatted = format_source_refs(
                    list(turn.source_refs),
                    language=self.lang_manager.current,
                )
                source_text = f"<div><small>{html.escape(formatted).replace(chr(10), '<br>')}</small></div>"
            blocks.append(f"<div><b>{role}</b><p>{content}</p>{source_text}</div><hr>")
        self.transcript.setHtml("".join(blocks))
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


def _unexpected_error(error) -> AppError:
    detail = str(error or "Unexpected course Q&A error")
    return AppError(
        code="QA-UI-001",
        severity="error",
        title_zh="问答请求失败",
        title_en="Q&A Request Failed",
        message_zh="本次问答未能完成。",
        message_en="The Q&A request could not be completed.",
        action_zh="请稍后重试；若持续失败，请检查 AI 设置。",
        action_en="Try again later; if it keeps failing, check AI settings.",
        technical_detail=detail,
    )
