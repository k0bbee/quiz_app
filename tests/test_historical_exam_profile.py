import unittest

from core.historical_exam_profile import build_historical_exam_profile
from models.question import Question
from models.course_project import CourseTopic
from utils.constants import Difficulty, QuestionType


def _question(
    question_id: str,
    *,
    topic: str = "cache",
    qtype: QuestionType = QuestionType.MULTIPLE_CHOICE,
    difficulty: Difficulty = Difficulty.MEDIUM,
    course_id: str = "course-a",
    historical: bool = True,
    match_status: str = "matched",
    source_file: str = "exam.txt",
) -> Question:
    question = Question(
        question_id=question_id,
        type=qtype,
        difficulty=difficulty,
        bilingual={"zh": {"stem": "题干"}, "en": {"stem": "Stem"}},
        correct_answer="A",
        topic=topic,
        metadata={},
    )
    if historical:
        question.metadata.update(
            {
                "historical_import": True,
                "source": "historical_import",
                "course_id": course_id,
                "topic_match_status": match_status,
                "source_refs": [{"source_file": source_file}],
            }
        )
    return question


class HistoricalExamProfileTests(unittest.TestCase):
    def test_profile_uses_only_reviewable_imports_in_course_scope(self):
        questions = [
            _question("cache-1", topic="cache", source_file="midterm.pdf"),
            _question("cache-2", topic="cache", source_file="midterm.pdf"),
            _question(
                "process-1",
                topic="process",
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.HARD,
                source_file="final.pdf",
            ),
            _question("wrong-course", course_id="course-b"),
            _question("unmatched", topic="cache", match_status="unmatched"),
            _question("out-of-scope", topic="io"),
            _question("manual", historical=False),
        ]

        profile = build_historical_exam_profile(
            questions,
            allowed_topic_ids=("cache", "process"),
            course_id="course-a",
        )

        self.assertIsNotNone(profile)
        self.assertEqual(3, profile.sample_count)
        self.assertEqual({"midterm.pdf", "final.pdf"}, set(profile.source_files))
        self.assertEqual(100, sum(profile.topic_weights.values()))
        self.assertEqual(100, sum(profile.question_type_weights.values()))
        self.assertEqual(100, sum(profile.difficulty_weights.values()))
        self.assertGreater(profile.topic_weights["cache"], profile.topic_weights["process"])
        self.assertIn("true_false", profile.question_type_weights)
        self.assertIn("hard", profile.difficulty_weights)

    def test_profile_keeps_unseen_allowed_topics_with_light_smoothing(self):
        profile = build_historical_exam_profile(
            [_question("cache-1", topic="cache")],
            allowed_topic_ids=(
                CourseTopic("cache", "Cache"),
                CourseTopic("process", "Process"),
            ),
            course_id="course-a",
        )

        self.assertEqual({"cache", "process"}, set(profile.topic_weights))
        self.assertGreater(profile.topic_weights["cache"], profile.topic_weights["process"])
        self.assertEqual(100, sum(profile.topic_weights.values()))

    def test_profile_returns_none_without_eligible_imports(self):
        self.assertIsNone(
            build_historical_exam_profile(
                [_question("manual", historical=False)],
                allowed_topic_ids=("cache",),
                course_id="course-a",
            )
        )


if __name__ == "__main__":
    unittest.main()
