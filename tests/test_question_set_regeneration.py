import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.question_set_regenerator import (
    apply_regenerated_questions,
    persist_new_question_set,
    persist_regenerated_question_set,
)
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from utils.constants import Difficulty, QuestionType


class QuestionSetRegenerationTests(unittest.TestCase):
    def _question(self, qid: str, topic: str) -> Question:
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

    def test_apply_regenerated_questions_replaces_ids_and_updates_metadata(self):
        qset = QuestionSet(
            set_id="set-review",
            title={"zh": "复习", "en": "Review"},
            description={"zh": "", "en": ""},
            topics=["old"],
            difficulty=Difficulty.EASY,
            estimated_minutes=10,
            questions=["old1", "old2"],
            metadata={"created_at": "2026-06-18T00:00:00+00:00", "source": "ai_generated"},
        )
        new_questions = [self._question("new1", "cache"), self._question("new2", "process")]

        updated = apply_regenerated_questions(qset, new_questions, difficulty=Difficulty.HARD)

        self.assertIs(updated, qset)
        self.assertEqual("set-review", updated.set_id)
        self.assertEqual(["new1", "new2"], updated.questions)
        self.assertEqual(["cache", "process"], updated.topics)
        self.assertEqual(Difficulty.HARD, updated.difficulty)
        self.assertEqual(4, updated.estimated_minutes)
        self.assertEqual("2026-06-18T00:00:00+00:00", updated.metadata["created_at"])
        self.assertEqual("ai_regenerated", updated.metadata["source"])
        self.assertIn("updated_at", updated.metadata)
        self.assertIn("regenerated_at", updated.metadata)

    def test_apply_regenerated_questions_updates_source_course_metadata(self):
        qset = QuestionSet(
            set_id="set-review",
            title={"zh": "复习", "en": "Review"},
            description={"zh": "", "en": ""},
            topics=["old"],
            difficulty=Difficulty.EASY,
            estimated_minutes=10,
            questions=["old1"],
            metadata={
                "course_id": "old-course",
                "course_title": "Old Course",
                "source": "ai_generated",
            },
        )
        course = SimpleNamespace(
            course_id="course-new",
            title="New Course",
            updated_at="2026-06-18T12:00:00+00:00",
        )

        updated = apply_regenerated_questions(
            qset,
            [self._question("new1", "cache")],
            course_project=course,
        )

        self.assertEqual("course-new", updated.metadata["course_id"])
        self.assertEqual("New Course", updated.metadata["course_title"])
        self.assertEqual("2026-06-18T12:00:00+00:00", updated.metadata["course_updated_at"])

    def test_persist_regeneration_replaces_set_and_deletes_orphaned_old_ai_questions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bank = QuestionBank(str(root / "questions"))
            sets = SetManager(str(root / "sets"))
            old = self._question("old-ai", "old")
            old.metadata["source"] = "ai_generated"
            bank.save(old)
            qset = QuestionSet(
                set_id="set-review",
                title={"zh": "复习", "en": "Review"},
                description={"zh": "", "en": ""},
                topics=["old"],
                difficulty=Difficulty.MEDIUM,
                estimated_minutes=4,
                questions=[old.question_id],
                metadata={"source": "ai_generated"},
            )
            sets.save(qset)
            new_questions = [self._question("new-1", "cache"), self._question("new-2", "process")]
            for question in new_questions:
                question.metadata["source"] = "ai_generated"

            updated, saved, deleted = persist_regenerated_question_set(
                bank,
                sets,
                None,
                qset,
                new_questions,
                difficulty=Difficulty.HARD,
            )

            self.assertEqual(2, saved)
            self.assertEqual(["old-ai"], deleted)
            self.assertEqual(["new-1", "new-2"], updated.questions)
            self.assertEqual(["new-1", "new-2"], sets.get(qset.set_id).questions)
            self.assertIsNone(bank.get("old-ai"))

    def test_persist_regeneration_rolls_back_new_questions_when_save_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bank = QuestionBank(str(root / "questions"))
            sets = SetManager(str(root / "sets"))
            old = self._question("old-ai", "old")
            old.metadata["source"] = "ai_generated"
            bank.save(old)
            qset = QuestionSet(
                set_id="set-review",
                title={"zh": "复习", "en": "Review"},
                description={"zh": "", "en": ""},
                topics=["old"],
                difficulty=Difficulty.MEDIUM,
                estimated_minutes=4,
                questions=[old.question_id],
                metadata={"source": "ai_generated"},
            )
            sets.save(qset)
            new_questions = [self._question("new-1", "cache"), self._question("new-2", "process")]
            original_save = bank.save
            calls = 0

            def flaky_save(question):
                nonlocal calls
                calls += 1
                return original_save(question) if calls == 1 else False

            with patch.object(bank, "save", side_effect=flaky_save):
                with self.assertRaisesRegex(RuntimeError, "1 of 2"):
                    persist_regenerated_question_set(
                        bank,
                        sets,
                        None,
                        qset,
                        new_questions,
                    )

            self.assertIsNone(bank.get("new-1"))
            self.assertIsNone(bank.get("new-2"))
            self.assertIsNotNone(bank.get("old-ai"))
            self.assertEqual(["old-ai"], sets.get(qset.set_id).questions)

    def test_persist_new_question_set_rolls_back_questions_when_set_save_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bank = QuestionBank(str(root / "questions"))
            sets = SetManager(str(root / "sets"))
            questions = [self._question("new-1", "cache"), self._question("new-2", "process")]
            qset = QuestionSet.create_new(
                title={"zh": "AI 练习", "en": "AI Practice"},
                description={"zh": "", "en": ""},
                topics=["cache", "process"],
                question_ids=[question.question_id for question in questions],
            )

            with patch.object(sets, "save", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "question set could not be saved"):
                    persist_new_question_set(bank, sets, qset, questions)

            self.assertIsNone(bank.get("new-1"))
            self.assertIsNone(bank.get("new-2"))
            self.assertIsNone(sets.get(qset.set_id))

    def test_persist_new_question_set_rolls_back_when_question_save_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bank = QuestionBank(str(root / "questions"))
            sets = SetManager(str(root / "sets"))
            questions = [self._question("new-1", "cache"), self._question("new-2", "process")]
            qset = QuestionSet.create_new(
                title={"zh": "AI 练习", "en": "AI Practice"},
                description={"zh": "", "en": ""},
                topics=["cache", "process"],
                question_ids=[question.question_id for question in questions],
            )
            original_save = bank.save
            calls = 0

            def flaky_save(question):
                nonlocal calls
                calls += 1
                return original_save(question) if calls == 1 else False

            with patch.object(bank, "save", side_effect=flaky_save):
                with self.assertRaisesRegex(RuntimeError, "1 of 2"):
                    persist_new_question_set(bank, sets, qset, questions)

            self.assertIsNone(bank.get("new-1"))
            self.assertIsNone(bank.get("new-2"))
            self.assertIsNone(sets.get(qset.set_id))


if __name__ == "__main__":
    unittest.main()
