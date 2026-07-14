"""Normalize generated question payload shapes without UI dependencies."""

from __future__ import annotations

from utils.constants import QuestionType


def normalize_raw_question(qdata):
    if not isinstance(qdata, dict):
        return qdata
    normalized = dict(qdata)
    qtype = normalized.get("type")
    if qtype == QuestionType.FILL_IN_BLANK.value:
        answer = normalized.get("correct_answer")
        if isinstance(answer, str):
            normalized["correct_answer"] = [answer.strip()] if answer.strip() else []
        elif isinstance(answer, (list, tuple)):
            normalized["correct_answer"] = [
                str(item).strip() for item in answer if str(item).strip()
            ]
    elif qtype == QuestionType.MATCHING.value:
        normalized = _normalize_matching_option_ids(normalized)
    elif qtype == QuestionType.ORDERING.value:
        normalized = _normalize_ordering_option_ids(normalized)
    return normalized


def _normalize_matching_option_ids(qdata: dict) -> dict:
    normalized = dict(qdata)
    bilingual = dict(normalized.get("bilingual", {}) or {})
    left_ids = _stable_ids_for_parallel_options(
        [bilingual.get(language, {}).get("options", {}).get("left", []) for language in ("zh", "en")],
        "left",
    )
    right_ids = _stable_ids_for_parallel_options(
        [bilingual.get(language, {}).get("options", {}).get("right", []) for language in ("zh", "en")],
        "right",
    )
    label_to_id: dict[str, str] = {}
    for language in ("zh", "en"):
        content = dict(bilingual.get(language, {}) or {})
        options = dict(content.get("options", {}) or {})
        options["left"] = _normalize_option_list(options.get("left", []), left_ids, label_to_id, language)
        options["right"] = _normalize_option_list(options.get("right", []), right_ids, label_to_id, language)
        content["options"] = options
        bilingual[language] = content
    answer = normalized.get("correct_answer")
    if isinstance(answer, list):
        normalized["correct_answer"] = [
            [_normalize_answer_token(pair[0], label_to_id), _normalize_answer_token(pair[1], label_to_id)]
            for pair in answer
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        ]
    normalized["bilingual"] = bilingual
    return normalized


def _normalize_ordering_option_ids(qdata: dict) -> dict:
    normalized = dict(qdata)
    bilingual = dict(normalized.get("bilingual", {}) or {})
    item_ids = _stable_ids_for_parallel_options(
        [bilingual.get(language, {}).get("options", []) for language in ("zh", "en")],
        "item",
    )
    label_to_id: dict[str, str] = {}
    for language in ("zh", "en"):
        content = dict(bilingual.get(language, {}) or {})
        content["options"] = _normalize_option_list(
            content.get("options", []) or [], item_ids, label_to_id, language
        )
        bilingual[language] = content
    answer = normalized.get("correct_answer")
    if isinstance(answer, list):
        normalized["correct_answer"] = [
            _normalize_answer_token(item, label_to_id) for item in answer
        ]
    normalized["bilingual"] = bilingual
    return normalized


def _stable_ids_for_parallel_options(option_lists: list[list], prefix: str) -> list[str]:
    max_count = max((len(options or []) for options in option_lists), default=0)
    ids = []
    for index in range(max_count):
        found = ""
        for options in option_lists:
            if index < len(options or []):
                found = _raw_option_id(options[index])
                if found:
                    break
        ids.append(found or f"{prefix}_{index + 1}")
    return ids


def _normalize_option_list(options: list, ids: list[str], label_to_id: dict[str, str], language: str) -> list[dict]:
    normalized = []
    for index, option in enumerate(options or []):
        option_id = ids[index] if index < len(ids) else _raw_option_id(option) or f"item_{index + 1}"
        label = _raw_option_label(option, language)
        normalized.append({"id": option_id, "text": label})
        for alias in _raw_option_aliases(option, label):
            if alias:
                label_to_id.setdefault(alias.strip().lower(), option_id)
        label_to_id.setdefault(option_id.strip().lower(), option_id)
    return normalized


def _raw_option_id(option) -> str:
    if isinstance(option, dict):
        for key in ("id", "value", "key"):
            value = option.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _raw_option_label(option, language: str = "") -> str:
    if isinstance(option, dict):
        for key in (language, "text", "label", "title", "name", "value", "id"):
            value = option.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return str(option)


def _raw_option_aliases(option, label: str) -> list[str]:
    aliases = [label]
    if isinstance(option, dict):
        for key in ("id", "value", "key", "text", "label", "title", "name", "zh", "en"):
            value = option.get(key)
            if value is not None and str(value).strip():
                aliases.append(str(value).strip())
    else:
        aliases.append(str(option))
    return aliases


def _normalize_answer_token(value, label_to_id: dict[str, str]) -> str:
    text = str(value or "").strip()
    return label_to_id.get(text.lower(), text)
