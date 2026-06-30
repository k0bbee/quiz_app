"""Question review card widget for the results screen."""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt

from models.question import Question
from core.language_manager import LanguageManager
from ui.widgets.source_refs import format_source_refs


class QuestionReviewCard(QFrame):
    """Displays a single question result in the review list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        self.lang_manager.language_changed.connect(self._on_language_changed)

        self._index = None
        self._question = None
        self._user_answer = None
        self._is_correct = None

        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self.setObjectName("reviewCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # Top row: status icon + index + correctness
        top = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setFixedWidth(24)
        self.index_label = QLabel()
        self.index_label.setObjectName("reviewIndexLabel")
        self.result_label = QLabel()
        top.addWidget(self.icon_label)
        top.addWidget(self.index_label)
        top.addWidget(self.result_label)
        top.addStretch()
        layout.addLayout(top)

        # Stem
        self.stem_label = QLabel()
        self.stem_label.setWordWrap(True)
        layout.addWidget(self.stem_label)

        # User answer vs correct answer
        self.answer_info = QLabel()
        self.answer_info.setObjectName("reviewAnswerInfo")
        layout.addWidget(self.answer_info)

        # Explanation
        self.explanation_label = QLabel()
        self.explanation_label.setObjectName("reviewExplanation")
        self.explanation_label.setWordWrap(True)
        layout.addWidget(self.explanation_label)

        self.source_label = QLabel()
        self.source_label.setObjectName("reviewSourceRefs")
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)


    def _on_language_changed(self, lang):
        """Re-render card text when language changes."""
        if self._question is not None:
            self._render()

    def set_result(self, index: int, question: Question, user_answer, is_correct: bool, lang: str = None):
        """Populate the card with question result data."""
        self._index = index
        self._question = question
        self._user_answer = user_answer
        self._is_correct = is_correct
        self._render()

    def _render(self):
        """Render all labels using stored data and current language."""
        current_lang = self.lang_manager.current

        # Index
        self.index_label.setText(f"Q{self._index + 1}")

        # Icon + result text
        if self._is_correct:
            self.icon_label.setText("✅")
            self.result_label.setText(self.lang_manager.get_text("正确 ✓", "Correct ✓"))
        else:
            self.icon_label.setText("❌")
            self.result_label.setText(self.lang_manager.get_text("错误 ✗", "Incorrect ✗"))

        # Stem
        self.stem_label.setText(self._question.get_stem(current_lang))

        # Answer info
        correct = self._format_answer(self._question, self._question.correct_answer, current_lang)
        user = self._format_answer(self._question, self._user_answer, current_lang)
        self.answer_info.setText(
            self.lang_manager.get_text(
                "你的答案: {}  |  正确答案: {}",
                "Your answer: {}  |  Correct: {}"
            ).format(user, correct)
        )

        # Explanation
        self.explanation_label.setText(self.lang_manager.get_text(
            "💡 解析: {}",
            "💡 Explanation: {}"
        ).format(self._question.get_explanation(current_lang)))
        self.source_label.setText(format_source_refs(
            (self._question.metadata or {}).get("source_refs", []),
            label=self.lang_manager.get_text("来源", "Source Evidence"),
        ))
        self.source_label.setVisible(bool(self.source_label.text()))

    def _format_answer(self, question: Question, answer, lang: str) -> str:
        """Render answer letters with their option text when possible."""
        if answer is None or answer == "":
            return self.lang_manager.get_text("(空)", "(empty)")
        if isinstance(answer, list):
            return " → ".join(str(x) for x in answer)

        answer_text = str(answer)
        options = question.get_options(lang)
        if len(answer_text) == 1 and answer_text.isalpha() and options:
            idx = ord(answer_text.upper()) - ord("A")
            if 0 <= idx < len(options):
                return options[idx]
        return answer_text
