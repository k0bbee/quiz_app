"""Application-wide Qt styling and button interaction policy."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QPushButton

from ui.font_scale import apply_font_scale


class _ButtonFocusPolicyFilter(QObject):
    """Keep action buttons keyboard reachable and visibly clickable."""

    _BUTTON_EVENTS = {
        QEvent.Type.Polish,
        QEvent.Type.Show,
        QEvent.Type.DynamicPropertyChange,
        QEvent.Type.EnabledChange,
    }

    def eventFilter(self, watched, event):  # noqa: N802 - Qt method name
        if isinstance(watched, QPushButton) and event.type() in self._BUTTON_EVENTS:
            _apply_button_interaction_policy(watched)
        return super().eventFilter(watched, event)


def _apply_button_interaction_policy(button: QPushButton) -> None:
    """Use consistent focus and cursor affordances for push buttons."""
    button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    cursor = (
        Qt.CursorShape.PointingHandCursor
        if button.isEnabled()
        else Qt.CursorShape.ArrowCursor
    )
    button.setCursor(cursor)


def _install_button_focus_policy(app: QApplication) -> None:
    """Install an app-wide policy for buttons created after startup."""
    if not hasattr(app, "_quiz_button_focus_policy_filter"):
        focus_filter = _ButtonFocusPolicyFilter(app)
        app.installEventFilter(focus_filter)
        app._quiz_button_focus_policy_filter = focus_filter
    for button in app.allWidgets():
        if isinstance(button, QPushButton):
            _apply_button_interaction_policy(button)


def apply_dark_palette(app: QApplication) -> None:
    """Set a dark palette so widgets without QSS backgrounds blend in."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1f1f1f"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#cccccc"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#313131"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#252526"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#cccccc"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#313131"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#cccccc"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#3794ff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#252526"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#cccccc"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#787878"))
    app.setPalette(palette)


def load_stylesheet(app: QApplication, font_scale: str = "medium") -> str:
    """Load and apply the repository QSS stylesheet."""
    qss_path = Path(__file__).resolve().parents[1] / "style.qss"
    app.setStyle("Fusion")
    apply_dark_palette(app)
    _install_button_focus_policy(app)
    try:
        stylesheet = qss_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Warning: Could not load stylesheet: {exc}", file=sys.stderr)
        return ""
    apply_font_scale(app, font_scale, base_stylesheet=stylesheet)
    return stylesheet
