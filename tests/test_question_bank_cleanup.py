import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.progress_tracker import ProgressManager
from core.question_bank_maintenance import remove_question_from_sets
from models.progress import ProgressRecord
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from ui.screens.question_bank_screen import QuestionBankScreen
from utils.json_io import read_json
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class QuestionBankCleanupTests(unittest.TestCase):
    def _question(self, qid: str, topic: str = "cache") -> Question:
        return Question(
            question_id=qid,
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": f"{topic} question",
                    "options": ["A. one", "B. two", "C. three", "D. four"],
                    "explanation": "A valid explanation with enough detail.",
                },
                "en": {
                    "stem": f"{topic} question",
                    "options": ["A. one", "B. two", "C. three", "D. four"],
                    "explanation": "A valid explanation with enough detail.",
                },
            },
            correct_answer="A",
            topic=topic,
        )

    def _set(self, set_id: str, question_ids: list[str]) -> QuestionSet:
        return QuestionSet(
            set_id=set_id,
            title={"zh": set_id, "en": set_id},
            description={"zh": "", "en": ""},
            topics=["cache"],
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=20,
            questions=question_ids,
        )

    def test_remove_question_from_sets_prunes_stale_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            manager.save(self._set("set-a", ["q1", "q2"]))
            manager.save(self._set("set-b", ["q1"]))
            manager.save(self._set("set-c", ["q3"]))

            changed = remove_question_from_sets(manager, "q1")

            self.assertEqual(2, changed)
            self.assertEqual(["q2"], manager.get("set-a").questions)
            self.assertEqual([], manager.get("set-b").questions)
            self.assertEqual(["q3"], manager.get("set-c").questions)
            self.assertEqual("question_deleted", manager.get("set-a").metadata["source"])
            self.assertIn("updated_at", manager.get("set-a").metadata)

    def test_question_bank_search_reuses_loaded_questions_until_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save_many([self._question("q1"), self._question("q2")])

            with patch("models.question.read_json", wraps=read_json) as read:
                first_page, first_total = question_bank.search(query="cache", limit=1)
                reads_after_first_search = read.call_count
                second_page, second_total = question_bank.search(query="cache", limit=1)

                self.assertEqual(2, first_total)
                self.assertEqual(2, second_total)
                self.assertEqual([q.question_id for q in first_page], [q.question_id for q in second_page])
                self.assertEqual(reads_after_first_search, read.call_count)

                question_bank.save(self._question("q3"))
                _page, updated_total = question_bank.search(query="cache", limit=5)

                self.assertEqual(3, updated_total)
                self.assertGreater(read.call_count, reads_after_first_search)

    def test_question_and_set_save_reject_path_traversal_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            question_bank = QuestionBank(str(root / "questions"))
            unsafe_question = self._question("../outside")

            with self.assertRaises(ValueError):
                question_bank.save(unsafe_question)

            self.assertFalse((root / "outside.json").exists())

            set_manager = SetManager(str(root / "sets"))
            unsafe_set = self._set("../outside-set", ["q1"])

            with self.assertRaises(ValueError):
                set_manager.save(unsafe_set)

            self.assertFalse((root / "outside-set.json").exists())

    def test_progress_save_rejects_path_traversal_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = ProgressManager(str(root / "progress"))
            record = ProgressRecord.create_new("set-a")
            record.progress_id = "../outside-progress"

            with self.assertRaises(ValueError):
                manager.save(record)

            self.assertFalse((root / "outside-progress.json").exists())

    def test_question_bank_screen_delete_prunes_question_sets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            q1 = self._question("q1")
            q2 = self._question("q2")
            question_bank.save_many([q1, q2])
            qset = self._set("set-a", ["q1", "q2"])
            set_manager.save(qset)

            screen = QuestionBankScreen(question_bank, set_manager=set_manager)
            screen.refresh()
            for row in range(screen.question_list.count()):
                item = screen.question_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == "q1":
                    screen.question_list.setCurrentRow(row)
                    break

            with patch("ui.screens.question_bank_screen.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                screen.delete_btn.click()

            self.assertIsNone(question_bank.get("q1"))
            self.assertEqual(["q2"], set_manager.get(qset.set_id).questions)


if __name__ == "__main__":
    unittest.main()
