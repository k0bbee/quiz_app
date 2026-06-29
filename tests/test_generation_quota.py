import unittest
import re

from ai.batch_generator import GenerationWorker, allocate_weighted_counts
from ai.generation_config import GenerationConfig
from core.app_errors import AppError


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
        if requested > 5:
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
        self.assertIsInstance(errors[0], AppError)
        self.assertEqual("GEN-QUOTA-001", errors[0].code)
        self.assertIn("requested distribution", errors[0].technical_detail)
        self.assertIn("true_false", errors[0].technical_detail)
        self.assertIn("hard", errors[0].technical_detail)
        self.assertIn("process", errors[0].technical_detail)
        self.assertIn("放宽", errors[0].action_zh)

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
        self.assertIn("batch", generation_messages[0].lower())

    def test_worker_does_not_oversample_very_small_generation_requests(self):
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

        self.assertEqual(3, worker._candidate_batch_count(3))

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
        self.assertTrue(any(count > 5 for count in client.requested_counts))

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
