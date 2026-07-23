"""Capability-constrained local CLI agent execution.

All local-agent calls go through run_local_agent so the policy (no tools,
no session persistence, no project/MCP loading, isolated work directory,
sanitized environment) is enforced in a single reviewable module.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping


class LocalAgentPolicyError(Exception):
    """The requested agent cannot meet the minimum security policy."""


# Keys dropped from the child environment to prevent credential leaking.
_SANITIZE_ENV_KEYS: frozenset[str] = frozenset({
    "QUIZ_APP_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "COHERE_API_KEY",
})

# Keys explicitly allowed through the sanitized environment.
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


def build_local_agent_command(agent: str, workspace: Path) -> list[str]:
    """Build a capability-constrained command line for *agent*.

    Only Claude CLI is currently eligible.  Codex has no verified no-tools
    mode and is explicitly rejected for untrusted document processing.
    """
    normalized = agent.strip().lower()
    if normalized == "claude":
        return [
            "claude",
            "--print",
            "--bare",
            "--tools", "",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]
    raise LocalAgentPolicyError(
        f"codex/unknown agent '{agent}' is not eligible for local generation: "
        "no verified no-tools mode is available. Use a restricted Claude CLI "
        "or a remote API instead."
    )


def sanitized_child_environment(
    source: Mapping[str, str],
) -> dict[str, str]:
    """Return a copy of *source* with credential-bearing keys removed.

    Only known-safe system keys and a narrow allowlist of non-secret vars
    survive.  This is defense-in-depth — the caller should never pass
    credential-bearing environment variables to a child process.
    """
    clean: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if upper in _SANITIZE_ENV_KEYS:
            continue
        if upper in _ALLOWED_ENV_KEYS:
            clean[key] = value
    return clean


def run_local_agent(
    agent: str,
    prompt: str,
    *,
    timeout: int = 180,
) -> str:
    """Execute *agent* with the prompt on stdin in a throwaway directory.

    Returns the stripped stdout on success.  Raises :class:`LocalAgentPolicyError`
    when the agent is ineligible, and :class:`subprocess.SubprocessError` or
    :class:`OSError` on execution failures.
    """
    workspace = Path(tempfile.mkdtemp(prefix="quiz-local-agent-"))
    try:
        command = build_local_agent_command(agent, workspace)
        env = sanitized_child_environment(os.environ)

        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(workspace),
            env=env,
        )
        if result.returncode != 0 or not result.stdout.strip():
            detail = (result.stderr or result.stdout or "").strip()[:500]
            raise subprocess.CalledProcessError(
                result.returncode,
                command,
                output=result.stdout,
                stderr=detail,
            )
        return result.stdout.strip()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
