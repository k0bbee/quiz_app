import os
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ai.course_summary_factory import provider_requires_api_key
from ai.llm_client import LLMClient
from ai.settings_validation import ai_generation_settings_error


class AIGenerationPreflightTests(unittest.TestCase):
    def test_local_agent_provider_does_not_require_api_key(self):
        self.assertFalse(provider_requires_api_key({"ai_provider": "local_agent"}))
        self.assertFalse(
            provider_requires_api_key({"ai_base_url": "local-agent://auto"})
        )
        self.assertFalse(
            provider_requires_api_key(
                {
                    "ai_provider": "custom",
                    "ai_base_url": "local-agent://codex",
                }
            )
        )
        self.assertTrue(provider_requires_api_key({"ai_provider": "custom"}))

    def test_ai_generation_preflight_reports_missing_remote_key(self):
        message = ai_generation_settings_error(
            {
                "ai_provider": "openai",
                "ai_base_url": "https://api.openai.com/v1",
                "ai_model": "gpt-4.1-mini",
            },
            api_key="",
            detected_agents=[],
        )

        self.assertIn("API key", message)

    def test_ai_generation_preflight_accepts_detected_claude(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            message = ai_generation_settings_error(
                {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "claude",
                },
                api_key="",
                detected_agents=["claude"],
            )

        self.assertEqual("", message)

    def test_ai_generation_preflight_rejects_detected_codex(self):
        message = ai_generation_settings_error(
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            api_key="",
            detected_agents=["codex"],
        )

        self.assertNotEqual("", message)
        self.assertIn("codex", message.lower())

    def test_local_agent_accepts_course_prompt_characters_without_shell_rejection(self):
        client = LLMClient(api_key="", base_url="local-agent://auto", model="claude")
        stdin = types.SimpleNamespace(write=Mock(), close=Mock())
        fake_proc = types.SimpleNamespace(
            poll=lambda: 0,
            returncode=0,
            communicate=lambda timeout=0: ('{"questions":[]}', ""),
            stdin=stdin,
        )
        messages = [
            {
                "role": "user",
                "content": "Cache set = block # modulo sets; tag -> compare [A/B].",
            }
        ]

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch(
                "ai.local_agent_runner.resolve_local_agent_executable",
                return_value=Path("claude"),
            ),
            patch(
                "ai.local_agent_runner.subprocess.Popen",
                return_value=fake_proc,
            ) as popen_mock,
        ):
            text = client.generate(messages)

        self.assertEqual(text, '{"questions":[]}')
        self.assertTrue(popen_mock.called)

    def test_local_agent_sends_prompt_via_stdin_not_command_arguments(self):
        client = LLMClient(api_key="", base_url="local-agent://auto", model="claude")
        prompt = "Sensitive course prompt with enough text to exceed safe argv expectations."
        messages = [{"role": "user", "content": prompt}]
        stdin = types.SimpleNamespace(write=Mock(), close=Mock())
        fake_proc = types.SimpleNamespace(
            poll=lambda: 0,
            returncode=0,
            communicate=lambda timeout=0: ('{"questions":[]}', ""),
            stdin=stdin,
        )

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch(
                "ai.local_agent_runner.resolve_local_agent_executable",
                return_value=Path("claude"),
            ),
            patch(
                "ai.local_agent_runner.subprocess.Popen",
                return_value=fake_proc,
            ) as popen_mock,
        ):
            text = client.generate(messages)

        self.assertEqual(text, '{"questions":[]}')
        command = popen_mock.call_args.args[0]
        self.assertNotIn(prompt, command)
        self.assertIn("--no-session-persistence", command)
        sent_prompt = stdin.write.call_args.args[0]
        self.assertIn(prompt, sent_prompt)
        stdin.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
