import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt

from ai.batch_generator import GenerationWorker
from ai.question_plan import QuestionPlanItem
from ai.llm_client import LLMClient
from ai.generation_report import GenerationReport
from core.app_errors import AppError
from core.background_task_center import BackgroundTaskCenter, TaskStatus
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from models.question import Question
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])

class GenerationRuntimeFlowTests(unittest.TestCase):
    def test_worker_rejects_choice_when_stem_leaks_answer_keyword(self):
            cases = [
                {
                    "topic": "input_output_improvements",
                    "correct_answer": "C",
                    "zh_stem": "以下哪种 I/O 方式中，CPU 发送命令后继续执行其他工作，直到设备通过中断(Interrupt)通知完成？",
                    "zh_options": [
                        "A. 轮询(Polling)",
                        "B. 直接存储器访问(DMA)",
                        "C. 中断驱动(Interrupt-driven) I/O",
                        "D. 同步(Synchronous) I/O",
                    ],
                    "en_stem": "Which I/O method lets the CPU continue until the device signals completion by interrupt?",
                    "en_options": [
                        "A. Polling",
                        "B. Direct memory access",
                        "C. Interrupt-driven I/O",
                        "D. Synchronous I/O",
                    ],
                },
                {
                    "topic": "virtual_memory",
                    "correct_answer": "B",
                    "zh_stem": "下列哪一项内存机制使用页表进行地址映射？",
                    "zh_options": [
                        "A. 磁盘调度",
                        "B. 虚拟内存",
                        "C. 文件索引",
                        "D. 网络路由",
                    ],
                    "en_stem": "Which memory mechanism uses page tables to translate addresses?",
                    "en_options": [
                        "A. Disk scheduling",
                        "B. Virtual memory",
                        "C. File indexing",
                        "D. Network routing",
                    ],
                },
            ]

            for case in cases:
                with self.subTest(topic=case["topic"]):
                    worker = GenerationWorker(
                        LLMClient(api_key="", base_url="local-agent://auto", model="codex"),
                        course_content="content",
                        topics=[case["topic"]],
                        count=1,
                        difficulty="medium",
                    )
                    raw = {
                        "type": "multiple_choice",
                        "difficulty": "medium",
                        "topic": case["topic"],
                        "correct_answer": case["correct_answer"],
                        "bilingual": {
                            "zh": {
                                "stem": case["zh_stem"],
                                "options": case["zh_options"],
                                "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                            },
                            "en": {
                                "stem": case["en_stem"],
                                "options": case["en_options"],
                                "explanation": (
                                    "This is a sufficiently detailed English explanation "
                                    "for why the answer is correct."
                                ),
                            },
                        },
                    }

                    ok, reason = worker._validate_raw_question(raw)

                    self.assertFalse(ok)
                    self.assertIn("answer keyword", reason)

    def test_local_agent_generation_start_does_not_read_persisted_api_key(self):
            class ForbiddenSecrets:
                def get_key(self):
                    raise AssertionError("local agent generation must not read persisted API keys")

            class FakeSignal:
                def connect(self, _callback):
                    pass

            class FakeWorker:
                def __init__(self, *args, **kwargs):
                    self.progress = FakeSignal()
                    self.question_ready = FakeSignal()
                    self.batch_done = FakeSignal()
                    self.partial_done = FakeSignal()
                    self.error = FakeSignal()
                    self.finished = FakeSignal()
                    self.args = args
                    self.kwargs = kwargs
                    self.started = False

                def start(self):
                    self.started = True

                def set_runtime_instruction(self, _instruction):
                    pass

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

            with patch("core.secrets_manager.SecretsManager.instance", return_value=ForbiddenSecrets()), \
                 patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FakeWorker):
                dialog._start_generation()

            self.assertIsInstance(dialog.worker, FakeWorker)
            self.assertTrue(dialog.worker.started)

    def test_generation_dialog_registers_worker_with_persistent_task_center(self):
            class FakeSignal:
                def connect(self, _callback):
                    pass

            class FakeWorker:
                def __init__(self, *args, **kwargs):
                    self.progress = FakeSignal()
                    self.question_ready = FakeSignal()
                    self.batch_done = FakeSignal()
                    self.partial_done = FakeSignal()
                    self.error = FakeSignal()
                    self.finished = FakeSignal()
                    self.kwargs = kwargs

                def start(self):
                    pass

                def set_runtime_instruction(self, _instruction):
                    pass

            with tempfile.TemporaryDirectory() as tmpdir:
                center = BackgroundTaskCenter(
                    Path(tmpdir) / "background_tasks.json",
                    id_factory=lambda: "task-1",
                )
                dialog = AIGenerationDialog(
                    "course content",
                    {
                        "ai_provider": "local_agent",
                        "ai_base_url": "local-agent://auto",
                        "ai_model": "codex",
                    },
                    available_topics=["cache"],
                    task_center=center,
                )
                dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
                dialog.set_draft_source("predicted_exam")
                dialog._generation_draft_id = "draft-task-1"
                dialog.set_title_input.setText("Cache recovery set")
                dialog.runtime_instruction_input.setPlainText("Avoid storage topics")

                with patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FakeWorker):
                    dialog._start_generation()

                self.assertIs(center, dialog.worker.kwargs["task_center"])
                self.assertEqual("task-1", dialog.worker.kwargs["task_id"])
                task = center.get("task-1")
                self.assertEqual(TaskStatus.QUEUED, task.status)
                self.assertEqual("question_generation", task.kind)
                self.assertEqual(15, task.metadata["requested_count"])
                self.assertEqual(["cache"], task.metadata["topic_ids"])
                self.assertEqual("predicted_exam", task.metadata["draft_source"])
                self.assertEqual("draft-task-1", task.metadata["draft_id"])
                self.assertNotIn("publish_destination", task.metadata)
                self.assertEqual("Cache recovery set", task.metadata["question_set_title"])
                self.assertEqual("Avoid storage topics", task.metadata["runtime_instruction"])
                self.assertEqual(15, task.metadata["exam_plan"]["question_count"])
                self.assertEqual(["cache"], task.metadata["exam_plan"]["selected_topics"])
                self.assertEqual("medium", task.metadata["exam_plan"]["difficulty"])
                self.assertEqual(
                    dialog._build_generation_config().normalized_type_weights(),
                    task.metadata["exam_plan"]["question_type_weights"],
                )

    def test_generation_dialog_ignores_queued_signals_from_replaced_worker(self):
            class FakeSignal:
                def __init__(self):
                    self.callbacks = []

                def connect(self, callback):
                    self.callbacks.append(callback)

                def emit(self, *args):
                    for callback in list(self.callbacks):
                        callback(*args)

            class FakeWorker:
                instances = []

                def __init__(self, *args, **kwargs):
                    self.progress = FakeSignal()
                    self.question_ready = FakeSignal()
                    self.batch_done = FakeSignal()
                    self.partial_done = FakeSignal()
                    self.error = FakeSignal()
                    self.finished = FakeSignal()
                    self.running = False
                    self.__class__.instances.append(self)

                def start(self):
                    self.running = True

                def isRunning(self):
                    return self.running

                def set_runtime_instruction(self, _instruction):
                    pass

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

            with patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FakeWorker), \
                 patch("ui.dialogs.ai_generation_dialog.QMessageBox.critical") as critical:
                dialog._start_generation()
                old_worker = FakeWorker.instances[-1]
                old_worker.running = False
                dialog._start_generation()

                old_worker.error.emit("late error from old run")
                old_worker.finished.emit()

            self.assertFalse(dialog._generation_failed)
            self.assertFalse(dialog.generate_btn.isEnabled())
            critical.assert_not_called()

    def test_direct_regeneration_requires_confirmation_before_discarding_results(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
            existing = [object(), object()]
            dialog.generated_questions = existing

            with patch(
                "ui.dialogs.ai_generation_dialog.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ) as confirm, patch(
                "ui.dialogs.ai_generation_dialog.GenerationWorker"
            ) as worker_type:
                dialog._start_generation()

            self.assertEqual(existing, dialog.generated_questions)
            confirm.assert_called_once()
            worker_type.assert_not_called()

    def test_generation_retry_task_links_back_to_partial_attempt(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                ids = iter(["task-1", "task-2"])
                center = BackgroundTaskCenter(
                    Path(tmpdir) / "background_tasks.json",
                    id_factory=lambda: next(ids),
                )
                dialog = AIGenerationDialog(
                    "course content",
                    {
                        "ai_provider": "local_agent",
                        "ai_base_url": "local-agent://auto",
                        "ai_model": "codex",
                    },
                    available_topics=["cache"],
                    task_center=center,
                )
                first_id = dialog._register_generation_task(
                    ["cache"],
                    count=5,
                    provider="local_agent",
                    model="codex",
                    template="quick_review",
                    retry=False,
                )
                center.start(first_id)
                center.fail(first_id, "partial", result_count=2)

                retry_id = dialog._register_generation_task(
                    ["cache"],
                    count=3,
                    provider="local_agent",
                    model="codex",
                    template="quick_review",
                    retry=True,
                )

                self.assertEqual(first_id, center.get(retry_id).retry_of)

    def test_dialog_applies_runtime_instruction_to_generation_worker(self):
            class FakeSignal:
                def connect(self, _callback):
                    pass

            class FakeWorker:
                def __init__(self, *args, **kwargs):
                    self.progress = FakeSignal()
                    self.question_ready = FakeSignal()
                    self.batch_done = FakeSignal()
                    self.partial_done = FakeSignal()
                    self.error = FakeSignal()
                    self.finished = FakeSignal()
                    self.instructions = []
                    self.started = False

                def set_runtime_instruction(self, instruction):
                    self.instructions.append(instruction)

                def start(self):
                    self.started = True

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

            with patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FakeWorker):
                dialog.runtime_instruction_input.setPlainText("后续题目避免关键词重复。")
                dialog._start_generation()

                self.assertEqual(["后续题目避免关键词重复。"], dialog.worker.instructions)

                dialog.runtime_instruction_input.setPlainText("后续题目集中在 DMA。")
                dialog.apply_runtime_instruction_btn.click()

            self.assertEqual(
                ["后续题目避免关键词重复。", "后续题目集中在 DMA。"],
                dialog.worker.instructions,
            )
            self.assertIn("后续要求", dialog.generation_log.toPlainText())

    def test_dialog_runtime_instruction_quick_actions_append_and_apply_text(self):
            class FakeWorker:
                def __init__(self):
                    self.instructions = []

                def set_runtime_instruction(self, instruction):
                    self.instructions.append(instruction)

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.worker = FakeWorker()
            dialog.runtime_instruction_input.setPlainText("后续题目集中在 DMA。")

            buttons = {
                button.text(): button
                for button in dialog.runtime_instruction_quick_buttons
            }
            self.assertIn("更贴近课件原文", buttons)
            self.assertIn("减少定义题", buttons)
            self.assertFalse(any("Focus" in label or "Original" in label for label in buttons))

            buttons["减少定义题"].click()

            instruction = dialog.runtime_instruction_input.toPlainText()
            self.assertIn("后续题目集中在 DMA。", instruction)
            self.assertIn("减少定义题", instruction)
            self.assertEqual([dialog._current_runtime_instruction()], dialog.worker.instructions)
            self.assertIn("后续要求", dialog.generation_log.toPlainText())

    def test_dialog_runtime_instruction_quick_actions_show_queued_before_worker_starts(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.worker = None

            buttons = {
                button.text(): button
                for button in dialog.runtime_instruction_quick_buttons
            }
            buttons["减少定义题"].click()

            log = dialog.generation_log.toPlainText()
            self.assertIn("后续要求已排队", log)
            self.assertNotIn("后续要求已更新", log)

    def test_cancel_during_generation_returns_without_waiting_for_worker(self):
            class RunningWorker:
                def __init__(self):
                    self.cancelled = False

                def isRunning(self):
                    return True

                def cancel(self):
                    self.cancelled = True

                def wait(self, _timeout):
                    raise AssertionError("cancel must not wait in the UI thread")

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            worker = RunningWorker()
            dialog.worker = worker

            dialog.reject()

            self.assertTrue(worker.cancelled)
            self.assertTrue(dialog._close_when_worker_stops)

    def test_cancelled_generation_closes_after_worker_finished_signal(self):
            class SlowWorker:
                def __init__(self):
                    self.cancelled = False

                def isRunning(self):
                    return True

                def cancel(self):
                    self.cancelled = True

                def wait(self, _timeout):
                    raise AssertionError("cancel must not wait in the UI thread")

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            worker = SlowWorker()
            dialog.worker = worker
            rejected = []
            dialog.rejected.connect(lambda: rejected.append(True))

            dialog.reject()

            self.assertTrue(worker.cancelled)
            self.assertEqual([], rejected)

            dialog._on_finished()

            self.assertEqual([True], rejected)

    def test_generation_finished_handler_does_not_wait_on_worker(self):
            class FinishedWorker:
                def wait(self, *_args):
                    raise AssertionError("finished handler must not wait on worker in the UI thread")

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog.worker = FinishedWorker()
            dialog._generation_failed = True

            dialog._on_finished()

            self.assertFalse(dialog.progress_bar.isVisible())
            self.assertTrue(dialog.generate_btn.isEnabled())

    def test_completed_generation_can_reopen_review_after_user_cancels(self):
            question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "Cache?",
                        "options": ["A. one", "B. two"],
                        "explanation": "A valid explanation text.",
                    },
                    "en": {
                        "stem": "Cache?",
                        "options": ["A. one", "B. two"],
                        "explanation": "A valid explanation text.",
                    },
                },
                correct_answer="A",
                topic="cache",
            )
            review_count = 0

            class ReviewDialog:
                def __init__(self, questions, parent=None):
                    self.questions = questions

                def exec(self):
                    nonlocal review_count
                    review_count += 1
                    if review_count == 1:
                        return QDialog.DialogCode.Rejected
                    return QDialog.DialogCode.Accepted

                def get_accepted_questions(self):
                    return self.questions

            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["cache"],
            )
            dialog._on_batch_done([question])

            with patch("ui.dialogs.ai_generation_dialog.QuestionReviewDialog", ReviewDialog):
                dialog._on_finished()

                self.assertEqual(1, review_count)
                self.assertFalse(dialog.review_partial_btn.isHidden())
                self.assertTrue(dialog.review_partial_btn.isEnabled())
                self.assertIn("审核已暂停", dialog.status_label.text())
                self.assertIn("1", dialog.review_partial_btn.text())

                dialog.review_partial_btn.click()

            self.assertEqual(2, review_count)
            self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
            self.assertEqual([question], dialog.generated_questions)

    def test_warning_focused_review_skips_clean_questions_and_keeps_them(self):
            clean = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "系统调用运行在内核态。",
                        "options": ["正确", "错误"],
                        "explanation": "系统调用会进入内核执行受保护的服务。",
                    },
                    "en": {
                        "stem": "System calls execute in kernel mode.",
                        "options": ["True", "False"],
                        "explanation": "A system call enters the kernel for a protected service.",
                    },
                },
                correct_answer=True,
                topic="process",
            )
            warning = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "DMA 可以减少 CPU 搬运数据的工作。",
                        "options": ["正确", "错误"],
                        "explanation": "",
                    },
                    "en": {
                        "stem": "DMA reduces CPU data-copy work.",
                        "options": ["True", "False"],
                        "explanation": "",
                    },
                },
                correct_answer=True,
                topic="io",
            )
            reviewed = {}

            class RejectingWarningReview:
                def __init__(self, questions, parent=None, **kwargs):
                    reviewed["questions"] = list(questions)
                    reviewed["kwargs"] = kwargs

                def exec(self):
                    return QDialog.DialogCode.Accepted

                def get_accepted_questions(self):
                    return []

            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["process", "io"],
            )
            self.addCleanup(dialog.close)
            dialog.generated_questions = [clean, warning]
            dialog.set_review_warnings_only(True)

            with patch(
                "ui.dialogs.ai_generation_dialog.QuestionReviewDialog",
                RejectingWarningReview,
            ):
                dialog._review_generated_questions()

            self.assertEqual([warning], reviewed["questions"])
            self.assertTrue(reviewed["kwargs"]["allow_empty_accept"])
            self.assertEqual([clean], dialog.generated_questions)
            self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())

    def test_warning_focused_review_auto_accepts_when_all_questions_are_clean(self):
            clean = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "合同依法成立后对当事人具有约束力。",
                        "options": ["正确", "错误"],
                        "explanation": "依法成立的合同原则上对当事人具有法律约束力。",
                    },
                    "en": {
                        "stem": "A lawfully formed contract binds its parties.",
                        "options": ["True", "False"],
                        "explanation": "A lawfully formed contract generally binds its parties.",
                    },
                },
                correct_answer=True,
                topic="contract",
            )
            dialog = AIGenerationDialog(
                "course content",
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                },
                available_topics=["contract"],
            )
            self.addCleanup(dialog.close)
            dialog.generated_questions = [clean]
            dialog.set_review_warnings_only(True)

            with patch(
                "ui.dialogs.ai_generation_dialog.QuestionReviewDialog",
            ) as review_dialog:
                dialog._review_generated_questions()

            review_dialog.assert_not_called()
            self.assertEqual([clean], dialog.generated_questions)
            self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())

    def test_generation_partial_result_shows_explicit_review_action_without_error_modal(self):
            question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {"stem": "Cache?", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    "en": {"stem": "Cache?", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                },
                correct_answer="A",
                topic="cache",
            )
            error = AppError(
                code="GEN-QUOTA-001",
                severity="warning",
                title_zh="生成未完成",
                title_en="Generation incomplete",
                message_zh="已接受 1/3 道题。",
                message_en="Accepted 1/3 questions.",
                action_zh="可先保存已生成题目，或稍后继续补齐。",
                action_en="Save generated questions now, or continue later.",
                technical_detail="Missing: true_false [2]",
            )
            report = GenerationReport(
                requested_count=3,
                accepted_count=1,
                rejected_count=4,
                attempts=3,
                max_attempts=3,
                status="partial",
                missing_quotas={"question_types": {"true_false": 2}},
                error=error,
            )
            reviewed = {}

            class AcceptingReviewDialog:
                def __init__(self, questions, parent=None):
                    reviewed["questions"] = questions

                def exec(self):
                    return QDialog.DialogCode.Accepted

                def get_accepted_questions(self):
                    return reviewed["questions"]

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog._generation_started_at = 100.0
            dialog.worker = object()

            with patch("ui.dialogs.ai_generation_dialog.QMessageBox.critical") as critical, \
                 patch("ui.dialogs.ai_generation_dialog.QuestionReviewDialog", AcceptingReviewDialog):
                dialog._on_partial_done([question], report)
                dialog._on_finished()

                self.assertFalse(critical.called)
                self.assertNotIn("questions", reviewed)
                self.assertNotEqual(QDialog.DialogCode.Accepted, dialog.result())
                self.assertFalse(dialog.review_partial_btn.isHidden())
                self.assertTrue(dialog.review_partial_btn.isEnabled())
                self.assertEqual("primaryButton", dialog.review_partial_btn.objectName())
                self.assertEqual("secondaryButton", dialog.generate_btn.objectName())
                self.assertIn("审核并保存", dialog.review_partial_btn.text())
                dialog.review_partial_btn.click()

            self.assertEqual([question], reviewed["questions"])
            self.assertEqual([question], dialog.generated_questions)
            self.assertIn("生成未完成", dialog.status_label.text())
            self.assertIn("已生成 1/3", dialog.status_label.text())
            self.assertIn("true_false", dialog.status_label.text())
            self.assertIn("已拒绝候选 4", dialog.status_label.text())
            self.assertFalse(dialog.partial_recovery_label.isHidden())
            self.assertEqual("generationPartialRecoveryLabel", dialog.partial_recovery_label.objectName())
            self.assertIn("可保存已生成题目", dialog.partial_recovery_label.text())
            self.assertIn("放宽约束", dialog.partial_recovery_label.text())
            self.assertIn("重新生成", dialog.partial_recovery_label.text())
            self.assertTrue(dialog.result() == QDialog.DialogCode.Accepted)

    def test_generation_partial_result_can_fill_missing_slots_and_merge_for_review(self):
            first_question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {"stem": "Cache?", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    "en": {"stem": "Cache?", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                },
                correct_answer="A",
                topic="cache",
            )
            retry_question = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.HARD,
                bilingual={
                    "zh": {"stem": "DMA?", "options": ["True", "False"], "explanation": "A valid explanation text."},
                    "en": {"stem": "DMA?", "options": ["True", "False"], "explanation": "A valid explanation text."},
                },
                correct_answer="True",
                topic="cache",
            )
            report = GenerationReport(
                requested_count=3,
                accepted_count=1,
                rejected_count=2,
                attempts=3,
                max_attempts=3,
                status="partial",
                failed_plan_items=[
                    QuestionPlanItem(
                        plan_id="plan-002",
                        topic_id="cache",
                        topic_title="Cache",
                        question_type="true_false",
                        difficulty="hard",
                        target_skill="application",
                    ),
                    QuestionPlanItem(
                        plan_id="plan-003",
                        topic_id="cache",
                        topic_title="Cache",
                        question_type="true_false",
                        difficulty="hard",
                        target_skill="comparison",
                    ),
                ],
                template="final_exam",
            )
            reviewed = {}

            class FakeSignal:
                def connect(self, _callback):
                    pass

            class FakeWorker:
                def __init__(self, *args, **kwargs):
                    self.progress = FakeSignal()
                    self.question_ready = FakeSignal()
                    self.batch_done = FakeSignal()
                    self.partial_done = FakeSignal()
                    self.error = FakeSignal()
                    self.finished = FakeSignal()
                    self.args = args
                    self.kwargs = kwargs
                    self.started = False

                def start(self):
                    self.started = True

            class AcceptingReviewDialog:
                def __init__(self, questions, parent=None):
                    reviewed["questions"] = questions

                def exec(self):
                    return QDialog.DialogCode.Accepted

                def get_accepted_questions(self):
                    return reviewed["questions"]

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process"],
            )
            dialog._on_partial_done([first_question], report)
            dialog._on_finished()

            self.assertFalse(dialog.fill_missing_btn.isHidden())
            self.assertTrue(dialog.fill_missing_btn.isEnabled())
            self.assertIn("2", dialog.fill_missing_btn.text())

            with patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FakeWorker), \
                 patch("ui.dialogs.ai_generation_dialog.QuestionReviewDialog", AcceptingReviewDialog):
                dialog.fill_missing_btn.click()

                self.assertIsInstance(dialog.worker, FakeWorker)
                self.assertTrue(dialog.worker.started)
                self.assertEqual(["cache"], dialog.worker.args[2])
                self.assertEqual(2, dialog.worker.args[3])
                self.assertEqual("mixed", dialog.worker.args[4])
                retry_config = dialog.worker.kwargs["generation_config"]
                self.assertEqual("final_exam", retry_config.template)
                self.assertEqual({"true_false": 2}, {k: v for k, v in retry_config.question_type_weights.items() if v})
                self.assertEqual({"hard": 2}, {k: v for k, v in retry_config.difficulty_weights.items() if v})

                dialog._on_batch_done([retry_question])
                dialog._on_finished()

            self.assertEqual([first_question, retry_question], reviewed["questions"])
            self.assertEqual([first_question, retry_question], dialog.generated_questions)

    def test_retry_generation_error_keeps_partial_questions_reviewable(self):
            question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {"stem": "Cache?", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    "en": {"stem": "Cache?", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                },
                correct_answer="A",
                topic="cache",
            )
            report = GenerationReport(
                requested_count=2,
                accepted_count=1,
                status="partial",
                failed_plan_items=[
                    QuestionPlanItem(
                        plan_id="plan-002",
                        topic_id="cache",
                        topic_title="Cache",
                        question_type="true_false",
                        difficulty="hard",
                        target_skill="application",
                    )
                ],
            )

            class FakeSignal:
                def connect(self, _callback):
                    pass

            class FakeWorker:
                def __init__(self, *args, **kwargs):
                    self.progress = FakeSignal()
                    self.question_ready = FakeSignal()
                    self.batch_done = FakeSignal()
                    self.partial_done = FakeSignal()
                    self.error = FakeSignal()
                    self.finished = FakeSignal()

                def start(self):
                    pass

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            dialog._on_partial_done([question], report)
            dialog._on_finished()

            with patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FakeWorker), \
                 patch("ui.dialogs.ai_generation_dialog.QMessageBox.critical"):
                dialog.fill_missing_btn.click()
                dialog._on_error("network timeout")

            self.assertEqual([question], dialog.generated_questions)
            self.assertFalse(dialog.review_partial_btn.isHidden())
            self.assertTrue(dialog.review_partial_btn.isEnabled())
            self.assertFalse(dialog.partial_recovery_label.isHidden())
            self.assertFalse(dialog.fill_missing_btn.isHidden())
            self.assertTrue(dialog.fill_missing_btn.isEnabled())

    def test_generation_start_failure_restores_idle_state(self):
            class FakeSignal:
                def connect(self, _callback):
                    pass

            class FailingWorker:
                def __init__(self, *args, **kwargs):
                    self.progress = FakeSignal()
                    self.question_ready = FakeSignal()
                    self.batch_done = FakeSignal()
                    self.partial_done = FakeSignal()
                    self.error = FakeSignal()
                    self.finished = FakeSignal()

                def set_runtime_instruction(self, _instruction):
                    pass

                def start(self):
                    raise RuntimeError("worker start failed")

            with tempfile.TemporaryDirectory() as tmpdir:
                center = BackgroundTaskCenter(
                    Path(tmpdir) / "background_tasks.json",
                    id_factory=lambda: "task-1",
                )
                dialog = AIGenerationDialog(
                    "course content",
                    {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                    available_topics=["cache"],
                    task_center=center,
                )
                dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

                with patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FailingWorker), \
                     patch("ui.dialogs.ai_generation_dialog.QMessageBox.critical") as critical:
                    dialog._start_generation()

                self.assertTrue(critical.called)
                self.assertFalse(dialog.generation_status_timer.isActive())
                self.assertIsNone(dialog._generation_started_at)
                self.assertTrue(dialog.generate_btn.isEnabled())
                self.assertFalse(dialog.progress_bar.isVisible())
                self.assertEqual(TaskStatus.FAILED, center.get("task-1").status)
