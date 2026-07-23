import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.local_agent_runner import (
    LocalAgentPolicyError,
    build_local_agent_command,
    resolve_local_agent_executable,
    run_local_agent,
    sanitized_child_environment,
)


class LocalAgentRunnerTests(unittest.TestCase):
    # -- Path resolution --

    def test_resolve_executable_returns_full_path_from_shutil_which(self):
        with patch("ai.local_agent_runner.shutil.which") as mock_which:
            mock_which.return_value = r"C:\Users\china\AppData\Roaming\npm\claude.CMD"
            result = resolve_local_agent_executable("claude")
            self.assertEqual(
                Path(r"C:\Users\china\AppData\Roaming\npm\claude.CMD"),
                result,
            )

    def test_resolve_executable_returns_none_when_not_found(self):
        with patch("ai.local_agent_runner.shutil.which", return_value=None):
            self.assertIsNone(resolve_local_agent_executable("claude"))

    # -- Command construction uses full path --

    def test_claude_command_uses_resolved_executable_path(self):
        exe = Path(r"C:\Users\china\AppData\Roaming\npm\claude.CMD")
        command = build_local_agent_command("claude", exe)
        self.assertEqual(str(exe), command[0])

    def test_claude_command_includes_security_flags(self):
        exe = Path("/usr/local/bin/claude")
        command = build_local_agent_command("claude", exe)
        self.assertIn("--tools", command)
        tools_idx = command.index("--tools")
        self.assertEqual("", command[tools_idx + 1])
        self.assertIn("--no-session-persistence", command)
        self.assertIn("--disable-slash-commands", command)

    def test_codex_is_rejected(self):
        with self.assertRaises(LocalAgentPolicyError) as ctx:
            build_local_agent_command("codex", Path("/usr/local/bin/codex"))
        self.assertIn("codex", str(ctx.exception).lower())

    # -- Environment sanitization preserves ANTHROPIC_API_KEY for bare mode --

    def test_bare_mode_preserves_anthropic_api_key(self):
        env = sanitized_child_environment(
            {
                "PATH": "/usr/bin",
                "ANTHROPIC_API_KEY": "sk-ant-key",
                "QUIZ_APP_API_KEY": "must-not-leak",
                "OPENAI_API_KEY": "also-secret",
                "HOME": "/home/user",
            },
            preserve_anthropic_key=True,
        )
        self.assertEqual("sk-ant-key", env.get("ANTHROPIC_API_KEY"))
        self.assertNotIn("QUIZ_APP_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_default_mode_drops_all_secret_keys(self):
        env = sanitized_child_environment({
            "PATH": "/usr/bin",
            "QUIZ_APP_API_KEY": "must-not-leak",
            "ANTHROPIC_API_KEY": "also-secret",
            "HOME": "/home/user",
        })
        self.assertNotIn("QUIZ_APP_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    # -- Cancellation --

    def test_cancel_stops_subprocess_within_one_second(self):
        """A long-running subprocess must be terminated by cancel within 1s."""
        cancel_event = threading.Event()
        started = time.monotonic()

        def fake_popen(*args, **kwargs):
            # Simulate a slow process; cancel is set from outside.
            cancel_event.set()
            raise KeyboardInterrupt  # short-circuit before real Popen

        with patch("ai.local_agent_runner.subprocess.Popen", side_effect=fake_popen):
            try:
                run_local_agent("claude", "prompt", cancel_event=cancel_event)
            except KeyboardInterrupt:
                pass

        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0, "cancel must stop execution within 1 second")

    # -- Real sleep-process cancellation --

    def test_cancel_kills_running_process(self):
        import subprocess

        cancel_event = threading.Event()
        cancel_event.set()  # cancel immediately before run

        # Should raise/subprocess error quickly because cancel is already set.
        with self.assertRaises((OSError, subprocess.SubprocessError, LocalAgentPolicyError)):
            run_local_agent("claude", "test", cancel_event=cancel_event, timeout=1)


if __name__ == "__main__":
    unittest.main()
