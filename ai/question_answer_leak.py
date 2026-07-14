"""Detect generated choice stems that reveal their correct option."""

from __future__ import annotations

import re


def choice_stem_leaks_answer_keyword(bilingual: dict, answer: str) -> bool:
    answer = str(answer or "").strip().upper()
    if answer not in {"A", "B", "C", "D"}:
        return False
    for language in ("zh", "en"):
        content = bilingual.get(language, {}) or {}
        options = content.get("options", []) or []
        option_text = _choice_option_text(options, answer)
        if not option_text:
            continue
        stem_tokens = _answer_leak_tokens(content.get("stem", ""))
        correct_tokens = _answer_leak_tokens(option_text)
        wrong_tokens = set()
        for index, option in enumerate(options):
            if index != ord(answer) - ord("A"):
                wrong_tokens.update(_answer_leak_tokens(option))
        if any(token in stem_tokens and token not in wrong_tokens for token in correct_tokens):
            return True
    return False


def _choice_option_text(options, answer: str) -> str:
    if not isinstance(options, list):
        return ""
    index = ord(answer) - ord("A")
    if index < 0 or index >= len(options):
        return ""
    return re.sub(
        r"^\s*[A-Da-d][\.\)、)]\s*", "", _raw_option_label(options[index])
    ).strip()


def _raw_option_label(option) -> str:
    if isinstance(option, dict):
        for key in ("text", "label", "title", "name", "value", "id"):
            value = option.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return str(option)


def _answer_leak_tokens(value) -> set[str]:
    text = str(value or "").lower()
    tokens: set[str] = set()
    for token in re.findall(r"[a-z][a-z\-]{2,}", text):
        normalized = token.strip("-")
        if normalized not in _ANSWER_LEAK_STOPWORDS:
            tokens.add(normalized)
        if "-" in normalized:
            tokens.update(
                part for part in normalized.split("-")
                if len(part) >= 4 and part not in _ANSWER_LEAK_STOPWORDS
            )
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if chunk not in _ANSWER_LEAK_STOPWORDS:
            tokens.add(chunk)
        for size in range(2, min(4, len(chunk)) + 1):
            for start in range(len(chunk) - size + 1):
                token = chunk[start:start + size]
                if token not in _ANSWER_LEAK_STOPWORDS:
                    tokens.add(token)
    return tokens


_ANSWER_LEAK_STOPWORDS = {
    "the", "and", "for", "with", "which", "what", "when", "where",
    "question", "answer", "option", "statement", "correct", "right", "wrong",
    "cpu", "io", "i/o", "方式", "以下", "哪种", "通知", "完成", "同步",
    "直接", "存储", "数据", "工作", "正确", "错误", "说法",
}
