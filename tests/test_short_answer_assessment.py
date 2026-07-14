import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from core.progress_tracker import ProgressManager
from models.question import Question, QuestionBank
from models.question_set import QuestionSet
from ui.dialogs.short_answer_assessment_dialog import ShortAnswerAssessmentDialog
from ui.screens.quiz_screen import QuizScreen
from utils.constants import Difficulty, QuestionType, QuizState


_APP = QApplication.instance() or QApplication([])


def _short_question(question_id: str, stem: str) -> Question:
    return Question(
        question_id=question_id,
        type=QuestionType.SHORT_ANSWER,
        difficulty=Difficulty.MEDIUM,
        bilingual={
            "zh": {"stem": stem, "options": [], "explanation": f"{stem}的详细解析。"},
            "en": {"stem": stem, "options": [], "explanation": f"Explanation for {stem}."},
        },
        correct_answer=f"{stem}的参考答案",
        topic="io",
    )


class ShortAnswerAssessmentTests(unittest.TestCase):
    def test_dialog_requires_each_grade_and_supports_back_navigation(self):
        first = _short_question("short-1", "解释 DMA")
        second = _short_question("short-2", "解释中断")
        dialog = ShortAnswerAssessmentDialog(
            [(first, "回答一"), (second, "回答二")],
            language="zh",
        )

        self.assertIn("1/2", dialog.progress_label.text())
        self.assertFalse(dialog.next_btn.isEnabled())

        dialog.correct_radio.setChecked(True)
        dialog.next_btn.click()
        self.assertIn("2/2", dialog.progress_label.text())
        self.assertIn("解释中断", dialog.stem_label.text())

        dialog.review_radio.setChecked(True)
        dialog.prev_btn.click()
        self.assertTrue(dialog.correct_radio.isChecked())
        dialog.next_btn.click()
        self.assertTrue(dialog.review_radio.isChecked())
        dialog.next_btn.click()

        self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual({"short-1": True, "short-2": False}, dialog.grades())

    def test_practice_short_answer_uses_assessment_before_submission(self):
        question = _short_question("short-practice", "解释轮询")
        qset = QuestionSet.create_new(
            title={"zh": "简答练习", "en": "Short Practice"},
            description={"zh": "", "en": ""},
            topics=["io"],
            question_ids=[question.question_id],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = QuizScreen(
                QuestionBank(str(Path(tmpdir) / "questions")),
                ProgressManager(str(Path(tmpdir) / "progress")),
            )
            screen.start_quiz(qset, [question], show_timer=False, submission_mode="practice")
            screen.answer_area.short_widget.editor.setPlainText("我的轮询解释")

            with patch(
                "ui.screens.quiz_screen.ShortAnswerAssessmentDialog"
            ) as dialog_class:
                dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
                dialog_class.return_value.grades.return_value = {question.question_id: True}
                screen._submit_answer()

            record = screen.session.answers[0]
            self.assertTrue(record.is_correct)
            self.assertEqual("manual_self_assessment", record.grading_method)
            self.assertEqual(QuizState.SHOWING_FEEDBACK, screen.session.state)
            self.assertIn("自评", screen.correct_indicator.text())
            self.assertIn("参考答案", screen.explanation_label.text())

    def test_exam_collects_all_short_answer_grades_before_finalizing(self):
        first = _short_question("short-exam-1", "解释 DMA")
        second = _short_question("short-exam-2", "解释中断")
        qset = QuestionSet.create_new(
            title={"zh": "简答模拟", "en": "Short Exam"},
            description={"zh": "", "en": ""},
            topics=["io"],
            question_ids=[first.question_id, second.question_id],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = QuizScreen(
                QuestionBank(str(Path(tmpdir) / "questions")),
                ProgressManager(str(Path(tmpdir) / "progress")),
            )
            screen.start_quiz(qset, [first, second], show_timer=False, submission_mode="exam")
            screen.session.jump_to(1)
            current = screen.session.current_question
            other = next(
                question for question in screen.session.questions
                if question.question_id != current.question_id
            )
            screen._draft_answers_by_question_id = {other.question_id: "回答一"}
            screen.answer_area.short_widget.editor.setPlainText("回答二")

            with patch(
                "ui.screens.quiz_screen.ShortAnswerAssessmentDialog"
            ) as dialog_class:
                dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
                dialog_class.return_value.grades.return_value = {
                    first.question_id: True,
                    second.question_id: False,
                }
                screen._finish_from_drafts()

            record = screen.session.get_progress_record()
            self.assertEqual(QuizState.COMPLETED, screen.session.state)
            grades_by_id = {
                answer.question_id: answer.is_correct for answer in record.answers
            }
            self.assertEqual({first.question_id: True, second.question_id: False}, grades_by_id)
            self.assertTrue(all(
                answer.grading_method == "manual_self_assessment"
                for answer in record.answers
            ))


if __name__ == "__main__":
    unittest.main()
