import unittest
from pathlib import Path

from tests.conftest import _is_qt_test_file


class TestSuitePartitioningTests(unittest.TestCase):
    def test_explicit_qt_file_markers_are_detected_before_module_import(self):
        tests_dir = Path(__file__).parent

        self.assertTrue(_is_qt_test_file(str(tests_dir / "test_generation_quota.py")))
        self.assertTrue(_is_qt_test_file(str(tests_dir / "test_topic_labels_ui.py")))

    def test_pure_counterparts_remain_collectable_without_qt(self):
        tests_dir = Path(__file__).parent

        self.assertFalse(
            _is_qt_test_file(str(tests_dir / "test_generation_core_quota.py"))
        )
        self.assertFalse(_is_qt_test_file(str(tests_dir / "test_topic_labels.py")))


if __name__ == "__main__":
    unittest.main()
