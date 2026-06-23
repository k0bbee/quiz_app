import unittest

from ai.exam_plan import ExamGenerationPlan
from ai.exam_request_interpreter import (
    ExamRequestError,
    ExamRequestInterpreter,
)


class FakeClient:
    def __init__(self, response, base_url="https://api.example.com/v1"):
        self.response = response
        self.base_url = base_url
        self.calls = []
        self.last_error = ""

    def generate_with_json(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ExamRequestInterpreterTests(unittest.TestCase):
    def setUp(self):
        self.current = ExamGenerationPlan(
            selected_topics=("cache",),
            topic_weights={"cache": 100},
        )

    def test_remote_llm_receives_strict_schema_and_returns_validated_plan(self):
        client = FakeClient(
            {
                "assistant_message": "已调整为期末模拟方案。",
                "question_count": 20,
                "difficulty": "hard",
                "template": "final_exam",
                "selected_topics": ["cache", "process"],
            }
        )
        interpreter = ExamRequestInterpreter(["cache", "process"], client)

        result = interpreter.interpret("出20道困难的期末模拟题", self.current)

        self.assertEqual("llm", result.source)
        self.assertEqual(20, result.plan.question_count)
        self.assertEqual("final_exam", result.plan.template)
        self.assertEqual(("cache", "process"), result.plan.selected_topics)
        self.assertTrue(result.changes)
        messages, kwargs = client.calls[0]
        prompt = "\n".join(message["content"] for message in messages)
        self.assertIn("ALLOWED_FIELDS", prompt)
        self.assertIn('"cache"', prompt)
        self.assertIn('"question_count": 15', prompt)
        self.assertEqual(0.1, kwargs["temperature"])

    def test_invalid_remote_patch_is_rejected_without_fallback(self):
        client = FakeClient({"question_count": 20, "temperature": 0.9})
        interpreter = ExamRequestInterpreter(["cache"], client)

        with self.assertRaisesRegex(ExamRequestError, "unknown field"):
            interpreter.interpret("出20道题", self.current)

        self.assertEqual(15, self.current.question_count)

    def test_remote_failure_reports_error_without_mutating_current_plan(self):
        client = FakeClient(None)
        client.last_error = "timeout"
        interpreter = ExamRequestInterpreter(["cache"], client)

        with self.assertRaisesRegex(ExamRequestError, "timeout"):
            interpreter.interpret("出20道题", self.current)

        self.assertEqual(15, self.current.question_count)

    def test_local_agent_is_not_called_and_uses_deterministic_chinese_parser(self):
        client = FakeClient(
            AssertionError("local CLI must not receive free-form requests"),
            base_url="local-agent://auto",
        )
        interpreter = ExamRequestInterpreter(["cache", "process", "memory"], client)

        result = interpreter.interpret(
            "请出24道期末模拟题，整体困难，cache和process为主，困难题占40%，判断题占10%",
            self.current,
        )

        self.assertEqual([], client.calls)
        self.assertEqual("local_rules", result.source)
        self.assertEqual(24, result.plan.question_count)
        self.assertEqual("hard", result.plan.difficulty)
        self.assertEqual("final_exam", result.plan.template)
        self.assertEqual(("cache", "process"), result.plan.selected_topics)
        self.assertEqual(40, result.plan.difficulty_weights["hard"])
        self.assertEqual(10, result.plan.question_type_weights["true_false"])

    def test_local_parser_applies_follow_up_to_latest_plan(self):
        interpreter = ExamRequestInterpreter(["cache", "process"])
        first = interpreter.interpret(
            "Create 20 hard final exam questions about cache and process",
            self.current,
        )

        second = interpreter.interpret(
            "Make it 25 questions and use fewer true false questions",
            first.plan,
        )

        self.assertEqual(25, second.plan.question_count)
        self.assertEqual("hard", second.plan.difficulty)
        self.assertEqual("final_exam", second.plan.template)
        self.assertLess(
            second.plan.question_type_weights["true_false"],
            first.plan.question_type_weights["true_false"],
        )

    def test_unrecognized_local_request_returns_actionable_error(self):
        interpreter = ExamRequestInterpreter(["cache"])

        with self.assertRaisesRegex(ExamRequestError, "具体"):
            interpreter.interpret("帮我优化一下", self.current)


if __name__ == "__main__":
    unittest.main()
