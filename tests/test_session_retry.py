import unittest
from types import SimpleNamespace

from core.session_retry import SessionRetryMode, session_retry_question_ids


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

        selected = session_retry_question_ids(record, SessionRetryMode.INCORRECT)

        self.assertEqual(("wrong",), selected)

    def test_unsure_excludes_skipped_even_when_confidence_is_unsure(self):
        record = SimpleNamespace(
            answers=[
                SimpleNamespace(question_id="skip", skipped=True, confidence="unsure"),
                SimpleNamespace(question_id="unsure", skipped=False, confidence="unsure"),
                SimpleNamespace(question_id="sure", skipped=False, confidence="sure"),
            ]
        )

        selected = session_retry_question_ids(record, SessionRetryMode.UNSURE)

        self.assertEqual(("unsure",), selected)

    def test_review_preserves_mark_order_and_ignores_empty_ids(self):
        record = SimpleNamespace(
            marked_review_question_ids=["q2", "", "q1", "q2"]
        )

        selected = session_retry_question_ids(record, SessionRetryMode.REVIEW)

        self.assertEqual(("q2", "q1"), selected)

    def test_unknown_retry_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported session retry mode"):
            session_retry_question_ids(SimpleNamespace(), "unknown")


if __name__ == "__main__":
    unittest.main()
