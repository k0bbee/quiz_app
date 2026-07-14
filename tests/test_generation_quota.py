import unittest
import re

from ai.batch_generator import GenerationWorker, allocate_weighted_counts
from ai.generation_batch_scheduler import GenerationBatchScheduler
from ai.generation_candidate_processor import CandidateProcessingResult
from ai.generation_config import GenerationConfig
from ai.generation_quota_tracker import GenerationQuotaTracker
from ai.generation_report import GenerationReport
from ai.generation_result_accumulator import GenerationResultAccumulator
from ai.question_plan import QuestionPlanItem
from core.app_errors import AppError
from models.course_project import CourseTopic
from utils.constants import topic_value


def raw_question(qtype, difficulty, topic, index=0):
    if qtype == "true_false":
        answer = "true"
        options_zh = ["正确", "错误"]
        options_en = ["True", "False"]
    else:
        answer = "A"
        options_zh = ["A. 正确", "B. 错误", "C. 错误", "D. 错误"]
        options_en = ["A. Right", "B. Wrong", "C. Wrong", "D. Wrong"]
    return {
        "type": qtype,
        "difficulty": difficulty,
        "topic": topic,
        "subtopic": f"subtopic-{index}",
        "correct_answer": answer,
        "bilingual": {
            "zh": {
                "stem": f"问题 {index}",
                "options": options_zh,
                "explanation": "这是足够长的中文解释，用于说明答案和推理过程。",
            },
            "en": {
                "stem": f"Question {index}",
                "options": options_en,
                "explanation": "This is a sufficiently detailed explanation of the correct reasoning.",
            },
        },
    }


