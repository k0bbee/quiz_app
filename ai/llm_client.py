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

    def __init__(
        self,
        api_key: str,
        base_url: str = None,
        model: str = "claude-sonnet-4-6",
        provider: str = "",
    ):
        self._api_key = api_key
        normalized_provider = str(provider or "").strip().lower()
        if normalized_provider == "local_agent" and not base_url:
            base_url = "local-agent://auto"
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        self.model = model
        self.provider = normalized_provider or self._infer_provider_from_base_url(self.base_url)
        self.last_error = ""

    def __repr__(self) -> str:
        return (
            f"LLMClient(model={self.model!r}, base_url={self.base_url!r}, "
            f"provider={self.provider!r})"
        )

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 8000,
    ) -> Optional[str]:
        """Send chat completion request. Returns response text or None on failure."""
        self.last_error = ""
        if self.base_url.startswith("local-agent://"):
            return self._generate_local_agent(messages, max_tokens)
        from ai.settings_validation import validate_remote_endpoint

        endpoint_result = validate_remote_endpoint(self.base_url)
        if not endpoint_result.ok:
            self.last_error = endpoint_result.message
            warning(self.last_error)
            return None
        if self.provider == "anthropic":
            return self._generate_anthropic(messages, temperature, max_tokens)
        return self._generate_openai_compatible(messages, temperature, max_tokens)

    @staticmethod
    def _infer_provider_from_base_url(base_url: str) -> str:
        """Infer provider for legacy settings that predate explicit provider storage."""
        normalized = (base_url or "").lower()
        if normalized.startswith("local-agent://"):
            return "local_agent"
        if "anthropic" in normalized:
            return "anthropic"
        if "openai" in normalized:
            return "openai"
        return "custom"

    def _generate_local_agent(self, messages: list[dict], max_tokens: int) -> Optional[str]:
        """Use a known local CLI agent without requiring an API key.

        This is intentionally allowlisted. It does not execute arbitrary commands
        from settings or model output.
        """
        prompt = self._messages_to_prompt(messages)

        preferred = (self.model or "auto").lower()
        candidates = []
        if preferred in {"auto", "claude"}:
            candidates.append(("claude", ["claude", "-p"]))
        if preferred in {"auto", "codex"}:
            candidates.append(("codex", ["codex", "exec", "-"]))

        missing = []
        for name, command in candidates:
            if shutil.which(command[0]) is None:
                missing.append(command[0])
                continue
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    input=prompt,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
                detail = (result.stderr or result.stdout or "").strip()[:500]
                self.last_error = f"Local agent {name} failed with exit code {result.returncode}: {detail}"
                debug(self.last_error)
            except (OSError, subprocess.SubprocessError) as exc:
                self.last_error = f"Local agent {name} request failed: {exc}"
                debug(self.last_error)
        if not self.last_error:
            wanted = ", ".join(missing or [name for name, _ in candidates])
            self.last_error = f"No supported local agent CLI found for model '{self.model}'. Tried: {wanted}."
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
                    self.last_error = "Anthropic API returned a non-JSON response."
                    debug(self.last_error)
                    return None
                extracted = self._extract_anthropic_response_text(data)
                if extracted:
                    return extracted
                self.last_error = (
                    "Anthropic API response did not contain usable text or JSON content."
                    f" {self._anthropic_empty_response_detail(data)}"
                )
                return None
            else:
                self.last_error = f"Anthropic API error {resp.status_code}: {resp.text[:500]}"
                debug(self.last_error)
                return None
        except requests.RequestException as e:
            self.last_error = f"Anthropic API request failed: {e}"
            debug(self.last_error)
            return None

    @staticmethod
    def _anthropic_empty_response_detail(data: dict) -> str:
        """Build an actionable diagnostic when Anthropic returns no usable text."""
        details = []
        stop_reason = data.get("stop_reason")
        if isinstance(stop_reason, str) and stop_reason:
            details.append(f"stop_reason={stop_reason}.")
            if stop_reason == "max_tokens":
                details.append(
                    "The response was likely truncated before final JSON text was emitted; "
                    "increase max_tokens or generate fewer questions per batch."
                )

        content = data.get("content", [])
        block_types = []
        if isinstance(content, list):
            block_types = [
                str(block.get("type", "unknown"))
                for block in content
                if isinstance(block, dict)
            ]
        if block_types:
            details.append(f"Content block types: {', '.join(block_types)}.")
            non_text_types = {block_type.lower() for block_type in block_types}
            if non_text_types and not (non_text_types & {"text", "json", "input_json"}):
                details.append(
                    "Only non-text blocks were returned; ask the model/provider to emit "
                    "a final text JSON response."
                )

        return " ".join(details).strip()

    @staticmethod
    def _extract_anthropic_response_text(data: dict) -> str:
        """Extract usable text from Anthropic or Anthropic-compatible responses."""
        content = data.get("content", [])
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""

        text_parts = []
        structured_parts = []
        for block in content:
            if isinstance(block, str):
                if block.strip():
                    text_parts.append(block.strip())
                continue
            if not isinstance(block, dict):
                continue

            text = block.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
                continue

            for key in ("input", "json", "arguments"):
                value = block.get(key)
                if isinstance(value, (dict, list)):
                    structured_parts.append(
                        json.dumps(value, ensure_ascii=False, sort_keys=True)
                    )
                    break
                if isinstance(value, str) and value.strip():
                    structured_parts.append(value.strip())
                    break

        if text_parts:
            return "\n".join(text_parts)
        if structured_parts:
            return "\n".join(structured_parts)
        return ""

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
            if resp.status_code == 400 and self._response_format_rejected(resp.text):
                fallback_payload = dict(payload)
                fallback_payload.pop("response_format", None)
                resp = requests.post(
                    url,
                    headers=headers,
                    json=fallback_payload,
                    timeout=120,
                )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError):
                    self.last_error = "OpenAI-compatible API returned a non-JSON response."
                    debug(self.last_error)
                    return None
                choices = data.get("choices", [])
                if not choices:
                    self.last_error = "OpenAI-compatible API response did not include choices."
                    return None
                content = choices[0].get("message", {}).get("content")
                extracted = self._extract_openai_response_text(content)
                if extracted is not None:
                    return extracted
                self.last_error = (
                    "OpenAI-compatible API response did not contain usable text content."
                )
                return None
            self.last_error = f"OpenAI-compatible API error {resp.status_code}: {resp.text[:500]}"
            debug(self.last_error)
            return None
        except requests.RequestException as e:
            self.last_error = f"OpenAI-compatible API request failed: {e}"
            debug(self.last_error)
            return None

    @staticmethod
    def _extract_openai_response_text(content) -> Optional[str]:
        """Normalize OpenAI-compatible message content to plain text."""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return None

        text_parts = []
        for part in content:
            if isinstance(part, str):
                if part.strip():
                    text_parts.append(part.strip())
                continue
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
                continue
            nested_text = part.get("content")
            if isinstance(nested_text, str) and nested_text.strip():
                text_parts.append(nested_text.strip())

        if text_parts:
            return "\n".join(text_parts)
        return None

    @staticmethod
    def _response_format_rejected(text: str) -> bool:
        normalized = (text or "").lower()
        return "response_format" in normalized and (
            "not support" in normalized
            or "unsupported" in normalized
            or "invalid" in normalized
            or "json_object" in normalized
        )

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
            if not isinstance(text, str):
                self.last_error = (
                    "LLM response text must be a string, "
                    f"got {type(text).__name__}."
                )
                debug(self.last_error)
                continue

            # Try to extract JSON from the response
            parse_errors = []
            try:
                for json_text in self._extract_json_candidates(text):
                    try:
                        data = json.loads(json_text)
                        if not isinstance(data, dict):
                            raise ValueError(
                                f"expected JSON object, got {type(data).__name__}"
                            )
                        self.last_error = ""
                        return data
                    except (json.JSONDecodeError, ValueError) as candidate_error:
                        parse_errors.append(str(candidate_error))
                if parse_errors:
                    raise ValueError(parse_errors[-1])
                raise ValueError("no JSON object or array found in response")
            except (json.JSONDecodeError, ValueError) as e:
                self.last_error = f"JSON parse error (attempt {attempt + 1}/{max_retries}): {e}"
                debug(self.last_error)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff

        return None

    @staticmethod
    def _extract_json_text(text: str) -> str:
        """Extract the first JSON object from a model response."""
        for candidate in LLMClient._extract_json_candidates(text):
            return candidate
        # Last resort: return the whole text; caller handles parse errors
        return text.strip()

    @staticmethod
    def _extract_balanced_json_value(text: str) -> str:
        """Return the first balanced JSON object/array, ignoring braces in strings."""
        for candidate in LLMClient._extract_balanced_json_values(text):
            return candidate
        return ""

    @staticmethod
    def _extract_json_candidates(text: str) -> list[str]:
        """Return JSON-looking candidates in model-response priority order."""
        candidates = []
        seen = set()
        for candidate in (
            *LLMClient._extract_fenced_json_blocks(text),
            *LLMClient._extract_balanced_json_values(text),
            text.strip(),
        ):
            normalized = candidate.strip()
            if normalized and normalized not in seen:
                candidates.append(normalized)
                seen.add(normalized)
        return candidates

    @staticmethod
    def _extract_fenced_json_blocks(text: str) -> list[str]:
        """Extract Markdown fenced blocks without treating inline backticks as fence ends."""
        blocks = []
        opening_pattern = re.compile(r"^[ \t]*```[^\r\n]*\r?\n", re.MULTILINE)
        closing_pattern = re.compile(r"^[ \t]*```[ \t]*$", re.MULTILINE)
        for opening in opening_pattern.finditer(text):
            start = opening.end()
            closing = closing_pattern.search(text, start)
            end = closing.start() if closing else len(text)
            block = text[start:end].strip()
            if block:
                blocks.append(block)
        return blocks

    @staticmethod
    def _extract_balanced_json_values(text: str) -> list[str]:
        """Return balanced top-level JSON candidates, ignoring braces in strings."""
        pairs = {"{": "}", "[": "]"}
        closers = set(pairs.values())
        values = []

        start = -1
        expected_stack: list[str] = []
        in_string = False
        escaped = False

        for idx, char in enumerate(text):
            if start < 0:
                if char in pairs:
                    start = idx
                    expected_stack = [pairs[char]]
                    in_string = False
                    escaped = False
                continue

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue
            if char in pairs:
                expected_stack.append(pairs[char])
                continue
            if char in closers:
                if not expected_stack or char != expected_stack[-1]:
                    start = -1
                    expected_stack = []
                    in_string = False
                    escaped = False
                    continue
                expected_stack.pop()
                if not expected_stack:
                    values.append(text[start : idx + 1].strip())
                    start = -1

        return values

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        """Flatten chat messages for local CLI agents."""
        parts = []
        for message in messages:
            role = message.get("role", "user").upper()
            parts.append(f"{role}:\n{message.get('content', '')}")
        return "\n\n".join(parts)
