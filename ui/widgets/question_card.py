"""Question card widget — displays the question stem as rich text."""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel


class QuestionCard(QFrame):
    """Displays the question stem with rich text support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setObjectName("questionCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Type indicator
        self.type_label = QLabel()
        self.type_label.setObjectName("questionTypeLabel")

        # Stem
        self.stem_label = QLabel()
        self.stem_label.setWordWrap(True)
        self.stem_label.setObjectName("questionStem")

        layout.addWidget(self.type_label)
        layout.addWidget(self.stem_label)

    def set_question(self, stem: str, qtype_label: str = ""):
        """Display the question stem text."""
        self.stem_label.setText(stem)
        if qtype_label:
            self.type_label.setText(qtype_label)
        else:
            self.type_label.clear()

    def clear(self):
        self.stem_label.clear()
        self.type_label.clear()
