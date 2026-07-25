"""Capability-constrained local CLI agent execution.

All local-agent calls go through run_local_agent so the policy (no tools,
no session persistence, no project/MCP loading, isolated work directory,
sanitized environment) is enforced in a single reviewable module.
"""

from __future__ import annotations

import ntpath
import os
import signal
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Mapping


class LocalAgentPolicyError(Exception):
    """The requested agent cannot meet the minimum security policy."""


# Keys unconditionally dropped from the child environment.
_SANITIZE_ENV_KEYS: frozenset[str] = frozenset({
    "QUIZ_APP_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "COHERE_API_KEY",
})

# Keys always allowed through.
_ALLOWED_ENV_KEYS: frozenset[str] = frozenset({
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "TMP",
    "TEMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "USER",
    "USERNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SHELL",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "ProgramData",
    "ALLUSERSPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "COMPUTERNAME",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
    "OS",
})

_MAX_LOCAL_AGENT_OUTPUT_CHARS = 4 * 1024 * 1024


def resolve_local_agent_executable(agent_name: str) -> Path | None:
    """Return the full resolved path to *agent_name*, or None if not found."""
    resolved = shutil.which(agent_name)
    if resolved is None:
        return None
    return Path(resolved)


def build_local_agent_command(agent_name: str, executable: Path) -> list[str]:
    """Build a capability-constrained command line using the resolved executable.

    Only Claude CLI is currently eligible.  Codex has no verified no-tools
    mode and is explicitly rejected.
    """
    normalized = agent_name.strip().lower()
    if normalized == "claude":
        return [
            str(executable),
            "--print",
            "--bare",
            "--tools", "",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]
    raise LocalAgentPolicyError(
        f"codex/unknown agent '{agent_name}' is not eligible for local "
        "generation: no verified no-tools mode is available. Use a "
        "restricted Claude CLI or a remote API instead."
    )


def sanitized_child_environment(
    source: Mapping[str, str],
    *,
    preserve_anthropic_key: bool = False,
) -> dict[str, str]:
    """Return a copy of *source* with credential-bearing keys removed.

    When *preserve_anthropic_key* is True, ANTHROPIC_API_KEY is kept
    (needed for Claude CLI in --bare mode).  Other secret keys are
    always dropped.
    """
    clean: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if upper in _SANITIZE_ENV_KEYS:
            continue
        if upper == "ANTHROPIC_API_KEY":
            if preserve_anthropic_key:
                clean[key] = value
            continue
        if upper in _ALLOWED_ENV_KEYS:
            clean[key] = value
    return clean


def _windows_cmd_wrap(command: list[str]) -> list[str]:
    """Wrap a Windows batch command through COMSPEC without enabling shell."""
    if not command:
        return command
    suffix = Path(command[0]).suffix.lower()
    if suffix in {".cmd", ".bat"}:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [
            comspec,
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline(command),
        ]
    return command


def _process_isolation_kwargs(platform: str) -> dict:
    """Return Popen options matching the platform's tree-kill strategy."""
    if platform == "nt":
        windows_process_group_flag = getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            None,
        )
        return {
            # subprocess only exposes this Windows SDK constant on Windows.
            # Keep platform simulation deterministic on Linux CI as well.
            "creationflags": windows_process_group_flag or 0x00000200,
        }
    return {"start_new_session": True}


def _drain_stream_bounded(
    stream,
    chunks: list[str],
    overflow: threading.Event,
) -> None:
    """Continuously drain a child stream without retaining unbounded output."""
    retained = 0
    while not overflow.is_set():
        chunk = stream.read(64 * 1024)
        if not chunk:
            return
        remaining = _MAX_LOCAL_AGENT_OUTPUT_CHARS - retained
        if remaining <= 0:
            overflow.set()
            return
        chunks.append(chunk[:remaining])
        retained += min(len(chunk), remaining)
        if len(chunk) > remaining:
            overflow.set()
            return


