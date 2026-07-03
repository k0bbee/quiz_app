import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from models.course_project import CourseTopic
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

    def test_review_dialog_displays_topic_title_not_internal_id(self):
        topic = CourseTopic(topic_id="interrupt_io", title="Interrupt-driven I/O")
        question = make_question(1)
        question.topic = topic

        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        details = dialog.detail_editor.toPlainText()
        self.assertIn("Topic: Interrupt-driven I/O", details)
        self.assertNotIn("Topic: interrupt_io", details)

    def test_review_dialog_displays_source_refs_for_generated_question(self):
        question = make_question(1)
        question.metadata["source_refs"] = [
            {
                "chunk_id": "source-0007",
                "source_file": "第21讲 Cache.pdf",
                "page_or_slide": 8,
                "heading": "Cache Address Breakdown",
            }
        ]

        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        details = dialog.detail_editor.toPlainText()
        self.assertIn("Source Evidence", details)
        self.assertIn("第21讲 Cache.pdf", details)
        self.assertIn("page 8", details.lower())
        self.assertIn("source-0007", details)
        self.assertIn("Cache Address Breakdown", details)

    def test_review_dialog_requires_manual_acceptance_for_low_confidence_questions(self):
        good = make_question(1)
        good.metadata["source_ref_status"] = "valid_model_ref"
        good.metadata["plan_match_status"] = "matched_by_plan_id"
        invalid_source = make_question(2)
        invalid_source.metadata["source_ref_status"] = "invalid_model_ref"
        shape_match = make_question(3)
        shape_match.metadata["plan_match_status"] = "matched_by_shape"
        missing_explanation = make_question(4)
        missing_explanation.bilingual["zh"]["explanation"] = ""
        missing_explanation.bilingual["en"]["explanation"] = ""

        dialog = QuestionReviewDialog(
            [good, invalid_source, shape_match, missing_explanation],
            page_size=10,
        )
        self.addCleanup(dialog.close)

        self.assertEqual({0}, dialog._accepted)
        self.assertEqual([good.question_id], [question.question_id for question in dialog.get_accepted_questions()])
        self.assertIn("⚠", dialog.question_list.item(1).text())
        self.assertIn("⚠", dialog.question_list.item(2).text())
        self.assertIn("⚠", dialog.question_list.item(3).text())

        dialog.question_list.setCurrentRow(1)
        details = dialog.detail_editor.toPlainText()
        self.assertIn("Review Warnings", details)
        self.assertIn("source", details.lower())

    def test_review_dialog_can_edit_current_question_before_accepting(self):
        question = make_question(1)
        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        dialog.zh_stem_editor.setPlainText("修改后的中文题干")
        dialog.en_stem_editor.setPlainText("Edited English stem")
        dialog.zh_options_editor.setPlainText("A. 正确项\nB. 干扰项\nC. 新干扰项")
        dialog.en_options_editor.setPlainText("A. Correct\nB. Distractor\nC. New distractor")
        dialog.correct_answer_editor.setText("C")
        dialog.zh_explanation_editor.setPlainText("修改后的中文解析")
        dialog.en_explanation_editor.setPlainText("Edited English explanation")

        dialog.apply_edit_btn.click()

        accepted = dialog.get_accepted_questions()
        self.assertEqual(1, len(accepted))
        edited = accepted[0]
        self.assertEqual("修改后的中文题干", edited.get_stem("zh"))
        self.assertEqual("Edited English stem", edited.get_stem("en"))
        self.assertEqual(["A. 正确项", "B. 干扰项", "C. 新干扰项"], edited.get_options("zh"))
        self.assertEqual(["A. Correct", "B. Distractor", "C. New distractor"], edited.get_options("en"))
        self.assertEqual("C", edited.correct_answer)
        self.assertEqual("修改后的中文解析", edited.get_explanation("zh"))
        self.assertEqual("Edited English explanation", edited.get_explanation("en"))
        self.assertIn("修改后的中文题干", dialog.question_list.item(0).text())

    def _visible_question_indexes(self, dialog: QuestionReviewDialog) -> list[int]:
        return [
            dialog.question_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(dialog.question_list.count())
        ]


if __name__ == "__main__":
    unittest.main()
