import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ai.course_qa import CourseQAError, CourseQAResponse
from models.course_project import CourseProject, CourseTopic
from ui.widgets.course_qa_panel import CourseQAPanel


_APP = QApplication.instance() or QApplication([])


def make_project():
    return CourseProject(
        course_id="qa-panel-course",
        title="I/O",
        source_folder="C:/materials",
        summary_markdown="# I/O\nDMA moves blocks without CPU copying every byte.",
        summary_path="C:/materials/summary.md",
        topics=[CourseTopic("io", "I/O")],
        documents=[],
        created_at="",
        updated_at="",
    )


class ImmediateService:
    def __init__(self, response):
        self.response = response
        self.questions = []

    def ask(self, question, *, history, language):
        self.questions.append((question, history, language))
        return self.response

    def cancel(self):
        pass


class BlockingService:
    def __init__(self):
        self.started = threading.Event()
        self.cancelled = False
        self.release = threading.Event()

    def ask(self, question, *, history, language):
        self.started.set()
        self.release.wait(1)
        return CourseQAResponse("late", (), "missing")

    def cancel(self):
        self.cancelled = True
        self.release.set()


class CourseQAPanelTests(unittest.TestCase):
    def test_send_renders_answer_and_source_evidence_without_blocking_ui(self):
        service = ImmediateService(
            CourseQAResponse(
                "DMA uses a controller.",
                ({"chunk_id": "source-1", "source_file": "lecture.pdf", "page_or_slide": 4},),
                "cited",
            )
        )
        panel = CourseQAPanel(lambda _project: service)
        self.addCleanup(panel.deleteLater)
        panel.set_course(make_project())
        panel.input.setPlainText("DMA 是什么？")
        panel.send_btn.click()

        QTest.qWait(100)
        QCoreApplication.processEvents()
        self.assertFalse(panel.is_busy)
        self.assertIn("DMA uses a controller.", panel.transcript.toPlainText())
        self.assertIn("lecture.pdf", panel.transcript.toPlainText())
        self.assertEqual("DMA 是什么？", service.questions[0][0])

    def test_stop_restores_question_and_cancels_request(self):
        service = BlockingService()
        panel = CourseQAPanel(lambda _project: service)
        self.addCleanup(panel.deleteLater)
        panel.set_course(make_project())
        panel.input.setPlainText("请解释 DMA。")
        panel.send_btn.click()
        self.assertTrue(service.started.wait(1))

        panel.stop_btn.click()
        QTest.qWait(30)
        self.assertFalse(panel.is_busy)
        self.assertTrue(service.cancelled)
        self.assertEqual("请解释 DMA。", panel.input.toPlainText())

    def test_factory_errors_are_shown_with_stable_code(self):
        error = CourseQAError(
            __import__("core.app_errors", fromlist=["AppError"]).AppError(
                code="QA-SCOPE-001",
                severity="warning",
                title_zh="超出范围",
                title_en="Out of scope",
                message_zh="请调整考试范围。",
                message_en="Adjust the exam scope.",
            )
        )
        panel = CourseQAPanel(lambda _project: (_ for _ in ()).throw(error))
        self.addCleanup(panel.deleteLater)
        panel.set_course(make_project())
        panel.input.setPlainText("范围外问题")
        panel.send_btn.click()

        self.assertIn("QA-SCOPE-001", panel.status_label.text())


if __name__ == "__main__":
    unittest.main()
