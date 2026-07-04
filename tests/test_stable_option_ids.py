import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.grader import Grader
from core.language_manager import LanguageManager
from models.question import Question
from ui.widgets.question_review_card import QuestionReviewCard
from ui.widgets.answer_area import AnswerArea, MatchingWidget, OrderingWidget
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class StableOptionIdTests(unittest.TestCase):
    def test_matching_widget_returns_and_restores_stable_ids(self):
        widget = MatchingWidget()
        widget.set_options({
            "left": [
                {"id": "l_cpu", "text": "CPU"},
                {"id": "l_gpu", "text": "GPU"},
            ],
            "right": [
                {"id": "r_processor", "text": "Processor"},
                {"id": "r_graphics", "text": "Graphics"},
            ],
        })

        widget.set_answer([
            ["l_cpu", "r_processor"],
            ["l_gpu", "r_graphics"],
        ])

        self.assertEqual(
            [["l_cpu", "r_processor"], ["l_gpu", "r_graphics"]],
            widget.get_answer(),
        )

    def test_ordering_widget_returns_and_restores_stable_ids(self):
        widget = OrderingWidget()
        widget.set_options([
            {"id": "fetch", "text": "Fetch"},
            {"id": "decode", "text": "Decode"},
            {"id": "execute", "text": "Execute"},
        ])

        widget.set_answer(["decode", "fetch", "execute"])

        self.assertEqual(["decode", "fetch", "execute"], widget.get_answer())
        self.assertEqual(["Decode", "Fetch", "Execute"], [
            widget.list_widget.item(index).text()
            for index in range(widget.list_widget.count())
        ])

    def test_answer_area_preserves_matching_answer_when_option_text_changes(self):
        area = AnswerArea()
        area.set_question_type(
            QuestionType.MATCHING,
            {
                "left": [{"id": "l_cpu", "text": "中央处理器"}],
                "right": [{"id": "r_processor", "text": "处理器"}],
            },
        )
        area.matching_widget.set_answer([["l_cpu", "r_processor"]])

        area.set_question_type(
            QuestionType.MATCHING,
            {
                "left": [{"id": "l_cpu", "text": "CPU"}],
                "right": [{"id": "r_processor", "text": "Processor"}],
            },
            preserve_answer=True,
        )

        self.assertEqual([["l_cpu", "r_processor"]], area.get_answer())
        self.assertEqual("CPU", area.matching_widget.left_list.item(0).text())
        self.assertEqual("Processor", area.matching_widget.combos[0].currentText())

    def test_answer_area_preserves_ordering_answer_when_option_text_changes(self):
        area = AnswerArea()
        area.set_question_type(
            QuestionType.ORDERING,
            [
                {"id": "fetch", "text": "取指"},
                {"id": "decode", "text": "译码"},
            ],
        )
        area.ordering_widget.set_answer(["decode", "fetch"])

        area.set_question_type(
            QuestionType.ORDERING,
            [
                {"id": "fetch", "text": "Fetch"},
                {"id": "decode", "text": "Decode"},
            ],
            preserve_answer=True,
        )

        self.assertEqual(["decode", "fetch"], area.get_answer())
        self.assertEqual(["Decode", "Fetch"], [
            area.ordering_widget.list_widget.item(index).text()
            for index in range(area.ordering_widget.list_widget.count())
        ])

    def test_matching_grader_accepts_stable_ids_across_language_text(self):
        question = Question(
            question_id="q-match-ids",
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

        is_correct, normalized = Grader.grade(question, [["l_cpu", "r_processor"]])

        self.assertTrue(is_correct)
        self.assertEqual([["l_cpu", "r_processor"]], normalized)

    def test_matching_grader_normalizes_legacy_text_answer_to_ids(self):
        question = Question(
            question_id="q-match-legacy-text",
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

        is_correct, normalized = Grader.grade(question, [["中央处理器", "处理器"]])

        self.assertTrue(is_correct)
        self.assertEqual([["l_cpu", "r_processor"]], normalized)

    def test_ordering_grader_accepts_stable_ids_across_language_text(self):
        question = Question(
            question_id="q-order-ids",
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

        is_correct, normalized = Grader.grade(question, ["fetch", "decode"])

        self.assertTrue(is_correct)
        self.assertEqual(["fetch", "decode"], normalized)

    def test_ordering_grader_normalizes_legacy_text_answer_to_ids(self):
        question = Question(
            question_id="q-order-legacy-text",
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

        is_correct, normalized = Grader.grade(question, ["取指", "译码"])

        self.assertTrue(is_correct)
        self.assertEqual(["fetch", "decode"], normalized)

    def test_review_card_formats_ordering_ids_as_readable_labels(self):
        question = Question(
            question_id="q-review-order",
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
        card = QuestionReviewCard()
        self.addCleanup(card.close)
        language_manager = LanguageManager.instance()
        previous_language = language_manager.current
        self.addCleanup(language_manager.set_language, previous_language)
        language_manager.set_language("en")

        card.set_result(0, question, ["decode", "fetch"], is_correct=False, lang="en")

        text = card.answer_info.text()
        self.assertIn("Decode → Fetch", text)
        self.assertIn("Fetch → Decode", text)
        self.assertNotIn("decode → fetch", text)


if __name__ == "__main__":
    unittest.main()
