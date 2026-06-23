"""Entry point for the Course Quiz Studio application."""

import sys
import os

# Ensure the quiz_app directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor

from config import APP_NAME
from ui.main_window import MainWindow


def _apply_dark_palette(app: QApplication):
    """Set a dark palette so widgets without QSS backgrounds blend in."""
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#1f1f1f"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#cccccc"))
    p.setColor(QPalette.ColorRole.Base, QColor("#313131"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#252526"))
    p.setColor(QPalette.ColorRole.Text, QColor("#cccccc"))
    p.setColor(QPalette.ColorRole.Button, QColor("#313131"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#cccccc"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Link, QColor("#3794ff"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#252526"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#cccccc"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#787878"))
    app.setPalette(p)


def load_stylesheet(app: QApplication) -> str:
    """Load and apply the QSS stylesheet from file."""
    qss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")
    app.setStyle("Fusion")
    _apply_dark_palette(app)
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            stylesheet = f.read()
    except (FileNotFoundError, OSError) as e:
        print(f"Warning: Could not load stylesheet: {e}", file=sys.stderr)
        return
    app.setStyleSheet(stylesheet)


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("Course Quiz Studio")
    app.setApplicationName(APP_NAME)

    load_stylesheet(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
