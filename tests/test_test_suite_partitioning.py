import unittest
from pathlib import Path

from tests import conftest
from tests.conftest import _is_qt_test_file


class _CollectionConfig:
    def __init__(self, *, run_copyright: bool):
        self.run_copyright = run_copyright

    def getoption(self, name: str) -> bool:
        if name == "--run-copyright":
            return self.run_copyright
        return False


class TestSuitePartitioningTests(unittest.TestCase):
    def test_explicit_qt_file_markers_are_detected_before_module_import(self):
        tests_dir = Path(__file__).parent

        self.assertTrue(_is_qt_test_file(str(tests_dir / "test_generation_quota.py")))
        self.assertTrue(_is_qt_test_file(str(tests_dir / "test_topic_labels_ui.py")))
        self.assertTrue(
            _is_qt_test_file(
                str(tests_dir / "test_generation_workspace_controller.py")
            )
        )

    def test_pure_counterparts_remain_collectable_without_qt(self):
        tests_dir = Path(__file__).parent

        self.assertFalse(
            _is_qt_test_file(str(tests_dir / "test_generation_core_quota.py"))
        )
        self.assertFalse(_is_qt_test_file(str(tests_dir / "test_topic_labels.py")))

    def test_copyright_workflows_have_a_dedicated_collection_boundary(self):
        tests_dir = Path(__file__).parent
        copyright_test = tests_dir / "test_copyright_submission_preflight.py"

        self.assertIs(
            conftest.pytest_ignore_collect(
                copyright_test,
                _CollectionConfig(run_copyright=False),
            ),
            True,
        )
        self.assertIsNone(
            conftest.pytest_ignore_collect(
                copyright_test,
                _CollectionConfig(run_copyright=True),
            )
        )


if __name__ == "__main__":
    unittest.main()
