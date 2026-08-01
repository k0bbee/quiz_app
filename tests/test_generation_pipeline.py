import unittest

from ai.generation_candidate_processor import GenerationCandidateProcessor
from ai.generation_config import (
    GenerationConfig,
    allocate_weighted_counts,
)
from ai.generation_events import (
    CompletedEvent,
    FailedEvent,
    PartialResultEvent,
    ProgressEvent,
    QuestionsReadyEvent,
)
from ai.generation_quota_tracker import GenerationQuotaTracker
from ai.generation_report import GenerationReport
from ai.generation_result_accumulator import GenerationResultAccumulator
from ai.generation_source_resolver import GenerationSourceResolver
from ai.question_generation_service import QuestionGenerationService
from core.app_errors import AppError
from core.generation_session_state import GenerationStage, GenerationSessionState


def raw_question(*, topic="io", difficulty="medium"):
    return {
        "type": "multiple_choice",
        "difficulty": difficulty,
        "topic": topic,
        "subtopic": "interrupts",
        "correct_answer": "A",
        "bilingual": {
            "zh": {
                "stem": "哪一种机制允许设备在工作完成后通知处理器？",
                "options": ["A. 中断", "B. 忙等待", "C. 缓存", "D. 分页"],
                "explanation": "中断允许设备在操作完成后主动通知处理器，处理器无需持续轮询设备状态。",
            },
            "en": {
                "stem": "Which mechanism lets a device notify the processor after completing work?",
                "options": ["A. Interrupt", "B. Busy wait", "C. Cache", "D. Paging"],
                "explanation": "An interrupt lets the device notify the processor after completion without continuous polling.",
            },
        },
    }


def quota_tracker(*, evidence_refs_by_topic=None):
    return GenerationQuotaTracker(
        GenerationConfig(
            question_type_weights={"multiple_choice": 100},
            difficulty_weights={"medium": 100},
            topic_weights={"io": 100},
        ),
        topics=["io"],
        count=1,
        evidence_refs_by_topic=evidence_refs_by_topic,
    )


class GenerationCandidateProcessorTests(unittest.TestCase):
    def test_accepts_candidate_and_attaches_plan_course_and_trusted_source_metadata(self):
        source_ref = {
            "chunk_id": "chunk-io-1",
            "source_file": "io.pdf",
            "page_or_slide": 12,
            "heading": "Interrupt-driven I/O",
            "excerpt": "A device raises an interrupt after completing an operation.",
        }
        tracker = quota_tracker(evidence_refs_by_topic={"io": [source_ref]})
        processor = GenerationCandidateProcessor(
            QuestionGenerationService(["io"]),
            tracker,
            GenerationSourceResolver([source_ref], {"io": [source_ref]}),
            ai_model="test-model",
            course_metadata={"course_id": "course-os", "course_title": "Operating Systems"},
        )

        result = processor.process(raw_question())

        self.assertTrue(result.accepted)
        self.assertEqual("", result.rejection_reason)
        self.assertEqual("io", result.question.topic_id())
        self.assertEqual("test-model", result.question.metadata["ai_model"])
        self.assertEqual("course-os", result.question.metadata["course_id"])
        self.assertEqual("plan-001", result.question.metadata["plan_id"])
        self.assertEqual("matched_by_shape", result.question.metadata["plan_match_status"])
        self.assertEqual("fallback_plan_evidence", result.question.metadata["source_ref_status"])
        self.assertEqual([source_ref], result.question.metadata["source_refs"])
        self.assertEqual([], tracker.missing_plan_items())

    def test_rejects_unselected_topic_without_consuming_quota(self):
        tracker = quota_tracker()
        processor = GenerationCandidateProcessor(
            QuestionGenerationService(["io"]),
            tracker,
            GenerationSourceResolver(),
            ai_model="test-model",
        )
        before = tracker.missing_quotas()

        result = processor.process(raw_question(topic="raid"))

        self.assertFalse(result.accepted)
        self.assertIsNone(result.question)
        self.assertIn("not selected", result.rejection_reason)
        self.assertEqual(before, tracker.missing_quotas())
        self.assertEqual(1, len(tracker.missing_plan_items()))

    def test_returns_stable_malformed_rejection_for_invalid_enum_value(self):
        processor = GenerationCandidateProcessor(
            QuestionGenerationService(["io"]),
            quota_tracker(),
            GenerationSourceResolver(),
            ai_model="test-model",
        )

        result = processor.process(raw_question(difficulty="impossible"))

        self.assertFalse(result.accepted)
        self.assertEqual("malformed question", result.rejection_reason)
        self.assertIn("impossible", result.detail)


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


