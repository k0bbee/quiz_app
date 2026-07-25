import unittest

from ai.generation_config import GenerationConfig, allocate_weighted_counts
from ai.generation_quota_tracker import GenerationQuotaTracker


class GenerationCoreQuotaTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
