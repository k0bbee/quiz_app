import unittest

from ai.generation_config import GenerationConfig
from ai.generation_request_service import GenerationRequestService


class RecordingClient:
    model = "test-model"

    def __init__(self, response, last_error=""):
        self.response = response
        self.last_error = last_error
        self.calls = []

    def generate_with_json(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.response


class GenerationRequestServiceTests(unittest.TestCase):
    def test_builds_prompt_with_latest_runtime_instruction_and_returns_questions(self):
        question = {"type": "true_false", "topic": "io"}
        client = RecordingClient({"questions": [question]})
        service = GenerationRequestService(
            client,
            course_context="Interrupts let devices notify the processor.",
            topics=["io"],
            difficulty="medium",
            topic_keywords={"io": ["interrupt"]},
        )

        result = service.request(
            candidate_count=1,
            generation_config=GenerationConfig(topic_weights={"io": 100}),
            question_plan_items=[],
            runtime_instruction="Avoid polling questions",
        )

        self.assertTrue(result.succeeded)
        self.assertEqual([question], result.questions)
        messages, kwargs = client.calls[0]
        self.assertEqual({"max_retries": 3}, kwargs)
        self.assertIn("Avoid polling questions", messages[-1]["content"])
        self.assertIn("Interrupts let devices notify", messages[-1]["content"])

    def test_returns_client_detail_when_generation_fails(self):
        client = RecordingClient(None, last_error="provider timed out")
        service = GenerationRequestService(
            client,
            course_context="content",
            topics=["io"],
            difficulty="medium",
        )

        result = service.request(
            candidate_count=1,
            generation_config=GenerationConfig(),
        )

        self.assertFalse(result.succeeded)
        self.assertEqual("provider timed out", result.error)
        self.assertEqual([], result.questions)

    def test_rejects_non_object_json_response(self):
        service = GenerationRequestService(
            RecordingClient([{"questions": []}]),
            course_context="content",
            topics=["io"],
            difficulty="medium",
        )

        result = service.request(1, GenerationConfig())

        self.assertFalse(result.succeeded)
        self.assertEqual(
            "AI response JSON must be an object with a questions list.",
            result.error,
        )

    def test_rejects_object_without_questions(self):
        service = GenerationRequestService(
            RecordingClient({"questions": []}),
            course_context="content",
            topics=["io"],
            difficulty="medium",
        )

        result = service.request(1, GenerationConfig())

        self.assertFalse(result.succeeded)
        self.assertEqual("No questions found in the API response.", result.error)


if __name__ == "__main__":
    unittest.main()
