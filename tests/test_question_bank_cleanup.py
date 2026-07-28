import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QAbstractItemView, QTableView

from core import course_index
from core.language_manager import LanguageManager
from core.background_task import TaskProgress
from core.background_task_center import BackgroundTaskCenter, TaskStatus
from core.question_quality_scan import QuestionQualityResult, QuestionQualityScanReport
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from ui.screens.question_bank_screen import QuestionBankScreen, QuestionQualityScanWorker
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class ManualSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class ManualQualityScanWorker:
    def __init__(self):
        self.progressed = ManualSignal()
        self.completed = ManualSignal()
        self.failed = ManualSignal()
        self.cancelled = ManualSignal()
        self.started = False
        self.cancel_called = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancel_called = True


class QuestionBankCleanupTests(unittest.TestCase):
    def test_question_bank_screen_requires_course_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))

            with self.assertRaises(TypeError):
                QuestionBankScreen(question_bank)

    def _screen(
        self,
        root: str | Path,
        question_bank: QuestionBank,
        *,
        set_manager: SetManager | None = None,
        course_manager: CourseProjectManager | None = None,
        task_center=None,
    ) -> QuestionBankScreen:
        return QuestionBankScreen(
            question_bank,
            set_manager=set_manager,
            course_manager=course_manager
            or CourseProjectManager(str(Path(root) / "courses")),
            task_center=task_center,
        )

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

    @staticmethod
    def _visible_question_ids(screen: QuestionBankScreen) -> set[str]:
        model = screen.question_table.model()
        return {
            str(model.index(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(model.rowCount())
        }

    @staticmethod
    def _select_question_ids(
        screen: QuestionBankScreen,
        question_ids: set[str],
    ) -> None:
        model = screen.question_table.model()
        selection_model = screen.question_table.selectionModel()
        selection_model.clearSelection()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if index.data(Qt.ItemDataRole.UserRole) in question_ids:
                selection_model.select(
                    index,
                    selection_model.SelectionFlag.Select
                    | selection_model.SelectionFlag.Rows,
                )

    def test_question_bank_screen_uses_structured_row_selection_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save(self._question("q-table", "cache"))

            screen = self._screen(tmpdir, question_bank)

            self.assertIsInstance(screen.question_table, QTableView)
            self.assertFalse(hasattr(screen, "question_list"))
            self.assertEqual(
                QAbstractItemView.SelectionBehavior.SelectRows,
                screen.question_table.selectionBehavior(),
            )
            self.assertEqual(
                QAbstractItemView.SelectionMode.ExtendedSelection,
                screen.question_table.selectionMode(),
            )
            self.assertFalse(screen.question_table.wordWrap())
            model = screen.question_table.model()
            self.assertEqual(5, model.columnCount())
            self.assertEqual(
                ["题目", "主题", "题型", "难度", "状态"],
                [
                    model.headerData(
                        column,
                        Qt.Orientation.Horizontal,
                        Qt.ItemDataRole.DisplayRole,
                    )
                    for column in range(model.columnCount())
                ],
            )
            self.assertEqual(
                "q-table",
                model.index(0, 0).data(Qt.ItemDataRole.UserRole),
            )
            self.assertEqual("cache question", model.index(0, 0).data())
            self.assertEqual("cache", model.index(0, 1).data())
            self.assertEqual("选择题", model.index(0, 2).data())
            self.assertEqual("中等", model.index(0, 3).data())

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
            screen.question_table.selectRow(0)

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

    def test_question_bank_screen_filters_generated_questions_by_current_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_a = self._question("q-course-a")
            course_a.metadata["course_id"] = "course-a"
            course_b = self._question("q-course-b")
            course_b.metadata["course_id"] = "course-b"
            manual = self._question("q-manual")
            question_bank.save_many([course_a, course_b, manual])

            screen = self._screen(tmpdir, question_bank)
            screen.set_current_course("course-a")
            screen.refresh()

            visible_ids = self._visible_question_ids(screen)
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

            screen = self._screen(tmpdir, question_bank, set_manager=set_manager)
            idx = screen.set_filter.findData("set-a")
            self.assertGreaterEqual(idx, 0)

            screen.set_filter.setCurrentIndex(idx)
            screen.refresh()

            visible_ids = self._visible_question_ids(screen)
            self.assertEqual({"q1", "q3"}, visible_ids)

    def test_question_bank_screen_assigns_new_manual_question_to_current_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            screen = self._screen(tmpdir, question_bank)
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

    def test_question_bank_screen_delete_prunes_question_sets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            q1 = self._question("q1")
            q2 = self._question("q2")
            question_bank.save_many([q1, q2])
            qset = self._set("set-a", ["q1", "q2"])
            set_manager.save(qset)

            screen = self._screen(tmpdir, question_bank, set_manager=set_manager)
            screen.refresh()
            self._select_question_ids(screen, {"q1"})

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

            screen = self._screen(tmpdir, question_bank, set_manager=set_manager)
            self._select_question_ids(screen, {"q1", "q2"})

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

            screen = self._screen(tmpdir, question_bank)
            model = screen.question_table.model()
            stem_index = model.index(0, 0)

            self.assertLessEqual(len(stem_index.data()), 96)
            self.assertNotIn("\n", stem_index.data())
            self.assertNotIn("选项噪音", stem_index.data())
            self.assertNotIn("解析", stem_index.data())
            self.assertIn(
                "I/O 中断流程",
                stem_index.data(Qt.ItemDataRole.ToolTipRole),
            )
            self.assertIn(
                "选项噪音",
                stem_index.data(Qt.ItemDataRole.ToolTipRole),
            )

    def test_question_bank_screen_displays_topic_title_not_internal_topic_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            topic = CourseTopic(topic_id="interrupt_io", title="Interrupt-driven I/O")
            question = self._question("q-topic-title", topic)
            question.bilingual["zh"]["stem"] = "中断驱动 I/O 的核心流程是什么？"
            question.bilingual["en"]["stem"] = "What is the core flow of interrupt-driven I/O?"
            question_bank.save(question)

            screen = self._screen(tmpdir, question_bank)
            model = screen.question_table.model()
            topic_index = model.index(0, 1)

            self.assertEqual("Interrupt-driven I/O", topic_index.data())
            self.assertIn(
                "Interrupt-driven I/O",
                topic_index.data(Qt.ItemDataRole.ToolTipRole),
            )
            self.assertNotIn("interrupt_io", topic_index.data())

    def test_question_bank_screen_selects_first_question_after_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question = self._question("q-first", "cache")
            question_bank.save(question)

            screen = self._screen(tmpdir, question_bank)

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

            screen = self._screen(tmpdir, question_bank)

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
            screen = self._screen(tmpdir, question_bank)

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
            screen = self._screen(tmpdir, question_bank)
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
            screen = self._screen(tmpdir, question_bank)

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
            screen = self._screen(
                tmpdir,
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

            screen = self._screen(tmpdir, question_bank)

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
            screen = self._screen(tmpdir, question_bank)

            def visible_ids() -> set[str]:
                return self._visible_question_ids(screen)

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

    def test_question_bank_quality_scan_tracks_progress_and_safe_cancel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bank = QuestionBank(str(root / "questions"))
            bank.save_many([self._question("q1"), self._question("q2")])
            center = BackgroundTaskCenter(root / "tasks.json")
            screen = self._screen(tmpdir, bank, task_center=center)
            worker = ManualQualityScanWorker()

            with patch(
                "ui.screens.question_bank_screen.QuestionQualityScanWorker",
                return_value=worker,
            ):
                screen.scan_quality_btn.click()

                snapshot = center.snapshots()[0]
                self.assertEqual("question_bank_validation", snapshot.kind)
                self.assertTrue(worker.started)
                self.assertFalse(screen.quality_scan_status_label.isHidden())
                self.assertFalse(screen.cancel_quality_scan_btn.isHidden())
                self.assertFalse(screen.question_table.isEnabled())
                self.assertFalse(screen.save_btn.isEnabled())

                worker.progressed.emit(TaskProgress("validating_question", 2, 8, "q2"))
                self.assertIn("2/8", screen.quality_scan_status_label.text())
                self.assertIn("q2", screen.quality_scan_status_label.text())

                screen.cancel_quality_scan_btn.click()

            self.assertEqual(TaskStatus.CANCELLED, center.get(snapshot.task_id).status)
            self.assertTrue(worker.cancel_called)
            self.assertFalse(screen.cancel_quality_scan_btn.isEnabled())

    def test_question_bank_quality_scan_result_drives_warning_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bank = QuestionBank(str(Path(tmpdir) / "questions"))
            bank.save_many([self._question("clean"), self._question("broken")])
            screen = self._screen(tmpdir, bank)
            worker = ManualQualityScanWorker()
            report = QuestionQualityScanReport(
                scanned_count=2,
                results=(
                    QuestionQualityResult("clean"),
                    QuestionQualityResult("broken", structural_errors=("invalid",)),
                ),
            )

            with patch(
                "ui.screens.question_bank_screen.QuestionQualityScanWorker",
                return_value=worker,
            ):
                screen.scan_quality_btn.click()
                worker.completed.emit(report)

            warning_index = screen.quality_filter.findData("quality_warnings")
            screen.quality_filter.setCurrentIndex(warning_index)
            visible_ids = self._visible_question_ids(screen)
            self.assertEqual({"broken"}, visible_ids)
            self.assertIn("1/2", screen.quality_scan_status_label.text())

    def test_question_quality_worker_completes_persistent_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bank = QuestionBank(str(root / "questions"))
            bank.save_many([self._question("q1"), self._question("q2")])
            center = BackgroundTaskCenter(root / "tasks.json")
            snapshot = center.create(
                kind="question_bank_validation",
                title="Validate question bank",
            )
            worker = QuestionQualityScanWorker(
                bank,
                task_center=center,
                task_id=snapshot.task_id,
            )
            reports = []
            worker.completed.connect(reports.append)

            worker.run()

            completed = center.get(snapshot.task_id)
            self.assertEqual(TaskStatus.COMPLETED, completed.status)
            self.assertEqual(2, completed.result_count)
            self.assertEqual(2, reports[0].scanned_count)

    def test_question_bank_quality_filter_uses_shared_option_bias_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            biased = self._question("q-biased", "cache")
            biased.bilingual["zh"]["options"] = [
                "A. " + "正确答案内容" * 6,
                "B. 干扰项",
                "C. 干扰项",
                "D. 干扰项",
            ]
            biased.correct_answer = "A"
            question_bank.save(biased)

            screen = self._screen(tmpdir, question_bank)
            quality_idx = screen.quality_filter.findData("quality_warnings")
            screen.quality_filter.setCurrentIndex(quality_idx)

            visible_ids = self._visible_question_ids(screen)
            self.assertEqual({"q-biased"}, visible_ids)

    def test_question_bank_screen_multi_selection_disables_ambiguous_editing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save_many([self._question("q1"), self._question("q2")])

            screen = self._screen(tmpdir, question_bank)
            self.assertEqual(
                QAbstractItemView.SelectionMode.ExtendedSelection,
                screen.question_table.selectionMode(),
            )

            self._select_question_ids(screen, {"q1", "q2"})

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

            screen = self._screen(tmpdir, question_bank, set_manager=set_manager)
            changed = []
            screen.question_bank_changed.connect(lambda: changed.append(True))
            self._select_question_ids(screen, {"q1", "q2"})

            with patch("ui.screens.question_bank_screen.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                screen.delete_btn.click()

            self.assertIsNone(question_bank.get("q1"))
            self.assertIsNone(question_bank.get("q2"))
            self.assertIsNotNone(question_bank.get("q3"))
            self.assertEqual(["q3"], set_manager.get(qset.set_id).questions)
            self.assertEqual(1, len(changed))

if __name__ == "__main__":
    unittest.main()
