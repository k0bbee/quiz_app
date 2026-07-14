import unittest

from ai.question_payload_normalizer import normalize_raw_question


class QuestionPayloadNormalizerTests(unittest.TestCase):
    def test_normalizes_fill_answer_strings(self):
        normalized = normalize_raw_question({
            "type": "fill_in_blank",
            "correct_answer": " DMA ",
        })

        self.assertEqual(["DMA"], normalized["correct_answer"])

    def test_normalizes_parallel_matching_labels_to_stable_ids(self):
        normalized = normalize_raw_question({
            "type": "matching",
            "correct_answer": [["CPU", "Processor"]],
            "bilingual": {
                "zh": {"options": {"left": ["CPU"], "right": ["Processor"]}},
                "en": {"options": {"left": ["CPU"], "right": ["Processor"]}},
            },
        })

        self.assertEqual([["left_1", "right_1"]], normalized["correct_answer"])
        self.assertEqual(
            {"id": "left_1", "text": "CPU"},
            normalized["bilingual"]["zh"]["options"]["left"][0],
        )


if __name__ == "__main__":
    unittest.main()
