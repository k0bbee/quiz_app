"""Structured controls for AI question generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import DEFAULT_DIFFICULTY_WEIGHTS, DEFAULT_QUESTION_TYPE_WEIGHTS

QUESTION_TYPE_DEFAULTS = dict(DEFAULT_QUESTION_TYPE_WEIGHTS)

DIFFICULTY_DEFAULTS = dict(DEFAULT_DIFFICULTY_WEIGHTS)

TEMPLATE_GUIDES = {
    "quick_review": "Quick review style: emphasize fast recall, core definitions, and common misconceptions.",
    "final_exam": "Final exam style: emphasize scenario reasoning, comparisons, calculations, and explanation-heavy questions.",
    "calculation_practice": "Calculation practice style: include concrete numbers, intermediate steps, and enough assumptions for every calculation.",
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
    normalized = {key: round(value * 100 / total) for key, value in source.items()}
    delta = 100 - sum(normalized.values())
    if normalized:
        first_key = next(iter(normalized))
        normalized[first_key] += delta
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
