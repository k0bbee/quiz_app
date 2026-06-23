"""Factory helpers for optional LLM course summary generation."""

from __future__ import annotations

from ai.course_summarizer import CourseSummaryGenerator
from ai.course_generation_profile import CourseGenerationProfileGenerator
from ai.llm_client import LLMClient
from ai.provider_presets import default_provider_settings, provider_from_base_url
from config import DEFAULT_SETTINGS


def provider_requires_api_key(settings: dict) -> bool:
    """Return whether the selected summary provider needs an API key."""
    provider = settings.get("ai_provider") or provider_from_base_url(settings.get("ai_base_url", ""))
    base_url = settings.get("ai_base_url", "")
    return provider != "local_agent" and not str(base_url).startswith("local-agent://")


def create_course_summary_generator(settings: dict, api_key: str = "") -> CourseSummaryGenerator | None:
    """Create a summary generator when settings are sufficient; otherwise None.

    Returning None is intentional: course initialization can still proceed with
    the deterministic local summary when an API key or local agent is not ready.
    """
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings or {})
    provider = merged.get("ai_provider") or provider_from_base_url(merged.get("ai_base_url", ""))
    defaults = default_provider_settings(provider)
    base_url = merged.get("ai_base_url") or defaults.get("base_url", "")
    model = merged.get("ai_model") or defaults.get("model", "")

    if provider_requires_api_key(merged) and not api_key.strip():
        return None

    client = LLMClient(api_key=api_key, base_url=base_url, model=model)
    return CourseSummaryGenerator(client)


def create_course_generation_profile_generator(
    settings: dict,
    api_key: str = "",
) -> CourseGenerationProfileGenerator:
    """Create a per-course profile generator, always retaining a local fallback."""
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings or {})
    provider = merged.get("ai_provider") or provider_from_base_url(merged.get("ai_base_url", ""))
    defaults = default_provider_settings(provider)
    base_url = merged.get("ai_base_url") or defaults.get("base_url", "")
    model = merged.get("ai_model") or defaults.get("model", "")

    if provider_requires_api_key(merged) and not api_key.strip():
        return CourseGenerationProfileGenerator()
    client = LLMClient(api_key=api_key, base_url=base_url, model=model)
    return CourseGenerationProfileGenerator(client)
