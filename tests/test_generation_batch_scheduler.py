import unittest

from ai.generation_batch_scheduler import GenerationBatchScheduler


TRUNCATION_DETAIL = (
    "JSON parse error (attempt 3/3): "
    "Unterminated string starting at: line 410 column 13"
)


class GenerationBatchSchedulerTests(unittest.TestCase):
    def test_plans_small_accept_batches_with_bounded_candidate_pool(self):
        scheduler = GenerationBatchScheduler(requested_count=12)

        plan = scheduler.plan_next(remaining=12)

        self.assertEqual(39, scheduler.max_attempts)
        self.assertEqual(1, plan.accept_target)
        self.assertEqual(4, plan.candidate_count)

    def test_reduces_truncated_candidate_batches_until_single_candidate(self):
        scheduler = GenerationBatchScheduler(requested_count=3)

        self.assertTrue(scheduler.recover_from_failure(TRUNCATION_DETAIL, 4))
        self.assertEqual(2, scheduler.plan_next(3).candidate_count)
        self.assertEqual(TRUNCATION_DETAIL, scheduler.last_truncation_detail)

        self.assertTrue(scheduler.recover_from_failure(TRUNCATION_DETAIL, 2))
        self.assertEqual(1, scheduler.plan_next(3).candidate_count)

        self.assertFalse(scheduler.recover_from_failure(TRUNCATION_DETAIL, 1))

    def test_success_restores_normal_candidate_batch_after_recovery(self):
        scheduler = GenerationBatchScheduler(requested_count=2)
        scheduler.recover_from_failure(TRUNCATION_DETAIL, 4)

        scheduler.record_success()

        self.assertEqual(4, scheduler.plan_next(2).candidate_count)
        self.assertEqual("", scheduler.last_truncation_detail)

    def test_does_not_reduce_batch_for_non_truncation_failure(self):
        scheduler = GenerationBatchScheduler(requested_count=2)

        recovered = scheduler.recover_from_failure(
            "Authentication failed: invalid API key",
            4,
        )

        self.assertFalse(recovered)
        self.assertEqual(4, scheduler.plan_next(2).candidate_count)
        self.assertEqual("", scheduler.last_truncation_detail)

    def test_builds_actionable_error_for_unrecoverable_truncation(self):
        scheduler = GenerationBatchScheduler(requested_count=1)

        app_error = scheduler.truncation_error(TRUNCATION_DETAIL)

        self.assertEqual("GEN-AI-JSON-001", app_error.code)
        self.assertIn("截断", app_error.message_zh)
        self.assertIn("truncated", app_error.message_en)
        self.assertEqual(TRUNCATION_DETAIL, app_error.technical_detail)


if __name__ == "__main__":
    unittest.main()
