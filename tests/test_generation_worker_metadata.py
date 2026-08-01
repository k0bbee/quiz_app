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
from ui.generation_workspace_controller import GenerationWorkspaceController
from ui.navigation import Route
from models.course_project import CourseProject, CourseTopic
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType, topic_value


_APP = QApplication.instance() or QApplication([])

class GenerationWorkerMetadataTests(unittest.TestCase):
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
