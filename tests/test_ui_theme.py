import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication

from main import _apply_dark_palette


_APP = QApplication.instance() or QApplication([])


class UiThemeTests(unittest.TestCase):
    def test_qss_uses_vscode_dark_tokens_and_top_level_backgrounds(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()

        for token in (
            "#181818", "#1f1f1f", "#252526", "#313131",
            "#0078d4", "#007fd4", "#cccccc",
        ):
            self.assertIn(token, qss)
        self.assertRegex(qss, r"qdialog[^\{]*\{[^}]*background-color:\s*#1f1f1f")
        self.assertIn("qpushbutton#primarybutton", qss)

    def test_default_button_is_secondary_instead_of_primary_blue(self):
        qss = Path("style.qss").read_text(encoding="utf-8").lower()
        match = re.search(r"qpushbutton\s*\{(?P<body>[^}]*)\}", qss, flags=re.DOTALL)

        self.assertIsNotNone(match)
        default_rule = match.group("body")
        self.assertIn("#313131", default_rule)
        self.assertNotIn("#0078d4", default_rule)

    def test_fallback_palette_matches_vscode_dark_base(self):
        _apply_dark_palette(_APP)
        palette = _APP.palette()

        self.assertEqual("#1f1f1f", palette.color(QPalette.ColorRole.Window).name())
        self.assertEqual("#cccccc", palette.color(QPalette.ColorRole.WindowText).name())
        self.assertEqual("#313131", palette.color(QPalette.ColorRole.Base).name())
        self.assertEqual("#0078d4", palette.color(QPalette.ColorRole.Highlight).name())


if __name__ == "__main__":
    unittest.main()
