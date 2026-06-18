import unittest

from ai.generation_config import GenerationConfig
from core.question_set_builder import build_ai_question_set
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


if __name__ == "__main__":
    unittest.main()
