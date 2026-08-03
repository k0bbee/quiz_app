import unittest
from types import SimpleNamespace

from core.session_retry import session_retry_question_ids


class SessionRetrySelectionTests(unittest.TestCase):
    def test_incorrect_excludes_skipped_and_deduplicates_stably(self):
        record = SimpleNamespace(
            answers=[
                SimpleNamespace(question_id="skip", skipped=True, is_correct=False),
                SimpleNamespace(question_id="wrong", skipped=False, is_correct=False),
                SimpleNamespace(question_id="wrong", skipped=False, is_correct=False),
                SimpleNamespace(question_id="right", skipped=False, is_correct=True),
            ]
        )

        selected = session_retry_question_ids(record)

        self.assertEqual(("wrong",), selected)


if __name__ == "__main__":
    unittest.main()
