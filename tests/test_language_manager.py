import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip
from PyQt6.QtWidgets import QApplication

from core.language_manager import LanguageManager


_APP = QApplication.instance() or QApplication([])


class LanguageManagerTests(unittest.TestCase):
    def test_instance_recovers_when_qt_object_was_deleted(self):
        manager = LanguageManager.instance()
        sip.delete(manager)

        recovered = LanguageManager.instance()

        self.assertIsNot(manager, recovered)
        self.assertEqual("zh", recovered.current)


if __name__ == "__main__":
    unittest.main()
