import unittest

from core.historical_question_import import (
    parse_historical_document,
    parse_historical_questions,
)
from utils.constants import QuestionType


class HistoricalQuestionImportTests(unittest.TestCase):
    def test_parses_multiple_choice_and_true_false_blocks_with_source_refs(self):
        text = """课程复习题
1．下列哪项描述了中断驱动 I/O？
A. CPU 一直轮询设备
B．设备完成后通知 CPU
C、CPU 直接执行 DMA
D: 程序完全不等待
答案：B
解析：设备通过中断通知处理器。

2、判断：DMA 是否需要 CPU 逐字节搬运数据？
A. 正确
B. 错误
参考答案：B
"""

        result = parse_historical_questions(
            text,
            source_file="io-exam.txt",
            course_id="course-os",
            topic_id="input-output",
            topic_title="输入输出",
        )

        self.assertEqual(2, len(result.questions))
        self.assertEqual((), result.warnings)

        first, second = result.questions
        self.assertEqual(QuestionType.MULTIPLE_CHOICE, first.type)
        self.assertEqual("B", first.correct_answer)
        self.assertEqual("course-os", first.metadata["course_id"])
        self.assertEqual("input-output", first.topic_id())
        self.assertEqual("输入输出", first.topic_title())
        self.assertEqual("io-exam.txt", first.metadata["source_refs"][0]["source_file"])
        self.assertEqual(2, first.metadata["source_refs"][0]["line_start"])
        self.assertIn("中断驱动", first.metadata["source_refs"][0]["excerpt"])

        self.assertEqual(QuestionType.TRUE_FALSE, second.type)
        self.assertEqual("false", second.correct_answer)
        self.assertEqual(first.get_stem("zh"), first.get_stem("en"))
        self.assertTrue(first.metadata["translation_missing"])

    def test_reports_incomplete_blocks_without_emitting_unsafe_questions(self):
        text = """1. 没有选项的题目
答案：A

2. 没有答案的题目
A. 选项一
B. 选项二

说明：这不是题目。
"""

        result = parse_historical_questions(text, source_file="ocr.txt")

        self.assertEqual(0, len(result.questions))
        self.assertEqual(
            ("question 1: missing options", "question 2: missing answer"),
            result.warnings,
        )

    def test_normalizes_ocr_spacing_and_accepts_answer_without_colon(self):
        text = """7．  哪个选项正确？
A．选项甲
B．选项乙
答案 B
"""

        result = parse_historical_questions(text, source_file="scan.txt")

        self.assertEqual(1, len(result.questions))
        question = result.questions[0]
        self.assertEqual("哪个选项正确？", question.get_stem("zh"))
        self.assertEqual("B", question.correct_answer)
        self.assertEqual(7, question.metadata["source_question_number"])

    def test_uses_document_parser_for_supported_text_documents(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "paper.txt"
            path.write_text(
                "1. 题目？\nA. 甲\nB. 乙\n答案：A\n",
                encoding="utf-8",
            )

            result = parse_historical_document(path, course_id="course-1")

        self.assertEqual(1, len(result.questions))
        self.assertEqual("course-1", result.questions[0].metadata["course_id"])


if __name__ == "__main__":
    unittest.main()
