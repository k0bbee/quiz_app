"""Shared course-term extraction helpers for topics and retrieval indexes."""

from __future__ import annotations

import re
from collections import Counter


STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "have", "will", "into",
    "your", "about", "when", "which", "where", "what", "why", "how", "can",
    "you", "are", "was", "were", "has", "use", "using", "page", "slide",
    "一个", "一种", "以及", "或者", "因此", "因为", "如果", "可以", "需要",
    "什么", "如何", "为什么", "主要", "系统", "课程", "内容", "问题",
    "handout", "notes", "slides", "lecture", "chapter", "course", "review",
    "uses", "order", "text", "one", "not", "based", "says", "generic", "single",
    # Common noise from non-course files and generated study-summary scaffolding.
    "files", "data", "details", "summary", "results", "diff", "total",
    "codes", "comments", "blanks", "lines", "all", "question", "questions",
    "discussion", "checkpoint", "previous", "答案", "解析",
    # English equivalents of generated study-summary scaffolding.
    "core", "concept", "concepts", "reasoning", "flow", "example", "examples",
    "exam", "direction", "directions", "answer", "answers", "point", "points",
    "overview",
}


TECHNICAL_KEYWORDS = {
    "address", "block", "byte", "cache", "cpu", "dma", "gpu", "index", "line",
    "mapping", "mmu", "offset", "pcb", "raid", "set", "simd", "simt", "tag",
    "tlb", "warp",
}


LOW_VALUE_KEYWORD_FRAGMENTS = {
    "根据课件", "课件上下文", "关键条件", "中间状态", "输出结果", "整理概念",
    "概念关系", "计算步骤", "人工补充", "当前抽取", "可考方向", "答题要点",
    "实际例子", "易错点", "核心概念", "推演流程",
    "core concept", "reasoning flow", "exam direction", "answer point",
}


def extract_course_terms(text: str, limit: int = 20) -> Counter:
    """Extract high-value course terms with shared noise filtering."""
    phrases = re.findall(r"[A-Z][a-z]+_[A-Z][a-z]+(?:_[A-Z][a-z]+)?", text)
    tokens = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_+-]{2,}", text)
    candidates: list[tuple[str, str]] = []
    for token in phrases + tokens:
        key = _normalize_english_plural(token.lower())
        if key in STOP_WORDS:
            continue
        if is_low_value_keyword(key):
            continue
        if token.isdigit():
            continue
        candidates.append((key, token))
        for part in re.split(r"[_+-]+", token):
            part_key = _normalize_english_plural(part.lower())
            if part_key != key and len(part_key) >= 2:
                if part_key not in STOP_WORDS and not is_low_value_keyword(part_key):
                    candidates.append((part_key, part))

    counts = Counter(key for key, _ in candidates)
    normalized = []
    for key, token in candidates:
        if re.match(r"^[a-z]{2,10}$", key) and key not in TECHNICAL_KEYWORDS:
            is_acronym = token.isupper() and 2 <= len(token) <= 8
            is_repeated_domain_term = counts[key] >= 2
            if not (is_acronym or is_repeated_domain_term):
                continue
        normalized.append(key)
    return Counter(dict(Counter(normalized).most_common(limit)))


def is_low_value_keyword(term: str) -> bool:
    """Return True for generated scaffolding terms that do not identify a topic."""
    return any(fragment in term for fragment in LOW_VALUE_KEYWORD_FRAGMENTS)


def _normalize_english_plural(term: str) -> str:
    if re.match(r"^[a-z]{4,}ies$", term):
        return f"{term[:-3]}y"
    if re.match(r"^[a-z]{4,}(sses|ches|shes|xes|zes)$", term):
        return term[:-2]
    if re.match(r"^[a-z]{5,}s$", term) and not term.endswith("ss"):
        return term[:-1]
    return term