class SequenceClient:
    model = "test-model"
    last_error = ""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_with_json(self, messages, **kwargs):
        self.calls.append(messages)
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class TopicDriftClient:
    model = "test-model"
    last_error = ""

    def __init__(self):
        self.requested_counts = []

    def generate_with_json(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        match = re.search(r"Generate\s+(\d+)\s+bilingual quiz questions", prompt)
        requested = int(match.group(1)) if match else 0
        self.requested_counts.append(requested)

        questions = []
        for index in range(min(3, requested)):
            questions.append(raw_question("multiple_choice", "medium", "other-topic", index))
        for index in range(max(0, requested - 3)):
            questions.append(raw_question("multiple_choice", "medium", "cache", 100 + index))
        return {"questions": questions}


class TruncationThenSuccessClient:
    model = "test-model"

    def __init__(self):
        self.last_error = ""
        self.requested_counts = []

    def generate_with_json(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        match = re.search(r"Generate\s+(\d+)\s+bilingual quiz questions", prompt)
        requested = int(match.group(1)) if match else 0
        self.requested_counts.append(requested)
        if requested > 2:
            self.last_error = (
                "JSON parse error (attempt 3/3): "
                "Unterminated string starting at: line 410 column 13"
            )
            return None
        self.last_error = ""
        return {
            "questions": [
                raw_question("multiple_choice", "medium", "cache", index)
                for index in range(requested)
            ]
        }


class OneTruncationThenSuccessClient:
    model = "test-model"

    def __init__(self):
        self.last_error = ""
        self.requested_counts = []
        self.failed_once = False

    def generate_with_json(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        match = re.search(r"Generate\s+(\d+)\s+bilingual quiz questions", prompt)
        requested = int(match.group(1)) if match else 0
        self.requested_counts.append(requested)
        if not self.failed_once:
            self.failed_once = True
            self.last_error = (
                "JSON parse error (attempt 3/3): "
                "Unterminated string starting at: line 410 column 13"
            )
            return None
        self.last_error = ""
        return {
            "questions": [
                raw_question("multiple_choice", "medium", "cache", len(self.requested_counts) * 100 + index)
                for index in range(requested)
            ]
        }


class AlwaysTruncatedClient:
    model = "test-model"
    last_error = (
        "JSON parse error (attempt 3/3): "
        "Unterminated string starting at: line 410 column 13"
    )

    def generate_with_json(self, messages, **kwargs):
        return None


class GenerationQuotaTests(unittest.TestCase):
    def test_weighted_allocation_is_deterministic_and_sums_to_count(self):
        allocated = allocate_weighted_counts(
            {"multiple_choice": 50, "scenario_choice": 30, "true_false": 20},
            7,
        )

        self.assertEqual(7, sum(allocated.values()))
        self.assertEqual(
            {"multiple_choice": 4, "scenario_choice": 2, "true_false": 1},
            allocated,
        )

    def test_quota_accept_refuses_filled_slots_without_mutating_remaining_counts(self):
        tracker = GenerationQuotaTracker(
            GenerationConfig(
                question_type_weights={"multiple_choice": 100},
                difficulty_weights={"medium": 100},
                topic_weights={"cache": 100},
            ),
            topics=["cache"],
            count=1,
        )

        tracker.accept("multiple_choice", "medium", "cache")
        before = tracker.missing_quotas()

        with self.assertRaises(ValueError):
            tracker.accept("multiple_choice", "medium", "cache")

        self.assertEqual(before, tracker.missing_quotas())
        self.assertEqual(0, tracker.remaining_types["multiple_choice"])
        self.assertEqual(0, tracker.remaining_difficulties["medium"])
        self.assertEqual(0, tracker.remaining_topics["cache"])

    def test_worker_builds_quota_tracker_from_pure_business_module(self):
        worker = GenerationWorker(
            SequenceClient([]),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
        )

        self.assertIsInstance(worker._make_quota_tracker(), GenerationQuotaTracker)

    def test_worker_builds_result_accumulator_from_pure_business_module(self):
        worker = GenerationWorker(
            SequenceClient([]),
            course_content="content",
            topics=["cache"],
            count=2,
            difficulty="medium",
            generation_config=GenerationConfig(template="final_exam"),
        )

        state = worker._make_result_accumulator(max_attempts=9)

        self.assertIsInstance(state, GenerationResultAccumulator)
        self.assertEqual(2, state.requested_count)
        self.assertEqual(9, state.max_attempts)
        self.assertEqual("final_exam", state.template)

    def test_worker_builds_batch_scheduler_from_pure_business_module(self):
        worker = GenerationWorker(
            SequenceClient([]),
            course_content="content",
            topics=["cache"],
            count=7,
            difficulty="medium",
        )

        scheduler = worker._make_batch_scheduler()

        self.assertIsInstance(scheduler, GenerationBatchScheduler)
        self.assertEqual(7, scheduler.requested_count)
        self.assertEqual(24, scheduler.max_attempts)

    def test_worker_delegates_candidate_acceptance_to_pure_processor(self):
        candidate = raw_question("multiple_choice", "medium", "cache")
        worker = GenerationWorker(
            SequenceClient([{"questions": [candidate]}]),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="medium",
        )
        accepted_sentinel = object()

        class RecordingProcessor:
            def __init__(self):
                self.payloads = []

            def process(self, payload):
                self.payloads.append(payload)
                return CandidateProcessingResult(question=accepted_sentinel)

        processor = RecordingProcessor()
        worker._make_candidate_processor = lambda quotas: processor
        completed = []
        worker.batch_done.connect(completed.append)

        worker.run()

        self.assertEqual([candidate], processor.payloads)
        self.assertEqual([[accepted_sentinel]], completed)

    def test_worker_normalizes_matching_options_and_answers_to_stable_ids(self):
        worker = GenerationWorker(
            SequenceClient([]),
            course_content="content",
            topics=["io"],
            count=1,
            difficulty="medium",
        )
        qdata = {
            "type": "matching",
            "difficulty": "medium",
            "topic": "io",
            "subtopic": "devices",
            "correct_answer": [["CPU", "Processor"], ["GPU", "Graphics"]],
            "bilingual": {
                "zh": {
                    "stem": "配对设备",
                    "options": {
                        "left": ["CPU", "GPU"],
                        "right": ["Processor", "Graphics"],
                    },
                    "explanation": "这是足够长的中文解释，用于说明每一组配对关系。",
                },
                "en": {
                    "stem": "Match devices",
                    "options": {
                        "left": ["Central Processing Unit", "Graphics Processor"],
                        "right": ["Main processor", "Graphics unit"],
                    },
                    "explanation": "This is a sufficiently detailed explanation of every matching pair.",
                },
            },
        }

        normalized = worker._normalize_raw_question(qdata)

        self.assertEqual([["left_1", "right_1"], ["left_2", "right_2"]], normalized["correct_answer"])
        self.assertEqual({"id": "left_1", "text": "CPU"}, normalized["bilingual"]["zh"]["options"]["left"][0])
        self.assertEqual(
            {"id": "right_1", "text": "Main processor"},
            normalized["bilingual"]["en"]["options"]["right"][0],
        )

    def test_worker_normalizes_ordering_options_and_answers_to_stable_ids(self):
        worker = GenerationWorker(
            SequenceClient([]),
            course_content="content",
            topics=["pipeline"],
            count=1,
            difficulty="medium",
        )
        qdata = {
            "type": "ordering",
            "difficulty": "medium",
            "topic": "pipeline",
            "subtopic": "stages",
            "correct_answer": ["取指", "译码", "执行"],
            "bilingual": {
                "zh": {
                    "stem": "排序",
                    "options": ["取指", "译码", "执行"],
                    "explanation": "这是足够长的中文解释，用于说明流水线阶段顺序。",
                },
                "en": {
                    "stem": "Order",
                    "options": ["Fetch", "Decode", "Execute"],
                    "explanation": "This is a sufficiently detailed explanation of the pipeline order.",
                },
            },
        }

        normalized = worker._normalize_raw_question(qdata)

        self.assertEqual(["item_1", "item_2", "item_3"], normalized["correct_answer"])
        self.assertEqual({"id": "item_1", "text": "取指"}, normalized["bilingual"]["zh"]["options"][0])
        self.assertEqual({"id": "item_3", "text": "Execute"}, normalized["bilingual"]["en"]["options"][2])

    def test_worker_retries_until_exact_type_difficulty_and_topic_quotas_are_met(self):
        wrong_batch = {
            "questions": [raw_question("multiple_choice", "medium", "cache", index) for index in range(4)]
        }
        correct_batch = {
            "questions": [
                raw_question("multiple_choice", "easy", "cache", 10),
                raw_question("true_false", "hard", "process", 11),
                raw_question("multiple_choice", "easy", "cache", 12),
                raw_question("true_false", "hard", "process", 13),
            ]
        }
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 50,
                "scenario_choice": 0,
                "true_false": 50,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 50, "medium": 0, "hard": 50},
            topic_weights={"cache": 50, "process": 50},
        )
        worker = GenerationWorker(
            SequenceClient([wrong_batch, correct_batch]),
            course_content="content",
            topics=["cache", "process"],
            count=4,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual(4, len(batches[0]))
        self.assertEqual(
            {"multiple_choice": 2, "true_false": 2},
            _counts(question.type.value for question in batches[0]),
        )
        self.assertEqual(
            {"easy": 2, "hard": 2},
            _counts(question.difficulty.value for question in batches[0]),
        )
        self.assertEqual(
            {"cache": 2, "process": 2},
            _counts(str(question.topic) for question in batches[0]),
        )

    def test_worker_rejects_candidates_that_only_match_marginal_buckets_not_plan_items(self):
        marginal_only_batch = {
            "questions": [
                raw_question("true_false", "easy", "cache", 1),
                raw_question("multiple_choice", "hard", "process", 2),
            ]
        }
        plan_matched_batch = {
            "questions": [
                raw_question("multiple_choice", "easy", "cache", 3),
                raw_question("true_false", "hard", "process", 4),
            ]
        }
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 50,
                "scenario_choice": 0,
                "true_false": 50,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 50, "medium": 0, "hard": 50},
            topic_weights={"cache": 50, "process": 50},
        )
        worker = GenerationWorker(
            SequenceClient([marginal_only_batch, plan_matched_batch]),
            course_content="content",
            topics=["cache", "process"],
            count=2,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        progress_messages = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)
        worker.progress.connect(progress_messages.append)

        worker.run()

        self.assertEqual([], errors)
        refill_messages = [
            message for message in progress_messages if "Filling plan slots" in message
        ]
        self.assertTrue(refill_messages)
        self.assertIn("planned slot", refill_messages[-1])
        self.assertIn("cache", refill_messages[-1])
        self.assertIn("process", refill_messages[-1])
        self.assertNotIn("cache/multiple_choice/easy", refill_messages[-1])
        self.assertNotIn("process/true_false/hard", refill_messages[-1])
        self.assertEqual(
            {
                ("cache", "multiple_choice", "easy"),
                ("process", "true_false", "hard"),
            },
            {
                (str(question.topic), question.type.value, question.difficulty.value)
                for question in batches[0]
            },
        )

    def test_worker_records_explicit_plan_id_match_on_generated_question(self):
        qdata = raw_question("multiple_choice", "medium", "cache", 1)
        qdata["plan_id"] = "plan-001"
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        worker = GenerationWorker(
            SequenceClient([{"questions": [qdata]}]),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        question = batches[0][0]
        self.assertEqual("plan-001", question.metadata["plan_id"])
        self.assertEqual("matched_by_plan_id", question.metadata["plan_match_status"])
        self.assertEqual("definition", question.metadata["target_skill"])

    def test_worker_records_shape_match_when_model_omits_plan_id(self):
        qdata = raw_question("multiple_choice", "medium", "cache", 1)
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        worker = GenerationWorker(
            SequenceClient([{"questions": [qdata]}]),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        question = batches[0][0]
        self.assertEqual("plan-001", question.metadata["plan_id"])
        self.assertEqual("matched_by_shape", question.metadata["plan_match_status"])

    def test_pending_plan_summary_is_limited_for_readable_progress(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        worker = GenerationWorker(
            SequenceClient([{"questions": []}]),
            course_content="content",
            topics=["cache"],
            count=12,
            difficulty="mixed",
            generation_config=config,
        )
        quotas = worker._make_quota_tracker()

        summary = quotas.pending_plan_summary(3)

        self.assertIn("3 planned slot", summary)
        self.assertIn("cache", summary)
        self.assertNotIn("cache/multiple_choice/medium", summary)

    def test_worker_emits_partial_result_when_quota_shortfall_has_accepted_questions(self):
        repeated = {
            "questions": [raw_question("multiple_choice", "easy", "cache", index) for index in range(4)]
        }
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 50,
                "scenario_choice": 0,
                "true_false": 50,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 50, "medium": 0, "hard": 50},
            topic_weights={"cache": 50, "process": 50},
            template="final_exam",
        )
        worker = GenerationWorker(
            SequenceClient([repeated]),
            course_content="content",
            topics=["cache", "process"],
            count=4,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        partials = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.partial_done.connect(lambda questions, report: partials.append((questions, report)))
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], batches)
        self.assertEqual([], errors)
        self.assertEqual(1, len(partials))
        questions, report = partials[0]
        self.assertEqual(2, len(questions))
        self.assertIsInstance(report, GenerationReport)
        self.assertEqual("partial", report.status)
        self.assertEqual("final_exam", report.template)
        self.assertEqual(4, report.requested_count)
        self.assertEqual(2, report.accepted_count)
        self.assertGreaterEqual(report.rejected_count, 1)
        self.assertGreaterEqual(
            report.rejection_reasons.get("quota already filled", 0),
            1,
        )
        self.assertEqual(2, report.shortfall)
        self.assertEqual(2, report.missing_quotas["question_types"]["true_false"])
        self.assertEqual(2, report.missing_quotas["difficulties"]["hard"])
        self.assertEqual(2, report.missing_quotas["topics"]["process"])
        self.assertEqual(2, len(report.failed_plan_items))
        self.assertEqual({"process"}, {item.topic_id for item in report.failed_plan_items})
        self.assertEqual({"true_false"}, {item.question_type for item in report.failed_plan_items})
        self.assertEqual({"hard"}, {item.difficulty for item in report.failed_plan_items})
        self.assertIsInstance(report.error, AppError)
        self.assertEqual("GEN-QUOTA-001", report.error.code)
        self.assertIn("Rejected reasons", report.summary_text("en"))
        self.assertIn("quota already filled", report.summary_text("en"))
        self.assertIn("true_false", report.summary_text("en"))
        self.assertIn("已生成 2/4", report.summary_text("zh"))

    def test_worker_emits_partial_result_when_cancelled_after_accepting_questions(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        worker = GenerationWorker(
            SequenceClient([
                {"questions": [raw_question("multiple_choice", "medium", "cache", 1)]},
                {"questions": [raw_question("multiple_choice", "medium", "cache", 2)]},
            ]),
            course_content="content",
            topics=["cache"],
            count=2,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        partials = []
        worker.batch_done.connect(batches.append)
        worker.partial_done.connect(lambda questions, report: partials.append((questions, report)))
        worker.question_ready.connect(lambda _questions: worker.cancel())

        worker.run()

        self.assertEqual([], batches)
        self.assertEqual(1, len(partials))
        questions, report = partials[0]
        self.assertEqual(["subtopic-1"], [question.subtopic for question in questions])
        self.assertIsInstance(report, GenerationReport)
        self.assertEqual("cancelled", report.status)
        self.assertEqual("GEN-CANCEL-001", report.error.code)

    def test_worker_skips_malformed_candidate_without_aborting_batch(self):
        malformed = raw_question("multiple_choice", "medium", "cache", 1)
        malformed["bilingual"] = "not an object"
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        worker = GenerationWorker(
            SequenceClient([{"questions": [malformed, raw_question("multiple_choice", "medium", "cache", 2)]}]),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        progress_messages = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)
        worker.progress.connect(progress_messages.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual(1, len(batches))
        self.assertEqual(1, len(batches[0]))
        self.assertEqual("subtopic-2", batches[0][0].subtopic)
        self.assertTrue(any("rejected 1" in message for message in progress_messages))

    def test_worker_rejects_top_level_non_object_json_response(self):
        worker = GenerationWorker(
            SequenceClient([["not", "an", "object"]]),
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="mixed",
        )
        errors = []
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual(["AI response JSON must be an object with a questions list."], errors)

    def test_worker_progress_reports_total_requested_count_not_batch_size(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        worker = GenerationWorker(
            SequenceClient([
                {"questions": [raw_question("multiple_choice", "medium", "cache", index) for index in range(10)]},
                {"questions": [raw_question("multiple_choice", "medium", "cache", index + 10) for index in range(5)]},
            ]),
            course_content="content",
            topics=["cache"],
            count=15,
            difficulty="mixed",
            generation_config=config,
        )
        progress_messages = []
        worker.progress.connect(progress_messages.append)

        worker.run()

        generation_messages = [
            message for message in progress_messages if message.startswith("Generating")
        ]
        self.assertTrue(generation_messages)
        self.assertIn("15 questions", generation_messages[0])
        self.assertNotIn("10 questions", generation_messages[0])
        self.assertIn("question 1/15", generation_messages[0].lower())

    def test_worker_retry_uses_failed_plan_items_without_rebuilding_slots(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 0,
                "scenario_choice": 0,
                "true_false": 100,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 0, "hard": 100},
            topic_weights={"process": 100},
            template="final_exam",
        )
        failed_slot = QuestionPlanItem(
            plan_id="plan-003",
            topic_id="process",
            topic_title="Process Scheduling",
            question_type="true_false",
            difficulty="hard",
            target_skill="scenario",
            evidence_chunk_ids=["source-process-01"],
        )
        client = SequenceClient([
            {
                "questions": [
                    {
                        **raw_question("true_false", "hard", "process", 3),
                        "plan_id": "plan-003",
                    }
                ]
            }
        ])
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["process"],
            count=1,
            difficulty="mixed",
            generation_config=config,
            question_plan_items=[failed_slot],
        )
        batches = []
        worker.batch_done.connect(batches.append)

        worker.run()

        prompt = client.calls[0][-1]["content"]
        self.assertIn("plan-003", prompt)
        self.assertNotIn("- plan-001:", prompt)
        self.assertIn("- true_false: 100%", prompt)
        self.assertIn("evidence=source-process-01", prompt)
        self.assertEqual("plan-003", batches[0][0].metadata["plan_id"])
        self.assertEqual("scenario", batches[0][0].metadata["target_skill"])
        self.assertEqual(["source-process-01"], batches[0][0].metadata["plan_evidence_chunk_ids"])

    def test_worker_uses_recovery_pool_for_small_generation_requests(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        client = TopicDriftClient()
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["cache"],
            count=3,
            difficulty="mixed",
            generation_config=config,
        )

        self.assertEqual(4, worker._candidate_batch_count(3))

    def test_worker_candidate_batch_count_is_monotonic_for_small_targets(self):
        worker = GenerationWorker(
            SequenceClient([{"questions": []}]),
            course_content="content",
            topics=["cache"],
            count=4,
            difficulty="mixed",
        )

        counts = [worker._candidate_batch_count(target) for target in range(1, 5)]

        self.assertEqual(sorted(counts), counts)
        self.assertGreaterEqual(worker._candidate_batch_count(2), worker._candidate_batch_count(1))

    def test_worker_oversamples_candidates_when_quota_filtering_rejects_model_drift(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        client = TopicDriftClient()
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["cache"],
            count=15,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual(1, len(batches))
        self.assertEqual(15, len(batches[0]))
        self.assertTrue(any(count > 1 for count in client.requested_counts))
        self.assertTrue(all(count <= 4 for count in client.requested_counts))

    def test_worker_accepts_fill_in_blank_string_answer_from_model(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 0,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 100,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        client = SequenceClient([
            {
                "questions": [
                    {
                        **raw_question("fill_in_blank", "medium", "cache", 1),
                        "correct_answer": "cache line",
                        "bilingual": {
                            "zh": {
                                "stem": "缓存中一次搬运的数据块称为____。",
                                "explanation": "这是足够长的中文解释，用于说明填空答案为什么正确。",
                            },
                            "en": {
                                "stem": "The block of data moved into cache is a ____.",
                                "explanation": "This is a sufficiently detailed explanation of the blank answer.",
                            },
                        },
                    }
                ]
            }
        ])
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["cache"],
            count=1,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual(["cache line"], batches[0][0].correct_answer)

    def test_worker_accepts_explicit_short_answer_with_reference_answer(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 0,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
                "matching": 0,
                "ordering": 0,
                "short_answer": 100,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"io": 100},
        )
        question = raw_question("short_answer", "medium", "io", 1)
        question["correct_answer"] = "DMA allows a device to transfer data without per-word CPU intervention."
        question["bilingual"]["zh"]["options"] = []
        question["bilingual"]["en"]["options"] = []
        client = SequenceClient([{"questions": [question]}])
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["io"],
            count=1,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual("short_answer", batches[0][0].type.value)
        self.assertIn("DMA", batches[0][0].correct_answer)

    def test_worker_maps_snake_case_model_topic_to_selected_topic_label(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"Input Output Improvements": 100},
        )
        client = SequenceClient([
            {
                "questions": [
                    raw_question(
                        "multiple_choice",
                        "medium",
                        "input_output_improvements",
                        1,
                    )
                ]
            }
        ])
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["Input Output Improvements"],
            count=1,
            difficulty="medium",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual("Input Output Improvements", batches[0][0].topic)

    def test_worker_maps_model_title_to_selected_course_topic_id(self):
        topic = CourseTopic(topic_id="io_interrupts", title="Interrupt-driven I/O")
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"io_interrupts": 100},
        )
        client = SequenceClient([
            {
                "questions": [
                    raw_question(
                        "multiple_choice",
                        "medium",
                        "Interrupt-driven I/O",
                        1,
                    )
                ]
            }
        ])
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=[topic],
            count=1,
            difficulty="medium",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual("io_interrupts", topic_value(batches[0][0].topic))

    def test_worker_reduces_candidate_batch_after_truncated_json_response(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        client = TruncationThenSuccessClient()
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["cache"],
            count=8,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual(1, len(batches))
        self.assertEqual(8, len(batches[0]))
        self.assertGreater(client.requested_counts[0], client.requested_counts[1])
        self.assertTrue(all(count <= 5 for count in client.requested_counts[1:]))

    def test_worker_restores_candidate_batch_limit_after_successful_truncation_recovery(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        client = OneTruncationThenSuccessClient()
        worker = GenerationWorker(
            client,
            course_content="content",
            topics=["cache"],
            count=10,
            difficulty="mixed",
            generation_config=config,
        )
        batches = []
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual(1, len(batches))
        self.assertEqual(10, len(batches[0]))
        self.assertGreater(client.requested_counts[0], client.requested_counts[1])
        self.assertGreater(client.requested_counts[2], client.requested_counts[1])

    def test_worker_reports_json_truncation_when_reduced_batches_still_fail(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
        )
        worker = GenerationWorker(
            AlwaysTruncatedClient(),
            course_content="content",
            topics=["cache"],
            count=3,
            difficulty="mixed",
            generation_config=config,
        )
        errors = []
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], AppError)
        self.assertEqual("GEN-AI-JSON-001", errors[0].code)
        self.assertIn("输出过长", errors[0].message_zh)
        self.assertIn("减少题目数量", errors[0].action_zh)


def _counts(values):
    result = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


if __name__ == "__main__":
    unittest.main()
