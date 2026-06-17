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
    p.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#cdd6f4"))
    p.setColor(QPalette.ColorRole.Base, QColor("#313244"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#181825"))
    p.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
    p.setColor(QPalette.ColorRole.Button, QColor("#313244"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#cdd6f4"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#89b4fa"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#1e1e2e"))
    p.setColor(QPalette.ColorRole.Link, QColor("#89b4fa"))
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
