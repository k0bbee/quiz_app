"""Minimal, privacy-preserving AI provider connectivity probe."""

from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(frozen=True)
class ConnectionProbeResult:
    ok: bool
    message: str
    elapsed_ms: int
    provider: str
    model: str


class AIConnectionProbe:
    """Send a tiny JSON request and normalize the result for UI consumers."""

    def __init__(self, client_factory=None, clock=None):
        self.client_factory = client_factory or self._default_client_factory
        self.clock = clock or time.monotonic

    @staticmethod
    def _default_client_factory(api_key: str, base_url: str, model: str):
        from ai.llm_client import LLMClient

        return LLMClient(api_key=api_key, base_url=base_url, model=model)

    def run(self, settings: dict, api_key: str) -> ConnectionProbeResult:
        provider = str(settings.get("ai_provider", "") or "custom")
        base_url = str(settings.get("ai_base_url", ""))
        model = str(settings.get("ai_model", ""))
        started = self.clock()
        client = self.client_factory(api_key, base_url, model)
        try:
            data = client.generate_with_json(
                [
                    {
                        "role": "system",
                        "content": 'Connectivity check only. Return exactly this JSON object: {"ok": true}',
                    },
                    {
                        "role": "user",
                        "content": 'Reply with {"ok": true} now.',
                    },
                ],
                temperature=0,
                max_tokens=64,
                max_retries=1,
            )
        except Exception as exc:
            return self._result(
                False,
                f"AI connection test failed: {exc}",
                started,
                provider,
                model,
            )

        if data is None:
            detail = str(getattr(client, "last_error", "") or "provider returned no JSON response")
            return self._result(
                False,
                f"AI connection test failed: {detail}",
                started,
                provider,
                model,
            )
        if not isinstance(data, dict) or data.get("ok") is not True:
            return self._result(
                False,
                "AI connection test protocol error: expected a JSON object with ok=true.",
                started,
                provider,
                model,
            )
        return self._result(
            True,
            f"Connected to provider '{provider}' with model '{model}'.",
            started,
            provider,
            model,
        )

    def _result(
        self,
        ok: bool,
        message: str,
        started: float,
        provider: str,
        model: str,
    ) -> ConnectionProbeResult:
        elapsed_ms = max(0, round((self.clock() - started) * 1000))
        return ConnectionProbeResult(ok, message, elapsed_ms, provider, model)
