import unittest

from core.grader import Grader
from models.question import Question
from utils.constants import Difficulty, QuestionType


def _matching_question() -> Question:
    return Question(
        question_id="q-match-stable-options",
        type=QuestionType.MATCHING,
        difficulty=Difficulty.MEDIUM,
        bilingual={
            "zh": {
                "stem": "配对",
                "options": {
                    "left": [{"id": "l_cpu", "text": "中央处理器"}],
                    "right": [{"id": "r_processor", "text": "处理器"}],
                },
                "explanation": "解释",
            },
            "en": {
                "stem": "Match",
                "options": {
                    "left": [{"id": "l_cpu", "text": "CPU"}],
                    "right": [{"id": "r_processor", "text": "Processor"}],
                },
                "explanation": "Explanation",
            },
        },
        correct_answer=[["l_cpu", "r_processor"]],
        topic="io",
    )


def _ordering_question() -> Question:
    return Question(
        question_id="q-order-stable-options",
        type=QuestionType.ORDERING,
        difficulty=Difficulty.MEDIUM,
        bilingual={
            "zh": {
                "stem": "排序",
                "options": [
                    {"id": "fetch", "text": "取指"},
                    {"id": "decode", "text": "译码"},
                ],
                "explanation": "解释",
            },
            "en": {
                "stem": "Order",
                "options": [
                    {"id": "fetch", "text": "Fetch"},
                    {"id": "decode", "text": "Decode"},
                ],
                "explanation": "Explanation",
            },
        },
        correct_answer=["fetch", "decode"],
        topic="pipeline",
    )


class StableOptionGradingTests(unittest.TestCase):
    def test_graders_accept_stable_ids_across_language_text(self):
        cases = (
            (
                "matching",
                _matching_question(),
                [["l_cpu", "r_processor"]],
                [["l_cpu", "r_processor"]],
            ),
            (
                "ordering",
                _ordering_question(),
                ["fetch", "decode"],
                ["fetch", "decode"],
            ),
        )

        for question_type, question, submitted, expected in cases:
            with self.subTest(question_type=question_type):
                is_correct, normalized = Grader.grade(question, submitted)

                self.assertTrue(is_correct)
                self.assertEqual(expected, normalized)

    def test_graders_normalize_legacy_text_answers_to_ids(self):
        cases = (
            (
                "matching",
                _matching_question(),
                [["中央处理器", "处理器"]],
                [["l_cpu", "r_processor"]],
            ),
            (
                "ordering",
                _ordering_question(),
                ["取指", "译码"],
                ["fetch", "decode"],
            ),
        )

        for question_type, question, submitted, expected in cases:
            with self.subTest(question_type=question_type):
                is_correct, normalized = Grader.grade(question, submitted)

                self.assertTrue(is_correct)
                self.assertEqual(expected, normalized)


if __name__ == "__main__":
    unittest.main()
