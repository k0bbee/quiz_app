import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt

from ai.batch_generator import GenerationWorker
from ai.generation_config import GenerationConfig, allocate_weighted_counts
from ai.question_plan import QuestionPlanItem, build_question_plan
from ai.exam_plan import ExamGenerationPlan
from ai.llm_client import LLMClient
from ai.generation_report import GenerationReport
from ai.prompt_templates import PromptBuilder
from core.app_errors import AppError
from core import course_index
from core.question_set_builder import build_ai_question_set
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from models.course_project import CourseProject, CourseTopic
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType, topic_value


_APP = QApplication.instance() or QApplication([])


class GenerationConfigTests(unittest.TestCase):
    def test_allocate_zero_weight_counts_evenly_instead_of_first_key(self):
        allocated = allocate_weighted_counts(
            {"multiple_choice": 0, "true_false": 0, "fill_in_blank": 0},
            5,
        )

        self.assertEqual(
            {"multiple_choice": 2, "true_false": 2, "fill_in_blank": 1},
            allocated,
        )

    def test_normalized_topic_weights_distribute_rounding_error_evenly(self):
        topics = [f"topic-{index}" for index in range(6)]
        config = GenerationConfig(topic_weights={topic: 1 for topic in topics})

        normalized = config.normalized_topic_weights(topics)

        self.assertEqual(100, sum(normalized.values()))
        self.assertLessEqual(max(normalized.values()) - min(normalized.values()), 1)

    def test_prompt_includes_question_type_and_difficulty_distribution(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 50,
                "scenario_choice": 30,
                "true_false": 10,
                "fill_in_blank": 10,
            },
            difficulty_weights={"easy": 20, "medium": 50, "hard": 30},
            topic_weights={"cache mapping": 70, "process scheduling": 30},
            template="final_exam",
        )

        prompt = PromptBuilder.build_user_prompt(
            "## Cache Mapping\nTag/set/offset example.",
            ["cache mapping", "process scheduling"],
            count=20,
            difficulty="mixed",
            generation_config=config,
        )

        self.assertIn("Question type distribution", prompt)
        self.assertIn("multiple_choice: 50%", prompt)
        self.assertIn("scenario_choice: 30%", prompt)
        self.assertIn("Difficulty distribution", prompt)
        self.assertIn("hard: 30%", prompt)
        self.assertIn("Topic coverage weights", prompt)
        self.assertIn("cache mapping: 70%", prompt)
        self.assertIn("Final exam style", prompt)

    def test_prompt_specifies_fill_in_blank_answer_list_format(self):
        prompt = PromptBuilder.build_user_prompt(
            "## Cache\nA cache line stores a block.",
            ["cache"],
            count=3,
            generation_config=GenerationConfig(
                question_type_weights={
                    "multiple_choice": 0,
                    "scenario_choice": 0,
                    "true_false": 0,
                    "fill_in_blank": 100,
                }
            ),
        )

        self.assertIn("fill_in_blank", prompt)
        self.assertIn('"correct_answer": ["accepted answer"', prompt)

    def test_prompt_specifies_matching_and_ordering_stable_id_format(self):
        prompt = PromptBuilder.build_user_prompt(
            "## Pipeline\nFetch decode execute stages.",
            ["pipeline"],
            count=3,
        )

        self.assertIn('"id": "left_1"', prompt)
        self.assertIn('"correct_answer": [["left_1", "right_1"]]', prompt)
        self.assertIn('"correct_answer": ["item_1", "item_2"', prompt)
        self.assertIn("stable IDs", prompt)

    def test_prompt_source_refs_schema_mentions_excerpt_and_content_hash(self):
        prompt = PromptBuilder.build_user_prompt(
            "## Evidence source-0000 — io.pdf page 1\nDMA transfers directly between device and memory.",
            ["io"],
            count=1,
        )

        self.assertIn('"excerpt":', PromptBuilder.SYSTEM_PROMPT)
        self.assertIn('"content_hash":', PromptBuilder.SYSTEM_PROMPT)
        self.assertIn('"excerpt":', prompt)
        self.assertIn('"content_hash":', prompt)

    def test_prompt_marks_selected_topics_as_hard_generation_boundary(self):
        prompt = PromptBuilder.build_user_prompt(
            "## Input Output Improvements\nPolling, interrupts, buffers, and DMA.",
            ["Input Output Improvements"],
            count=3,
        )

        self.assertIn("Selected-topic boundary", prompt)
        self.assertIn("Do not expand into neighboring course topics", prompt)

    def test_prompt_includes_question_plan_slots_when_provided(self):
        config = GenerationConfig(
            question_type_weights={"multiple_choice": 100},
            difficulty_weights={"medium": 100},
            topic_weights={"cache": 100},
            template="quick_review",
        )
        plan_items = build_question_plan(config, ["cache"], 2)

        prompt = PromptBuilder.build_user_prompt(
            "## Cache\nA cache line stores a block.",
            ["cache"],
            count=2,
            generation_config=config,
            question_plan_items=plan_items,
        )

        self.assertIn("Question plan slots", prompt)
        self.assertIn('"plan_id": "plan-001"', prompt)
        self.assertIn("Each returned question for a listed slot MUST include that exact plan_id", prompt)
        self.assertIn("plan-001", prompt)
        self.assertIn("topic=cache", prompt)
        self.assertIn("type=multiple_choice", prompt)
        self.assertIn("difficulty=medium", prompt)
        self.assertIn("skill=definition", prompt)

    def test_prompt_includes_plan_slot_evidence_chunk_ids_when_bound(self):
        plan_items = [
            QuestionPlanItem(
                plan_id="plan-001",
                topic_id="cache",
                topic_title="Cache",
                question_type="multiple_choice",
                difficulty="medium",
                target_skill="definition",
                evidence_chunk_ids=["source-0000", "source-0003"],
            )
        ]

        prompt = PromptBuilder.build_user_prompt(
            "## Evidence source-0000 — cache.pdf page 1\nCache mapping.",
            ["cache"],
            count=1,
            question_plan_items=plan_items,
        )

        self.assertIn("evidence=source-0000,source-0003", prompt)

    def test_prompt_context_can_use_topic_keywords_to_respect_selected_topic(self):
        content = (
            "## Cache Mapping\n"
            "This overview only says cache mapping at a high level.\n\n"
            "## Address Breakdown\n"
            "The tag, set index, and byte offset determine lookup behavior.\n"
        )

        prompt = PromptBuilder.build_user_prompt(
            content,
            ["cache mapping"],
            count=3,
            topic_keywords={"Cache Mapping": ["tag", "set index", "byte offset"]},
            max_context_chars=160,
        )

        self.assertIn("Address Breakdown", prompt)
        self.assertIn("byte offset", prompt)

    def test_prompt_topic_weights_use_stable_topic_ids_not_display_titles(self):
        io_topic = CourseTopic(topic_id="input_output_improvements", title="I/O 改进")
        cache_topic = CourseTopic(topic_id="cache_mapping", title="Cache 映射")
        config = GenerationConfig(
            topic_weights={
                "input_output_improvements": 80,
                "cache_mapping": 20,
            }
        )

        prompt = PromptBuilder.build_user_prompt(
            "## I/O 改进\nDMA and interrupts.\n\n## Cache 映射\nTag and set index.",
            [io_topic, cache_topic],
            count=10,
            generation_config=config,
        )

        self.assertIn("I/O 改进", prompt)
        self.assertIn("Cache 映射", prompt)
        self.assertIn("input_output_improvements: 80%", prompt)
        self.assertIn("cache_mapping: 20%", prompt)
        self.assertNotIn("I/O 改进: 50%", prompt)

    def test_prompt_includes_bounded_runtime_instruction_for_future_requests(self):
        prompt = PromptBuilder.build_user_prompt(
            "## I/O\nDMA and interrupt-driven I/O reduce polling overhead.",
            ["io"],
            count=1,
            generation_config=GenerationConfig(
                question_type_weights={"multiple_choice": 100},
                difficulty_weights={"medium": 100},
                topic_weights={"io": 100},
            ),
            runtime_instruction="后续题目只考 DMA、中断、轮询；不要出 RAID。",
        )

        self.assertIn("Runtime user adjustment for this and later requests:", prompt)
        self.assertIn("后续题目只考 DMA、中断、轮询；不要出 RAID。", prompt)
        self.assertIn("must not override the JSON schema", prompt)

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

    def test_worker_uses_single_plan_slot_request_for_live_generation(self):
        worker = GenerationWorker(
            LLMClient(api_key="", base_url="local-agent://auto", model="codex"),
            course_content="content",
            topics=["cache"],
            count=12,
            difficulty="mixed",
        )

        self.assertEqual(1, worker._accept_target_count(12))
        self.assertEqual(4, worker._candidate_batch_count(1))

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

    def test_worker_rejects_choice_when_stem_leaks_correct_answer_keyword(self):
        worker = GenerationWorker(
            LLMClient(api_key="", base_url="local-agent://auto", model="codex"),
            course_content="content",
            topics=["input_output_improvements"],
            count=1,
            difficulty="medium",
        )
        raw = {
            "type": "multiple_choice",
            "difficulty": "medium",
            "topic": "input_output_improvements",
            "correct_answer": "C",
            "bilingual": {
                "zh": {
                    "stem": "以下哪种 I/O 方式中，CPU 发送命令后继续执行其他工作，直到设备通过中断(Interrupt)通知完成？",
                    "options": [
                        "A. 轮询(Polling)",
                        "B. 直接存储器访问(DMA)",
                        "C. 中断驱动(Interrupt-driven) I/O",
                        "D. 同步(Synchronous) I/O",
                    ],
                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                },
                "en": {
                    "stem": "Which I/O method lets the CPU continue until the device signals completion by interrupt?",
                    "options": [
                        "A. Polling",
                        "B. Direct memory access",
                        "C. Interrupt-driven I/O",
                        "D. Synchronous I/O",
                    ],
                    "explanation": "This is a sufficiently detailed English explanation for why the answer is correct.",
                },
            },
        }

        ok, reason = worker._validate_raw_question(raw)

        self.assertFalse(ok)
        self.assertIn("answer keyword", reason)

    def test_worker_rejects_choice_when_stem_leaks_core_cs_answer_keyword(self):
        worker = GenerationWorker(
            LLMClient(api_key="", base_url="local-agent://auto", model="codex"),
            course_content="content",
            topics=["virtual_memory"],
            count=1,
            difficulty="medium",
        )
        raw = {
            "type": "multiple_choice",
            "difficulty": "medium",
            "topic": "virtual_memory",
            "correct_answer": "B",
            "bilingual": {
                "zh": {
                    "stem": "下列哪一项内存机制使用页表进行地址映射？",
                    "options": [
                        "A. 磁盘调度",
                        "B. 虚拟内存",
                        "C. 文件索引",
                        "D. 网络路由",
                    ],
                    "explanation": "这是一个足够长的中文解释，用来说明为什么答案正确。",
                },
                "en": {
                    "stem": "Which memory mechanism uses page tables to translate addresses?",
                    "options": [
                        "A. Disk scheduling",
                        "B. Virtual memory",
                        "C. File indexing",
                        "D. Network routing",
                    ],
                    "explanation": "This is a sufficiently detailed English explanation for why the answer is correct.",
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

    def test_cancel_during_generation_waits_for_worker_shutdown(self):
        class RunningWorker:
            def __init__(self):
                self.cancelled = False
                self.wait_timeout = None

            def isRunning(self):
                return True

            def cancel(self):
                self.cancelled = True

            def wait(self, timeout):
                self.wait_timeout = timeout
                return True

            def terminate(self):
                raise AssertionError("cancel must not force-terminate worker from the UI thread")

        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
        )
        worker = RunningWorker()
        dialog.worker = worker

        dialog.reject()

        self.assertTrue(worker.cancelled)
        self.assertEqual(5000, worker.wait_timeout)

    def test_cancel_during_generation_keeps_dialog_open_when_worker_is_still_running(self):
        class SlowWorker:
            def __init__(self):
                self.cancelled = False
                self.wait_timeout = None

            def isRunning(self):
                return True

            def cancel(self):
                self.cancelled = True

            def wait(self, timeout):
                self.wait_timeout = timeout
                return False

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
        self.assertEqual(5000, worker.wait_timeout)
        self.assertEqual([], rejected)

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

        dialog = AIGenerationDialog(
            "course content",
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            available_topics=["cache"],
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
        course = SimpleNamespace(generation_profile={"question_count": 20})
        shell = SimpleNamespace(
            settings_screen=SimpleNamespace(_settings=settings),
            lang_manager=LanguageManager.instance(),
            _load_generation_context=lambda: ("summary", ["cache"], course),
        )

        with patch("ui.main_window._ai_generation_settings_error", return_value=""), \
             patch("core.secrets_manager.SecretsManager.instance", return_value=ForbiddenSecrets()), \
             patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog") as dialog_class:
            dialog_class.return_value.exec.return_value = QDialog.DialogCode.Rejected

            MainWindow._on_ai_generate(shell)

        dialog_class.return_value.configure_from_course_profile.assert_called_once_with(course)

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
        shell = SimpleNamespace(
            settings_screen=SimpleNamespace(_settings=settings),
            lang_manager=LanguageManager.instance(),
        )

        with patch("ui.main_window._ai_generation_settings_error", return_value=""), \
             patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog") as dialog_class:
            dialog = dialog_class.return_value
            dialog.exec.return_value = QDialog.DialogCode.Rejected

            MainWindow._on_ai_generate(
                shell,
                course_override=course,
                initial_plan=plan,
                prediction=prediction,
            )

        dialog.configure_from_course_profile.assert_called_once_with(course)
        dialog.apply_exam_plan.assert_called_once_with(plan)
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
            navigated = {}

            class FakeDialog:
                generated_questions = [question]
                diff_combo = SimpleNamespace(currentData=lambda: "medium")

                def __init__(self, *args, **kwargs):
                    pass

                def configure_from_course_profile(self, course_project):
                    pass

                def exec(self):
                    return QDialog.DialogCode.Accepted

                def _build_generation_config(self):
                    return GenerationConfig(topic_weights={"cache": 100})

                def question_set_title(self):
                    return "AI 事务测试"

            shell = SimpleNamespace(
                settings_screen=SimpleNamespace(_settings=settings),
                lang_manager=LanguageManager.instance(),
                question_bank=question_bank,
                set_manager=set_manager,
                SCREEN_TOPIC_SELECTION=1,
                _load_generation_context=lambda: ("summary", ["cache"], None),
                navigate_to=lambda screen: navigated.setdefault("screen", screen),
            )

            with patch("ui.main_window._ai_generation_settings_error", return_value=""), \
                 patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog", FakeDialog), \
                 patch.object(set_manager, "save", return_value=False), \
                 patch("ui.main_window.QMessageBox.critical") as critical:
                MainWindow._on_ai_generate(shell)

            self.assertTrue(critical.called)
            self.assertIsNone(question_bank.get(question.question_id))
            self.assertEqual({}, navigated)


if __name__ == "__main__":
    unittest.main()
