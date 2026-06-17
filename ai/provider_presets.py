"""User-friendly AI provider presets."""

from __future__ import annotations

import shutil


PROVIDER_PRESETS = {
    "anthropic": {
        "label": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-sonnet-4-6", "claude-opus-4-8", "claude-fable-5"],
        "help": "Use an Anthropic API key. The app calls the /messages endpoint.",
    },
    "openai": {
        "label": "OpenAI-compatible",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4.1-mini", "gpt-4.1"],
        "help": "Works with OpenAI and most compatible /chat/completions providers.",
    },
    "local_agent": {
        "label": "Local CLI Agent",
        "base_url": "local-agent://auto",
        "models": ["auto", "claude", "codex"],
        "help": "Uses a detected local CLI agent when available. No API key is needed. Experimental and local-only.",
    },
    "custom": {
        "label": "Custom endpoint",
        "base_url": "",
        "models": [],
        "help": "Use this when your provider gives a custom base URL and model name.",
    },
}


def default_provider_settings(provider: str) -> dict:
    """Return default base URL and model for a provider."""
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["anthropic"])
    models = preset.get("models", [])
    return {
        "provider": provider,
        "base_url": preset.get("base_url", ""),
        "model": models[0] if models else "",
        "models": models,
        "help": preset.get("help", ""),
    }


def provider_from_base_url(base_url: str) -> str:
    """Infer provider from a stored base URL for backwards compatibility."""
    if "anthropic" in (base_url or ""):
        return "anthropic"
    if "openai" in (base_url or ""):
        return "openai"
    if (base_url or "").startswith("local-agent://"):
        return "local_agent"
    return "custom"


def detect_local_agents() -> list[str]:
    """Return known local agent CLIs available on PATH."""
    found = []
    for command in ("codex", "claude"):
        if shutil.which(command):
            found.append(command)
    return found
