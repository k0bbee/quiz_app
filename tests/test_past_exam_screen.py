import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QSplitter

from core.language_manager import LanguageManager
from models.past_exam import (
    PastExamAnalysis,
    PastExamContent,
    PastExamManager,
    PastExamQuestionTypeProfile,
    PastExamRecord,
    PastExamTopicProfile,
)
from ui.screens.past_exam_screen import PastExamScreen


_APP = QApplication.instance() or QApplication([])


class PastExamScreenTests(unittest.TestCase):
    def doCleanups(self):
        result = super().doCleanups()
        for widget in QApplication.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _APP.processEvents()
        return result

    def test_screen_uses_workbench_layout_and_bounds_large_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PastExamManager(tmpdir)
            record = self._record(course_id="course-a", assignment_mode="manual")
            manager.save_record(record)
            manager.save_content(record.exam_id, PastExamContent("Question\n" * 10000, ["Question"]))
            screen = PastExamScreen(manager, self._course_manager())

            self.assertIsInstance(screen.workspace_splitter, QSplitter)
            self.assertEqual(1, screen.exam_list.count())
            self.assertEqual(0, screen.exam_list.currentRow())

            preview = screen.content_preview.toPlainText()
            self.assertLess(len(preview), 45000)
            self.assertIn("预览已截断", preview)
            self.assertIn("Systems", screen.assignment_status.text())
            self.assertEqual("course-a", screen.assignment_combo.currentData())
            for button in (
                screen.browse_btn,
                screen.import_btn,
                screen.save_assignment_btn,
                screen.analyze_btn,
                screen.predict_btn,
            ):
                self.assertTrue(button.icon().isNull())

    def test_import_worker_receives_manual_or_automatic_assignment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "exam.txt"
            source.write_text("Question one", encoding="utf-8")
            screen = PastExamScreen(PastExamManager(root / "past_exams"), self._course_manager())
            screen.file_input.setText(str(source))
            screen.title_input.setText("2025 Final")
            screen.import_course_combo.setCurrentIndex(
                screen.import_course_combo.findData("course-a")
            )

            worker = screen._create_import_worker()

            self.assertEqual(source, worker.source_path)
            self.assertEqual("2025 Final", worker.title)
            self.assertEqual("course-a", worker.manual_course_id)

            screen.import_course_combo.setCurrentIndex(
                screen.import_course_combo.findData(None)
            )
            self.assertIsNone(screen._create_import_worker().manual_course_id)

            screen.import_course_combo.setCurrentIndex(
                screen.import_course_combo.findData("")
            )
            self.assertEqual("", screen._create_import_worker().manual_course_id)

    def test_user_can_reassign_or_unassign_an_imported_exam(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PastExamManager(tmpdir)
            record = self._record(course_id="", assignment_mode="unassigned")
            manager.save_record(record)
            manager.save_content(record.exam_id, PastExamContent("Question one", ["Question one"]))
            screen = PastExamScreen(manager, self._course_manager())
            screen.exam_list.setCurrentRow(0)
            self.assertIn("建议", screen.assignment_status.text())
            self.assertIn("Systems", screen.assignment_status.text())
            screen.assignment_combo.setCurrentIndex(
                screen.assignment_combo.findData("course-b")
            )

            screen.save_assignment_btn.click()

            self.assertEqual("course-b", manager.get(record.exam_id).course_id)
            self.assertIn("Marxism", screen.assignment_status.text())

            screen.assignment_combo.setCurrentIndex(screen.assignment_combo.findData(""))
            screen.save_assignment_btn.click()
            self.assertEqual("", manager.get(record.exam_id).course_id)

    def test_shutdown_requests_cancellation_without_waiting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = PastExamScreen(PastExamManager(tmpdir), self._course_manager())
            worker = Mock()
            worker.isRunning.return_value = True
            screen._import_worker = worker

            self.assertFalse(screen.request_shutdown())

            worker.cancel.assert_called_once_with()

    def test_analysis_conflict_message_explains_that_stale_result_was_not_saved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = PastExamScreen(PastExamManager(tmpdir), self._course_manager())

            with patch("ui.screens.past_exam_screen.QMessageBox.critical") as critical:
                screen._on_analysis_failed(
                    "Historical exam changed during analysis; run analysis again"
                )

            message = critical.call_args.args[2]
            self.assertIn("课程归属已变化", message)
            self.assertIn("未保存", message)
            self.assertIn("重新分析", message)

    def test_analysis_action_requires_course_and_displays_explainable_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PastExamManager(tmpdir)
            record = self._record(course_id="course-a", assignment_mode="manual")
            manager.save_record(record)
            manager.save_content(record.exam_id, PastExamContent("一、判断题\n1. I/O 中断。（ ）"))
            analysis = PastExamAnalysis(
                source_sha256=record.source_sha256,
                analyzed_at="2026-07-13T00:00:00+00:00",
                detected_question_count=1,
                question_types=(PastExamQuestionTypeProfile("true_false", 1, 0.95, ("一、判断题",)),),
                topic_profile=(PastExamTopicProfile("io", "I/O 中断", 100, 2, ("i o 中断",)),),
            )
            manager.save_analysis(record.exam_id, analysis)
            manager.save_record(PastExamRecord.from_dict({
                **record.to_dict(),
                "analysis_status": "complete",
            }))

            screen = PastExamScreen(manager, self._course_manager(with_topics=True))

            self.assertTrue(screen.analyze_btn.isEnabled())
            self.assertTrue(screen.predict_btn.isEnabled())
            screen._set_import_busy(True)
            self.assertFalse(screen.assignment_combo.isEnabled())
            self.assertFalse(screen.save_assignment_btn.isEnabled())
            self.assertFalse(screen.analyze_btn.isEnabled())
            self.assertFalse(screen.predict_btn.isEnabled())
            screen._set_import_busy(False)
            self.assertTrue(screen.assignment_combo.isEnabled())
            self.assertTrue(screen.predict_btn.isEnabled())
            self.assertIn("1 题", screen.analysis_summary.text())
            self.assertIn("判断题 1", screen.analysis_summary.text())
            self.assertIn("I/O 中断 100%", screen.analysis_summary.text())
            self.assertIn("i o 中断", screen.analysis_summary.text())
            self.assertTrue(screen.analyze_btn.icon().isNull())
            self.assertTrue(screen.predict_btn.icon().isNull())

            requested = []
            screen.prediction_requested.connect(lambda course_id, prediction: requested.append((course_id, prediction)))
            screen.predict_btn.click()
            self.assertEqual("course-a", requested[0][0])
            self.assertEqual((record.exam_id,), requested[0][1].exam_ids)
            self.assertEqual(("io",), requested[0][1].plan.selected_topics)

            manager.reassign_course(record.exam_id, "")
            screen.refresh()
            screen._select_exam(record.exam_id)
            self.assertFalse(screen.analyze_btn.isEnabled())
            self.assertFalse(screen.predict_btn.isEnabled())
            self.assertIn("归属课程", screen.analysis_summary.text())

    @staticmethod
    def _record(course_id="", assignment_mode="unassigned"):
        return PastExamRecord(
            exam_id="past-exam-a",
            title="2025 Final",
            source_filename="exam.pdf",
            source_path="source/exam.pdf",
            content_path="content.json",
            source_sha256="abc123",
            imported_at="2026-07-13T00:00:00+00:00",
            course_id=course_id,
            assignment_mode=assignment_mode,
            match_candidates=[{
                "course_id": "course-a",
                "course_title": "Systems",
                "score": 0.31,
                "matched_terms": ["input output", "dma"],
            }],
            warnings=["Page 1 text recovered by OCR fallback"],
        )

    @staticmethod
    def _course_manager(with_topics=False):
        topics = [SimpleNamespace(
            topic_id="io",
            title="I/O 中断",
            aliases=[],
            keywords=["中断"],
        )] if with_topics else []
        courses = [
            SimpleNamespace(course_id="course-a", title="Systems", topics=topics),
            SimpleNamespace(course_id="course-b", title="Marxism", topics=[]),
        ]
        by_id = {course.course_id: course for course in courses}
        return SimpleNamespace(
            load_all=lambda: list(courses),
            get=lambda course_id: by_id.get(course_id),
        )


if __name__ == "__main__":
    unittest.main()
