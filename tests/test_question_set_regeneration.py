import unittest
from types import SimpleNamespace

from core.question_set_regenerator import apply_regenerated_questions
from models.question import Question
from models.question_set import QuestionSet
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


if __name__ == "__main__":
    unittest.main()
