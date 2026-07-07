import unittest

from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType


class ModelDeserializationTests(unittest.TestCase):
    def test_question_set_from_dict_coerces_legacy_string_title_and_description(self):
        qset = QuestionSet.from_dict(
            {
                "set_id": "legacy-set",
                "title": "旧版题集",
                "description": "旧版描述",
                "topics": ["cache"],
                "difficulty": "medium",
                "estimated_minutes": 20,
                "questions": ["q1"],
            }
        )

        self.assertEqual("旧版题集", qset.get_title("zh"))
        self.assertEqual("旧版题集", qset.get_title("en"))
        self.assertEqual("旧版描述", qset.get_description("zh"))
        self.assertEqual("旧版描述", qset.get_description("en"))

    def test_question_set_from_dict_falls_back_for_unknown_difficulty(self):
        qset = QuestionSet.from_dict(
            {
                "set_id": "bad-difficulty-set",
                "title": {"zh": "题集", "en": "Set"},
                "description": {"zh": "", "en": ""},
                "topics": ["cache"],
                "difficulty": "impossible",
                "estimated_minutes": 20,
                "questions": ["q1"],
            }
        )

        self.assertEqual(Difficulty.MEDIUM, qset.difficulty)

    def test_question_from_dict_falls_back_for_unknown_type_and_difficulty(self):
        question = Question.from_dict(
            {
                "question_id": "q-bad-enum",
                "type": "essay",
                "difficulty": "impossible",
                "bilingual": {
                    "zh": {"stem": "题干", "options": [], "explanation": "解释"},
                    "en": {"stem": "Stem", "options": [], "explanation": "Explanation"},
                },
                "correct_answer": "A",
                "topic": "cache",
            }
        )

        self.assertEqual(QuestionType.MULTIPLE_CHOICE, question.type)
        self.assertEqual(Difficulty.MEDIUM, question.difficulty)


if __name__ == "__main__":
    unittest.main()
