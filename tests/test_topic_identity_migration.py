import tempfile
import unittest
from pathlib import Path

from core.topic_identity_migration import repair_question_topic_identities
from models.course_project import CourseProject, CourseTopic
from models.question import Question, QuestionBank
from utils.constants import Difficulty, QuestionType
from utils.json_io import read_json, write_json


def _bilingual(stem: str) -> dict:
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


class TopicIdentityMigrationTests(unittest.TestCase):
    def _project(self) -> CourseProject:
        return CourseProject(
            course_id="course-a",
            title="Systems",
            source_folder="",
            summary_markdown="",
            summary_path="",
            topics=[
                CourseTopic(
                    topic_id="cache_mapping",
                    title="Cache Address Mapping",
                    aliases=["Cache Mapping"],
                    keywords=["cache", "tag", "set"],
                ),
                CourseTopic(
                    topic_id="interrupt_io",
                    title="Interrupt-driven I/O",
                    aliases=["I/O Interrupts"],
                    keywords=["interrupt", "dma"],
                ),
            ],
            documents=[],
            created_at="2026-06-18T00:00:00+00:00",
            updated_at="2026-06-18T00:00:00+00:00",
        )

    def _question(self, qid: str, topic: str, course_id: str = "course-a") -> Question:
        question = Question(
            question_id=qid,
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual=_bilingual(f"{topic} question"),
            correct_answer="A",
            topic=topic,
        )
        if course_id:
            question.metadata["course_id"] = course_id
        return question

    def test_repair_updates_legacy_topic_title_to_stable_topic_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_dir = Path(tmpdir) / "questions"
            question_dir.mkdir()
            write_json(
                str(question_dir / "q-legacy.json"),
                {
                    "question_id": "q-legacy",
                    "type": "multiple_choice",
                    "difficulty": "medium",
                    "bilingual": _bilingual("Cache Mapping question"),
                    "correct_answer": "A",
                    "topic": "Cache Mapping",
                    "subtopic": "",
                    "metadata": {"course_id": "course-a"},
                },
            )
            bank = QuestionBank(str(question_dir))

            report = repair_question_topic_identities(bank, self._project())

            self.assertEqual(1, report.scanned)
            self.assertEqual(1, report.updated)
            self.assertEqual([], report.unmatched)
            payload = read_json(str(Path(tmpdir) / "questions" / "q-legacy.json"))
            self.assertEqual("cache_mapping", payload["topic"])
            self.assertEqual("cache_mapping", payload["topic_id"])
            self.assertEqual("Cache Address Mapping", payload["topic_title"])
            self.assertEqual("Cache Mapping", payload["metadata"]["legacy_topic"])
            self.assertEqual("Cache Address Mapping", payload["metadata"]["topic_title"])

    def test_repair_reports_unmatched_topics_without_guessing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            bank.save(self._question("q-unknown", "Quantum Networking"))

            report = repair_question_topic_identities(bank, self._project())

            self.assertEqual(1, report.scanned)
            self.assertEqual(0, report.updated)
            self.assertEqual(["q-unknown"], [item.question_id for item in report.unmatched])
            payload = read_json(str(Path(tmpdir) / "questions" / "q-unknown.json"))
            self.assertEqual("quantum networking", payload["topic"])

    def test_repair_skips_questions_from_other_courses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            bank.save(self._question("q-other-course", "Cache Mapping", course_id="course-b"))

            report = repair_question_topic_identities(bank, self._project())

            self.assertEqual(0, report.scanned)
            self.assertEqual(1, report.skipped_other_course)
            payload = read_json(str(Path(tmpdir) / "questions" / "q-other-course.json"))
            self.assertEqual("cache mapping", payload["topic"])

    def test_repair_detects_ambiguous_legacy_topic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            ambiguous = self._project()
            ambiguous.topics[1].aliases.append("Cache Mapping")
            bank.save(self._question("q-ambiguous", "Cache Mapping"))

            report = repair_question_topic_identities(bank, ambiguous)

            self.assertEqual(1, report.scanned)
            self.assertEqual(0, report.updated)
            self.assertEqual("ambiguous", report.unmatched[0].reason)


if __name__ == "__main__":
    unittest.main()
