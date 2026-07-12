import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QAbstractItemView

from core import course_index
from core.language_manager import LanguageManager
from core.progress_tracker import ProgressManager
from core.question_bank_maintenance import (
    backfill_source_refs_from_course,
    delete_unreferenced_ai_questions,
    remove_question_from_sets,
)
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.progress import AnswerRecord, ProgressRecord
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from ui.screens.question_bank_screen import QuestionBankScreen
from utils.json_io import read_json, write_json
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class QuestionBankCleanupTests(unittest.TestCase):
    def _question(self, qid: str, topic: str = "cache") -> Question:
        return Question(
            question_id=qid,
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": f"{topic} question",
                    "options": ["A. one", "B. two", "C. three", "D. four"],
                    "explanation": "A valid explanation with enough detail.",
                },
                "en": {
                    "stem": f"{topic} question",
                    "options": ["A. one", "B. two", "C. three", "D. four"],
                    "explanation": "A valid explanation with enough detail.",
                },
            },
            correct_answer="A",
            topic=topic,
        )

    def _set(self, set_id: str, question_ids: list[str]) -> QuestionSet:
        return QuestionSet(
            set_id=set_id,
            title={"zh": set_id, "en": set_id},
            description={"zh": "", "en": ""},
            topics=["cache"],
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=20,
            questions=question_ids,
        )

    def test_remove_question_from_sets_prunes_stale_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            manager.save(self._set("set-a", ["q1", "q2"]))
            manager.save(self._set("set-b", ["q1"]))
            manager.save(self._set("set-c", ["q3"]))

            changed = remove_question_from_sets(manager, "q1")

            self.assertEqual(2, changed)
            self.assertEqual(["q2"], manager.get("set-a").questions)
            self.assertEqual([], manager.get("set-b").questions)
            self.assertEqual(["q3"], manager.get("set-c").questions)
            self.assertEqual("question_deleted", manager.get("set-a").metadata["source"])
            self.assertIn("updated_at", manager.get("set-a").metadata)

    def test_question_bank_search_reuses_loaded_questions_until_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save_many([self._question("q1"), self._question("q2")])

            with patch("models.question.read_json", wraps=read_json) as read:
                first_page, first_total = question_bank.search(query="cache", limit=1)
                reads_after_first_search = read.call_count
                second_page, second_total = question_bank.search(query="cache", limit=1)

                self.assertEqual(2, first_total)
                self.assertEqual(2, second_total)
                self.assertEqual([q.question_id for q in first_page], [q.question_id for q in second_page])
                self.assertEqual(reads_after_first_search, read.call_count)

                question_bank.save(self._question("q3"))
                _page, updated_total = question_bank.search(query="cache", limit=5)

                self.assertEqual(3, updated_total)
                self.assertGreater(read.call_count, reads_after_first_search)

    def test_question_bank_count_existing_skips_unsafe_question_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save(self._question("q-safe"))

            count = question_bank.count_existing(["q-safe", "../escape", "???", "q-safe"])

            self.assertEqual(1, count)

    def test_backfill_source_refs_from_course_updates_stale_question_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            project = CourseProject(
                course_id="course-source-backfill",
                title="Systems",
                source_folder="",
                summary_markdown="## Cache\nCache mapping.",
                summary_path="",
                topics=[
                    CourseTopic(
                        topic_id="cache",
                        title="Cache",
                        keywords=["cache"],
                        source_files=["cache.pdf"],
                    )
                ],
                documents=[
                    {
                        "path": "cache.pdf",
                        "title": "Cache lecture",
                        "extension": ".pdf",
                        "pages": ["Cache lines and cache mapping details."],
                    }
                ],
                created_at="2026-07-02T00:00:00+00:00",
                updated_at="2026-07-02T00:00:00+00:00",
            )
            index = course_index.build_source_index(project)
            question = self._question("q-source-backfill", "cache")
            question.metadata["course_id"] = project.course_id
            question.metadata["source_refs"] = [
                {
                    "chunk_id": "old-source-01",
                    "source_file": "cache.pdf",
                    "page_or_slide": 1,
                    "content_hash": index[0]["content_hash"][:12],
                }
            ]
            question_bank.save(question)

            changed = backfill_source_refs_from_course(question_bank, project)

            saved = question_bank.get("q-source-backfill")
            ref = saved.metadata["source_refs"][0]
            self.assertEqual(1, changed)
            self.assertEqual(index[0]["chunk_id"], ref["chunk_id"])
            self.assertEqual("old-source-01", ref["resolved_from_chunk_id"])
            self.assertIn("Cache lines and cache mapping", ref["excerpt"])

    def test_question_bank_screen_backfills_source_refs_from_current_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
            project = CourseProject(
                course_id="course-ui-backfill",
                title="Systems",
                source_folder="",
                summary_markdown="## Cache\nCache mapping.",
                summary_path="",
                topics=[
                    CourseTopic(
                        topic_id="cache",
                        title="Cache",
                        keywords=["cache"],
                        source_files=["cache.pdf"],
                    )
                ],
                documents=[
                    {
                        "path": "cache.pdf",
                        "title": "Cache lecture",
                        "extension": ".pdf",
                        "pages": ["Cache lines and cache mapping details."],
                    }
                ],
                created_at="2026-07-02T00:00:00+00:00",
                updated_at="2026-07-02T00:00:00+00:00",
            )
            course_manager.save(project)
            index = course_index.build_source_index(project)
            question = self._question("q-ui-source", "cache")
            question.metadata["course_id"] = project.course_id
            question.metadata["source_refs"] = [
                {
                    "chunk_id": "old-source-01",
                    "source_file": "cache.pdf",
                    "page_or_slide": 1,
                    "content_hash": index[0]["content_hash"][:12],
                }
            ]
            question_bank.save(question)

            screen = QuestionBankScreen(question_bank, course_manager=course_manager)
            screen.set_current_course(project.course_id)
            screen.question_list.setCurrentRow(0)

            with patch("ui.screens.question_bank_screen.QMessageBox.information") as info:
                screen.backfill_source_refs_btn.click()

            saved = question_bank.get("q-ui-source")
            self.assertEqual(index[0]["chunk_id"], saved.metadata["source_refs"][0]["chunk_id"])
            self.assertIn("Cache lines and cache mapping", screen.source_refs_label.text())
            info.assert_called_once()
            self.assertIn("1", info.call_args.args[2])

    def test_question_bank_screen_backfill_source_refs_requires_a_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
            screen = QuestionBankScreen(question_bank, course_manager=course_manager)

            with patch("ui.screens.question_bank_screen.QMessageBox.warning") as warning:
                screen.backfill_source_refs_btn.click()

            warning.assert_called_once()
            self.assertIn("课程", warning.call_args.args[2])

    def test_question_bank_search_filters_generated_questions_by_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_a = self._question("q-course-a")
            course_a.metadata["course_id"] = "course-a"
            course_b = self._question("q-course-b")
            course_b.metadata["course_id"] = "course-b"
            manual = self._question("q-manual")
            question_bank.save_many([course_a, course_b, manual])

            items, total = question_bank.search(course_id="course-a")

            self.assertEqual(1, total)
            self.assertEqual({"q-course-a"}, {question.question_id for question in items})

    def test_question_bank_get_many_filters_generated_questions_by_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_a = self._question("q-course-a")
            course_a.metadata["course_id"] = "course-a"
            course_b = self._question("q-course-b")
            course_b.metadata["course_id"] = "course-b"
            manual = self._question("q-manual")
            question_bank.save_many([course_a, course_b, manual])

            questions = question_bank.get_many(
                ["q-course-a", "q-course-b", "q-manual"],
                course_id="course-a",
            )

            self.assertEqual({"q-course-a"}, {question.question_id for question in questions})

    def test_question_bank_screen_filters_generated_questions_by_current_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_a = self._question("q-course-a")
            course_a.metadata["course_id"] = "course-a"
            course_b = self._question("q-course-b")
            course_b.metadata["course_id"] = "course-b"
            manual = self._question("q-manual")
            question_bank.save_many([course_a, course_b, manual])

            screen = QuestionBankScreen(question_bank)
            screen.set_current_course("course-a")
            screen.refresh()

            visible_ids = {
                screen.question_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(screen.question_list.count())
            }
            self.assertEqual({"q-course-a"}, visible_ids)

    def test_question_bank_screen_filters_questions_by_selected_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            q1 = self._question("q1", "cache")
            q2 = self._question("q2", "pipeline")
            q3 = self._question("q3", "interrupt")
            question_bank.save_many([q1, q2, q3])
            set_manager.save(self._set("set-a", ["q1", "q3"]))
            set_manager.save(self._set("set-b", ["q2"]))

            screen = QuestionBankScreen(question_bank, set_manager=set_manager)
            idx = screen.set_filter.findData("set-a")
            self.assertGreaterEqual(idx, 0)

            screen.set_filter.setCurrentIndex(idx)
            screen.refresh()

            visible_ids = {
                screen.question_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(screen.question_list.count())
            }
            self.assertEqual({"q1", "q3"}, visible_ids)

    def test_question_bank_screen_assigns_new_manual_question_to_current_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            screen = QuestionBankScreen(question_bank)
            screen.set_current_course("course-a")
            screen._new_question()

            screen.form_editor.zh_stem_editor.setPlainText("哪个答案正确？")
            screen.form_editor.zh_explanation_editor.setPlainText("A 是正确答案。")
            screen.form_editor.en_stem_editor.setPlainText("Which answer is correct?")
            screen.form_editor.en_explanation_editor.setPlainText("A is the correct answer.")
            for row in range(4):
                screen.form_editor.choice_table.item(row, 1).setText(f"中文选项 {row + 1}")
                screen.form_editor.choice_table.item(row, 2).setText(f"Option {row + 1}")

            with patch("ui.screens.question_bank_screen.QMessageBox.information"):
                screen._save_question()

            saved = question_bank.load_all()
            self.assertEqual(1, len(saved))
            self.assertEqual("course-a", saved[0].metadata.get("course_id"))

    def test_question_and_set_save_reject_path_traversal_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            question_bank = QuestionBank(str(root / "questions"))
            unsafe_question = self._question("../outside")

            with self.assertRaises(ValueError):
                question_bank.save(unsafe_question)

            self.assertFalse((root / "outside.json").exists())

            set_manager = SetManager(str(root / "sets"))
            unsafe_set = self._set("../outside-set", ["q1"])

            with self.assertRaises(ValueError):
                set_manager.save(unsafe_set)

            self.assertFalse((root / "outside-set.json").exists())

    def test_question_bank_save_does_not_cache_question_when_disk_write_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question = self._question("q-unsaved")

            with patch("models.question.write_json", return_value=False):
                ok = question_bank.save(question)

            self.assertFalse(ok)
            self.assertIsNone(question_bank.get("q-unsaved"))
            self.assertEqual([], question_bank.load_all())

    def test_set_manager_save_does_not_cache_set_when_disk_write_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            qset = self._set("set-unsaved", ["q1"])

            with patch("models.question_set.write_json", return_value=False):
                ok = set_manager.save(qset)

            self.assertFalse(ok)
            self.assertIsNone(set_manager.get("set-unsaved"))
            self.assertEqual([], set_manager.load_all())

    def test_set_manager_get_refreshes_when_cached_file_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            qset = self._set("set-stale", ["q1"])
            set_manager.save(qset)

            cached = set_manager.get("set-stale")
            self.assertEqual(["q1"], cached.questions)

            changed = self._set("set-stale", ["q2"])
            changed.title = {"zh": "更新后", "en": "Updated"}
            write_json(str(Path(tmpdir) / "sets" / "set-stale.json"), changed.to_dict())

            refreshed = set_manager.get("set-stale")

            self.assertEqual(["q2"], refreshed.questions)
            self.assertEqual("更新后", refreshed.get_title("zh"))

    def test_progress_save_rejects_path_traversal_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = ProgressManager(str(root / "progress"))
            record = ProgressRecord.create_new("set-a")
            record.progress_id = "../outside-progress"

            with self.assertRaises(ValueError):
                manager.save(record)

            self.assertFalse((root / "outside-progress.json").exists())

    def test_question_bank_screen_delete_prunes_question_sets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            q1 = self._question("q1")
            q2 = self._question("q2")
            question_bank.save_many([q1, q2])
            qset = self._set("set-a", ["q1", "q2"])
            set_manager.save(qset)

            screen = QuestionBankScreen(question_bank, set_manager=set_manager)
            screen.refresh()
            for row in range(screen.question_list.count()):
                item = screen.question_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == "q1":
                    screen.question_list.setCurrentRow(row)
                    break

            with patch("ui.screens.question_bank_screen.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                screen.delete_btn.click()

            self.assertIsNone(question_bank.get("q1"))
            self.assertEqual(["q2"], set_manager.get(qset.set_id).questions)

    def test_question_bank_screen_delete_removes_empty_question_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            q1 = self._question("q1")
            q2 = self._question("q2")
            question_bank.save_many([q1, q2])
            qset = self._set("set-empty-after-delete", ["q1", "q2"])
            set_manager.save(qset)

            screen = QuestionBankScreen(question_bank, set_manager=set_manager)
            for row in range(screen.question_list.count()):
                item = screen.question_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) in {"q1", "q2"}:
                    item.setSelected(True)
            screen._on_selection_changed()

            with patch("ui.screens.question_bank_screen.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                screen.delete_btn.click()

            self.assertIsNone(question_bank.get("q1"))
            self.assertIsNone(question_bank.get("q2"))
            self.assertIsNone(set_manager.get(qset.set_id))
            self.assertEqual(-1, screen.set_filter.findData(qset.set_id))

    def test_question_bank_screen_uses_compact_single_line_titles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            noisy = self._question("q-noisy", "输入输出系统与中断控制" * 3)
            noisy.bilingual["zh"]["stem"] = (
                "I/O 中断流程中 CPU、设备控制器和内存之间的核心协作是什么？\n"
                "A. 这是选项噪音，不应该进入列表标题\n"
                "B. 这也是选项噪音\n"
                "解析：这是题目解析噪音，也不应该进入标题"
            )
            question_bank.save(noisy)

            screen = QuestionBankScreen(question_bank)
            item = screen.question_list.item(0)

            self.assertLessEqual(len(item.text()), 96)
            self.assertNotIn("\n", item.text())
            self.assertNotIn("选项噪音", item.text())
            self.assertNotIn("解析", item.text())
            self.assertIn("I/O 中断流程", item.toolTip())
            self.assertIn("选项噪音", item.toolTip())

    def test_question_bank_screen_displays_topic_title_not_internal_topic_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            topic = CourseTopic(topic_id="interrupt_io", title="Interrupt-driven I/O")
            question = self._question("q-topic-title", topic)
            question.bilingual["zh"]["stem"] = "中断驱动 I/O 的核心流程是什么？"
            question.bilingual["en"]["stem"] = "What is the core flow of interrupt-driven I/O?"
            question_bank.save(question)

            screen = QuestionBankScreen(question_bank)
            item = screen.question_list.item(0)

            self.assertIn("Interrupt-driven I/O", item.text())
            self.assertIn("Interrupt-driven I/O", item.toolTip())
            self.assertNotIn("interrupt_io", item.text())

    def test_question_bank_screen_selects_first_question_after_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question = self._question("q-first", "cache")
            question_bank.save(question)

            screen = QuestionBankScreen(question_bank)

            self.assertEqual("q-first", screen.current_question_id)
            self.assertIn('"question_id": "q-first"', screen.editor.toPlainText())
            self.assertTrue(screen.save_btn.isEnabled())
            self.assertTrue(screen.delete_btn.isEnabled())

    def test_question_bank_screen_uses_structured_editor_for_selected_question(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question = self._question("q-form", "interrupt_io")
            question.bilingual["zh"]["stem"] = "中断驱动 I/O 如何减少忙等？"
            question_bank.save(question)

            screen = QuestionBankScreen(question_bank)

            self.assertIs(screen.detail_stack.currentWidget(), screen.form_editor)
            self.assertEqual("q-form", screen.current_question_id)
            self.assertEqual(
                "中断驱动 I/O 如何减少忙等？",
                screen.form_editor.zh_stem_editor.toPlainText(),
            )
            self.assertEqual("interrupt_io", screen.form_editor.topic_combo.currentData())
            self.assertTrue(screen.editor_mode_btn.isEnabled())

    def test_question_bank_screen_round_trips_advanced_json_back_to_form(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save(self._question("q-advanced", "cache"))
            screen = QuestionBankScreen(question_bank)

            screen.editor_mode_btn.click()
            self.assertIs(screen.detail_stack.currentWidget(), screen.editor)
            payload = json.loads(screen.editor.toPlainText())
            payload["bilingual"]["zh"]["stem"] = "由高级 JSON 修改的题干"
            screen.editor.setPlainText(json.dumps(payload, ensure_ascii=False))

            screen.editor_mode_btn.click()

            self.assertIs(screen.detail_stack.currentWidget(), screen.form_editor)
            self.assertEqual(
                "由高级 JSON 修改的题干",
                screen.form_editor.zh_stem_editor.toPlainText(),
            )

    def test_question_bank_screen_saves_structured_matching_edits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save(Question(
                question_id="q-match-form",
                type=QuestionType.MATCHING,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "配对",
                        "options": {
                            "left": [{"id": "left_dma", "text": "DMA"}],
                            "right": [{"id": "right_direct", "text": "直接内存访问"}],
                        },
                        "explanation": "正确配对。",
                    },
                    "en": {
                        "stem": "Match",
                        "options": {
                            "left": [{"id": "left_dma", "text": "DMA"}],
                            "right": [{"id": "right_direct", "text": "Direct memory access"}],
                        },
                        "explanation": "Correct pair.",
                    },
                },
                correct_answer=[["left_dma", "right_direct"]],
                topic="io",
            ))
            screen = QuestionBankScreen(question_bank)
            screen.form_editor.matching_table.item(0, 4).setText("Direct memory transfer")

            with (
                patch("ui.screens.question_bank_screen.QMessageBox.information"),
                patch("ui.screens.question_bank_screen.QMessageBox.warning") as warning,
            ):
                screen._save_question()

            warning.assert_not_called()
            saved = question_bank.get("q-match-form")
            self.assertEqual(QuestionType.MATCHING, saved.type)
            self.assertEqual([["left_dma", "right_direct"]], saved.correct_answer)
            self.assertEqual(
                "Direct memory transfer",
                saved.bilingual["en"]["options"]["right"][0]["text"],
            )

    def test_question_bank_screen_shows_empty_state_when_no_questions_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save(self._question("q-first", "cache"))
            screen = QuestionBankScreen(question_bank)

            screen.search_input.setText("no-matching-question")
            screen._reset_and_refresh()

            self.assertEqual("", screen.current_question_id)
            self.assertIn("没有匹配的题目", screen.editor.toPlainText())
            self.assertTrue(screen.editor.isReadOnly())
            self.assertFalse(screen.save_btn.isEnabled())
            self.assertFalse(screen.delete_btn.isEnabled())

    def test_question_bank_screen_uses_user_friendly_source_refs_label(self):
        lang_manager = LanguageManager.instance()
        previous_lang = lang_manager.current
        self.addCleanup(lang_manager.set_language, previous_lang)

        with tempfile.TemporaryDirectory() as tmpdir:
            screen = QuestionBankScreen(
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            lang_manager.set_language("zh")
            self.assertNotIn("补全", screen.backfill_source_refs_btn.text())
            self.assertNotIn("来源证据", screen.backfill_source_refs_btn.text())
            self.assertIn("关联课程原文", screen.backfill_source_refs_btn.text())

            lang_manager.set_language("en")
            self.assertNotIn("Backfill", screen.backfill_source_refs_btn.text())
            self.assertIn("Link to Course Materials", screen.backfill_source_refs_btn.text())

    def test_question_bank_screen_displays_source_refs_in_detail_panel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question = self._question("q-source", "cache")
            question.metadata["source_refs"] = [
                {
                    "chunk_id": "source-0007",
                    "source_file": "第21讲 Cache.pdf",
                    "page_or_slide": 8,
                    "heading": "Cache Address Breakdown",
                }
            ]
            question_bank.save(question)

            screen = QuestionBankScreen(question_bank)
            item = screen.question_list.item(0)
            screen.question_list.setCurrentItem(item)
            screen._on_selection_changed()

            source_text = screen.source_refs_label.text()
            self.assertIn("第21讲 Cache.pdf", source_text)
            self.assertIn("页码/幻灯片 8", source_text)
            self.assertIn("source-0007", source_text)
            self.assertIn("Cache Address Breakdown", source_text)
            self.assertFalse(screen.source_refs_label.isHidden())

    def test_question_bank_screen_filters_source_and_quality_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            exact = self._question("q-exact", "cache")
            exact.metadata["source_ref_status"] = "valid_model_ref"
            exact.metadata["source_refs"] = [{"chunk_id": "source-0001"}]

            missing = self._question("q-missing-source", "cache")
            missing.metadata["source_ref_status"] = "missing"

            fallback = self._question("q-fallback-source", "cache")
            fallback.metadata["source_ref_status"] = "fallback_global_evidence"
            fallback.metadata["source_refs"] = [{"chunk_id": "source-0002"}]

            weak_plan = self._question("q-weak-plan", "cache")
            weak_plan.metadata["plan_match_status"] = "matched_by_shape"
            weak_plan.metadata["source_ref_status"] = "valid_model_ref"
            weak_plan.metadata["source_refs"] = [{"chunk_id": "source-0003"}]

            question_bank.save_many([exact, missing, fallback, weak_plan])
            screen = QuestionBankScreen(question_bank)

            def visible_ids() -> set[str]:
                return {
                    screen.question_list.item(row).data(Qt.ItemDataRole.UserRole)
                    for row in range(screen.question_list.count())
                }

            quality_idx = screen.quality_filter.findData("quality_warnings")
            self.assertGreaterEqual(quality_idx, 0)
            screen.quality_filter.setCurrentIndex(quality_idx)
            self.assertEqual({"q-missing-source", "q-fallback-source", "q-weak-plan"}, visible_ids())

            missing_idx = screen.quality_filter.findData("missing_source")
            screen.quality_filter.setCurrentIndex(missing_idx)
            self.assertEqual({"q-missing-source"}, visible_ids())

            fallback_idx = screen.quality_filter.findData("fallback_source")
            screen.quality_filter.setCurrentIndex(fallback_idx)
            self.assertEqual({"q-fallback-source"}, visible_ids())

            weak_plan_idx = screen.quality_filter.findData("weak_plan")
            screen.quality_filter.setCurrentIndex(weak_plan_idx)
            self.assertEqual({"q-weak-plan"}, visible_ids())

    def test_question_bank_screen_multi_selection_disables_ambiguous_editing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save_many([self._question("q1"), self._question("q2")])

            screen = QuestionBankScreen(question_bank)
            self.assertEqual(
                QAbstractItemView.SelectionMode.ExtendedSelection,
                screen.question_list.selectionMode(),
            )

            screen.question_list.item(0).setSelected(True)
            screen.question_list.item(1).setSelected(True)
            screen._on_selection_changed()

            self.assertEqual("", screen.current_question_id)
            self.assertIn("2", screen.editor.toPlainText())
            self.assertFalse(screen.save_btn.isEnabled())
            self.assertTrue(screen.delete_btn.isEnabled())

    def test_question_bank_screen_batch_delete_prunes_question_sets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            q1 = self._question("q1")
            q2 = self._question("q2")
            q3 = self._question("q3")
            question_bank.save_many([q1, q2, q3])
            qset = self._set("set-a", ["q1", "q2", "q3"])
            set_manager.save(qset)

            screen = QuestionBankScreen(question_bank, set_manager=set_manager)
            changed = []
            screen.question_bank_changed.connect(lambda: changed.append(True))
            for row in range(screen.question_list.count()):
                item = screen.question_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) in {"q1", "q2"}:
                    item.setSelected(True)
            screen._on_selection_changed()

            with patch("ui.screens.question_bank_screen.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                screen.delete_btn.click()

            self.assertIsNone(question_bank.get("q1"))
            self.assertIsNone(question_bank.get("q2"))
            self.assertIsNotNone(question_bank.get("q3"))
            self.assertEqual(["q3"], set_manager.get(qset.set_id).questions)
            self.assertEqual(1, len(changed))

    def test_regeneration_cleanup_deletes_only_truly_orphaned_ai_questions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))
            progress_manager = ProgressManager(str(root / "progress"))

            orphan = self._question("q-orphan")
            orphan.metadata["source"] = "ai_generated"
            shared = self._question("q-shared")
            shared.metadata["source"] = "ai_generated"
            historical = self._question("q-history")
            historical.metadata["source"] = "ai_generated"
            manual = self._question("q-manual")
            manual.metadata["source"] = "manual"
            question_bank.save_many([orphan, shared, historical, manual])

            set_manager.save(self._set("set-other", ["q-shared"]))
            record = ProgressRecord.create_new("set-regenerated")
            record.answers = [
                AnswerRecord(
                    question_id="q-history",
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                )
            ]
            progress_manager.save(record)

            deleted = delete_unreferenced_ai_questions(
                question_bank,
                set_manager,
                ["q-orphan", "q-shared", "q-history", "q-manual"],
                progress_manager=progress_manager,
            )

            self.assertEqual(["q-orphan"], deleted)
            self.assertIsNone(question_bank.get("q-orphan"))
            self.assertIsNotNone(question_bank.get("q-shared"))
            self.assertIsNotNone(question_bank.get("q-history"))
            self.assertIsNotNone(question_bank.get("q-manual"))


if __name__ == "__main__":
    unittest.main()
