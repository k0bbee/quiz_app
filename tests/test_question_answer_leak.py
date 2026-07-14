import unittest

from ai.question_answer_leak import choice_stem_leaks_answer_keyword


class QuestionAnswerLeakTests(unittest.TestCase):
    def test_detects_keyword_unique_to_correct_option(self):
        bilingual = {
            "zh": {
                "stem": "哪种方式通过中断通知 CPU 完成？",
                "options": ["A. 轮询", "B. 中断驱动 I/O", "C. DMA", "D. 通道"],
            },
            "en": {
                "stem": "Which method notifies the CPU using an interrupt?",
                "options": ["A. Polling", "B. Interrupt-driven I/O", "C. DMA", "D. Channel"],
            },
        }

        self.assertTrue(choice_stem_leaks_answer_keyword(bilingual, "B"))

    def test_ignores_generic_words_shared_by_distractors(self):
        bilingual = {
            "zh": {
                "stem": "以下哪种 I/O 方式正确？",
                "options": ["A. 轮询方式", "B. 中断方式", "C. DMA 方式", "D. 通道方式"],
            },
            "en": {
                "stem": "Which I/O method is correct?",
                "options": ["A. Polling method", "B. Interrupt method", "C. DMA method", "D. Channel method"],
            },
        }

        self.assertFalse(choice_stem_leaks_answer_keyword(bilingual, "B"))


if __name__ == "__main__":
    unittest.main()
