import unittest

from core.question_validation import validate_question_quality
from models.question import Question
from utils.constants import Difficulty, QuestionType


def _question() -> Question:
    return Question.create_new(
        QuestionType.MULTIPLE_CHOICE,
        Difficulty.MEDIUM,
        {
            "zh": {
                "stem": "选择正确机制。",
                "options": ["A. 正确", "B. 错误", "C. 错误", "D. 错误"],
                "explanation": "这是正常长度的中文解析。",
            },
            "en": {
                "stem": "Choose the mechanism.",
                "options": ["A. Correct", "B. Wrong", "C. Wrong", "D. Wrong"],
                "explanation": "This is a normal English explanation.",
            },
        },
        "A",
        "io",
    )


class QuestionValidationTests(unittest.TestCase):
    def test_validator_rejects_trusted_source_status_without_source_refs(self):
        for source_status in ("verified", "valid_model_ref", "fallback_plan_evidence"):
            with self.subTest(source_status=source_status):
                question = _question()
                question.metadata["source_ref_status"] = source_status

                issues = validate_question_quality(question)

                self.assertIn(
                    "source_status_without_refs",
                    [issue.code for issue in issues],
                )

    def test_validator_does_not_require_sources_for_unlabelled_manual_question(self):
        issues = validate_question_quality(_question())

        self.assertNotIn(
            "source_status_without_refs",
            [issue.code for issue in issues],
        )

    def test_validator_returns_stable_codes_bilingual_text_and_repairs(self):
        question = _question()
        question.metadata["source_ref_status"] = "invalid_model_ref"
        question.metadata["plan_match_status"] = "matched_by_shape"
        question.bilingual["zh"]["explanation"] = ""
        question.bilingual["en"]["explanation"] = ""

        issues = validate_question_quality(question)

        self.assertEqual(
            ["source_invalid", "plan_shape_match", "explanation_missing"],
            [issue.code for issue in issues],
        )
        self.assertEqual("来源无效或缺失", issues[0].message("zh"))
        self.assertEqual("Source invalid or missing", issues[0].message("en"))
        self.assertEqual("replace_source", issues[0].repair_action)
        self.assertEqual("[无来源]", issues[0].tag("zh"))

    def test_validator_marks_partial_and_plan_fallback_sources_for_review(self):
        for source_status in ("partial_model_ref", "fallback_plan_evidence"):
            with self.subTest(source_status=source_status):
                question = _question()
                question.metadata["source_ref_status"] = source_status
                question.metadata["source_refs"] = [{"chunk_id": "source-1"}]

                issues = validate_question_quality(question)

                self.assertIn(
                    "source_weak",
                    [issue.code for issue in issues],
                )

    def test_validator_detects_bilingual_imbalance_and_option_length_bias(self):
        question = _question()
        question.bilingual["zh"]["explanation"] = "短"
        question.bilingual["en"]["explanation"] = "x" * 100
        question.bilingual["zh"]["options"][0] = "A. " + "很长的正确答案" * 8

        issues = validate_question_quality(question)

        self.assertEqual(
            ["bilingual_explanation_imbalance", "correct_option_length_bias"],
            [issue.code for issue in issues],
        )

    def test_validator_accounts_for_information_density_of_cjk_explanations(self):
        question = _question()
        question.bilingual["zh"]["explanation"] = "高价格使供给量超过需求量，市场出现过剩。"
        question.bilingual["en"]["explanation"] = (
            "At a higher price, quantity supplied exceeds quantity demanded, "
            "so the market develops a surplus."
        )

        issues = validate_question_quality(question)

        self.assertNotIn("bilingual_explanation_imbalance", [issue.code for issue in issues])


if __name__ == "__main__":
    unittest.main()
