import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models.question import Question, QuestionBank
from utils.constants import Difficulty, QuestionType
from utils.json_io import read_json, write_json


class QuestionIndexTests(unittest.TestCase):
    def _question(
        self,
        question_id: str,
        *,
        course_id: str,
        topic: str,
        difficulty: Difficulty = Difficulty.MEDIUM,
        marker: str = "",
    ) -> Question:
        question = Question(
            question_id=question_id,
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=difficulty,
            bilingual={
                "zh": {
                    "stem": f"{marker} 中文题干",
                    "options": ["A", "B", "C", "D"],
                    "explanation": f"{marker} 中文解析",
                },
                "en": {
                    "stem": f"{marker} English stem",
                    "options": ["A", "B", "C", "D"],
                    "explanation": f"{marker} English explanation",
                },
            },
            correct_answer="A",
            topic=topic,
            metadata={
                "course_id": course_id,
                "topic_title": topic.title(),
                "quality_status": "passed",
                "source_ref_status": "verified",
                "updated_at": f"2026-07-15T00:00:0{question_id[-1]}+00:00",
            },
        )
        return question

    def test_search_uses_persistent_index_for_filtering_and_pagination(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            questions_dir = Path(tmpdir) / "questions"
            bank = QuestionBank(str(questions_dir))
            bank.save_many([
                self._question("q1", course_id="course-a", topic="ethics", marker="needle"),
                self._question("q2", course_id="course-a", topic="law", marker="needle"),
                self._question("q3", course_id="course-b", topic="ethics", marker="needle"),
                self._question("q4", course_id="course-a", topic="ethics", marker="other"),
            ])
            bank.clear_cache()

            with patch("models.question.read_json", wraps=read_json) as reader:
                items, total = bank.search(
                    query="needle",
                    topic="ethics",
                    course_id="course-a",
                    offset=0,
                    limit=1,
                )

            self.assertEqual(1, total)
            self.assertEqual(["q1"], [item.question_id for item in items])
            self.assertEqual(1, reader.call_count)
            self.assertTrue((questions_dir.parent / ".question_index.sqlite3").exists())

    def test_external_json_change_is_detected_and_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            questions_dir = Path(tmpdir) / "questions"
            bank = QuestionBank(str(questions_dir))
            bank.save(self._question("q1", course_id="course-a", topic="ethics"))
            self.assertEqual(1, bank.count(course_id="course-a"))

            external = self._question("q2", course_id="course-a", topic="law")
            self.assertTrue(write_json(str(questions_dir / "q2.json"), external.to_dict()))

            self.assertEqual(2, bank.count(course_id="course-a"))
            self.assertEqual(["q1", "q2"], bank.question_ids(course_id="course-a"))

            replacement = self._question("q1", course_id="course-b", topic="physics")
            self.assertTrue(write_json(str(questions_dir / "q1.json"), replacement.to_dict()))

            self.assertEqual(1, bank.count(course_id="course-a"))
            self.assertEqual(1, bank.count(course_id="course-b"))

    def test_topic_filters_load_only_index_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            questions_dir = Path(tmpdir) / "questions"
            bank = QuestionBank(str(questions_dir))
            bank.save_many([
                self._question("q1", course_id="course-a", topic="ethics"),
                self._question("q2", course_id="course-a", topic="law"),
                self._question("q3", course_id="course-b", topic="ethics"),
            ])
            bank.clear_cache()

            with patch("models.question.read_json", wraps=read_json) as reader:
                single = bank.filter_by_topic("ethics", course_id="course-a")
                bank.clear_cache()
                multiple = bank.filter_by_topics(["law"], course_id="course-a")

            self.assertEqual(["q1"], [item.question_id for item in single])
            self.assertEqual(["q2"], [item.question_id for item in multiple])
            self.assertEqual(2, reader.call_count)

    def test_corrupt_index_recovers_from_authoritative_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            questions_dir = Path(tmpdir) / "questions"
            bank = QuestionBank(str(questions_dir))
            bank.save(self._question("q1", course_id="course-a", topic="ethics"))
            self.assertEqual(1, bank.count())

            index_path = questions_dir.parent / ".question_index.sqlite3"
            index_path.write_bytes(b"not a sqlite database")

            recovered = QuestionBank(str(questions_dir))
            self.assertEqual(1, recovered.count())
            self.assertEqual("q1", recovered.get("q1").question_id)

    def test_index_schema_contains_expected_filter_indexes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            questions_dir = Path(tmpdir) / "questions"
            bank = QuestionBank(str(questions_dir))
            bank.save(self._question("q1", course_id="course-a", topic="ethics"))
            bank.count()

            connection = sqlite3.connect(questions_dir.parent / ".question_index.sqlite3")
            try:
                names = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list('questions')")
                }
            finally:
                connection.close()

            self.assertTrue({
                "idx_questions_course_topic",
                "idx_questions_course_difficulty",
                "idx_questions_type",
                "idx_questions_quality_status",
                "idx_questions_updated_at",
            }.issubset(names))

    def test_index_failure_does_not_block_authoritative_json_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            questions_dir = Path(tmpdir) / "questions"
            bank = QuestionBank(str(questions_dir))
            question = self._question("q1", course_id="course-a", topic="ethics")

            with patch.object(bank._index, "ensure_current", side_effect=OSError("index unavailable")):
                self.assertTrue(bank.save(question))
                bank.clear_cache()
                items, total = bank.search(course_id="course-a")

            self.assertEqual(1, total)
            self.assertEqual(["q1"], [item.question_id for item in items])
            self.assertEqual("q1", read_json(str(questions_dir / "q1.json"))["question_id"])

    def test_save_many_updates_index_in_one_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            questions_dir = Path(tmpdir) / "questions"
            bank = QuestionBank(str(questions_dir))
            questions = [
                self._question(f"q{index}", course_id="course-a", topic="ethics")
                for index in range(1, 4)
            ]

            with patch.object(
                bank,
                "_try_ensure_index_current",
                wraps=bank._try_ensure_index_current,
            ) as ensure_current, patch.object(
                bank._index,
                "upsert_many",
                wraps=bank._index.upsert_many,
            ) as upsert_many:
                saved = bank.save_many(questions)

            self.assertEqual(3, saved)
            ensure_current.assert_called_once_with()
            upsert_many.assert_called_once()
            self.assertEqual(3, len(upsert_many.call_args.args[0]))

            reloaded = QuestionBank(str(questions_dir))
            self.assertEqual(["q1", "q2", "q3"], reloaded.question_ids(course_id="course-a"))


if __name__ == "__main__":
    unittest.main()
