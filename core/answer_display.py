"""Readable display helpers for stored answer payloads."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from models.question import Question
from utils.constants import QuestionType


def format_answer_for_display(
    question: Question,
    answer: Any,
    lang: str = "zh",
    empty_text: str = "(empty)",
) -> str:
    """Render stored answers as user-facing text instead of internal IDs."""
    if answer is None or answer == "":
        return empty_text

    if question.type == QuestionType.MATCHING:
        return _format_matching_answer(question, answer, lang)
    if question.type == QuestionType.ORDERING:
        return _format_ordering_answer(question, answer, lang)
    if question.type == QuestionType.FILL_IN_BLANK and isinstance(answer, list):
        return " / ".join(str(item) for item in answer)

    answer_text = str(answer)
    if question.type in (QuestionType.MULTIPLE_CHOICE, QuestionType.SCENARIO_CHOICE):
        options = question.get_options(lang)
        if len(answer_text) == 1 and answer_text.isalpha() and isinstance(options, list):
            idx = ord(answer_text.upper()) - ord("A")
            if 0 <= idx < len(options):
                return option_text(options[idx], lang)
    return answer_text


def option_text(option: Any, lang: str = "zh") -> str:
    """Return the human-readable text for an option object."""
    if isinstance(option, dict):
        candidates = [
            option.get(lang),
            option.get("text"),
            option.get("label"),
            option.get("title"),
            option.get("name"),
            option.get("value"),
            option.get("id"),
        ]
        for candidate in candidates:
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
    return str(option)


def option_identity(option: Any, lang: str = "zh") -> str:
    """Return the stable identity for an option, falling back to display text."""
    if isinstance(option, dict):
        for key in ("id", "value", "key"):
            value = option.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return option_text(option, lang)


def option_label_map(question: Question, lang: str = "zh") -> dict[str, str]:
    """Build a stable-id/text lookup for structured question answers."""
    options = question.get_options(lang) or question.get_options("zh") or question.get_options("en")
    mapping: dict[str, str] = {}

    def add(option: Any) -> None:
        identity = option_identity(option, lang)
        label = option_text(option, lang)
        if identity:
            mapping[str(identity)] = label
        if label:
            mapping[str(label)] = label

    if isinstance(options, dict):
        for values in options.values():
            if isinstance(values, Iterable) and not isinstance(values, (str, bytes, dict)):
                for option in values:
                    add(option)
    elif isinstance(options, list):
        for option in options:
            add(option)
    return mapping


def _format_matching_answer(question: Question, answer: Any, lang: str) -> str:
    labels = option_label_map(question, lang)
    if not isinstance(answer, list):
        return str(answer)
    pairs = []
    for pair in answer:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            pairs.append(str(pair))
            continue
        left = labels.get(str(pair[0]), str(pair[0]))
        right = labels.get(str(pair[1]), str(pair[1]))
        pairs.append(f"{left} → {right}")
    return "; ".join(pairs)


def _format_ordering_answer(question: Question, answer: Any, lang: str) -> str:
    labels = option_label_map(question, lang)
    if not isinstance(answer, list):
        return str(answer)
    return " → ".join(labels.get(str(item), str(item)) for item in answer)
