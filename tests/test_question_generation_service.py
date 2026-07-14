import unittest

from ai.question_generation_service import QuestionGenerationService


def _bilingual(stem_zh="选择机制。", stem_en="Choose the mechanism.", options=None):
    options = options or ["A. 轮询", "B. 中断", "C. DMA", "D. 通道"]
    return {
        "zh": {
            "stem": stem_zh,
            "options": list(options),
            "explanation": "这是足够长的中文解析，用于完整说明答案为什么正确。",
        },
        "en": {
            "stem": stem_en,
            "options": ["A. Polling", "B. Interrupt", "C. DMA", "D. Channel"],
            "explanation": "This explanation is long enough to explain why the answer is correct.",
        },
    }


class QuestionGenerationServiceTests(unittest.TestCase):
    def test_prepare_normalizes_fill_answer_and_canonical_topic(self):
        service = QuestionGenerationService(["input_output_improvements"])
        raw = {
            "type": "fill_in_blank",
            "difficulty": "medium",
            "topic": "input output improvements and DMA",
            "correct_answer": " DMA ",
            "bilingual": _bilingual(),
        }

        prepared, reason = service.prepare_raw_question(raw)

        self.assertEqual("", reason)
        self.assertEqual(["DMA"], prepared["correct_answer"])
        self.assertEqual("input_output_improvements", prepared["topic"])

    def test_prepare_rejects_ambiguous_topic_substring(self):
        service = QuestionGenerationService(["process", "input_output_improvements"])
        raw = {
            "type": "multiple_choice",
            "difficulty": "medium",
            "topic": "processor scheduling",
            "correct_answer": "A",
            "bilingual": _bilingual(),
        }

        prepared, reason = service.prepare_raw_question(raw)

        self.assertIsNone(prepared)
        self.assertIn("not selected", reason)

    def test_prepare_normalizes_matching_options_to_stable_ids(self):
        service = QuestionGenerationService(["io"])
        raw = {
            "type": "matching",
            "difficulty": "medium",
            "topic": "io",
            "correct_answer": [["CPU", "Processor"], ["GPU", "Graphics"]],
            "bilingual": {
                "zh": {
                    "stem": "配对设备。",
                    "options": {"left": ["CPU", "GPU"], "right": ["Processor", "Graphics"]},
                    "explanation": "这是足够长的中文解析，用于说明每一组设备配对关系。",
                },
                "en": {
                    "stem": "Match devices.",
                    "options": {"left": ["CPU", "GPU"], "right": ["Processor", "Graphics"]},
                    "explanation": "This explanation is long enough to describe every device pair.",
                },
            },
        }

        prepared, reason = service.prepare_raw_question(raw)

        self.assertEqual("", reason)
        self.assertEqual([["left_1", "right_1"], ["left_2", "right_2"]], prepared["correct_answer"])
        self.assertEqual("left_1", prepared["bilingual"]["zh"]["options"]["left"][0]["id"])

    def test_prepare_rejects_choice_stem_that_leaks_answer_keyword(self):
        service = QuestionGenerationService(["io"])
        raw = {
            "type": "multiple_choice",
            "difficulty": "medium",
            "topic": "io",
            "correct_answer": "B",
            "bilingual": _bilingual(
                stem_zh="哪种方式通过中断通知 CPU 完成？",
                stem_en="Which method notifies the CPU using an interrupt?",
            ),
        }

        prepared, reason = service.prepare_raw_question(raw)

        self.assertIsNone(prepared)
        self.assertIn("answer keyword", reason)


if __name__ == "__main__":
    unittest.main()
