import unittest

from ai.generation_config import GenerationConfig, allocate_weighted_counts
from ai.prompt_templates import PromptBuilder
from ai.question_plan import QuestionPlanItem, build_question_plan
from models.course_project import CourseTopic


class GenerationPromptConfigTests(unittest.TestCase):
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
            "## Evidence source-0000 — io.pdf page 1\n"
            "DMA transfers directly between device and memory.",
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
        self.assertIn(
            "Each returned question for a listed slot MUST include that exact plan_id",
            prompt,
        )
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


if __name__ == "__main__":
    unittest.main()
