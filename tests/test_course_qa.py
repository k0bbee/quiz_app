import os
import tempfile
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ai.course_qa import CourseQAError, CourseQAResponse, CourseQAService, CourseQATurn
from core.app_errors import AppError
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from ui.screens.course_screen import CourseScreen
from ui.widgets.course_qa_panel import CourseQAPanel


_APP = QApplication.instance() or QApplication([])


class FakeClient:
    def __init__(self, response="I/O uses interrupts. [来源 1]", error=""):
        self.response = response
        self.last_error = error
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.response


def project(selected=True):
    return CourseProject(
        course_id="systems",
        title="Computer Systems",
        source_folder="",
        summary_markdown=(
            "## Input Output\nInterrupt-driven I/O lets the CPU continue until notification.\n\n"
            "## Virtual Memory\nPage replacement chooses a victim page.\n"
        ),
        summary_path="",
        topics=[
            CourseTopic(
                topic_id="input_output",
                title="Input Output",
                keywords=["I/O", "interrupt", "DMA"],
                source_files=["io.pdf"],
            ),
            CourseTopic(
                topic_id="virtual_memory",
                title="Virtual Memory",
                keywords=["page replacement", "address translation"],
                source_files=["memory.pdf"],
            ),
        ],
        documents=[
            {
                "path": "io.pdf",
                "title": "I/O Lecture",
                "extension": ".pdf",
                "pages": ["Interrupt-driven I/O notifies the CPU when the device completes."],
            },
            {
                "path": "memory.pdf",
                "title": "Memory Lecture",
                "extension": ".pdf",
                "pages": ["Virtual memory uses address translation and page replacement."],
            },
        ],
        created_at="2026-07-15T00:00:00+00:00",
        updated_at="2026-07-15T00:00:00+00:00",
        exam_scope_mode="selected" if selected else "all",
        exam_scope_topic_ids=["input_output"] if selected else [],
    )


class CourseQAServiceTests(unittest.TestCase):
    def test_prompt_uses_exam_scope_evidence_and_recent_history(self):
        client = FakeClient()
        service = CourseQAService(client, project())

        result = service.ask(
            "中断驱动 I/O 为什么不需要 CPU 一直轮询？",
            history=[
                CourseQATurn("user", "什么是轮询？"),
                CourseQATurn("assistant", "轮询会反复检查设备状态。"),
            ],
            language="zh",
        )

        self.assertEqual("I/O uses interrupts. [来源 1]", result.answer)
        self.assertEqual("io.pdf", result.source_refs[0]["source_file"])
        messages, kwargs = client.calls[0]
        prompt = "\n".join(message["content"] for message in messages)
        self.assertIn("什么是轮询", prompt)
        self.assertIn("Interrupt-driven I/O", prompt)
        self.assertNotIn("Virtual memory uses address translation", prompt)
        self.assertIn("[来源 1]", prompt)
        self.assertLessEqual(kwargs["max_tokens"], 1800)

    def test_explicit_out_of_scope_topic_is_rejected_before_model_call(self):
        client = FakeClient()
        service = CourseQAService(client, project())

        with self.assertRaises(CourseQAError) as raised:
            service.ask("请解释 Virtual Memory 的 page replacement 算法", language="zh")

        self.assertEqual("QA-SCOPE-001", raised.exception.error.code)
        self.assertIn("Virtual Memory", raised.exception.error.message("zh"))
        self.assertEqual([], client.calls)

    def test_empty_model_response_has_stable_user_facing_error(self):
        client = FakeClient(response=None, error="upstream timeout")
        service = CourseQAService(client, project(selected=False))

        with self.assertRaises(CourseQAError) as raised:
            service.ask("解释 I/O 中断", language="zh")

        self.assertEqual("QA-AI-001", raised.exception.error.code)
        self.assertIn("稍后重试", raised.exception.error.action("zh"))
        self.assertEqual("upstream timeout", raised.exception.error.technical_detail)

    def test_history_is_bounded_before_it_reaches_provider(self):
        client = FakeClient()
        service = CourseQAService(client, project(selected=False), max_history_turns=4)
        history = [CourseQATurn("user", f"turn-{index}") for index in range(10)]

        service.ask("解释 I/O 中断", history=history, language="en")

        messages, _kwargs = client.calls[0]
        combined = "\n".join(message["content"] for message in messages)
        self.assertNotIn("turn-5", combined)
        self.assertIn("turn-6", combined)
        self.assertIn("turn-9", combined)

    def test_selected_scope_never_falls_back_to_tagged_out_of_scope_source(self):
        scoped_project = project()
        scoped_project.documents = [scoped_project.documents[1]]
        client = FakeClient()

        result = CourseQAService(client, scoped_project).ask(
            "解释 Input Output 的中断机制",
            language="zh",
        )

        self.assertEqual((), result.source_refs)
        prompt = "\n".join(message["content"] for message in client.calls[0][0])
        self.assertNotIn("Virtual memory uses address translation", prompt)

    def test_previous_out_of_scope_text_does_not_block_a_valid_new_question(self):
        client = FakeClient()
        service = CourseQAService(client, project())

        service.ask(
            "解释 Input Output 中断",
            history=[CourseQATurn("user", "Earlier I asked about Virtual Memory")],
            language="zh",
        )

        self.assertEqual(1, len(client.calls))

    def test_context_budget_never_truncates_the_student_question(self):
        large_project = project(selected=False)
        large_project.documents = [{
            "path": "io.pdf",
            "title": "Long I/O lecture",
            "extension": ".pdf",
            "pages": [("interrupt controller evidence " * 300) for _ in range(5)],
        }]
        unique_question = "UNIQUE-STUDENT-QUESTION explain interrupt completion"
        client = FakeClient()

        CourseQAService(client, large_project, max_context_chars=2000).ask(
            unique_question,
            language="en",
        )

        final_prompt = client.calls[0][0][-1]["content"]
        self.assertIn(unique_question, final_prompt)
        self.assertLessEqual(len(final_prompt), 2000)


