import tempfile
import unittest
from pathlib import Path

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.mock_exam_exporter import MockExamExporter, render_mock_exam_markdown
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType
from ui.screens.topic_selection_screen import TopicSelectionScreen


_APP = QApplication.instance() or QApplication([])


class MockExamExporterTests(unittest.TestCase):
    def _make_question_set(self) -> QuestionSet:
        return QuestionSet(
            set_id="set-final-review",
            title={"zh": "期末复习卷", "en": "Final Review"},
            description={"zh": "覆盖缓存和调度", "en": "Covers cache and scheduling"},
            topics=["cache", "scheduling"],
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=90,
            questions=["q1", "q2"],
        )

    def _make_questions(self) -> list[Question]:
        return [
            Question(
                question_id="q1",
                type=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "直接映射缓存中 set 如何计算？",
                        "options": [
                            "A. block number modulo set count",
                            "B. tag modulo way count",
                            "C. byte offset modulo cache size",
                            "D. 随机选择",
                        ],
                        "explanation": "Direct mapping uses block number modulo number of sets.",
                    },
                    "en": {
                        "stem": "How is the set chosen in direct-mapped cache?",
                        "options": [
                            "A. block number modulo set count",
                            "B. tag modulo way count",
                            "C. byte offset modulo cache size",
                            "D. randomly",
                        ],
                        "explanation": "Direct mapping uses block number modulo number of sets.",
                    },
                },
                correct_answer="A",
                topic="cache",
                subtopic="mapping",
            ),
            Question(
                question_id="q2",
                type=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "Round Robin 一定比 FCFS 平均等待时间更短。",
                        "options": ["True", "False"],
                        "explanation": "RR improves responsiveness but does not guarantee lower average waiting time.",
                    },
                    "en": {
                        "stem": "Round Robin always has shorter average waiting time than FCFS.",
                        "options": ["True", "False"],
                        "explanation": "RR improves responsiveness but does not guarantee lower average waiting time.",
                    },
                },
                correct_answer="False",
                topic="scheduling",
            ),
        ]

    def test_render_markdown_includes_exam_body_and_answer_key(self):
        markdown = render_mock_exam_markdown(
            self._make_question_set(),
            self._make_questions(),
            lang="zh",
            include_answers=True,
        )

        self.assertIn("# 期末复习卷", markdown)
        self.assertIn("预计时间: 90 min", markdown)
        self.assertIn("## 模块 1: cache", markdown)
        self.assertIn("直接映射缓存中 set 如何计算？", markdown)
        self.assertIn("A. block number modulo set count", markdown)
        self.assertIn("## 答案与解析", markdown)
        self.assertIn("1. A", markdown)
        self.assertIn("2. False", markdown)
        self.assertIn("RR improves responsiveness", markdown)

    def test_export_writes_utf8_markdown_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "exam.md"

            written = MockExamExporter.write_markdown(
                output_path,
                self._make_question_set(),
                self._make_questions(),
                lang="zh",
            )

            self.assertEqual(output_path, written)
            content = output_path.read_text(encoding="utf-8")
            self.assertIn("# 期末复习卷", content)
            self.assertIn("答案与解析", content)

    def test_topic_selection_screen_emits_export_request_for_selected_set(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            qset = self._make_question_set()
            manager.save(qset)
            screen = TopicSelectionScreen(manager)
            emitted = []
            screen.export_mock_exam.connect(emitted.append)

            screen.refresh()
            self.assertFalse(screen.export_btn.isEnabled())

            screen.set_list.setCurrentRow(0)
            self.assertTrue(screen.export_btn.isEnabled())
            screen.export_btn.click()

            self.assertEqual([qset.set_id], emitted)

    def test_topic_selection_screen_emits_regenerate_request_for_selected_set(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            qset = self._make_question_set()
            manager.save(qset)
            screen = TopicSelectionScreen(manager)
            emitted = []
            screen.regenerate_questions.connect(emitted.append)

            screen.refresh()
            self.assertFalse(screen.regenerate_btn.isEnabled())

            screen.set_list.setCurrentRow(0)
            self.assertTrue(screen.regenerate_btn.isEnabled())
            screen.regenerate_btn.click()

            self.assertEqual([qset.set_id], emitted)


if __name__ == "__main__":
    unittest.main()
