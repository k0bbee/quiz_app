import tempfile
import unittest
from pathlib import Path

from models.course_project import CourseTopic
from models.question import Question, QuestionBank
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType
from utils.json_io import read_json, write_json


def _bilingual(stem: str = "Which answer is correct?") -> dict:
    return {
        "zh": {
            "stem": stem,
            "options": ["A. one", "B. two", "C. three", "D. four"],
            "explanation": "A is correct because it matches the course concept.",
        },
        "en": {
            "stem": stem,
            "options": ["A. one", "B. two", "C. three", "D. four"],
            "explanation": "A is correct because it matches the course concept.",
        },
    }


class TopicIdentityTests(unittest.TestCase):
    def test_question_serializes_course_topic_with_stable_id_and_display_title(self):
        topic = CourseTopic(
            topic_id="cache_mapping",
            title="Cache Mapping",
            keywords=["tag", "set index"],
            source_files=["lecture.md"],
        )
        question = Question(
            question_id="q-topic-id",
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual=_bilingual(),
            correct_answer="A",
            topic=topic,
        )

        payload = question.to_dict()

        self.assertEqual("cache_mapping", payload["topic"])
        self.assertEqual("cache_mapping", payload["topic_id"])
        self.assertEqual("Cache Mapping", payload["topic_title"])

    def test_question_deserialization_prefers_topic_id_over_stale_title(self):
        question = Question.from_dict(
            {
                "question_id": "q-stale-title",
                "type": "multiple_choice",
                "difficulty": "medium",
                "bilingual": _bilingual(),
                "correct_answer": "A",
                "topic": "Old Cache Mapping",
                "topic_id": "cache_mapping",
                "topic_title": "Old Cache Mapping",
            }
        )

        self.assertEqual("cache_mapping", question.topic)
        self.assertEqual("Old Cache Mapping", question.metadata["topic_title"])

    def test_question_bank_filters_legacy_title_by_renamed_topic_alias(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_dir = Path(tmpdir) / "questions"
            question_dir.mkdir()
            write_json(
                str(question_dir / "q-legacy.json"),
                {
                    "question_id": "q-legacy",
                    "type": "multiple_choice",
                    "difficulty": "medium",
                    "bilingual": _bilingual("Legacy title question"),
                    "correct_answer": "A",
                    "topic": "Cache Mapping",
                    "subtopic": "",
                    "metadata": {},
                },
            )
            bank = QuestionBank(str(question_dir))
            renamed = CourseTopic(
                topic_id="cache_mapping",
                title="Cache Address Mapping",
                aliases=["Cache Mapping"],
            )

            questions = bank.filter_by_topic(renamed)

            self.assertEqual(["q-legacy"], [question.question_id for question in questions])

    def test_question_set_serializes_topic_ids_without_losing_titles(self):
        topic = CourseTopic(topic_id="interrupt_io", title="Interrupt-driven I/O")
        qset = QuestionSet(
            set_id="set-topic-id",
            title={"zh": "I/O", "en": "I/O"},
            description={"zh": "", "en": ""},
            topics=[topic],
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=20,
            questions=["q1"],
        )

        payload = qset.to_dict()

        self.assertEqual(["interrupt_io"], payload["topics"])
        self.assertEqual(["interrupt_io"], payload["topic_ids"])
        self.assertEqual(["Interrupt-driven I/O"], payload["topic_titles"])

    def test_saved_question_file_uses_topic_id_as_primary_topic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            topic = CourseTopic(topic_id="interrupt_io", title="Interrupt-driven I/O")
            question = Question(
                question_id="q-save",
                type=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual=_bilingual(),
                correct_answer="A",
                topic=topic,
            )

            bank.save(question)

            payload = read_json(str(Path(tmpdir) / "questions" / "q-save.json"))
            self.assertEqual("interrupt_io", payload["topic"])
            self.assertEqual("interrupt_io", payload["topic_id"])
            self.assertEqual("Interrupt-driven I/O", payload["topic_title"])


if __name__ == "__main__":
    unittest.main()
