import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt

from ai.batch_generator import GenerationWorker
from ai.generation_config import GenerationConfig
from ai.question_plan import QuestionPlanItem
from ai.exam_plan import ExamGenerationPlan
from ai.llm_client import LLMClient
from ai.generation_report import GenerationReport
from core.app_errors import AppError
from core.background_task_center import BackgroundTaskCenter, TaskStatus
from core import course_index
from core.question_set_builder import build_ai_question_set
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from ui.navigation import Route
from models.course_project import CourseProject, CourseTopic
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType, topic_value


_APP = QApplication.instance() or QApplication([])


class GenerationConfigTests(unittest.TestCase):
    def test_generation_dialog_keeps_review_action_after_save_error(self):
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
        dialog.generated_questions = [
            Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "合同题",
                        "options": ["正确", "错误"],
                        "explanation": "解释。",
                    },
                    "en": {
                        "stem": "Contract question",
                        "options": ["True", "False"],
                        "explanation": "Explanation.",
                    },
                },
                correct_answer=True,
                topic="contract",
            )
        ]

        dialog.show_save_error("disk full")

        self.assertFalse(dialog.review_partial_btn.isHidden())
        self.assertTrue(dialog.review_partial_btn.isEnabled())
        self.assertIn("disk full", dialog.status_label.text())
        self.assertIn("仍保留", dialog.status_label.text())

    def test_generation_dialog_restores_review_pending_draft(self):
        dialog = AIGenerationDialog(
            "course content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=["cache"],
        )
        self.addCleanup(dialog.close)
        question = Question.create_new(
            qtype=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "缓存恢复题",
                    "options": ["正确", "错误"],
                    "explanation": "解释。",
                },
                "en": {
                    "stem": "Cache recovery question",
                    "options": ["True", "False"],
                    "explanation": "Explanation.",
                },
            },
            correct_answer=True,
            topic="cache",
        )
        draft = SimpleNamespace(
            questions=(question,),
            question_set_title="缓存恢复练习",
            exam_plan=ExamGenerationPlan(
                question_count=10,
                difficulty="mixed",
                selected_topics=("cache",),
                topic_weights={"cache": 100},
            ),
            review_warnings_only=True,
        )

        dialog.restore_generation_draft(draft)

        self.assertEqual([question], dialog.generated_questions)
        self.assertEqual("缓存恢复练习", dialog.question_set_title())
        self.assertEqual("mixed", dialog.build_exam_plan().difficulty)
        self.assertFalse(dialog.review_partial_btn.isHidden())
        self.assertIn("1 道题", dialog.status_label.text())

    def test_generation_dialog_notifies_when_new_questions_become_durable(self):
        dialog = AIGenerationDialog(
            "course content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=["cache"],
        )
        self.addCleanup(dialog.close)
        question = Question.create_new(
            qtype=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "新草稿题",
                    "options": ["正确", "错误"],
                    "explanation": "解释。",
                },
                "en": {
                    "stem": "New draft question",
                    "options": ["True", "False"],
                    "explanation": "Explanation.",
                },
            },
            correct_answer=True,
            topic="cache",
        )
        notifications = []
        dialog.draft_changed.connect(lambda: notifications.append("changed"))

        dialog._on_question_ready([question])

        self.assertEqual([question], dialog.generated_questions)
        self.assertEqual(["changed"], notifications)

    def test_regenerated_question_set_returns_to_library_set_tab(self):
        from ui.question_set_action_controller import (
            QuestionSetActionController,
        )

        question = Question.create_new(
            qtype=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": "重新生成题",
                    "options": ["正确", "错误"],
                    "explanation": "解释。",
                },
                "en": {
                    "stem": "Regenerated question",
                    "options": ["True", "False"],
                    "explanation": "Explanation.",
                },
            },
            correct_answer=True,
            topic="cache",
        )
        question_set = QuestionSet.create_new(
            title={"zh": "缓存题集", "en": "Cache Set"},
            description={"zh": "", "en": ""},
            topics=["cache"],
            question_ids=[question.question_id],
        )
        dialog = SimpleNamespace(
            generated_questions=[question],
            diff_combo=SimpleNamespace(
                currentData=lambda: Difficulty.MEDIUM.value,
            ),
            configure_from_question_set=Mock(),
            exec=Mock(return_value=QDialog.DialogCode.Accepted),
        )
        navigated = []
        shell = SimpleNamespace(
            lang_manager=SimpleNamespace(
                current="zh",
                get_text=lambda zh, _en: zh,
            ),
            history_protection=SimpleNamespace(
                confirm_navigation=lambda _screen: True,
            ),
            set_manager=SimpleNamespace(get=lambda _set_id: question_set),
            question_bank=Mock(),
            progress_manager=Mock(),
            topic_screen=SimpleNamespace(refresh=Mock()),
            navigate_route=navigated.append,
            SCREEN_QUESTION_BANK=6,
            _generation_controller=lambda: SimpleNamespace(
                prepare=lambda **_kwargs: SimpleNamespace(
                    dialog=dialog,
                    course_project=Mock(),
                )
            ),
        )
        controller = QuestionSetActionController(
            shell,
            message_box=SimpleNamespace(
                information=Mock(),
                warning=Mock(),
                critical=Mock(),
            ),
            regenerator=Mock(return_value=(question_set, 1, [])),
        )

        controller.regenerate(question_set.set_id)

        self.assertEqual([Route.library("sets")], navigated)

    def test_generation_dialog_schedules_confirmed_plan_after_it_is_shown(self):
        dialog = AIGenerationDialog(
            "course content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=["cache"],
        )
        self.addCleanup(dialog.close)

        with patch(
            "ui.dialogs.ai_generation_dialog.QTimer.singleShot",
        ) as single_shot:
            dialog.start_generation_when_shown()

        single_shot.assert_called_once()
        delay, callback = single_shot.call_args.args
        self.assertEqual(0, delay)
        self.assertIs(dialog, callback.__self__)
        self.assertEqual("_start_generation", callback.__name__)

    def test_generation_worker_cancel_interrupts_active_client_request(self):
        client = SimpleNamespace(model="test-model", cancel=Mock())
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
        )

        worker.cancel()

        client.cancel.assert_called_once_with()

    def test_worker_keeps_generation_config(self):
        config = GenerationConfig(template="quick_review")
        worker = GenerationWorker(
            LLMClient(api_key="", base_url="local-agent://auto", model="codex"),
            course_content="content",
            topics=["cache"],
            count=5,
            difficulty="mixed",
            generation_config=config,
        )

        self.assertIs(worker.generation_config, config)

    def test_worker_delegates_payload_preparation_to_pure_generation_service(self):
        worker = GenerationWorker(
            LLMClient(api_key="", base_url="local-agent://auto", model="codex"),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
        )

        class RecordingService:
            def normalize_raw_question(self, qdata):
                return {"normalized": qdata}

            def validate_raw_question(self, qdata):
                return False, f"checked {qdata['value']}"

            def normalize_topic(self, raw_topic):
                return f"topic:{raw_topic}"

        worker._generation_service = RecordingService()

        self.assertEqual({"normalized": {"value": 1}}, worker._normalize_raw_question({"value": 1}))
        self.assertEqual((False, "checked 2"), worker._validate_raw_question({"value": 2}))
        self.assertEqual("topic:cache", worker._normalize_topic("cache"))

    def test_worker_topic_normalization_does_not_use_ambiguous_substrings(self):
        worker = GenerationWorker(
            LLMClient(api_key="", base_url="local-agent://auto", model="codex"),
            course_content="content",
            topics=["process", "input_output_improvements"],
            count=3,
            difficulty="mixed",
        )

        self.assertIsNone(worker._normalize_topic("processor scheduling"))
        self.assertIsNone(worker._normalize_topic("i/o"))
        self.assertEqual(
            "input_output_improvements",
            worker._normalize_topic("input output improvements and DMA"),
        )

    def test_worker_records_source_course_metadata_on_generated_questions(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def generate_with_json(self, *_args, **_kwargs):
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "cache",
                            "subtopic": "mapping",
                            "correct_answer": "A",
                            "bilingual": {
                                "zh": {
                                    "stem": "哪一个说法正确？",
                                    "options": ["A. 正确", "B. 错误", "C. 错误", "D. 错误"],
                                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                                },
                                "en": {
                                    "stem": "Which statement is correct?",
                                    "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                                    "explanation": "This is a sufficiently detailed English explanation for the answer.",
                                },
                            },
                        }
                    ]
                }

        course = SimpleNamespace(
            course_id="course-20260618-demo",
            title="Systems 2B",
            updated_at="2026-06-18T12:00:00+00:00",
        )
        worker = GenerationWorker(
            FakeClient(),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
            course_project=course,
        )
        batches = []
        worker.batch_done.connect(batches.append)

        with patch("ai.batch_generator.retrieve_course_context", return_value="Cache context"):
            worker.run()

        question = batches[0][0]
        self.assertEqual("course-20260618-demo", question.metadata["course_id"])
        self.assertEqual("Systems 2B", question.metadata["course_title"])
        self.assertEqual("2026-06-18T12:00:00+00:00", question.metadata["course_updated_at"])
        self.assertEqual("test-model", question.metadata["ai_model"])

    def test_worker_records_model_source_refs_on_generated_questions(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def generate_with_json(self, *_args, **_kwargs):
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "cache",
                            "subtopic": "mapping",
                            "correct_answer": "A",
                            "source_refs": [
                                {
                                    "chunk_id": "source-0002",
                                    "source_file": "cache.pdf",
                                    "page_or_slide": 3,
                                    "heading": "Cache lecture p3",
                                }
                            ],
                            "bilingual": {
                                "zh": {
                                    "stem": "哪一个说法正确？",
                                    "options": ["A. 正确", "B. 错误", "C. 错误", "D. 错误"],
                                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                                },
                                "en": {
                                    "stem": "Which statement is correct?",
                                    "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                                    "explanation": "This is a sufficiently detailed English explanation for the answer.",
                                },
                            },
                        }
                    ]
                }

        worker = GenerationWorker(
            FakeClient(),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
        )
        batches = []
        worker.batch_done.connect(batches.append)

        worker.run()

        self.assertEqual(
            [
                {
                    "chunk_id": "source-0002",
                    "source_file": "cache.pdf",
                    "page_or_slide": 3,
                    "heading": "Cache lecture p3",
                }
            ],
            batches[0][0].metadata["source_refs"],
        )

    def test_worker_emits_accepted_questions_before_final_batch_done(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def generate_with_json(self, *_args, **_kwargs):
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "cache",
                            "subtopic": "mapping",
                            "correct_answer": "A",
                            "bilingual": {
                                "zh": {
                                    "stem": "哪一个说法正确？",
                                    "options": ["A. 正确", "B. 错误", "C. 错误", "D. 错误"],
                                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                                },
                                "en": {
                                    "stem": "Which statement is correct?",
                                    "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                                    "explanation": "This is a sufficiently detailed English explanation for the answer.",
                                },
                            },
                        }
                    ]
                }

        worker = GenerationWorker(
            FakeClient(),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
            generation_config=GenerationConfig(
                question_type_weights={"multiple_choice": 100},
                difficulty_weights={"medium": 100},
                topic_weights={"cache": 100},
            ),
        )
        events = []
        worker.question_ready.connect(lambda questions: events.append(("ready", len(questions))))
        worker.batch_done.connect(lambda questions: events.append(("done", len(questions))))

        worker.run()

        self.assertEqual([("ready", 1), ("done", 1)], events)

    def test_worker_applies_runtime_instruction_to_later_requests(self):
        def raw_question(stem: str):
            return {
                "type": "multiple_choice",
                "difficulty": "medium",
                "topic": "cache",
                "subtopic": "mapping",
                "correct_answer": "A",
                "bilingual": {
                    "zh": {
                        "stem": stem,
                        "options": ["A. 正确", "B. 错误", "C. 错误", "D. 错误"],
                        "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                    },
                    "en": {
                        "stem": stem,
                        "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                        "explanation": "This is a sufficiently detailed English explanation for the answer.",
                    },
                },
            }

        class FakeClient:
            model = "test-model"
            last_error = ""

            def __init__(self):
                self.calls = []

            def generate_with_json(self, messages, **_kwargs):
                self.calls.append(messages[-1]["content"])
                return {"questions": [raw_question(f"Question {len(self.calls)}?")]}

        client = FakeClient()
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["cache"],
            count=2,
            difficulty="medium",
            generation_config=GenerationConfig(
                question_type_weights={"multiple_choice": 100},
                difficulty_weights={"medium": 100},
                topic_weights={"cache": 100},
            ),
        )

        worker.question_ready.connect(
            lambda _questions: worker.set_runtime_instruction("后续题目避免关键词重复。")
        )

        worker.run()

        self.assertNotIn("后续题目避免关键词重复。", client.calls[0])
        self.assertIn("后续题目避免关键词重复。", client.calls[1])

    def test_worker_falls_back_to_retrieved_source_refs_when_model_omits_them(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def generate_with_json(self, messages, **_kwargs):
                self.prompt = messages[-1]["content"]
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "io_improvements",
                            "subtopic": "dma",
                            "correct_answer": "A",
                            "bilingual": {
                                "zh": {
                                    "stem": "DMA 的作用是什么？",
                                    "options": ["A. 减少 CPU 搬运", "B. 增加轮询", "C. 只用于 RAID", "D. 禁用中断"],
                                    "explanation": "这是一个足够长的中文解释，用来说明 DMA 为什么可以减少 CPU 搬运。",
                                },
                                "en": {
                                    "stem": "What does DMA do?",
                                    "options": ["A. Reduces CPU copying", "B. Increases polling", "C. Only uses RAID", "D. Disables interrupts"],
                                    "explanation": "This is a sufficiently detailed English explanation for why DMA reduces CPU copying.",
                                },
                            },
                        }
                    ]
                }

        client = FakeClient()
        topic = CourseTopic(
            topic_id="io_improvements",
            title="Input Output Improvements",
            keywords=["DMA"],
            source_files=["io.pdf"],
        )
        project = CourseProject(
            course_id="course-io",
            title="Systems",
            source_folder="",
            summary_markdown="## Input Output Improvements\nDMA transfers reduce CPU overhead.",
            summary_path="",
            topics=[topic],
            documents=[
                {
                    "path": "io.pdf",
                    "title": "I/O lecture",
                    "extension": ".pdf",
                    "pages": ["DMA transfers directly between device and memory."],
                }
            ],
            created_at="2026-06-30T00:00:00+00:00",
            updated_at="2026-06-30T00:00:00+00:00",
        )
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=[topic],
            count=1,
            difficulty="medium",
            course_project=project,
        )
        batches = []
        worker.batch_done.connect(batches.append)

        worker.run()

        refs = batches[0][0].metadata["source_refs"]
        self.assertRegex(refs[0]["chunk_id"], r"^source-[0-9a-f]{10}$")
        self.assertEqual("io.pdf", refs[0]["source_file"])
        self.assertEqual(1, refs[0]["page_or_slide"])
        self.assertIn("DMA transfers directly", refs[0]["excerpt"])
        self.assertRegex(refs[0]["content_hash"], r"^[0-9a-f]{12}$")
        self.assertIn(refs[0]["chunk_id"], client.prompt)

    def test_worker_falls_back_to_plan_slot_source_refs_per_topic(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def generate_with_json(self, *_args, **_kwargs):
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "cache",
                            "subtopic": "mapping",
                            "correct_answer": "A",
                            "bilingual": {
                                "zh": {
                                    "stem": "Cache?",
                                    "options": ["A. 对", "B. 错", "C. 错", "D. 错"],
                                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                                },
                                "en": {
                                    "stem": "Cache?",
                                    "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                                    "explanation": "This is a sufficiently detailed English explanation for the answer.",
                                },
                            },
                        },
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "process",
                            "subtopic": "scheduling",
                            "correct_answer": "A",
                            "bilingual": {
                                "zh": {
                                    "stem": "Process?",
                                    "options": ["A. 对", "B. 错", "C. 错", "D. 错"],
                                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                                },
                                "en": {
                                    "stem": "Process?",
                                    "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                                    "explanation": "This is a sufficiently detailed English explanation for the answer.",
                                },
                            },
                        },
                    ]
                }

        project = CourseProject(
            course_id="course-evidence",
            title="Systems",
            source_folder="",
            summary_markdown="## Cache\nCache lines.\n\n## Process\nScheduling.",
            summary_path="",
            topics=[
                CourseTopic(
                    topic_id="cache",
                    title="Cache",
                    keywords=["cache"],
                    source_files=["cache.pdf"],
                ),
                CourseTopic(
                    topic_id="process",
                    title="Process",
                    keywords=["process"],
                    source_files=["process.pdf"],
                ),
            ],
            documents=[
                {
                    "path": "cache.pdf",
                    "title": "Cache lecture",
                    "extension": ".pdf",
                    "pages": ["Cache lines and cache mapping."],
                },
                {
                    "path": "process.pdf",
                    "title": "Process lecture",
                    "extension": ".pdf",
                    "pages": ["Process scheduling and ready queues."],
                },
            ],
            created_at="2026-07-02T00:00:00+00:00",
            updated_at="2026-07-02T00:00:00+00:00",
        )
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 50, "process": 50},
        )
        worker = GenerationWorker(
            FakeClient(),
            course_content="content",
            topics=project.topics,
            count=2,
            difficulty="mixed",
            course_project=project,
            generation_config=config,
        )
        batches = []
        worker.batch_done.connect(batches.append)

        worker.run()

        refs_by_topic = {
            topic_value(question.topic): question.metadata["source_refs"][0]
            for question in batches[0]
        }
        self.assertRegex(refs_by_topic["cache"]["chunk_id"], r"^source-[0-9a-f]{10}$")
        self.assertEqual("cache.pdf", refs_by_topic["cache"]["source_file"])
        self.assertRegex(refs_by_topic["process"]["chunk_id"], r"^source-[0-9a-f]{10}$")
        self.assertEqual("process.pdf", refs_by_topic["process"]["source_file"])
        self.assertNotEqual(refs_by_topic["cache"]["chunk_id"], refs_by_topic["process"]["chunk_id"])
        for question in batches[0]:
            self.assertEqual(
                [question.metadata["source_refs"][0]["chunk_id"]],
                question.metadata["plan_evidence_chunk_ids"],
            )

    def test_worker_does_not_attach_unrelated_global_source_ref_when_plan_has_no_evidence(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def generate_with_json(self, *_args, **_kwargs):
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "cache_mapping",
                            "subtopic": "tag",
                            "correct_answer": "A",
                            "bilingual": {
                                "zh": {
                                    "stem": "Cache tag 的作用是什么？",
                                    "options": ["A. 区分块", "B. 触发 DMA", "C. 管理中断", "D. 控制 RAID"],
                                    "explanation": "这是一个足够长的中文解释，用来说明 tag 为什么用于区分缓存块。",
                                },
                                "en": {
                                    "stem": "What does a cache tag do?",
                                    "options": ["A. Identifies blocks", "B. Triggers DMA", "C. Manages interrupts", "D. Controls RAID"],
                                    "explanation": "This is a sufficiently detailed English explanation for why tags identify cache blocks.",
                                },
                            },
                        }
                    ]
                }

        project = CourseProject(
            course_id="course-unrelated-evidence",
            title="Systems",
            source_folder="",
            summary_markdown="## Cache\nCache tags identify blocks.",
            summary_path="",
            topics=[
                CourseTopic(
                    topic_id="cache_mapping",
                    title="Cache Mapping",
                    keywords=["cache", "tag"],
                    source_files=[],
                )
            ],
            documents=[
                {
                    "path": "io.pdf",
                    "title": "I/O lecture",
                    "extension": ".pdf",
                    "pages": ["DMA transfers data directly between a device and memory."],
                }
            ],
            created_at="2026-07-03T00:00:00+00:00",
            updated_at="2026-07-03T00:00:00+00:00",
        )
        worker = GenerationWorker(
            FakeClient(),
            course_content="content",
            topics=project.topics,
            count=1,
            difficulty="mixed",
            course_project=project,
            generation_config=GenerationConfig(
                question_type_weights={"multiple_choice": 100},
                difficulty_weights={"medium": 100},
                topic_weights={"cache_mapping": 100},
            ),
        )
        batches = []
        worker.batch_done.connect(batches.append)

        worker.run()

        question = batches[0][0]
        self.assertNotIn("source_refs", question.metadata)
        self.assertNotIn("plan_evidence_chunk_ids", question.metadata)

    def test_worker_labels_cached_source_ref_fallback_as_global_when_no_plan_evidence(self):
        worker = GenerationWorker(
            llm_client=None,
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
        )
        worker._cached_source_refs = [
            {
                "chunk_id": "source-0000",
                "source_file": "cache.pdf",
                "page_or_slide": 1,
                "excerpt": "Cache mapping source.",
                "content_hash": "abc123def456",
            }
        ]

        refs, status, invalid = worker._question_source_refs({}, plan_item=None, quotas=None)

        self.assertEqual("source-0000", refs[0]["chunk_id"])
        self.assertEqual("fallback_global_evidence", status)
        self.assertEqual([], invalid)

    def test_worker_delegates_source_resolution_with_explicit_plan_refs(self):
        worker = GenerationWorker(
            llm_client=None,
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
        )

        class RecordingResolver:
            def __init__(self):
                self.call = None

            def resolve(self, qdata, plan_item=None, plan_refs=None):
                self.call = (qdata, plan_item, plan_refs)
                return [{"chunk_id": "delegated"}], "valid_model_ref", []

        class Quotas:
            def evidence_refs_for_item(self, plan_item):
                return [{"chunk_id": "plan-source"}]

        resolver = RecordingResolver()
        worker._source_resolver = resolver

        result = worker._question_source_refs(
            {"source_refs": [{"chunk_id": "model-source"}]},
            plan_item=None,
            quotas=Quotas(),
        )

        self.assertEqual(([{"chunk_id": "delegated"}], "valid_model_ref", []), result)
        self.assertEqual([{"chunk_id": "plan-source"}], resolver.call[2])

    def test_worker_marks_valid_model_source_ref_from_current_evidence(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def __init__(self, chunk_id: str):
                self.chunk_id = chunk_id

            def generate_with_json(self, *_args, **_kwargs):
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "cache",
                            "subtopic": "mapping",
                            "correct_answer": "A",
                            "source_refs": [
                                {
                                    "chunk_id": self.chunk_id,
                                    "source_file": "cache.pdf",
                                    "page_or_slide": 1,
                                    "heading": "Cache lecture page 1",
                                }
                            ],
                            "bilingual": {
                                "zh": {
                                    "stem": "Cache?",
                                    "options": ["A. 对", "B. 错", "C. 错", "D. 错"],
                                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                                },
                                "en": {
                                    "stem": "Cache?",
                                    "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                                    "explanation": "This is a sufficiently detailed English explanation for the answer.",
                                },
                            },
                        }
                    ]
                }

        project = CourseProject(
            course_id="course-valid-source",
            title="Systems",
            source_folder="",
            summary_markdown="## Cache\nCache lines.",
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
                    "pages": ["Cache lines and cache mapping."],
                }
            ],
            created_at="2026-07-02T00:00:00+00:00",
            updated_at="2026-07-02T00:00:00+00:00",
        )
        expected_chunk_id = course_index.build_source_index(project)[0]["chunk_id"]
        worker = GenerationWorker(
            FakeClient(expected_chunk_id),
            course_content="content",
            topics=project.topics,
            count=1,
            difficulty="medium",
            course_project=project,
            generation_config=GenerationConfig(
                question_type_weights={
                    "multiple_choice": 100,
                    "scenario_choice": 0,
                    "true_false": 0,
                    "fill_in_blank": 0,
                },
                difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
                topic_weights={"cache": 100},
            ),
        )
        batches = []
        worker.batch_done.connect(batches.append)

        worker.run()

        question = batches[0][0]
        ref = question.metadata["source_refs"][0]
        self.assertEqual(expected_chunk_id, ref["chunk_id"])
        self.assertIn("Cache lines and cache mapping", ref["excerpt"])
        self.assertRegex(ref["content_hash"], r"^[0-9a-f]{12}$")
        self.assertEqual("valid_model_ref", question.metadata["source_ref_status"])

    def test_worker_replaces_forged_model_source_ref_with_plan_evidence(self):
        class FakeClient:
            model = "test-model"
            last_error = ""

            def generate_with_json(self, *_args, **_kwargs):
                return {
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "difficulty": "medium",
                            "topic": "cache",
                            "subtopic": "mapping",
                            "correct_answer": "A",
                            "source_refs": [
                                {
                                    "chunk_id": "source-9999",
                                    "source_file": "invented.pdf",
                                    "page_or_slide": 99,
                                    "heading": "Invented",
                                }
                            ],
                            "bilingual": {
                                "zh": {
                                    "stem": "Cache?",
                                    "options": ["A. 对", "B. 错", "C. 错", "D. 错"],
                                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                                },
                                "en": {
                                    "stem": "Cache?",
                                    "options": ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"],
                                    "explanation": "This is a sufficiently detailed English explanation for the answer.",
                                },
                            },
                        }
                    ]
                }

        project = CourseProject(
            course_id="course-invalid-source",
            title="Systems",
            source_folder="",
            summary_markdown="## Cache\nCache lines.",
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
                    "pages": ["Cache lines and cache mapping."],
                }
            ],
            created_at="2026-07-02T00:00:00+00:00",
            updated_at="2026-07-02T00:00:00+00:00",
        )
        worker = GenerationWorker(
            FakeClient(),
            course_content="content",
            topics=project.topics,
            count=1,
            difficulty="medium",
            course_project=project,
            generation_config=GenerationConfig(
                question_type_weights={
                    "multiple_choice": 100,
                    "scenario_choice": 0,
                    "true_false": 0,
                    "fill_in_blank": 0,
                },
                difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
                topic_weights={"cache": 100},
            ),
        )
        batches = []
        worker.batch_done.connect(batches.append)

        worker.run()

        question = batches[0][0]
        self.assertRegex(question.metadata["source_refs"][0]["chunk_id"], r"^source-[0-9a-f]{10}$")
        self.assertEqual("cache.pdf", question.metadata["source_refs"][0]["source_file"])
        self.assertEqual("invalid_model_ref", question.metadata["source_ref_status"])
        self.assertEqual(["source-9999"], question.metadata["invalid_source_ref_ids"])

    def test_dialog_returns_generation_config_from_controls(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        dialog.mc_slider.setValue(40)
        dialog.scenario_slider.setValue(30)
        dialog.true_false_slider.setValue(20)
        dialog.fill_blank_slider.setValue(10)
        dialog.matching_slider.setValue(25)
        dialog.ordering_slider.setValue(15)
        dialog.short_answer_slider.setValue(35)
        dialog.easy_slider.setValue(10)
        dialog.medium_slider.setValue(60)
        dialog.hard_slider.setValue(30)
        dialog.topic_weight_sliders["cache"].setValue(80)
        dialog.topic_weight_sliders["process"].setValue(20)
        dialog.template_combo.setCurrentIndex(dialog.template_combo.findData("final_exam"))
        for index in range(dialog.topic_list.count()):
            dialog.topic_list.item(index).setCheckState(Qt.CheckState.Checked)

        config = dialog._build_generation_config()

        self.assertEqual(config.question_type_weights["multiple_choice"], 40)
        self.assertEqual(config.question_type_weights["scenario_choice"], 30)
        self.assertEqual(config.question_type_weights["matching"], 25)
        self.assertEqual(config.question_type_weights["ordering"], 15)
        self.assertEqual(config.question_type_weights["short_answer"], 35)
        self.assertEqual(config.difficulty_weights["medium"], 60)
        self.assertEqual(config.topic_weights["cache"], 80)
        self.assertEqual(config.topic_weights["process"], 20)
        self.assertEqual(config.template, "final_exam")

    def test_dialog_shows_generation_plan_preview_from_current_controls(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        dialog.count_spin.setValue(10)
        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.topic_list.item(1).setCheckState(Qt.CheckState.Checked)
        dialog.topic_weight_sliders["cache"].setValue(70)
        dialog.topic_weight_sliders["process"].setValue(30)
        dialog.mc_slider.setValue(50)
        dialog.scenario_slider.setValue(30)
        dialog.true_false_slider.setValue(20)
        dialog.fill_blank_slider.setValue(0)
        dialog.easy_slider.setValue(20)
        dialog.medium_slider.setValue(50)
        dialog.hard_slider.setValue(30)

        dialog._refresh_weight_labels()
        dialog._update_preview()

        preview = dialog.plan_preview.toPlainText()
        self.assertIn("本次计划生成 10 题", preview)
        self.assertIn("主题分布", preview)
        self.assertIn("cache: 7", preview)
        self.assertIn("process: 3", preview)
        self.assertIn("题型分布", preview)
        self.assertIn("multiple_choice: 5", preview)
        self.assertIn("scenario_choice: 3", preview)
        self.assertIn("true_false: 2", preview)
        self.assertIn("难度分布", preview)
        self.assertIn("easy: 2", preview)
        self.assertIn("medium: 5", preview)
        self.assertIn("hard: 3", preview)
        self.assertIn("组合计划", preview)
        self.assertIn("cache", preview)
        self.assertIn("multiple_choice", preview)
        self.assertIn("definition", preview)

    def test_generation_plan_preview_updates_when_count_changes(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.count_spin.setValue(6)
        self.assertIn("本次计划生成 6 题", dialog.plan_preview.toPlainText())

        dialog.count_spin.setValue(12)

        self.assertIn("本次计划生成 12 题", dialog.plan_preview.toPlainText())

    def test_generation_dialog_footer_summary_guides_empty_topic_state(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )

        summary = dialog.footer_summary_label.text()

        self.assertEqual("generationFooterSummary", dialog.footer_summary_label.objectName())
        self.assertIn("已选主题：0", summary)
        self.assertIn("计划生成：15 题", summary)
        self.assertIn("请选择主题", summary)

    def test_generation_dialog_footer_summary_updates_with_selected_topics_and_count(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )

        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.count_spin.setValue(9)

        summary = dialog.footer_summary_label.text()

        self.assertIn("已选主题：1", summary)
        self.assertIn("计划生成：9 题", summary)
        self.assertIn("覆盖：cache", summary)

    def test_generation_dialog_disables_generate_button_when_no_topics_selected(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        self.assertFalse(dialog.generate_btn.isEnabled())

        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(dialog.generate_btn.isEnabled())

        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(dialog.generate_btn.isEnabled())

    def test_dialog_exposes_question_set_title(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )

        dialog.set_title_input.setText("  I/O 中断专项  ")

        self.assertEqual("I/O 中断专项", dialog.question_set_title())

    def test_ai_question_set_uses_user_supplied_title_without_reusing_chinese_as_english(self):
        question = Question.create_new(
            QuestionType.MULTIPLE_CHOICE,
            Difficulty.MEDIUM,
            {
                "zh": {"stem": "题干", "options": ["A. 对", "B. 错"], "explanation": "解释"},
                "en": {"stem": "Stem", "options": ["A. True", "B. False"], "explanation": "Explanation"},
            },
            "A",
            "interrupts",
            source="ai_generated",
        )

        qset = build_ai_question_set(
            [question],
            selected_difficulty="medium",
            generation_config=GenerationConfig(),
            custom_title="I/O 中断专项",
            lang="zh",
        )

        self.assertEqual("I/O 中断专项", qset.get_title("zh"))
        self.assertIn("AI Practice", qset.get_title("en"))
        self.assertNotIn("中断", qset.get_title("en"))
        self.assertTrue(qset.metadata["renamed_by_user"])

    def test_dialog_uses_saved_practice_defaults_as_initial_generation_settings(self):
        dialog = AIGenerationDialog(
            "course content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
                "default_question_count": 24,
                "default_difficulty": "hard",
                "default_generation_template": "final_exam",
                "default_question_type_weights": {
                    "multiple_choice": 45,
                    "scenario_choice": 35,
                    "true_false": 15,
                    "fill_in_blank": 5,
                },
                "default_difficulty_weights": {
                    "easy": 10,
                    "medium": 70,
                    "hard": 20,
                },
            },
            available_topics=["cache"],
        )

        self.assertEqual(24, dialog.count_spin.value())
        self.assertEqual("hard", dialog.diff_combo.currentData())
        self.assertEqual("final_exam", dialog.template_combo.currentData())
        self.assertEqual(45, dialog.mc_slider.value())
        self.assertEqual(35, dialog.scenario_slider.value())
        self.assertEqual(15, dialog.true_false_slider.value())
        self.assertEqual(5, dialog.fill_blank_slider.value())
        self.assertEqual(10, dialog.easy_slider.value())
        self.assertEqual(70, dialog.medium_slider.value())
        self.assertEqual(20, dialog.hard_slider.value())

    def test_dialog_language_change_refreshes_preview_after_difficulty_combo_rebuild(self):
        dialog = AIGenerationDialog(
            "course content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
                "default_difficulty": "hard",
            },
            available_topics=["cache"],
        )
        self.addCleanup(dialog.close)
        observed_difficulties = []
        dialog._update_preview = lambda: observed_difficulties.append(dialog.diff_combo.currentData())

        dialog._on_language_changed("en")

        self.assertEqual(["hard"], observed_difficulties)

    def test_dialog_topic_weight_rows_follow_selected_topics(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process", "memory"],
        )

        self.assertTrue(dialog.topic_weight_rows["cache"].isHidden())
        self.assertTrue(dialog.topic_weight_rows["process"].isHidden())
        self.assertTrue(dialog.topic_weight_labels["cache"].isHidden())

        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

        self.assertFalse(dialog.topic_weight_rows["cache"].isHidden())
        self.assertFalse(dialog.topic_weight_labels["cache"].isHidden())
        self.assertTrue(dialog.topic_weight_rows["process"].isHidden())

        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Unchecked)

        self.assertTrue(dialog.topic_weight_rows["cache"].isHidden())

    def test_dialog_toggle_all_topics_refreshes_preview_once(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process", "memory", "io", "network"],
        )
        self.addCleanup(dialog.close)
        calls = {"sync": 0, "preview": 0}
        original_sync = dialog._sync_topic_weight_rows
        original_preview = dialog._update_preview

        def counted_sync():
            calls["sync"] += 1
            original_sync()

        def counted_preview():
            calls["preview"] += 1
            original_preview()

        dialog._sync_topic_weight_rows = counted_sync
        dialog._update_preview = counted_preview

        dialog._toggle_all(True)

        self.assertEqual(
            [Qt.CheckState.Checked] * 5,
            [dialog.topic_list.item(index).checkState() for index in range(dialog.topic_list.count())],
        )
        self.assertEqual({"sync": 1, "preview": 1}, calls)

    def test_dialog_weight_labels_update_normalized_effective_percentages_after_confirmation(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.topic_list.item(1).setCheckState(Qt.CheckState.Checked)

        self.assertEqual("50%", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())
        self.assertEqual("50%", dialog.weight_value_labels[dialog.topic_weight_sliders["process"]].text())

        dialog.topic_weight_sliders["cache"].setValue(100)
        dialog.topic_weight_sliders["process"].setValue(80)

        self.assertEqual("50%", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())
        self.assertEqual("50%", dialog.weight_value_labels[dialog.topic_weight_sliders["process"]].text())

        dialog.refresh_weight_preview_btn.click()

        self.assertEqual("56%", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())
        self.assertEqual("44%", dialog.weight_value_labels[dialog.topic_weight_sliders["process"]].text())
        self.assertNotIn("→", dialog.weight_value_labels[dialog.topic_weight_sliders["cache"]].text())

    def test_single_selected_topic_weight_shows_effective_share_not_raw_weight(self):
        topics = [f"topic_{index}" for index in range(19)] + ["input_output_improvements"]
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=topics,
        )
        io_index = topics.index("input_output_improvements")

        dialog.topic_list.item(io_index).setCheckState(Qt.CheckState.Checked)

        label = dialog.weight_value_labels[
            dialog.topic_weight_sliders["input_output_improvements"]
        ]
        self.assertEqual("100%", label.text())
        self.assertNotEqual("5%", label.text())

    def test_generation_progress_hides_internal_plan_slot_keys(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["input_output_improvements"],
        )

        dialog._on_progress(
            "Filling plan slots: input_output_improvements/true_false/easy, "
            "input_output_improvements/multiple_choice/medium"
        )

        status = dialog.status_label.text()
        log_text = dialog.generation_log.toPlainText()
        self.assertIn("正在安排", status)
        self.assertNotIn("input_output_improvements/true_false/easy", status)
        self.assertNotIn("input_output_improvements/true_false/easy", log_text)

    def test_generation_progress_keeps_readable_plan_slot_summary(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )

        message = dialog._display_progress_message(
            "Filling plan slots: 3 planned slot(s) across Cache, Process"
        )

        self.assertIn("3", message)
        self.assertIn("Cache", message)
        self.assertIn("Process", message)
        self.assertNotIn("planned slot", message)

    def test_course_preview_keeps_more_context_for_selected_topic(self):
        long_content = (
            "## Input Output Improvements\n"
            + "DMA, interrupts, buffering and I/O controller details. " * 90
            + "deep sentinel detail about interrupt driven I/O latency."
        )
        dialog = AIGenerationDialog(
            long_content,
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["Input Output Improvements"],
        )

        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

        preview = dialog.prompt_preview.toPlainText()
        self.assertGreater(len(preview), 3000)
        self.assertIn("deep sentinel detail", preview)

    def test_generation_status_keeps_latest_progress_and_elapsed_hint(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        dialog._generation_started_at = 100.0

        with patch("ui.dialogs.ai_generation_dialog.time.monotonic", return_value=106.4):
            dialog._on_progress("Requesting batch 1/3 from AI...")

        text = dialog.status_label.text()
        self.assertIn("Requesting batch 1/3", text)
        self.assertIn("6s", text)
        self.assertIn("可取消", text)

    def test_generation_progress_log_keeps_recent_events(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )

        dialog._on_progress("Building prompt...")
        dialog._on_progress("Accepted 2 question(s), rejected 1.")

        log_text = dialog.generation_log.toPlainText()
        self.assertIn("正在准备课程上下文", log_text)
        self.assertIn("本批接受 2 道，拒绝 1 道", log_text)
        self.assertEqual("generationProgressLog", dialog.generation_log.objectName())

    def test_generation_progress_log_scrolls_to_latest_event(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        dialog.generation_log.setFixedHeight(40)
        dialog.show()
        try:
            _APP.processEvents()
            for index in range(60):
                dialog._append_generation_event(f"event {index}")
            _APP.processEvents()
            scrollbar = dialog.generation_log.verticalScrollBar()
            self.assertGreater(scrollbar.maximum(), 0)
            scrollbar.setValue(0)

            dialog._append_generation_event("latest event")
            _APP.processEvents()

            self.assertEqual(scrollbar.maximum(), scrollbar.value())
            self.assertTrue(dialog.generation_log.toPlainText().endswith("latest event"))
        finally:
            dialog.close()

    def test_generation_status_localizes_single_question_request_progress(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )

        message = dialog._display_progress_message(
            "Generating question 3/10... (attempt 4/30; requesting 1 candidate)"
        )

        self.assertIn("正在生成第 3/10 题", message)

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

    def test_dialog_can_prefill_from_existing_question_set(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process", "gpu"],
        )
        qset = QuestionSet(
            set_id="set-review",
            title={"zh": "复习", "en": "Review"},
            description={"zh": "", "en": ""},
            topics=["cache", "gpu"],
            difficulty=Difficulty.HARD,
            estimated_minutes=20,
            questions=["q1", "q2", "q3", "q4", "q5"],
        )

        dialog.configure_from_question_set(qset)

        self.assertEqual(dialog.count_spin.value(), 5)
        self.assertEqual(dialog.diff_combo.currentData(), "hard")
        checked = {
            dialog.topic_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.topic_list.count())
            if dialog.topic_list.item(index).checkState() == Qt.CheckState.Checked
        }
        self.assertEqual({"cache", "gpu"}, checked)

    def test_dialog_exam_plan_round_trip_applies_all_controls(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        target = ExamGenerationPlan(
            question_count=22,
            difficulty="mixed",
            template="final_exam",
            selected_topics=("process",),
            question_type_weights={
                "multiple_choice": 20,
                "scenario_choice": 20,
                "true_false": 20,
                "fill_in_blank": 10,
                "matching": 10,
                "ordering": 10,
                "short_answer": 10,
            },
            difficulty_weights={"easy": 10, "medium": 50, "hard": 40},
            topic_weights={"process": 100},
        )

        dialog.apply_exam_plan(target)
        rebuilt = dialog.build_exam_plan()

        self.assertEqual(target.to_dict(), rebuilt.to_dict())
        checked = {
            dialog.topic_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.topic_list.count())
            if dialog.topic_list.item(index).checkState() == Qt.CheckState.Checked
        }
        self.assertEqual({"process"}, checked)

    def test_exam_assistant_button_uses_descriptive_label_instead_of_jargon(self):
        from core.language_manager import LanguageManager

        lang_manager = LanguageManager.instance()
        previous_lang = lang_manager.current
        self.addCleanup(lang_manager.set_language, previous_lang)

        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )

        lang_manager.set_language("zh")
        self.assertNotIn("试卷助手", dialog.exam_assistant_btn.text())

        lang_manager.set_language("en")
        self.assertNotIn("Exam Assistant", dialog.exam_assistant_btn.text())

    def test_accepted_exam_assistant_plan_is_applied(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        target = ExamGenerationPlan(
            question_count=30,
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )

        with patch("ui.dialogs.exam_assistant_dialog.ExamAssistantDialog") as assistant_class:
            assistant = assistant_class.return_value
            assistant.exec.return_value = QDialog.DialogCode.Accepted
            assistant.get_confirmed_plan.return_value = target

            dialog._open_exam_assistant()

        self.assertEqual(30, dialog.count_spin.value())
        assistant_class.assert_called_once()

    def test_dialog_prefills_all_controls_from_course_generation_profile(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        profile = ExamGenerationPlan(
            question_count=26,
            difficulty="mixed",
            template="calculation_practice",
            selected_topics=("cache", "process"),
            question_type_weights={
                "multiple_choice": 30,
                "scenario_choice": 30,
                "true_false": 10,
                "fill_in_blank": 30,
            },
            difficulty_weights={"easy": 10, "medium": 40, "hard": 50},
            topic_weights={"cache": 70, "process": 30},
        )
        course = SimpleNamespace(generation_profile=profile.to_dict())

        applied = dialog.configure_from_course_profile(course)

        self.assertTrue(applied)
        self.assertEqual(profile.to_dict(), dialog.build_exam_plan().to_dict())

    def test_malformed_course_profile_keeps_current_controls_and_shows_error(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        before = dialog.build_exam_plan().to_dict()
        course = SimpleNamespace(
            generation_profile={"selected_topics": ["invented topic"]}
        )

        applied = dialog.configure_from_course_profile(course)

        self.assertFalse(applied)
        self.assertEqual(before, dialog.build_exam_plan().to_dict())
        self.assertIn("invented topic", dialog.status_label.text())

    def test_course_profile_legacy_topic_names_are_migrated_before_apply(self):
        from models.course_project import CourseTopic

        io_topic = CourseTopic(
            topic_id="input_output_improvements",
            title="Input Output Improvements",
            aliases=["input output improvements", "I/O 改进"],
        )
        vm_topic = CourseTopic(
            topic_id="virtual_memory_address_translation_and_page_replacement",
            title="Virtual Memory Address Translation and Page Replacement",
        )
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=[io_topic, vm_topic],
        )
        course = SimpleNamespace(
            topics=[io_topic, vm_topic],
            generation_profile={
                "selected_topics": [
                    "input output improvements",
                    "Virtual Memory Address Translation and Page Replacement",
                ],
                "topic_weights": {
                    "input output improvements": 70,
                    "Virtual Memory Address Translation and Page Replacement": 30,
                },
            },
        )

        applied = dialog.configure_from_course_profile(course)

        self.assertTrue(applied)
        plan = dialog.build_exam_plan()
        self.assertEqual(
            (
                "input_output_improvements",
                "virtual_memory_address_translation_and_page_replacement",
            ),
            plan.selected_topics,
        )
        self.assertEqual(70, plan.topic_weights["input_output_improvements"])
        self.assertEqual(
            30,
            plan.topic_weights["virtual_memory_address_translation_and_page_replacement"],
        )
        self.assertNotIn("无效", dialog.status_label.text())

    def test_course_profile_warning_detail_is_not_shown_in_generation_dialog_status(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        profile = ExamGenerationPlan(
            question_count=12,
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )
        course = SimpleNamespace(
            generation_profile=profile.to_dict(),
            generation_profile_source="local",
            generation_profile_warning=(
                "Course profile LLM request failed: "
                "Anthropic API response did not contain a text block."
            ),
        )

        applied = dialog.configure_from_course_profile(course)

        self.assertTrue(applied)
        status = dialog.status_label.text()
        self.assertIn("本地回退", status)
        self.assertNotIn("Course profile LLM request failed", status)
        self.assertNotIn("Anthropic API response did not contain a text block", status)

    def test_question_set_history_overrides_course_profile_on_regeneration(self):
        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache", "process"],
        )
        course_profile = ExamGenerationPlan(
            question_count=20,
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )
        dialog.configure_from_course_profile(
            SimpleNamespace(generation_profile=course_profile.to_dict())
        )
        question_set = QuestionSet(
            set_id="set-history",
            title={"zh": "历史", "en": "History"},
            description={"zh": "", "en": ""},
            topics=["process"],
            difficulty=Difficulty.HARD,
            estimated_minutes=30,
            questions=[f"q-{index}" for index in range(18)],
            metadata={
                "difficulty_mode": "hard",
                "generation_template": "final_exam",
                "question_type_weights": {
                    "multiple_choice": 40,
                    "scenario_choice": 40,
                    "true_false": 10,
                    "fill_in_blank": 10,
                },
                "difficulty_weights": {"easy": 10, "medium": 30, "hard": 60},
                "topic_weights": {"process": 100},
            },
        )

        dialog.configure_from_question_set(question_set)
        rebuilt = dialog.build_exam_plan()

        self.assertEqual(18, rebuilt.question_count)
        self.assertEqual("final_exam", rebuilt.template)
        self.assertEqual(("process",), rebuilt.selected_topics)
        self.assertEqual(60, rebuilt.difficulty_weights["hard"])

    def test_main_generation_flow_applies_active_course_profile_before_opening(self):
        from core.language_manager import LanguageManager
        from ui.main_window import MainWindow

        class ForbiddenSecrets:
            def get_key(self):
                raise AssertionError("local agent generation preflight must not read persisted API keys")

        settings = {
            "ai_provider": "local_agent",
            "ai_base_url": "local-agent://auto",
            "ai_model": "codex",
        }
        course = SimpleNamespace(
            course_id="course-cache",
            title="Cache",
            generation_profile={"question_count": 20},
        )
        task_center = object()
        workspace = Mock()
        workspace.generation_widget.return_value = None
        shell = SimpleNamespace(
            settings_screen=SimpleNamespace(settings_snapshot=lambda: dict(settings)),
            lang_manager=LanguageManager.instance(),
            _load_generation_context=lambda: ("summary", ["cache"], course),
            task_center=task_center,
            _generation_workspace=workspace,
            SCREEN_GENERATION=8,
            navigate_to=Mock(return_value=True),
        )

        with patch("ui.generation_workspace_controller.ai_generation_settings_error", return_value=""), \
             patch("core.secrets_manager.SecretsManager.instance", return_value=ForbiddenSecrets()), \
             patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog") as dialog_class:
            MainWindow._on_ai_generate(shell)

        dialog_class.return_value.configure_from_course_profile.assert_called_once_with(course)
        dialog_class.return_value.exec.assert_not_called()
        workspace.show_generation_widget.assert_called_once()
        self.assertIs(task_center, dialog_class.call_args.kwargs["task_center"])

    def test_predicted_generation_prefills_reviewable_plan_after_course_defaults(self):
        from core.language_manager import LanguageManager
        from ui.main_window import MainWindow

        settings = {
            "ai_provider": "local_agent",
            "ai_base_url": "local-agent://auto",
            "ai_model": "codex",
        }
        course = SimpleNamespace(
            course_id="course-a",
            title="Systems",
            summary_markdown="summary",
            topics=[CourseTopic("io", "I/O")],
            generation_profile={"question_count": 10},
        )
        plan = ExamGenerationPlan(
            question_count=20,
            difficulty="mixed",
            template="final_exam",
            selected_topics=("io",),
            topic_weights={"io": 100},
        )
        prediction = SimpleNamespace(plan=plan, source_count=2, warnings=("short_answer",))
        workspace = Mock()
        workspace.generation_widget.return_value = None
        shell = SimpleNamespace(
            settings_screen=SimpleNamespace(settings_snapshot=lambda: dict(settings)),
            lang_manager=LanguageManager.instance(),
            _generation_workspace=workspace,
            SCREEN_GENERATION=8,
            navigate_to=Mock(return_value=True),
        )

        with patch("ui.generation_workspace_controller.ai_generation_settings_error", return_value=""), \
             patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog") as dialog_class:
            dialog = dialog_class.return_value

            MainWindow._on_ai_generate(
                shell,
                course_override=course,
                initial_plan=plan,
                prediction=prediction,
            )

        dialog.configure_from_course_profile.assert_called_once_with(course)
        dialog.apply_exam_plan.assert_called_once_with(plan)
        dialog.set_draft_source.assert_called_once_with("manual")
        dialog.exec.assert_not_called()
        workspace.show_generation_widget.assert_called_once()
        dialog.set_title_input.setText.assert_called_once_with("Systems预测模拟卷")
        self.assertIn("2 份历史真题画像", dialog.status_label.setText.call_args.args[0])
        self.assertIn("不代表未来考题", dialog.status_label.setText.call_args.args[0])

    def test_main_generation_flow_rolls_back_questions_when_question_set_save_fails(self):
        from core.language_manager import LanguageManager
        from models.question import QuestionBank
        from models.question_set import SetManager
        from ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))
            question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "Cache 题",
                        "options": ["A. one", "B. two"],
                        "explanation": "解释说明足够完整。",
                    },
                    "en": {
                        "stem": "Cache question",
                        "options": ["A. one", "B. two"],
                        "explanation": "Explanation text with enough detail.",
                    },
                },
                correct_answer="A",
                topic="cache",
            )
            settings = {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            }
            class FakeDialog:
                generated_questions = [question]
                diff_combo = SimpleNamespace(currentData=lambda: "medium")

                def __init__(self, *args, **kwargs):
                    self.accepted = Mock()
                    self.rejected = Mock()
                    self.show_save_error = Mock()
                    self.deleteLater = Mock()

                def configure_from_course_profile(self, course_project):
                    pass

                def _build_generation_config(self):
                    return GenerationConfig(topic_weights={"cache": 100})

                def question_set_title(self):
                    return "AI 事务测试"

            workspace = Mock()
            workspace.generation_widget.return_value = None
            navigate_to = Mock(return_value=True)
            shell = SimpleNamespace(
                settings_screen=SimpleNamespace(settings_snapshot=lambda: dict(settings)),
                lang_manager=LanguageManager.instance(),
                question_bank=question_bank,
                set_manager=set_manager,
                SCREEN_TOPIC_SELECTION=1,
                SCREEN_GENERATION=8,
                _generation_workspace=workspace,
                _load_generation_context=lambda: ("summary", ["cache"], None),
                navigate_to=navigate_to,
                _on_question_bank_changed=Mock(),
            )

            with patch("ui.generation_workspace_controller.ai_generation_settings_error", return_value=""), \
                 patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog", FakeDialog), \
                 patch.object(set_manager, "save", return_value=False), \
                 patch("ui.generation_workspace_controller.QMessageBox.critical") as critical:
                MainWindow._on_ai_generate(shell)
                dialog = workspace.show_generation_widget.call_args.args[0]
                dialog.accepted.connect.call_args.args[0]()

            critical.assert_not_called()
            dialog.show_save_error.assert_called_once()
            self.assertIsNone(question_bank.get(question.question_id))
            navigate_to.assert_called_once_with(
                8,
                allow_first_run_redirect=False,
            )


if __name__ == "__main__":
    unittest.main()
