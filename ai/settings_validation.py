"""Preflight validation for AI provider settings."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from urllib.parse import urlsplit

from ai.course_summary_factory import provider_requires_api_key
from ai.provider_presets import detect_local_agents, provider_from_base_url


@dataclass(frozen=True)
class AISettingsValidationResult:
    ok: bool
    message: str


def validate_remote_endpoint(base_url: str) -> AISettingsValidationResult:
    """Require HTTPS for remote services, allowing HTTP only on loopback."""
    value = str(base_url or "").strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        return AISettingsValidationResult(False, f"Invalid AI Base URL: {exc}")

    if parsed.scheme not in {"http", "https"}:
        return AISettingsValidationResult(
            False,
            "Remote AI Base URL must use HTTPS (HTTP is allowed only for localhost).",
        )
    if not parsed.hostname or any(char.isspace() for char in parsed.hostname):
        return AISettingsValidationResult(False, "AI Base URL must include a valid host name.")
    if parsed.username is not None or parsed.password is not None:
        return AISettingsValidationResult(
            False,
            "AI Base URL must not contain embedded user names or passwords.",
        )
    if port is not None and not 1 <= port <= 65535:
        return AISettingsValidationResult(False, "AI Base URL contains an invalid port.")

    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        return AISettingsValidationResult(
            False,
            "Remote AI endpoints must use HTTPS; plain HTTP is allowed only for localhost.",
        )
    return AISettingsValidationResult(True, "AI endpoint URL is safe to use.")


def _is_loopback_host(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_ai_settings(
    settings: dict,
    api_key: str = "",
    detected_agents: list[str] | None = None,
) -> AISettingsValidationResult:
    """Return a user-facing validation result for current AI settings."""
    base_url = str(settings.get("ai_base_url", "")).strip()
    provider = settings.get("ai_provider") or provider_from_base_url(base_url)
    model = str(settings.get("ai_model", "")).strip()

    if not provider:
        return AISettingsValidationResult(False, "Choose an AI provider.")
    if not base_url:
        return AISettingsValidationResult(False, "AI Base URL is required.")
    if not model:
        return AISettingsValidationResult(False, "AI model is required.")

    if provider == "local_agent" or base_url.startswith("local-agent://"):
        detected = detected_agents or []
        if model == "auto":
            if "claude" in detected:
                return AISettingsValidationResult(True, "Local agent ready: claude.")
            if detected:
                return AISettingsValidationResult(
                    False,
                    "Codex CLI detected but cannot guarantee no-tools isolation; "
                    "only Claude CLI is currently eligible for local generation. "
                    "Install Claude CLI or switch to a remote API.",
                )
            return AISettingsValidationResult(
                False,
                "No eligible local CLI agent detected. "
                "Install claude CLI or use a remote API.",
            )
        if model != "claude":
            return AISettingsValidationResult(
                False,
                f"Local agent '{model}' is not eligible for safe execution. "
                "Only Claude CLI is currently supported. "
                "Switch to a remote API or use model=claude.",
            )
        if model in detected:
            return AISettingsValidationResult(True, f"Local agent ready: {model}.")
        return AISettingsValidationResult(
            False,
            f"Local agent '{model}' was not found on PATH. "
            "Install claude CLI or log in.",
        )

    endpoint_result = validate_remote_endpoint(base_url)
    if not endpoint_result.ok:
        return endpoint_result

    if provider_requires_api_key({"ai_provider": provider, "ai_base_url": base_url}) and not api_key.strip():
        return AISettingsValidationResult(False, "API key is required for the selected remote provider.")

    return AISettingsValidationResult(True, f"AI settings look valid for provider '{provider}' and model '{model}'.")


def ai_generation_settings_error(
    settings: dict,
    api_key: str,
    detected_agents: list[str] | None = None,
) -> str:
    """Return a blocking generation-settings message, or an empty string."""
    result = validate_ai_settings(
        settings,
        api_key=api_key,
        detected_agents=(
            detect_local_agents() if detected_agents is None else detected_agents
        ),
    )
    return "" if result.ok else result.message