def run_local_agent(
    agent_name: str,
    prompt: str,
    *,
    timeout: int = 180,
    cancel_event: threading.Event | None = None,
) -> str:
    """Execute *agent_name* with the prompt on stdin in a throwaway directory.

    Returns the stripped stdout on success.  Raises :class:`LocalAgentPolicyError`
    when the agent is ineligible, and :class:`subprocess.SubprocessError` or
    :class:`OSError` on execution failures.

    The optional *cancel_event* is polled every 50 ms; when set the child
    process tree is terminated and a :class:`LocalAgentPolicyError` is raised.
    """
    executable = resolve_local_agent_executable(agent_name)
    if executable is None:
        raise LocalAgentPolicyError(
            f"Local agent '{agent_name}' not found on PATH."
        )

    if cancel_event is not None and cancel_event.is_set():
        raise LocalAgentPolicyError("Local agent execution cancelled.")

    command = build_local_agent_command(agent_name, executable)
    if agent_name.strip().lower() == "claude" and not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise LocalAgentPolicyError(
            "Restricted Claude CLI execution requires ANTHROPIC_API_KEY "
            "in the process environment because --bare disables stored login state."
        )
    env = sanitized_child_environment(os.environ, preserve_anthropic_key=True)
    workspace = Path(tempfile.mkdtemp(prefix="quiz-local-agent-"))
    launch_command = _windows_cmd_wrap(command) if os.name == "nt" else command

    try:
        proc = subprocess.Popen(
            launch_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workspace),
            env=env,
            **_process_isolation_kwargs(os.name),
        )
        try:
            stdout_data, stderr_data = "", ""
            deadline = time_monotonic() + timeout
            if proc.stdin is not None:
                proc.stdin.write(prompt)
                proc.stdin.close()
                proc.stdin = None

            stdout_chunks: list[str] = []
            stderr_chunks: list[str] = []
            output_overflow = threading.Event()
            streams = (getattr(proc, "stdout", None), getattr(proc, "stderr", None))
            drain_threads: list[threading.Thread] = []
            if all(callable(getattr(stream, "read", None)) for stream in streams):
                for name, stream, chunks in (
                    ("stdout", streams[0], stdout_chunks),
                    ("stderr", streams[1], stderr_chunks),
                ):
                    thread = threading.Thread(
                        target=_drain_stream_bounded,
                        args=(stream, chunks, output_overflow),
                        daemon=True,
                        name=f"local-agent-{name}",
                    )
                    thread.start()
                    drain_threads.append(thread)

            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    _terminate_process(proc)
                    raise LocalAgentPolicyError(
                        "Local agent execution cancelled by user."
                    )
                if output_overflow.is_set():
                    _terminate_process(proc)
                    raise LocalAgentPolicyError(
                        "Local agent output exceeded the 4 MiB safety limit."
                    )
                if time_monotonic() > deadline:
                    _terminate_process(proc)
                    raise subprocess.TimeoutExpired(launch_command, timeout)
                time.sleep(0.05)  # 50 ms poll

            if drain_threads:
                for thread in drain_threads:
                    thread.join(timeout=5)
                if any(thread.is_alive() for thread in drain_threads):
                    _terminate_process(proc)
                    raise subprocess.TimeoutExpired(launch_command, timeout)
                stdout_data = "".join(stdout_chunks)
                stderr_data = "".join(stderr_chunks)
            else:
                # Test doubles and legacy wrappers may only expose communicate().
                stdout_data, stderr_data = proc.communicate(timeout=5)

        except subprocess.TimeoutExpired:
            _terminate_process(proc)
            raise

        if proc.returncode != 0 or not (stdout_data or "").strip():
            detail = (stderr_data or stdout_data or "").strip()[:500]
            raise subprocess.CalledProcessError(
                proc.returncode, command,
                output=stdout_data,
                stderr=detail,
            )
        return (stdout_data or "").strip()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _terminate_process(
    proc: subprocess.Popen,
    *,
    platform: str | None = None,
) -> None:
    """Best-effort termination of a subprocess and its children."""
    platform = platform or os.name
    tree_terminated = False

    if platform == "nt":
        try:
            system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
            if not system_root:
                raise OSError("Windows system directory is unavailable")
            taskkill = ntpath.join(system_root, "System32", "taskkill.exe")
            result = subprocess.run(
                [
                    taskkill,
                    "/PID",
                    str(proc.pid),
                    "/T",
                    "/F",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                shell=False,
            )
            tree_terminated = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            tree_terminated = False
    else:
        try:
            os.killpg(os.getpgid(proc.pid), getattr(signal, "SIGKILL", 9))
            tree_terminated = True
        except (AttributeError, OSError, ProcessLookupError):
            tree_terminated = False

    if not tree_terminated:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def time_monotonic() -> float:
    """Thin wrapper so tests can override without mocking the stdlib."""
    return time.monotonic()
