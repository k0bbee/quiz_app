import unittest

from ai.connection_probe import AIConnectionProbe


class FakeClient:
    def __init__(self, response=None, last_error="", exception=None):
        self.response = response
        self.last_error = last_error
        self.exception = exception
        self.calls = []

    def generate_with_json(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.exception:
            raise self.exception
        return self.response


class Clock:
    def __init__(self, *values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


class AIConnectionProbeTests(unittest.TestCase):
    def settings(self):
        return {
            "ai_provider": "openai",
            "ai_base_url": "https://api.example.com/v1",
            "ai_model": "test-model",
        }

    def test_success_uses_minimal_json_protocol_and_reports_elapsed_time(self):
        client = FakeClient({"ok": True})
        captured = {}

        def factory(api_key, base_url, model, provider):
            captured.update(api_key=api_key, base_url=base_url, model=model, provider=provider)
            return client

        probe = AIConnectionProbe(client_factory=factory, clock=Clock(10.0, 10.125))

        result = probe.run(self.settings(), "sk-secret")

        self.assertTrue(result.ok)
        self.assertEqual(125, result.elapsed_ms)
        self.assertEqual("openai", result.provider)
        self.assertEqual("test-model", result.model)
        self.assertEqual("sk-secret", captured["api_key"])
        self.assertEqual("openai", captured["provider"])
        messages, kwargs = client.calls[0]
        prompt = "\n".join(message["content"] for message in messages)
        self.assertIn('{"ok": true}', prompt)
        self.assertNotIn("sk-secret", prompt)
        self.assertNotIn("course", prompt.lower())
        self.assertEqual(0, kwargs["temperature"])
        self.assertEqual(64, kwargs["max_tokens"])
        self.assertEqual(1, kwargs["max_retries"])

    def test_client_error_is_propagated_without_claiming_success(self):
        client = FakeClient(None, last_error="HTTP 401 invalid API key")
        probe = AIConnectionProbe(
            client_factory=lambda *_args: client,
            clock=Clock(1.0, 1.2),
        )

        result = probe.run(self.settings(), "bad-key")

        self.assertFalse(result.ok)
        self.assertIn("HTTP 401", result.message)
        self.assertEqual(200, result.elapsed_ms)

    def test_malformed_protocol_response_is_rejected(self):
        client = FakeClient({"status": "fine"})
        probe = AIConnectionProbe(
            client_factory=lambda *_args: client,
            clock=Clock(2.0, 2.01),
        )

        result = probe.run(self.settings(), "sk-test")

        self.assertFalse(result.ok)
        self.assertIn("protocol", result.message.lower())

    def test_unexpected_client_exception_becomes_actionable_result(self):
        client = FakeClient(exception=RuntimeError("connection reset"))
        probe = AIConnectionProbe(
            client_factory=lambda *_args: client,
            clock=Clock(3.0, 3.5),
        )

        result = probe.run(self.settings(), "sk-test")

        self.assertFalse(result.ok)
        self.assertIn("connection reset", result.message)
        self.assertEqual(500, result.elapsed_ms)


if __name__ == "__main__":
    unittest.main()
