import unittest
from types import SimpleNamespace

from ai.generation_config import GenerationConfig
from core.question_set_builder import build_ai_question_set
from models.course_project import CourseTopic
from models.question import Question
from utils.constants import Difficulty, QuestionType


class QuestionSetBuilderTests(unittest.TestCase):
    def _question(self, qid: str, topic: str, difficulty: Difficulty = Difficulty.MEDIUM) -> Question:
        return Question(
            question_id=qid,
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=difficulty,
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

    def test_build_ai_question_set_preserves_selected_difficulty_and_generation_config(self):
        config = GenerationConfig(
            question_type_weights={"multiple_choice": 40, "scenario_choice": 30, "true_false": 20, "fill_in_blank": 10},
            difficulty_weights={"easy": 10, "medium": 50, "hard": 40},
            topic_weights={"cache": 75, "process": 25},
            template="final_exam",
        )

        qset = build_ai_question_set(
            [self._question("q1", "cache"), self._question("q2", "process")],
            selected_difficulty="hard",
            generation_config=config,
            lang="en",
        )

        self.assertEqual(Difficulty.HARD, qset.difficulty)
        self.assertEqual(["cache", "process"], qset.topics)
        self.assertEqual(["q1", "q2"], qset.questions)
        self.assertEqual("ai_generated", qset.metadata["source"])
        self.assertEqual("hard", qset.metadata["difficulty_mode"])
        self.assertEqual("final_exam", qset.metadata["generation_template"])
        self.assertEqual({"cache": 75, "process": 25}, qset.metadata["topic_weights"])
        self.assertEqual(4, qset.estimated_minutes)

    def test_build_ai_question_set_uses_medium_display_difficulty_for_mixed_mode(self):
        qset = build_ai_question_set(
            [self._question("q1", "cache", Difficulty.EASY), self._question("q2", "cache", Difficulty.HARD)],
            selected_difficulty="mixed",
            generation_config=GenerationConfig(template="quick_review"),
            lang="zh",
        )

        self.assertEqual(Difficulty.MEDIUM, qset.difficulty)
        self.assertEqual("mixed", qset.metadata["difficulty_mode"])

    def test_build_ai_question_set_records_source_course_metadata(self):
        course = SimpleNamespace(
            course_id="course-20260618-demo",
            title="Systems 2B",
            updated_at="2026-06-18T12:00:00+00:00",
        )

        qset = build_ai_question_set(
            [self._question("q1", "cache")],
            selected_difficulty="medium",
            generation_config=GenerationConfig(template="quick_review"),
            lang="en",
            course_project=course,
        )

        self.assertEqual("course-20260618-demo", qset.metadata["course_id"])
        self.assertEqual("Systems 2B", qset.metadata["course_title"])
        self.assertEqual("2026-06-18T12:00:00+00:00", qset.metadata["course_updated_at"])

    def test_build_ai_question_set_uses_topic_ids_for_storage_and_titles_for_display(self):
        topic = CourseTopic(topic_id="interrupt_io", title="Interrupt-driven I/O")

        qset = build_ai_question_set(
            [self._question("q1", topic)],
            selected_difficulty="medium",
            generation_config=GenerationConfig(template="quick_review"),
            lang="en",
        )

        self.assertEqual(["interrupt_io"], qset.topics)
        self.assertIn("Interrupt-driven I/O", qset.get_title("en"))

    def test_build_ai_question_set_does_not_reuse_chinese_custom_title_as_english_title(self):
        topic = CourseTopic(topic_id="interrupt_io", title="Interrupt-driven I/O")

        qset = build_ai_question_set(
            [self._question("q1", topic)],
            selected_difficulty="medium",
            generation_config=GenerationConfig(template="quick_review"),
            lang="zh",
            custom_title="I/O 中断专项",
        )

        self.assertEqual("I/O 中断专项", qset.get_title("zh"))
        self.assertIn("AI Practice", qset.get_title("en"))
        self.assertNotIn("中断", qset.get_title("en"))

    def test_build_ai_question_set_reuses_english_custom_title_for_both_languages(self):
        qset = build_ai_question_set(
            [self._question("q1", "cache")],
            selected_difficulty="medium",
            generation_config=GenerationConfig(template="quick_review"),
            lang="en",
            custom_title="DMA Practice",
        )

        self.assertEqual("DMA Practice", qset.get_title("zh"))
        self.assertEqual("DMA Practice", qset.get_title("en"))


if __name__ == "__main__":
    unittest.main()
