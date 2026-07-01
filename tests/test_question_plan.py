import unittest
from collections import Counter

from ai.generation_config import GenerationConfig, planned_generation_counts
from ai.generation_report import GenerationReport
from ai.question_plan import QuestionPlanItem, build_question_plan, summarize_plan_items


class QuestionPlanTests(unittest.TestCase):
    def test_build_question_plan_creates_stable_items_with_exact_marginals(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 50,
                "scenario_choice": 30,
                "true_false": 20,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 20, "medium": 50, "hard": 30},
            topic_weights={"cache": 70, "process": 30},
            template="final_exam",
        )

        items = build_question_plan(config, ["cache", "process"], 10)

        self.assertEqual(10, len(items))
        self.assertEqual("plan-001", items[0].plan_id)
        self.assertEqual("pending", items[0].status)
        self.assertEqual([], items[0].evidence_chunk_ids)
        self.assertEqual(Counter({"cache": 7, "process": 3}), Counter(item.topic_id for item in items))
        self.assertEqual(
            Counter({"multiple_choice": 5, "scenario_choice": 3, "true_false": 2}),
            Counter(item.question_type for item in items),
        )
        self.assertEqual(
            Counter({"easy": 2, "medium": 5, "hard": 3}),
            Counter(item.difficulty for item in items),
        )
        self.assertEqual(
            Counter({"application": 3, "scenario": 3, "comparison": 2, "calculation": 1, "definition": 1}),
            Counter(item.target_skill for item in items),
        )
        self.assertIn("process", [item.topic_id for item in items[:4]])

    def test_summarize_plan_items_groups_by_topic_type_difficulty_and_skill(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 100,
                "scenario_choice": 0,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 100, "hard": 0},
            topic_weights={"cache": 100},
            template="quick_review",
        )
        items = build_question_plan(config, ["cache"], 3)

        summary = summarize_plan_items(items)

        self.assertEqual(
            {"cache": {("multiple_choice", "medium", "definition"): 2, ("multiple_choice", "medium", "comparison"): 1}},
            summary,
        )

    def test_generation_report_summarizes_failed_plan_item_combinations(self):
        config = GenerationConfig(
            question_type_weights={
                "multiple_choice": 0,
                "scenario_choice": 100,
                "true_false": 0,
                "fill_in_blank": 0,
            },
            difficulty_weights={"easy": 0, "medium": 0, "hard": 100},
            topic_weights={"cache": 100},
            template="final_exam",
        )
        failed = build_question_plan(config, ["cache"], 2)

        report = GenerationReport(
            requested_count=2,
            accepted_count=0,
            status="partial",
            failed_plan_items=failed,
        )

        text = report.summary_text("zh")

        self.assertIn("失败组合", text)
        self.assertIn("cache", text)
        self.assertIn("hard / scenario_choice / application", text)
        self.assertIn("hard / scenario_choice / scenario", text)

    def test_generation_report_builds_retry_plan_from_failed_plan_items_only(self):
        failed = [
            QuestionPlanItem(
                plan_id="plan-003",
                topic_id="process",
                topic_title="Process",
                question_type="true_false",
                difficulty="hard",
                target_skill="application",
            ),
            QuestionPlanItem(
                plan_id="plan-004",
                topic_id="cache",
                topic_title="Cache",
                question_type="fill_in_blank",
                difficulty="easy",
                target_skill="definition",
            ),
        ]
        report = GenerationReport(
            requested_count=4,
            accepted_count=2,
            status="partial",
            failed_plan_items=failed,
            template="final_exam",
        )

        retry = report.retry_plan()

        self.assertEqual(2, retry.count)
        self.assertEqual(["process", "cache"], retry.topics)
        self.assertEqual("final_exam", retry.config.template)
        self.assertEqual(
            Counter(item.topic_id for item in failed),
            Counter(planned_generation_counts(retry.config, retry.topics, retry.count)["topics"]),
        )
        self.assertEqual(
            Counter(item.question_type for item in failed),
            Counter(planned_generation_counts(retry.config, retry.topics, retry.count)["question_types"]),
        )
        self.assertEqual(
            Counter(item.difficulty for item in failed),
            Counter(planned_generation_counts(retry.config, retry.topics, retry.count)["difficulties"]),
        )
        self.assertEqual(0, retry.config.question_type_weights["multiple_choice"])
        self.assertEqual(0, retry.config.difficulty_weights["medium"])


if __name__ == "__main__":
    unittest.main()