class GenerationEventTests(unittest.TestCase):
    def test_progress_and_failure_events_preserve_payloads(self):
        progress = ProgressEvent("Generating question 1/3")
        failure = FailedEvent("provider timed out")

        self.assertEqual("Generating question 1/3", progress.message)
        self.assertEqual("provider timed out", failure.error)

    def test_question_events_snapshot_mutable_input_lists(self):
        first = object()
        questions = [first]
        ready = QuestionsReadyEvent.from_questions(questions)
        completed = CompletedEvent.from_questions(questions)
        questions.append(object())

        self.assertEqual((first,), ready.questions)
        self.assertEqual((first,), completed.questions)

    def test_partial_event_keeps_questions_and_structured_report(self):
        question = object()
        report = GenerationReport(
            requested_count=2,
            accepted_count=1,
            rejected_count=0,
            attempts=1,
            max_attempts=3,
            status="partial",
        )

        event = PartialResultEvent.from_questions([question], report)

        self.assertEqual((question,), event.questions)
        self.assertIs(report, event.report)


class RecordingQuotaState:
    def missing_quotas(self):
        return {"topics": {"io": 1}}

    def missing_plan_items(self):
        return ["plan-002"]


class GenerationResultAccumulatorTests(unittest.TestCase):
    def test_tracks_attempts_questions_and_stable_rejection_categories(self):
        state = GenerationResultAccumulator(
            requested_count=3,
            max_attempts=12,
            template="final_exam",
        )
        first = object()
        second = object()

        state.start_attempt()
        state.start_attempt()
        state.accept([first, second])
        state.reject("quota already filled for difficulty medium")
        state.reject("quota already filled for topic io")
        state.reject("missing zh stem")

        self.assertEqual(2, state.attempts)
        self.assertEqual([first, second], state.questions)
        self.assertEqual(2, state.accepted_count)
        self.assertEqual(3, state.rejected_count)
        self.assertEqual(
            {"quota already filled": 2, "incomplete question content": 1},
            state.rejection_reasons,
        )

    def test_builds_partial_report_from_current_state_and_quota_snapshot(self):
        state = GenerationResultAccumulator(
            requested_count=2,
            max_attempts=9,
            template="quick_review",
        )
        state.start_attempt()
        state.accept([object()])
        state.reject("topic raid was not selected")
        app_error = AppError(
            code="GEN-TEST-001",
            severity="error",
            title_zh="测试",
            title_en="Test",
            message_zh="测试",
            message_en="Test",
        )

        report = state.build_report(
            status="partial",
            quotas=RecordingQuotaState(),
            error=app_error,
        )

        self.assertEqual(2, report.requested_count)
        self.assertEqual(1, report.accepted_count)
        self.assertEqual(1, report.rejected_count)
        self.assertEqual(1, report.attempts)
        self.assertEqual(9, report.max_attempts)
        self.assertEqual("partial", report.status)
        self.assertEqual({"topics": {"io": 1}}, report.missing_quotas)
        self.assertEqual(["plan-002"], report.failed_plan_items)
        self.assertEqual({"topic not selected": 1}, report.rejection_reasons)
        self.assertEqual("quick_review", report.template)
        self.assertIs(app_error, report.error)

    def test_empty_rejection_reason_is_counted_as_unknown(self):
        state = GenerationResultAccumulator(1, max_attempts=3)

        state.reject("")

        self.assertEqual({"unknown rejection": 1}, state.rejection_reasons)


class GenerationSessionStateTests(unittest.TestCase):
    def test_stage_transitions_preserve_reviewable_partial_results(self):
        state = GenerationSessionState()

        self.assertEqual(GenerationStage.CONFIGURING, state.stage)
        state.start()
        self.assertEqual(GenerationStage.RUNNING, state.stage)
        state.keep_partial_results()
        self.assertEqual(GenerationStage.PARTIAL, state.stage)
        state.request_review()
        self.assertEqual(GenerationStage.REVIEW_PENDING, state.stage)

    def test_failure_and_cancellation_are_terminal_until_a_new_run_starts(self):
        state = GenerationSessionState()

        state.start()
        state.fail()
        self.assertEqual(GenerationStage.FAILED, state.stage)
        state.cancel()
        self.assertEqual(GenerationStage.FAILED, state.stage)
        state.start()
        self.assertEqual(GenerationStage.RUNNING, state.stage)
        state.cancel()
        self.assertEqual(GenerationStage.CANCELLED, state.stage)

    def test_failure_with_retained_questions_can_explicitly_reopen_review(self):
        state = GenerationSessionState()

        state.start()
        state.fail()
        state.recover_for_review()

        self.assertEqual(GenerationStage.REVIEW_PENDING, state.stage)
