"""Preflight validation for AI provider settings."""

from __future__ import annotations

from dataclasses import dataclass

from ai.course_summary_factory import provider_requires_api_key
from ai.provider_presets import provider_from_base_url


@dataclass(frozen=True)
class AISettingsValidationResult:
    ok: bool
    message: str


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
            if detected:
                return AISettingsValidationResult(True, f"Local agent ready: {', '.join(detected)}.")
            return AISettingsValidationResult(False, "No local CLI agent detected. Install or log in to codex/claude CLI.")
        if model in detected:
            return AISettingsValidationResult(True, f"Local agent ready: {model}.")
        return AISettingsValidationResult(False, f"Local agent '{model}' was not found on PATH.")

    if provider_requires_api_key({"ai_provider": provider, "ai_base_url": base_url}) and not api_key.strip():
        return AISettingsValidationResult(False, "API key is required for the selected remote provider.")

    return AISettingsValidationResult(True, f"AI settings look valid for provider '{provider}' and model '{model}'.")
