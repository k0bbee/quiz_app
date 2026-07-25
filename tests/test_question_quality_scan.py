import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.background_task import BackgroundTaskCancelled, TaskControl
from core.question_quality_scan import scan_question_bank_quality
from models.question import Question, QuestionBank
from utils.constants import Difficulty, QuestionType


def question(question_id: str, *, course_id: str = "course-a") -> Question:
    return Question(
        question_id=question_id,
        type=QuestionType.MULTIPLE_CHOICE,
        difficulty=Difficulty.MEDIUM,
        bilingual={
            "zh": {
                "stem": "供给与需求如何决定均衡价格？",
                "options": ["A. 市场互动", "B. 随机", "C. 固定", "D. 无关"],
                "explanation": "供给曲线与需求曲线的交点决定市场均衡。",
            },
            "en": {
                "stem": "How do supply and demand determine equilibrium price?",
                "options": ["A. Market interaction", "B. Randomly", "C. Fixed", "D. Unrelated"],
                "explanation": "The intersection of supply and demand determines equilibrium.",
            },
        },
        correct_answer="A",
        topic="market_equilibrium",
        metadata={"course_id": course_id},
    )


class QuestionQualityScanTests(unittest.TestCase):
    def test_scan_combines_structural_shared_and_stored_quality_issues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            clean = question("clean")
            source_warning = question("source-warning")
            source_warning.metadata["source_ref_status"] = "missing"
            stored_warning = question("stored-warning")
            stored_warning.metadata["quality_warnings"] = ["legacy warning"]
            invalid = question("invalid")
            invalid.correct_answer = "Z"
            invalid.bilingual["zh"]["explanation"] = ""
            bank.save_many([clean, source_warning, stored_warning, invalid])
            progress = []

            report = scan_question_bank_quality(
                bank,
                course_id="course-a",
                task=TaskControl(progress.append),
            )

        self.assertEqual(4, report.scanned_count)
        self.assertEqual(3, report.issue_question_count)
        self.assertEqual(
            {"source-warning", "stored-warning", "invalid"},
            set(report.issue_question_ids),
        )
        self.assertIn("source_invalid", report.result_for("source-warning").issue_codes)
        self.assertIn("stored_quality_warning", report.result_for("stored-warning").issue_codes)
        self.assertTrue(report.result_for("invalid").structural_errors)
        self.assertFalse(report.result_for("clean").has_issues)
        self.assertEqual("validated", progress[-1].stage)
        self.assertEqual((4, 4), (progress[-2].current, progress[-2].total))

    def test_scan_respects_course_scope_and_cancels_between_questions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            bank.save_many([
                question("a-1", course_id="course-a"),
                question("a-2", course_id="course-a"),
                question("b-1", course_id="course-b"),
            ])
            progress = []
            task = TaskControl(
                lambda item: (
                    progress.append(item),
                    task.cancel()
                    if item.stage == "validating_question" and item.current == 1
                    else None,
                )
            )

            with self.assertRaises(BackgroundTaskCancelled):
                scan_question_bank_quality(bank, course_id="course-a", task=task)

        validating = [item for item in progress if item.stage == "validating_question"]
        self.assertEqual(1, validating[-1].current)
        self.assertEqual(3, validating[-1].total)
        self.assertNotIn("b-1", [item.detail for item in validating])

    def test_scan_streams_question_files_without_double_bank_lookup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            bank.save_many([question("q1"), question("q2")])
            bank.question_ids = Mock(side_effect=AssertionError("must not pre-read every JSON"))
            bank.get = Mock(side_effect=AssertionError("must not read each JSON twice"))

            report = scan_question_bank_quality(bank, course_id="course-a")

        self.assertEqual(2, report.scanned_count)
        bank.question_ids.assert_not_called()
        bank.get.assert_not_called()

    def test_scan_batches_progress_events_but_keeps_final_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            bank.save_many([question(f"q-{index:03d}") for index in range(26)])
            progress = []

            report = scan_question_bank_quality(bank, task=TaskControl(progress.append))

        validating = [item for item in progress if item.stage == "validating_question"]
        self.assertEqual(26, report.scanned_count)
        self.assertEqual(
            [(1, 26), (25, 26), (26, 26)],
            [(item.current, item.total) for item in validating],
        )


if __name__ == "__main__":
    unittest.main()
