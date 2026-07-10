"""Structured controls for AI question generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import floor

from config import DEFAULT_DIFFICULTY_WEIGHTS, DEFAULT_QUESTION_TYPE_WEIGHTS

QUESTION_TYPE_DEFAULTS = dict(DEFAULT_QUESTION_TYPE_WEIGHTS)

DIFFICULTY_DEFAULTS = dict(DEFAULT_DIFFICULTY_WEIGHTS)

TEMPLATE_GUIDES = {
    "quick_review": "Quick review style: emphasize fast recall, core definitions, and common misconceptions.",
    "final_exam": "Final exam style: emphasize scenario reasoning, comparisons, calculations, and explanation-heavy questions.",
    "calculation_practice": "Calculation practice style: include concrete numbers, intermediate steps, and enough assumptions for every calculation.",
}


def allocate_weighted_counts(weights: dict[str, int], count: int) -> dict[str, int]:
    """Convert percentages/relative weights into exact deterministic counts."""
    keys = list(weights)
    if count < 0:
        raise ValueError("count must not be negative")
    source = {key: max(0, int(weights[key])) for key in keys}
    total = sum(source.values())
    if not keys:
        return {}
    if total <= 0:
        source = {key: 1 for key in keys}
        total = len(keys)
    raw = {key: source[key] * count / total for key in keys}
    allocated = {key: floor(raw[key]) for key in keys}
    remainder = count - sum(allocated.values())
    ranked = sorted(
        keys,
        key=lambda key: (-(raw[key] - allocated[key]), keys.index(key)),
    )
    for key in ranked[:remainder]:
        allocated[key] += 1
    return allocated


def planned_generation_counts(
    config: "GenerationConfig", topics: list[str], count: int
) -> dict[str, dict[str, int]]:
    """Return the deterministic marginal plan shown before generation starts."""
    topic_keys = [str(topic) for topic in topics]
    return {
        "topics": allocate_weighted_counts(
            config.normalized_topic_weights(topic_keys),
            count,
        ),
        "question_types": allocate_weighted_counts(
            config.normalized_type_weights(),
            count,
        ),
        "difficulties": allocate_weighted_counts(
            config.normalized_difficulty_weights(),
            count,
        ),
    }


@dataclass
class GenerationConfig:
    """User-adjustable generation weights and template preferences."""

    question_type_weights: dict[str, int] = field(default_factory=lambda: dict(QUESTION_TYPE_DEFAULTS))
    difficulty_weights: dict[str, int] = field(default_factory=lambda: dict(DIFFICULTY_DEFAULTS))
    topic_weights: dict[str, int] = field(default_factory=dict)
    template: str = "quick_review"

    def normalized_type_weights(self) -> dict[str, int]:
        return _normalize_weights(self.question_type_weights, QUESTION_TYPE_DEFAULTS)

    def normalized_difficulty_weights(self) -> dict[str, int]:
        return _normalize_weights(self.difficulty_weights, DIFFICULTY_DEFAULTS)

    def normalized_topic_weights(self, topics: list) -> dict[str, int]:
        if not topics:
            return {}
        if self.topic_weights:
            selected = [str(topic) for topic in topics]
            weighted = _match_topic_weights_to_selected(self.topic_weights, selected)
            return _normalize_weights(weighted, None)
        share = 100 // len(topics)
        weights = {str(topic): share for topic in topics}
        weights[str(topics[-1])] += 100 - sum(weights.values())
        return weights

    def template_guide(self) -> str:
        return TEMPLATE_GUIDES.get(self.template, TEMPLATE_GUIDES["quick_review"])


def _normalize_weights(weights: dict[str, int], defaults: dict[str, int] | None) -> dict[str, int]:
    source = dict(defaults or {})
    source.update({key: max(0, int(value)) for key, value in weights.items()})
    total = sum(source.values())
    if total <= 0:
        return dict(defaults or {})
    raw = {key: source[key] * 100 / total for key in source}
    normalized = {key: floor(raw[key]) for key in source}
    remainder = 100 - sum(normalized.values())
    ranked = sorted(
        source,
        key=lambda key: (-(raw[key] - normalized[key]), list(source).index(key)),
    )
    for key in ranked[:remainder]:
        normalized[key] += 1
    return normalized


def _match_topic_weights_to_selected(weights: dict[str, int], selected_topics: list[str]) -> dict[str, int]:
    result = {topic: 0 for topic in selected_topics}
    exact = {topic.lower(): topic for topic in selected_topics}
    canonical = {_topic_key(topic): topic for topic in selected_topics}
    for raw_key, raw_value in weights.items():
        key = str(raw_key)
        key_canonical = _topic_key(key)
        target = exact.get(key.lower()) or canonical.get(key_canonical)
        if target is None and key_canonical:
            for selected_key, selected in canonical.items():
                if key_canonical in selected_key or selected_key in key_canonical:
                    target = selected
                    break
        if target is not None:
            result[target] = max(0, int(raw_value))
    if sum(result.values()) <= 0:
        share = 100 // len(selected_topics)
        result = {topic: share for topic in selected_topics}
        result[selected_topics[-1]] += 100 - sum(result.values())
    return result


def _topic_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))
