"""LLM API client — OpenAI-compatible wrapper with retry logic."""
from utils.logger import debug, warning, error

import json
import re
import shutil
import subprocess
import time
from typing import Optional

import requests


class LLMClient:
    """OpenAI-compatible API client for question generation."""

    def __init__(self, api_key: str, base_url: str = None, model: str = "claude-sonnet-4-6"):
        self._api_key = api_key
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        self.model = model

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model!r}, base_url={self.base_url!r})"

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 8000,
    ) -> Optional[str]:
        """Send chat completion request. Returns response text or None on failure."""
        if self.base_url.startswith("local-agent://"):
            return self._generate_local_agent(messages, max_tokens)
        if "anthropic" in self.base_url:
            return self._generate_anthropic(messages, temperature, max_tokens)
        return self._generate_openai_compatible(messages, temperature, max_tokens)

    def _generate_local_agent(self, messages: list[dict], max_tokens: int) -> Optional[str]:
        """Use a known local CLI agent without requiring an API key.

        This is intentionally allowlisted. It does not execute arbitrary commands
        from settings or model output.
        """
        prompt = self._messages_to_prompt(messages)

        preferred = (self.model or "auto").lower()
        candidates = []
        if preferred in {"auto", "claude"}:
            candidates.append(("claude", ["claude", "-p", prompt]))
        if preferred in {"auto", "codex"}:
            candidates.append(("codex", ["codex", "exec", prompt]))

        for name, command in candidates:
            if shutil.which(command[0]) is None:
                continue
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
                debug(f"Local agent {name} failed ({result.returncode}): {result.stderr[:500]}")
            except (OSError, subprocess.SubprocessError) as exc:
                debug(f"Local agent {name} request failed: {exc}")
        return None

    def _generate_anthropic(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> Optional[str]:
        """Send an Anthropic Messages API request."""
        url = f"{self.base_url}/messages"
        system_prompt = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        user_messages = [m for m in messages if m.get("role") != "system"]
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError):
                    debug("LLM API returned non-JSON response")
                    return None
                # Extract from Anthropic response format
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        return block["text"]
                return None
            else:
                debug(f"LLM API error ({resp.status_code}): {resp.text[:500]}")
                return None
        except requests.RequestException as e:
            debug(f"LLM API request failed: {e}")
            return None

    def _generate_openai_compatible(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> Optional[str]:
        """Send an OpenAI-compatible chat completion request."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError):
                    debug("LLM API returned non-JSON response (openai-compatible)")
                    return None
                choices = data.get("choices", [])
                if not choices:
                    return None
                return choices[0].get("message", {}).get("content")
            debug(f"LLM API error ({resp.status_code}): {resp.text[:500]}")
            return None
        except requests.RequestException as e:
            debug(f"LLM API request failed: {e}")
            return None

    def generate_with_json(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 8000,
        max_retries: int = 3,
    ) -> Optional[dict]:
        """Generate response and parse as JSON with retry on parse failure."""
        for attempt in range(max_retries):
            text = self.generate(messages, temperature, max_tokens)
            if text is None:
                continue

            # Try to extract JSON from the response
            try:
                json_text = self._extract_json_text(text)

                return json.loads(json_text)
            except (json.JSONDecodeError, ValueError) as e:
                debug(f"JSON parse error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff

        return None

    @staticmethod
    def _extract_json_text(text: str) -> str:
        """Extract the first JSON object from a model response."""
        if "```json" in text:
            start = text.index("```json") + 7
            try:
                end = text.index("```", start)
            except ValueError:
                end = len(text)
            return text[start:end].strip()
        if "```" in text:
            start = text.index("```") + 3
            try:
                end = text.index("```", start)
            except ValueError:
                end = len(text)
            return text[start:end].strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0).strip()
        # Last resort: return the whole text; caller handles parse errors
        return text.strip()

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        """Flatten chat messages for local CLI agents."""
        parts = []
        for message in messages:
            role = message.get("role", "user").upper()
            parts.append(f"{role}:\n{message.get('content', '')}")
        return "\n\n".join(parts)
