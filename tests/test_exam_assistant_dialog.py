import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QSplitter

from ai.exam_plan import ExamGenerationPlan, ExamPlanPatch, apply_exam_plan_patch, describe_plan_changes
from ai.exam_request_interpreter import InterpretationResult
from ui.dialogs.exam_assistant_dialog import ExamAssistantDialog


_APP = QApplication.instance() or QApplication([])


class FakeInterpreter:
    def __init__(self, available_topics):
        self.available_topics = available_topics
        self.calls = []

    def interpret(self, request, current):
        self.calls.append((request, current))
        count = 20 if len(self.calls) == 1 else 25
        patch = ExamPlanPatch.from_mapping(
            {
                "assistant_message": f"Applied request {len(self.calls)}",
                "question_count": count,
            }
        )
        updated = apply_exam_plan_patch(current, patch, self.available_topics)
        return InterpretationResult(
            plan=updated,
            assistant_message=patch.assistant_message,
            changes=tuple(describe_plan_changes(current, updated)),
            source="local_rules",
        )


class ExamAssistantDialogTests(unittest.TestCase):
    def setUp(self):
        self.initial = ExamGenerationPlan(
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )
        self.interpreter = FakeInterpreter(["cache", "process"])
        self.dialog = ExamAssistantDialog(
            self.initial,
            ["cache", "process"],
            interpreter=self.interpreter,
        )

    def tearDown(self):
        self.dialog.close()

    def test_dialog_uses_two_pane_review_layout_and_semantic_actions(self):
        self.assertIsInstance(self.dialog.content_splitter, QSplitter)
        self.assertEqual(Qt.Orientation.Horizontal, self.dialog.content_splitter.orientation())
        self.assertEqual(self.dialog.left_pane, self.dialog.content_splitter.widget(0))
        self.assertEqual(self.dialog.right_pane, self.dialog.content_splitter.widget(1))
        self.assertTrue(self.dialog.left_pane.isAncestorOf(self.dialog.transcript))
        self.assertTrue(self.dialog.left_pane.isAncestorOf(self.dialog.request_input))
        self.assertTrue(self.dialog.right_pane.isAncestorOf(self.dialog.plan_preview))
        self.assertTrue(self.dialog.right_pane.isAncestorOf(self.dialog.changes_preview))
        self.assertEqual("secondaryButton", self.dialog.interpret_btn.objectName())
        self.assertEqual("secondaryButton", self.dialog.cancel_btn.objectName())
        self.assertEqual("primaryButton", self.dialog.apply_btn.objectName())
        self.assertFalse(self.dialog.apply_btn.isEnabled())

    def test_interpretation_updates_only_draft_and_supports_follow_up(self):
        first = self.interpreter.interpret("make 20", self.dialog.draft_plan)
        self.dialog._apply_interpretation("make 20", first)

        self.assertEqual(15, self.initial.question_count)
        self.assertEqual(20, self.dialog.draft_plan.question_count)
        self.assertTrue(self.dialog.apply_btn.isEnabled())
        self.assertIn("make 20", self.dialog.transcript.toPlainText())
        self.assertIn("Applied request 1", self.dialog.transcript.toPlainText())

        second = self.interpreter.interpret("make 25", self.dialog.draft_plan)
        self.dialog._apply_interpretation("make 25", second)

        self.assertEqual(20, self.interpreter.calls[1][1].question_count)
        self.assertEqual(25, self.dialog.draft_plan.question_count)
        self.assertIn("question_count", self.dialog.changes_preview.toPlainText())

    def test_confirm_returns_draft_while_cancel_returns_no_plan(self):
        result = self.interpreter.interpret("make 20", self.dialog.draft_plan)
        self.dialog._apply_interpretation("make 20", result)
        self.dialog._confirm()

        self.assertEqual(QDialog.DialogCode.Accepted, self.dialog.result())
        self.assertEqual(20, self.dialog.get_confirmed_plan().question_count)

        cancelled = ExamAssistantDialog(
            self.initial,
            ["cache"],
            interpreter=FakeInterpreter(["cache"]),
        )
        cancelled.reject()
        self.assertIsNone(cancelled.get_confirmed_plan())
        cancelled.close()

    def test_submit_runs_interpreter_and_reenables_controls(self):
        self.dialog.request_input.setPlainText("make 20")

        self.dialog._submit_request()
        for _ in range(20):
            QTest.qWait(10)
            if self.dialog.worker and self.dialog.worker.isFinished():
                break
        _APP.processEvents()

        self.assertEqual(20, self.dialog.draft_plan.question_count)
        self.assertTrue(self.dialog.request_input.isEnabled())
        self.assertTrue(self.dialog.interpret_btn.isEnabled())
        self.assertIn("make 20", self.dialog.transcript.toPlainText())


if __name__ == "__main__":
    unittest.main()
