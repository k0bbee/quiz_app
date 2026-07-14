import unittest

from ai.generation_batch_scheduler import GenerationBatchScheduler
from ai.generation_candidate_processor import CandidateProcessingResult
from ai.generation_events import (
    CompletedEvent,
    FailedEvent,
    PartialResultEvent,
    ProgressEvent,
    QuestionsReadyEvent,
)
from ai.generation_request_service import GenerationRequestResult
from ai.generation_result_accumulator import GenerationResultAccumulator
from ai.generation_runner import GenerationRunner
from core.app_errors import AppError


TRUNCATION_DETAIL = (
    "JSON parse error (attempt 3/3): "
    "Unterminated string starting at: line 410 column 13"
)


class FakeQuotas:
    template = "quick_review"

    def remaining_config(self):
        return object()

    def pending_plan_items(self, _limit):
        return []

    def pending_plan_summary(self, _limit):
        return ""

    def missing_quotas(self):
        return {"topics": {}}

    def missing_plan_items(self):
        return []

    def shortfall_error(self, accepted, requested):
        return AppError(
            code="GEN-QUOTA-001",
            severity="error",
            title_zh="生成未完成",
            title_en="Generation incomplete",
            message_zh=f"{accepted}/{requested}",
            message_en=f"{accepted}/{requested}",
        )


class SequenceRequestService:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def request(self, candidate_count, config, plan_items, runtime_instruction):
        self.calls.append((candidate_count, config, plan_items, runtime_instruction))
        return self.results.pop(0)


class AcceptingProcessor:
    def process(self, payload):
        return CandidateProcessingResult(question=f"question-{payload}")


def make_runner(
    requested_count,
    request_service,
    *,
    is_cancelled=lambda: False,
    runtime_instruction=lambda: "",
):
    scheduler = GenerationBatchScheduler(requested_count)
    return GenerationRunner(
        requested_count=requested_count,
        scheduler=scheduler,
        result_state=GenerationResultAccumulator(
            requested_count,
            max_attempts=scheduler.max_attempts,
            template="quick_review",
        ),
        quotas=FakeQuotas(),
        candidate_processor=AcceptingProcessor(),
        request_service=request_service,
        is_cancelled=is_cancelled,
        runtime_instruction=runtime_instruction,
    )


class GenerationRunnerTests(unittest.TestCase):
    def test_accepts_only_the_planned_live_target_from_each_candidate_pool(self):
        requests = SequenceRequestService(
            [
                GenerationRequestResult(questions=["one", "extra-one"]),
                GenerationRequestResult(questions=["two", "extra-two"]),
            ]
        )
        runner = make_runner(2, requests)

        events = list(runner.events())

        self.assertEqual(
            [("question-one",), ("question-two",)],
            [event.questions for event in events if isinstance(event, QuestionsReadyEvent)],
        )
        self.assertEqual(2, len(requests.calls))

    def test_emits_live_batches_and_reads_runtime_instruction_before_each_request(self):
        requests = SequenceRequestService(
            [
                GenerationRequestResult(questions=["one"]),
                GenerationRequestResult(questions=["two"]),
            ]
        )
        instruction = {"value": ""}
        runner = make_runner(
            2,
            requests,
            runtime_instruction=lambda: instruction["value"],
        )

        events = []
        ready_count = 0
        for event in runner.events():
            events.append(event)
            if isinstance(event, QuestionsReadyEvent):
                ready_count += 1
                if ready_count == 1:
                    instruction["value"] = "Avoid repeated keywords"

        self.assertEqual(["", "Avoid repeated keywords"], [call[3] for call in requests.calls])
        self.assertEqual(
            [("question-one",), ("question-two",)],
            [event.questions for event in events if isinstance(event, QuestionsReadyEvent)],
        )
        self.assertEqual(
            ("question-one", "question-two"),
            next(event.questions for event in events if isinstance(event, CompletedEvent)),
        )

    def test_preserves_accepted_questions_when_cancelled_after_live_batch(self):
        requests = SequenceRequestService(
            [GenerationRequestResult(questions=["one"])]
        )
        cancelled = {"value": False}
        runner = make_runner(
            2,
            requests,
            is_cancelled=lambda: cancelled["value"],
        )

        events = []
        for event in runner.events():
            events.append(event)
            if isinstance(event, QuestionsReadyEvent):
                cancelled["value"] = True

        partial = next(event for event in events if isinstance(event, PartialResultEvent))
        self.assertEqual(("question-one",), partial.questions)
        self.assertEqual("cancelled", partial.report.status)
        self.assertEqual("GEN-CANCEL-001", partial.report.error.code)

    def test_retries_truncated_json_with_smaller_candidate_batch(self):
        requests = SequenceRequestService(
            [
                GenerationRequestResult(error=TRUNCATION_DETAIL),
                GenerationRequestResult(questions=["one"]),
            ]
        )
        runner = make_runner(1, requests)

        events = list(runner.events())

        self.assertEqual([4, 2], [call[0] for call in requests.calls])
        self.assertTrue(
            any(
                isinstance(event, ProgressEvent)
                and "smaller batch" in event.message
                for event in events
            )
        )
        self.assertIsInstance(events[-1], CompletedEvent)

    def test_emits_failed_event_for_nonrecoverable_provider_error(self):
        runner = make_runner(
            1,
            SequenceRequestService(
                [GenerationRequestResult(error="provider timed out")]
            ),
        )

        events = list(runner.events())

        failure = next(event for event in events if isinstance(event, FailedEvent))
        self.assertEqual("provider timed out", failure.error)
        self.assertFalse(any(isinstance(event, CompletedEvent) for event in events))


if __name__ == "__main__":
    unittest.main()