class ImmediateService:
    def ask(self, question, *, history, language):
        return CourseQAResponse(
            answer=f"answer: {question}",
            source_refs=({
                "source_file": "io.pdf",
                "page_or_slide": 1,
                "heading": "I/O Lecture page 1",
                "excerpt": "Interrupt evidence",
            },),
        )


class BlockingService:
    def __init__(self, release):
        self.release = release

    def ask(self, question, *, history, language):
        self.release.wait(timeout=2)
        return CourseQAResponse(answer="late answer", source_refs=())


class ErrorService:
    def ask(self, question, *, history, language):
        raise CourseQAError(AppError(
            code="QA-TEST-001",
            severity="warning",
            title_zh="测试错误",
            title_en="Test Error",
            message_zh="无法回答",
            message_en="Cannot answer",
        ))


class CourseQAPanelTests(unittest.TestCase):
    def _wait_until(self, predicate, timeout=1.5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _APP.processEvents()
            if predicate():
                return True
            QTest.qWait(10)
        return predicate()

    def test_course_screen_toggles_qa_inside_summary_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CourseProjectManager(tmpdir)
            manager.save(project(selected=False))
            screen = CourseScreen(manager, qa_service_factory=lambda _project: ImmediateService())
            screen.project_list.setCurrentRow(0)

            self.assertIs(screen.content_stack.currentWidget(), screen.summary_preview)
            screen.qa_mode_btn.click()
            self.assertIs(screen.content_stack.currentWidget(), screen.qa_panel)
            self.assertEqual("systems", screen.qa_panel.course.course_id)
            screen.qa_mode_btn.click()
            self.assertIs(screen.content_stack.currentWidget(), screen.summary_preview)

    def test_course_task_stops_and_disables_active_qa(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            release = threading.Event()
            manager = CourseProjectManager(tmpdir)
            manager.save(project(selected=False))
            screen = CourseScreen(
                manager,
                qa_service_factory=lambda _project: BlockingService(release),
            )
            screen.project_list.setCurrentRow(0)
            screen.qa_mode_btn.click()
            screen.qa_panel.input.setPlainText("slow question")
            screen.qa_panel.send_btn.click()
            self.assertTrue(screen.qa_panel.is_busy)

            screen._set_course_task_active(True)
            release.set()

            self.assertFalse(screen.qa_panel.is_busy)
            self.assertFalse(screen.qa_panel.isEnabled())

            screen._set_course_task_active(False)
            self.assertTrue(screen.qa_panel.isEnabled())
            self.assertNotIn("正在依据", screen.qa_panel.status_label.text())

    def test_panel_sends_on_enter_and_renders_answer_with_source(self):
        panel = CourseQAPanel(lambda _project: ImmediateService())
        panel.set_course(project(selected=False))
        panel.input.setPlainText("Why interrupts?")

        QTest.keyClick(panel.input, Qt.Key.Key_Return)

        self.assertTrue(self._wait_until(lambda: not panel.is_busy))
        self.assertEqual(["user", "assistant"], [turn.role for turn in panel.turns])
        self.assertIn("answer: Why interrupts?", panel.transcript.toPlainText())
        self.assertIn("io.pdf", panel.transcript.toPlainText())
        self.assertEqual("", panel.input.toPlainText())

    def test_shift_enter_keeps_multiline_input_without_sending(self):
        panel = CourseQAPanel(lambda _project: ImmediateService())
        panel.set_course(project(selected=False))
        panel.input.setPlainText("first line")

        QTest.keyClick(panel.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)

        self.assertFalse(panel.is_busy)
        self.assertIn("\n", panel.input.toPlainText())
        self.assertEqual([], panel.turns)

    def test_stop_restores_draft_and_discards_late_response(self):
        release = threading.Event()
        panel = CourseQAPanel(lambda _project: BlockingService(release))
        panel.set_course(project(selected=False))
        panel.input.setPlainText("slow question")
        panel.send_btn.click()
        self.assertTrue(panel.is_busy)

        panel.stop_btn.click()
        self.assertEqual([], panel.turns)
        self.assertEqual("slow question", panel.input.toPlainText())
        self.assertIn("修改后重试", panel.status_label.text())
        release.set()

        self.assertFalse(panel.is_busy)
        self.assertTrue(panel.input.isEnabled())
        QTest.qWait(100)
        _APP.processEvents()
        self.assertNotIn("late answer", panel.transcript.toPlainText())

    def test_course_switch_retracts_pending_question_without_leaking_draft(self):
        release = threading.Event()
        original = project(selected=False)
        other = project(selected=False)
        other.course_id = "biology"
        other.title = "Biology"
        panel = CourseQAPanel(lambda _project: BlockingService(release))
        panel.set_course(original)
        panel.input.setPlainText("question for systems")
        panel.send_btn.click()

        panel.set_course(other)

        self.assertFalse(panel.is_busy)
        self.assertEqual("", panel.input.toPlainText())
        self.assertEqual([], panel.turns)
        panel.set_course(original)
        self.assertEqual([], panel.turns)
        release.set()
        QTest.qWait(100)
        _APP.processEvents()
        self.assertNotIn("late answer", panel.transcript.toPlainText())

    def test_scope_update_cancels_answer_started_from_stale_course_state(self):
        release = threading.Event()
        panel = CourseQAPanel(lambda _project: BlockingService(release))
        panel.set_course(project(selected=False))
        panel.input.setPlainText("question before scope update")
        panel.send_btn.click()

        panel.set_course(project(selected=True))

        self.assertFalse(panel.is_busy)
        self.assertEqual("selected", panel.course.exam_scope_mode)
        self.assertEqual([], panel.turns)
        release.set()
        QTest.qWait(100)
        _APP.processEvents()
        self.assertNotIn("late answer", panel.transcript.toPlainText())

    def test_failed_question_returns_to_input_and_does_not_pollute_history(self):
        panel = CourseQAPanel(lambda _project: ErrorService())
        panel.set_course(project(selected=False))
        panel.input.setPlainText("retry this")
        panel.send_btn.click()

        self.assertTrue(self._wait_until(lambda: not panel.is_busy))
        self.assertEqual([], panel.turns)
        self.assertEqual("retry this", panel.input.toPlainText())
        self.assertIn("QA-TEST-001", panel.status_label.text())


if __name__ == "__main__":
    unittest.main()
