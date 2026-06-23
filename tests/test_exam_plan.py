import unittest
from dataclasses import FrozenInstanceError

from ai.exam_plan import (
    ExamGenerationPlan,
    ExamPlanPatch,
    ExamPlanValidationError,
    apply_exam_plan_patch,
    describe_plan_changes,
)


class ExamPlanTests(unittest.TestCase):
    def test_plan_is_immutable_and_normalizes_weight_groups(self):
        plan = ExamGenerationPlan(
            selected_topics=("cache", "process"),
            question_type_weights={"multiple_choice": 2, "scenario_choice": 1},
            difficulty_weights={"easy": 1, "medium": 2, "hard": 1},
            topic_weights={"cache": 3, "process": 1},
        )

        self.assertEqual(100, sum(plan.question_type_weights.values()))
        self.assertEqual(100, sum(plan.difficulty_weights.values()))
        self.assertEqual(100, sum(plan.topic_weights.values()))
        self.assertEqual(75, plan.topic_weights["cache"])
        with self.assertRaises(FrozenInstanceError):
            plan.question_count = 20
        with self.assertRaises(TypeError):
            plan.topic_weights["cache"] = 10

    def test_patch_rejects_unknown_fields_and_boolean_integer(self):
        with self.assertRaisesRegex(ExamPlanValidationError, "unknown field"):
            ExamPlanPatch.from_mapping({"temperature": 0.9})
        with self.assertRaisesRegex(ExamPlanValidationError, "question_count"):
            ExamPlanPatch.from_mapping({"question_count": True})

    def test_patch_rejects_out_of_range_values_and_unknown_weight_keys(self):
        for value in (2, 61):
            with self.subTest(value=value):
                with self.assertRaises(ExamPlanValidationError):
                    ExamPlanPatch.from_mapping({"question_count": value})

        with self.assertRaisesRegex(ExamPlanValidationError, "question type"):
            ExamPlanPatch.from_mapping({"question_type_weights": {"essay": 20}})
        with self.assertRaisesRegex(ExamPlanValidationError, "difficulty"):
            ExamPlanPatch.from_mapping({"difficulty": "extreme"})

    def test_apply_patch_enforces_topic_allowlist_and_normalizes_weights(self):
        current = ExamGenerationPlan(
            question_count=15,
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )
        patch = ExamPlanPatch.from_mapping(
            {
                "question_count": 24,
                "difficulty": "hard",
                "template": "final_exam",
                "selected_topics": ["cache", "process"],
                "question_type_weights": {
                    "multiple_choice": 1,
                    "scenario_choice": 1,
                    "true_false": 0,
                    "fill_in_blank": 0,
                },
                "topic_weights": {"cache": 3, "process": 1},
            }
        )

        updated = apply_exam_plan_patch(current, patch, ["cache", "process", "memory"])

        self.assertEqual(24, updated.question_count)
        self.assertEqual("hard", updated.difficulty)
        self.assertEqual("final_exam", updated.template)
        self.assertEqual(("cache", "process"), updated.selected_topics)
        self.assertEqual(50, updated.question_type_weights["multiple_choice"])
        self.assertEqual(75, updated.topic_weights["cache"])

        unknown = ExamPlanPatch.from_mapping({"selected_topics": ["network"]})
        with self.assertRaisesRegex(ExamPlanValidationError, "unknown topic"):
            apply_exam_plan_patch(current, unknown, ["cache", "process"])

    def test_topic_selection_without_weights_uses_equal_distribution(self):
        current = ExamGenerationPlan(
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )
        patch = ExamPlanPatch.from_mapping(
            {"selected_topics": ["cache", "process", "memory"]}
        )

        updated = apply_exam_plan_patch(
            current,
            patch,
            ["cache", "process", "memory"],
        )

        self.assertEqual(100, sum(updated.topic_weights.values()))
        self.assertEqual({"cache", "process", "memory"}, set(updated.topic_weights))
        self.assertLessEqual(max(updated.topic_weights.values()) - min(updated.topic_weights.values()), 1)

    def test_change_description_contains_only_changed_fields(self):
        before = ExamGenerationPlan(question_count=15, difficulty="medium")
        after = apply_exam_plan_patch(
            before,
            ExamPlanPatch.from_mapping({"question_count": 20, "difficulty": "hard"}),
            [],
        )

        changes = describe_plan_changes(before, after)

        self.assertEqual(["question_count", "difficulty"], [change.field for change in changes])
        self.assertEqual(15, changes[0].before)
        self.assertEqual(20, changes[0].after)


if __name__ == "__main__":
    unittest.main()
