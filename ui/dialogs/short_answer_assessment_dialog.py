"""Focused self-assessment flow for one or more short-answer responses."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from core.language_manager import LanguageManager


class ShortAnswerAssessmentDialog(QDialog):
    """Collect an explicit correct/review decision for every short answer."""

    def __init__(self, items, language: str = "zh", parent=None):
        super().__init__(parent)
        self._items = list(items or [])
        if not self._items:
            raise ValueError("short-answer assessment requires at least one response")
        self._language = "zh" if language == "zh" else "en"
        self._index = 0
        self._grades: dict[str, bool] = {}
        self.lang_manager = LanguageManager.instance()
        self._setup_ui()
        self._show_current()

    def _text(self, zh: str, en: str) -> str:
        return zh if self._language == "zh" else en

    def _setup_ui(self) -> None:
        self.setWindowTitle(self._text("简答题自评", "Short Answer Self-Assessment"))
        self.setMinimumSize(680, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("assessmentProgressLabel")
        layout.addWidget(self.progress_label)

        guidance = QLabel(self._text(
            "请对照参考答案和解析自行确认。此结果将计入进度统计。",
            "Compare your response with the reference and explanation. Your choice will count toward progress.",
        ))
        guidance.setObjectName("mutedLabel")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)

        self.stem_label = QLabel()
        self.stem_label.setObjectName("assessmentStemLabel")
        self.stem_label.setWordWrap(True)
        layout.addWidget(self.stem_label)

        self.user_answer_label = QLabel()
        layout.addWidget(self.user_answer_label)
        self.user_answer_view = QPlainTextEdit()
        self.user_answer_view.setReadOnly(True)
        self.user_answer_view.setMaximumHeight(110)
        layout.addWidget(self.user_answer_view)

        self.reference_label = QLabel()
        layout.addWidget(self.reference_label)
        self.reference_view = QPlainTextEdit()
        self.reference_view.setReadOnly(True)
        self.reference_view.setMaximumHeight(110)
        layout.addWidget(self.reference_view)

        self.explanation_label = QLabel()
        layout.addWidget(self.explanation_label)
        self.explanation_view = QPlainTextEdit()
        self.explanation_view.setReadOnly(True)
        self.explanation_view.setMaximumHeight(110)
        layout.addWidget(self.explanation_view)

        self.correct_radio = QRadioButton(self._text(
            "回答基本正确",
            "My answer is substantially correct",
        ))
        self.review_radio = QRadioButton(self._text(
            "仍需复习",
            "I still need to review this",
        ))
        self.grade_group = QButtonGroup(self)
        self.grade_group.addButton(self.correct_radio)
        self.grade_group.addButton(self.review_radio)
        self.correct_radio.toggled.connect(
            lambda checked: self._record_grade(True) if checked else None
        )
        self.review_radio.toggled.connect(
            lambda checked: self._record_grade(False) if checked else None
        )
        layout.addWidget(self.correct_radio)
        layout.addWidget(self.review_radio)

        footer = QHBoxLayout()
        self.cancel_btn = QPushButton(self._text("返回答题", "Return to Answers"))
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)
        footer.addStretch()
        self.prev_btn = QPushButton(self._text("上一题", "Previous"))
        self.prev_btn.setObjectName("secondaryButton")
        self.prev_btn.clicked.connect(self._previous)
        footer.addWidget(self.prev_btn)
        self.next_btn = QPushButton()
        self.next_btn.setObjectName("primaryButton")
        self.next_btn.clicked.connect(self._next_or_finish)
        footer.addWidget(self.next_btn)
        layout.addLayout(footer)

    def _show_current(self) -> None:
        question, answer = self._items[self._index]
        total = len(self._items)
        self.progress_label.setText(self._text(
            f"简答题自评 {self._index + 1}/{total}",
            f"Short answer {self._index + 1}/{total}",
        ))
        self.stem_label.setText(question.get_stem(self._language))
        self.user_answer_label.setText(self._text("你的答案", "Your Answer"))
        self.user_answer_view.setPlainText(str(answer or ""))
        self.reference_label.setText(self._text("AI 参考答案", "AI Reference Answer"))
        self.reference_view.setPlainText(str(question.correct_answer or ""))
        self.explanation_label.setText(self._text("解析", "Explanation"))
        self.explanation_view.setPlainText(question.get_explanation(self._language))

        question_id = question.question_id
        self.grade_group.setExclusive(False)
        self.correct_radio.setChecked(self._grades.get(question_id) is True)
        self.review_radio.setChecked(
            question_id in self._grades and self._grades[question_id] is False
        )
        self.grade_group.setExclusive(True)
        self.prev_btn.setEnabled(self._index > 0)
        self.next_btn.setText(self._text(
            "完成自评" if self._index == total - 1 else "下一题",
            "Finish" if self._index == total - 1 else "Next",
        ))
        self.next_btn.setEnabled(question_id in self._grades)

    def _record_grade(self, is_correct: bool) -> None:
        question, _answer = self._items[self._index]
        self._grades[question.question_id] = is_correct
        self.next_btn.setEnabled(True)

    def _previous(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._show_current()

    def _next_or_finish(self) -> None:
        question, _answer = self._items[self._index]
        if question.question_id not in self._grades:
            return
        if self._index < len(self._items) - 1:
            self._index += 1
            self._show_current()
            return
        if len(self._grades) == len(self._items):
            self.accept()

    def grades(self) -> dict[str, bool]:
        return dict(self._grades)
