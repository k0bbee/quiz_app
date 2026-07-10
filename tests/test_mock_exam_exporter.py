import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QAbstractItemView
from PyQt6.QtCore import Qt

from core.mock_exam_exporter import MockExamExporter, render_mock_exam_markdown
from models.question import Question
from models.question_set import QuestionSet
from models.progress import ProgressRecord, SessionSummary
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

    def test_render_markdown_formats_structured_answers_without_internal_ids(self):
        qset = self._make_question_set()
        qset.questions = ["q-match", "q-order"]
        questions = [
            Question(
                question_id="q-match",
                type=QuestionType.MATCHING,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "配对 I/O 术语。",
                        "options": {
                            "left": [{"id": "left_dma", "text": "DMA"}],
                            "right": [{"id": "right_direct", "text": "直接内存访问"}],
                        },
                        "explanation": "DMA 与直接内存访问配对。",
                    },
                    "en": {
                        "stem": "Match I/O terms.",
                        "options": {
                            "left": [{"id": "left_dma", "text": "DMA"}],
                            "right": [{"id": "right_direct", "text": "Direct memory access"}],
                        },
                        "explanation": "DMA matches direct memory access.",
                    },
                },
                correct_answer=[["left_dma", "right_direct"]],
                topic="io",
            ),
            Question(
                question_id="q-order",
                type=QuestionType.ORDERING,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "排序。",
                        "options": [
                            {"id": "fetch", "text": "取指"},
                            {"id": "decode", "text": "译码"},
                        ],
                        "explanation": "先取指再译码。",
                    },
                    "en": {
                        "stem": "Order.",
                        "options": [
                            {"id": "fetch", "text": "Fetch"},
                            {"id": "decode", "text": "Decode"},
                        ],
                        "explanation": "Fetch before decode.",
                    },
                },
                correct_answer=["fetch", "decode"],
                topic="pipeline",
            ),
        ]

        markdown = render_mock_exam_markdown(qset, questions, lang="en", include_answers=True)

        self.assertIn("DMA → Direct memory access", markdown)
        self.assertIn("Fetch → Decode", markdown)
        self.assertNotIn("left_dma", markdown)
        self.assertNotIn("right_direct", markdown)
        self.assertNotIn("fetch → decode", markdown)

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
            emitted_singles = []
            emitted_batches = []
            screen.export_mock_exam.connect(emitted_singles.append)
            screen.export_mock_exams.connect(emitted_batches.append)

            screen.refresh()
            self.assertFalse(screen.export_btn.isEnabled())

            screen.set_list.setCurrentRow(0)
            self.assertTrue(screen.export_btn.isEnabled())
            screen.export_btn.click()

            self.assertEqual([qset.set_id], emitted_singles)
            self.assertEqual([], emitted_batches)

    def test_topic_selection_screen_ignores_current_item_without_explicit_selection(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            qset = self._make_question_set()
            manager.save(qset)
            screen = TopicSelectionScreen(manager)
            exported = []
            regenerated = []
            started = []
            screen.export_mock_exam.connect(exported.append)
            screen.regenerate_questions.connect(regenerated.append)
            screen.quiz_start.connect(lambda set_id, questions: started.append((set_id, questions)))

            screen.refresh()
            screen.set_list.setCurrentRow(0)
            self.assertIsNotNone(screen.set_list.currentItem())
            screen.set_list.clearSelection()
            screen._on_set_selection_changed()

            self.assertEqual([], screen._selected_set_ids())
            self.assertFalse(screen.export_btn.isEnabled())
            self.assertFalse(screen.start_btn.isEnabled())
            self.assertFalse(screen.regenerate_btn.isEnabled())
            self.assertFalse(screen.rename_btn.isEnabled())

            screen._export_selected_set()
            screen._regenerate_selected_set()
            screen._start_quiz()

            self.assertEqual([], exported)
            self.assertEqual([], regenerated)
            self.assertEqual([], started)

    def test_topic_selection_screen_emits_export_requests_for_multiple_selected_sets(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            first = self._make_question_set()
            first.set_id = "set-a"
            second = self._make_question_set()
            second.set_id = "set-b"
            manager.save(first)
            manager.save(second)
            screen = TopicSelectionScreen(manager)
            emitted_singles = []
            emitted_batches = []
            screen.export_mock_exam.connect(emitted_singles.append)
            screen.export_mock_exams.connect(emitted_batches.append)

            screen.refresh()
            self.assertEqual(
                QAbstractItemView.SelectionMode.ExtendedSelection,
                screen.set_list.selectionMode(),
            )

            screen.set_list.setCurrentRow(0)
            screen.set_list.item(1).setSelected(True)
            self.assertTrue(screen.export_btn.isEnabled())
            screen.export_btn.click()

            self.assertEqual([], emitted_singles)
            self.assertEqual(1, len(emitted_batches))
            self.assertCountEqual([first.set_id, second.set_id], emitted_batches[0])

    def test_topic_selection_screen_filters_by_multiple_selected_topics(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            cache = self._make_question_set()
            cache.set_id = "set-cache"
            cache.topics = ["cache"]
            scheduling = self._make_question_set()
            scheduling.set_id = "set-scheduling"
            scheduling.topics = ["scheduling"]
            memory = self._make_question_set()
            memory.set_id = "set-memory"
            memory.topics = ["memory"]
            manager.save(cache)
            manager.save(scheduling)
            manager.save(memory)

            screen = TopicSelectionScreen(manager)
            screen.refresh()
            model = screen.topic_filter.model()
            for row in range(screen.topic_filter.count()):
                if screen.topic_filter.itemData(row) in {"cache", "scheduling"}:
                    model.item(row).setCheckState(Qt.CheckState.Checked)

            screen._render_sets()

            visible_ids = {
                screen.set_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(screen.set_list.count())
            }
            self.assertEqual({"set-cache", "set-scheduling"}, visible_ids)

    def test_topic_selection_screen_emits_regenerate_request_for_ai_generated_set(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            qset = self._make_question_set()
            qset.metadata["source"] = "ai_generated"
            manager.save(qset)
            screen = TopicSelectionScreen(manager)
            emitted = []
            screen.regenerate_questions.connect(emitted.append)

            screen.refresh()
            self.assertFalse(screen.regenerate_btn.isEnabled())

            screen.set_list.setCurrentRow(0)
            self.assertFalse(screen.regenerate_btn.isHidden())
            self.assertTrue(screen.regenerate_btn.isEnabled())
            screen.regenerate_btn.click()

            self.assertEqual([qset.set_id], emitted)

    def test_topic_selection_screen_hides_regenerate_for_manual_set(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            qset = self._make_question_set()
            qset.metadata["source"] = "manual"
            manager.save(qset)
            screen = TopicSelectionScreen(manager)
            emitted = []
            screen.regenerate_questions.connect(emitted.append)

            screen.refresh()
            screen.set_list.setCurrentRow(0)

            self.assertTrue(screen.regenerate_btn.isHidden())
            self.assertFalse(screen.regenerate_btn.isEnabled())
            screen._regenerate_selected_set()
            self.assertEqual([], emitted)

    def test_topic_selection_screen_batches_progress_loading_when_rendering_sets(self):
        from models.question_set import SetManager

        class CountingProgressManager:
            def __init__(self, records):
                self.records = list(records)
                self.load_all_calls = 0
                self.load_for_set_calls = []

            def load_all(self):
                self.load_all_calls += 1
                return list(self.records)

            def load_for_set(self, set_id):
                self.load_for_set_calls.append(set_id)
                return [record for record in self.records if record.set_id == set_id]

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            sets = []
            for index in range(3):
                qset = self._make_question_set()
                qset.set_id = f"set-{index}"
                qset.title = {"zh": f"题集 {index}", "en": f"Set {index}"}
                manager.save(qset)
                sets.append(qset)

            progress = ProgressRecord.create_new(sets[1].set_id)
            progress.status = "completed"
            progress.summary = SessionSummary(
                total_questions=2,
                answered=2,
                correct=1,
                incorrect=1,
                score_percentage=50.0,
            )
            progress_manager = CountingProgressManager([progress])
            screen = TopicSelectionScreen(manager, progress_manager=progress_manager)

            screen.refresh()

            self.assertEqual(1, progress_manager.load_all_calls)
            self.assertEqual([], progress_manager.load_for_set_calls)
            rendered = [screen.set_list.item(row).text() for row in range(screen.set_list.count())]
            self.assertTrue(any("recent 50%" in text or "最近 50%" in text for text in rendered))

    def test_topic_selection_screen_can_rename_selected_question_set(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            qset = self._make_question_set()
            manager.save(qset)
            screen = TopicSelectionScreen(manager)
            screen.refresh()
            screen.set_list.setCurrentRow(0)

            with patch(
                "ui.screens.topic_selection_screen.QInputDialog.getText",
                return_value=("期末强化题集", True),
            ):
                screen.rename_btn.click()

            renamed = manager.get(qset.set_id)
            self.assertEqual("期末强化题集", renamed.get_title("zh"))
            self.assertEqual("期末强化题集", renamed.get_title("en"))
            self.assertIn("期末强化题集", screen.set_list.item(0).text())

    def test_topic_selection_screen_filters_generated_sets_by_current_course(self):
        from models.question_set import SetManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            course_a = self._make_question_set()
            course_a.set_id = "set-course-a"
            course_a.metadata["course_id"] = "course-a"
            course_b = self._make_question_set()
            course_b.set_id = "set-course-b"
            course_b.metadata["course_id"] = "course-b"
            manual = self._make_question_set()
            manual.set_id = "set-manual"
            manager.save(course_a)
            manager.save(course_b)
            manager.save(manual)

            screen = TopicSelectionScreen(manager)
            screen.set_current_course("course-a")
            screen.refresh()

            visible_ids = {
                screen.set_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(screen.set_list.count())
            }
            self.assertEqual({"set-course-a", "set-manual"}, visible_ids)


if __name__ == "__main__":
    unittest.main()
