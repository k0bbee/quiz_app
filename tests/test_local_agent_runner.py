import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import ctypes
from pathlib import Path
from unittest.mock import Mock, patch

import ai.local_agent_runner as local_agent_runner
from ai.local_agent_runner import (
    LocalAgentPolicyError,
    _terminate_process,
    _windows_cmd_wrap,
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

    def test_windows_cmd_is_launched_through_comspec_without_shell(self):
        command = [
            r"C:\Users\china\AppData\Roaming\npm\claude.CMD",
            "--print",
            "--tools",
            "",
        ]

        with patch.dict(os.environ, {"COMSPEC": r"C:\Windows\System32\cmd.exe"}):
            launch = _windows_cmd_wrap(command)

        self.assertEqual(r"C:\Windows\System32\cmd.exe", launch[0])
        self.assertEqual(["/d", "/s", "/c"], launch[1:4])
        self.assertIn("claude.CMD", launch[4])
        self.assertIn("--print", launch[4])

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
        cancel_event = threading.Event()
        timer = threading.Timer(0.1, cancel_event.set)
        timer.start()
        started = time.monotonic()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("ai.local_agent_runner.resolve_local_agent_executable", return_value=Path(sys.executable)), \
             patch(
                 "ai.local_agent_runner.build_local_agent_command",
                 return_value=[sys.executable, "-c", "import time; time.sleep(30)"],
            ):
            with self.assertRaises(LocalAgentPolicyError):
                run_local_agent("claude", "prompt", cancel_event=cancel_event)
        elapsed = time.monotonic() - started
        timer.cancel()
        self.assertLess(elapsed, 1.0, "cancel must stop execution within 1 second")

    def test_prompt_is_sent_to_stdin_before_waiting_for_exit(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("ai.local_agent_runner.resolve_local_agent_executable", return_value=Path(sys.executable)), \
             patch(
                 "ai.local_agent_runner.build_local_agent_command",
                 return_value=[
                     sys.executable,
                     "-c",
                     "import sys; print(sys.stdin.read())",
                 ],
             ):
            result = run_local_agent("claude", "course prompt", timeout=3)

        self.assertEqual("course prompt", result)

    def test_cancel_kills_running_process(self):
        cancel_event = threading.Event()
        cancel_event.set()  # cancel immediately before run

        # Should raise/subprocess error quickly because cancel is already set.
        with self.assertRaises((OSError, subprocess.SubprocessError, LocalAgentPolicyError)):
            run_local_agent("claude", "test", cancel_event=cancel_event, timeout=1)

    def test_windows_termination_uses_taskkill_for_entire_process_tree(self):
        proc = Mock(pid=4242)
        proc.poll.return_value = None
        proc.wait.return_value = 0
        taskkill_result = Mock(returncode=0)

        with patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}), \
             patch(
                 "ai.local_agent_runner.subprocess.run",
                 return_value=taskkill_result,
             ) as run:
            _terminate_process(proc, platform="nt")

        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(
            [
                r"C:\Windows\System32\taskkill.exe",
                "/PID",
                "4242",
                "/T",
                "/F",
            ],
            command,
        )
        self.assertFalse(run.call_args.kwargs["shell"])
        proc.kill.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows process-tree integration test")
    def test_cancel_removes_spawned_child_process_on_windows(self):
        cancel_event = threading.Event()
        with tempfile.TemporaryDirectory() as tmpdir:
            child_pid_file = Path(tmpdir) / "child.pid"
            parent_script = (
                "import pathlib,subprocess,sys,time;"
                "child=subprocess.Popen([sys.executable,'-c',"
                "'import time; time.sleep(30)']);"
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
                "time.sleep(30)"
            )

            def cancel_after_child_starts():
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if child_pid_file.exists():
                        cancel_event.set()
                        return
                    time.sleep(0.02)

            trigger = threading.Thread(
                target=cancel_after_child_starts,
                daemon=True,
            )
            trigger.start()
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
                 patch(
                     "ai.local_agent_runner.resolve_local_agent_executable",
                     return_value=Path(sys.executable),
                 ), patch(
                     "ai.local_agent_runner.build_local_agent_command",
                     return_value=[
                         sys.executable,
                         "-c",
                         parent_script,
                         str(child_pid_file),
                     ],
                 ):
                with self.assertRaises(LocalAgentPolicyError):
                    run_local_agent(
                        "claude",
                        "prompt",
                        cancel_event=cancel_event,
                        timeout=5,
                    )
            trigger.join(timeout=1)

            self.assertTrue(child_pid_file.exists())
            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 2
            while _windows_process_is_active(child_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(
                _windows_process_is_active(child_pid),
                f"child process {child_pid} survived cancellation",
            )

    def test_posix_termination_kills_the_spawned_process_group(self):
        proc = Mock(pid=4242)
        proc.poll.return_value = None
        proc.wait.return_value = 0

        with patch(
            "ai.local_agent_runner.os.getpgid",
            return_value=4242,
            create=True,
        ), patch(
            "ai.local_agent_runner.os.killpg",
            create=True,
        ) as killpg:
            _terminate_process(proc, platform="posix")

        killpg.assert_called_once()
        self.assertEqual(4242, killpg.call_args.args[0])
        proc.kill.assert_not_called()

    def test_process_isolation_matches_tree_termination_strategy(self):
        windows = local_agent_runner._process_isolation_kwargs("nt")
        posix = local_agent_runner._process_isolation_kwargs("posix")

        self.assertEqual(
            subprocess.CREATE_NEW_PROCESS_GROUP,
            windows["creationflags"],
        )
        self.assertEqual({"start_new_session": True}, posix)

    def test_missing_claude_auth_is_rejected_before_process_start(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("ai.local_agent_runner.resolve_local_agent_executable", return_value=Path(sys.executable)), \
             patch("ai.local_agent_runner.subprocess.Popen") as popen:
            with self.assertRaises(LocalAgentPolicyError) as ctx:
                run_local_agent("claude", "prompt")

        popen.assert_not_called()
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))


def _windows_process_is_active(pid: int) -> bool:
    """Return whether a Windows PID still represents a running process."""
    process_query_limited_information = 0x1000
    still_active = 259
    handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
        process_query_limited_information,
        False,
        pid,
    )
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
            handle,
            ctypes.byref(exit_code),
        ):
            return False
        return exit_code.value == still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
