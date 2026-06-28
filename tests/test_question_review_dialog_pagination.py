import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from models.question import Question
from ui.dialogs.question_review_dialog import QuestionReviewDialog
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


def make_question(index: int) -> Question:
    return Question.create_new(
        QuestionType.MULTIPLE_CHOICE,
        Difficulty.MEDIUM,
        {
            "zh": {
                "stem": f"问题 {index}",
                "options": ["A", "B"],
                "explanation": "解释",
            },
            "en": {
                "stem": f"Question {index}",
                "options": ["A", "B"],
                "explanation": "Explanation",
            },
        },
        "A",
        "cache",
    )


class QuestionReviewDialogPaginationTests(unittest.TestCase):
    def test_review_dialog_renders_only_current_page_for_large_batches(self):
        questions = [make_question(index) for index in range(25)]

        dialog = QuestionReviewDialog(questions, page_size=10)
        self.addCleanup(dialog.close)

        self.assertEqual(10, dialog.question_list.count())
        self.assertEqual([*range(10)], self._visible_question_indexes(dialog))
        self.assertIn("1 / 3", dialog.page_label.text())
        self.assertFalse(dialog.prev_page_btn.isEnabled())
        self.assertTrue(dialog.next_page_btn.isEnabled())

        dialog.next_page_btn.click()

        self.assertEqual(10, dialog.question_list.count())
        self.assertEqual([*range(10, 20)], self._visible_question_indexes(dialog))
        self.assertEqual(10, dialog._current_index)
        self.assertIn("2 / 3", dialog.page_label.text())
        self.assertTrue(dialog.prev_page_btn.isEnabled())
        self.assertTrue(dialog.next_page_btn.isEnabled())

        dialog.next_page_btn.click()

        self.assertEqual(5, dialog.question_list.count())
        self.assertEqual([*range(20, 25)], self._visible_question_indexes(dialog))
        self.assertIn("3 / 3", dialog.page_label.text())
        self.assertTrue(dialog.prev_page_btn.isEnabled())
        self.assertFalse(dialog.next_page_btn.isEnabled())

    def test_review_dialog_preserves_acceptance_state_across_pages(self):
        questions = [make_question(index) for index in range(12)]
        dialog = QuestionReviewDialog(questions, page_size=5)
        self.addCleanup(dialog.close)

        dialog.next_page_btn.click()
        self.assertEqual(5, dialog._current_index)

        dialog.reject_btn.click()
        self.assertNotIn(5, dialog._accepted)

        dialog.prev_page_btn.click()
        dialog.next_page_btn.click()

        self.assertNotIn(5, dialog._accepted)
        self.assertEqual([question.question_id for question in questions if question is not questions[5]],
                         [question.question_id for question in dialog.get_accepted_questions()])

        dialog.accept_all_btn.click()

        self.assertEqual([question.question_id for question in questions],
                         [question.question_id for question in dialog.get_accepted_questions()])

    def _visible_question_indexes(self, dialog: QuestionReviewDialog) -> list[int]:
        return [
            dialog.question_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(dialog.question_list.count())
        ]


if __name__ == "__main__":
    unittest.main()
