"""Consistent page title and optional supporting text."""

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PageHeader(QWidget):
    """Render the shared title hierarchy used at the top of workspaces."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("pageHeader")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("screenTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("screenSubtitle")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)
        self.set_subtitle(subtitle)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        text = subtitle.strip()
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))
