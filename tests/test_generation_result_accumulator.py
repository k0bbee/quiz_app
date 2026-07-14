import unittest

from ai.generation_result_accumulator import GenerationResultAccumulator
from core.app_errors import AppError


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


if __name__ == "__main__":
    unittest.main()
