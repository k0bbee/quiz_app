import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.local_agent_runner import (
    LocalAgentPolicyError,
    build_local_agent_command,
    sanitized_child_environment,
)


class LocalAgentRunnerTests(unittest.TestCase):
    def test_claude_runner_disables_tools_and_persistence(self):
        command = build_local_agent_command("claude", Path("C:/isolated"))
        self.assertIn("--tools", command)
        tools_idx = command.index("--tools")
        self.assertEqual("", command[tools_idx + 1])
        self.assertIn("--no-session-persistence", command)
        self.assertIn("--disable-slash-commands", command)

    def test_claude_runner_includes_print_and_isolated_workdir(self):
        command = build_local_agent_command("claude", Path("/tmp/w"))
        self.assertIn("--print", command)
        self.assertIn("--bare", command)

    def test_child_environment_drops_quiz_app_api_key(self):
        env = sanitized_child_environment({
            "PATH": "/usr/bin",
            "QUIZ_APP_API_KEY": "must-not-leak",
            "ANTHROPIC_API_KEY": "also-secret",
            "OPENAI_API_KEY": "secret-too",
            "HOME": "/home/user",
        })
        self.assertEqual("/usr/bin", env["PATH"])
        self.assertEqual("/home/user", env["HOME"])
        self.assertNotIn("QUIZ_APP_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_child_environment_preserves_system_path_and_temp(self):
        env = sanitized_child_environment({
            "PATH": "C:\\Windows",
            "SYSTEMROOT": "C:\\Windows",
            "TMP": "C:\\Temp",
            "TEMP": "C:\\Temp",
        })
        self.assertEqual("C:\\Windows", env["PATH"])
        self.assertEqual("C:\\Windows", env["SYSTEMROOT"])
        self.assertEqual("C:\\Temp", env["TMP"])

    def test_codex_is_rejected_without_verified_no_tools_mode(self):
        with self.assertRaises(LocalAgentPolicyError) as ctx:
            build_local_agent_command("codex", Path("C:/isolated"))
        self.assertIn("codex", str(ctx.exception).lower())
        self.assertIn("no-tools", str(ctx.exception).lower())

    def test_build_command_rejects_unknown_agent(self):
        with self.assertRaises(LocalAgentPolicyError):
            build_local_agent_command("unknown-cli", Path("/tmp"))


if __name__ == "__main__":
    unittest.main()
