import unittest

from ai.batch_generator import GenerationWorker, allocate_weighted_counts
from ai.generation_config import GenerationConfig


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

    def test_worker_retries_until_exact_type_difficulty_and_topic_quotas_are_met(self):
        wrong_batch = {
            "questions": [raw_question("multiple_choice", "medium", "cache", index) for index in range(4)]
        }
        correct_batch = {
            "questions": [
                raw_question("multiple_choice", "easy", "cache", 10),
                raw_question("multiple_choice", "hard", "process", 11),
                raw_question("true_false", "easy", "process", 12),
                raw_question("true_false", "hard", "cache", 13),
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

    def test_worker_reports_quota_shortfall_and_does_not_emit_partial_batch(self):
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
        errors = []
        worker.batch_done.connect(batches.append)
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual([], batches)
        self.assertEqual(1, len(errors))
        self.assertIn("requested distribution", errors[0])
        self.assertIn("true_false", errors[0])
        self.assertIn("hard", errors[0])
        self.assertIn("process", errors[0])

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


def _counts(values):
    result = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


if __name__ == "__main__":
    unittest.main()
