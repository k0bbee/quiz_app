import unittest
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.qt

from ui.history_protection_controller import HistoryProtectionController


class HistoryProtectionControllerTests(unittest.TestCase):
    def test_message_reports_failed_records_and_bounded_error_details(self):
        report = SimpleNamespace(
            failed_progress_ids=("one", "two"),
            errors=("first", "second", "third", "fourth"),
        )
        host = SimpleNamespace(
            startup_migration_report=report,
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text
            ),
        )

        message = HistoryProtectionController(host).message()

        self.assertIn("2 条旧练习记录", message)
        self.assertIn("first", message)
        self.assertIn("third", message)
        self.assertNotIn("fourth", message)


if __name__ == "__main__":
    unittest.main()
