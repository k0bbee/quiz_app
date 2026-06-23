"""Validated immutable configuration for natural-language exam requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from types import MappingProxyType
from typing import Any, Mapping

from ai.generation_config import DIFFICULTY_DEFAULTS, QUESTION_TYPE_DEFAULTS


DIFFICULTIES = ("easy", "medium", "hard", "mixed")
TEMPLATES = ("quick_review", "final_exam", "calculation_practice")
QUESTION_TYPES = tuple(QUESTION_TYPE_DEFAULTS)
DIFFICULTY_WEIGHT_KEYS = tuple(DIFFICULTY_DEFAULTS)


class ExamPlanValidationError(ValueError):
    """Raised when an untrusted exam-plan patch violates the local schema."""


@dataclass(frozen=True)
class PlanChange:
    """One user-reviewable difference between two plans."""

    field: str
    before: object
    after: object


@dataclass(frozen=True)
class ExamGenerationPlan:
    """Deeply immutable, normalized generation configuration."""

    question_count: int = 15
    difficulty: str = "medium"
    template: str = "quick_review"
    selected_topics: tuple[str, ...] = ()
    question_type_weights: Mapping[str, int] = field(
        default_factory=lambda: dict(QUESTION_TYPE_DEFAULTS)
    )
    difficulty_weights: Mapping[str, int] = field(
        default_factory=lambda: dict(DIFFICULTY_DEFAULTS)
    )
    topic_weights: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        _validate_question_count(self.question_count)
        if self.difficulty not in DIFFICULTIES:
            raise ExamPlanValidationError(f"invalid difficulty: {self.difficulty!r}")
        if self.template not in TEMPLATES:
            raise ExamPlanValidationError(f"invalid template: {self.template!r}")

        topics = _unique_strings(self.selected_topics, "selected_topics")
        object.__setattr__(self, "selected_topics", topics)
        object.__setattr__(
            self,
            "question_type_weights",
            MappingProxyType(
                _normalize_weight_group(
                    self.question_type_weights,
                    QUESTION_TYPES,
                    QUESTION_TYPE_DEFAULTS,
                    "question type",
                )
            ),
        )
        object.__setattr__(
            self,
            "difficulty_weights",
            MappingProxyType(
                _normalize_weight_group(
                    self.difficulty_weights,
                    DIFFICULTY_WEIGHT_KEYS,
                    DIFFICULTY_DEFAULTS,
                    "difficulty weight",
                )
            ),
        )
        object.__setattr__(
            self,
            "topic_weights",
            MappingProxyType(_normalize_topic_weights(self.topic_weights, topics)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "question_count": self.question_count,
            "difficulty": self.difficulty,
            "template": self.template,
            "selected_topics": list(self.selected_topics),
            "question_type_weights": dict(self.question_type_weights),
            "difficulty_weights": dict(self.difficulty_weights),
            "topic_weights": dict(self.topic_weights),
        }


@dataclass(frozen=True)
class ExamPlanPatch:
    """Strict partial update accepted from an LLM or local parser."""

    assistant_message: str = ""
    question_count: int | None = None
    difficulty: str | None = None
    template: str | None = None
    selected_topics: tuple[str, ...] | None = None
    question_type_weights: Mapping[str, int] | None = None
    difficulty_weights: Mapping[str, int] | None = None
    topic_weights: Mapping[str, int] | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ExamPlanPatch":
        if not isinstance(data, Mapping):
            raise ExamPlanValidationError("exam plan patch must be a JSON object")
        allowed = {
            "assistant_message",
            "question_count",
            "difficulty",
            "template",
            "selected_topics",
            "question_type_weights",
            "difficulty_weights",
            "topic_weights",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ExamPlanValidationError(f"unknown field(s): {', '.join(unknown)}")

        message = data.get("assistant_message", "")
        if not isinstance(message, str):
            raise ExamPlanValidationError("assistant_message must be text")

        count = data.get("question_count")
        if count is not None:
            _validate_question_count(count)

        difficulty = data.get("difficulty")
        if difficulty is not None and difficulty not in DIFFICULTIES:
            raise ExamPlanValidationError(f"invalid difficulty: {difficulty!r}")

        template = data.get("template")
        if template is not None and template not in TEMPLATES:
            raise ExamPlanValidationError(f"invalid template: {template!r}")

        selected = data.get("selected_topics")
        if selected is not None:
            if not isinstance(selected, (list, tuple)):
                raise ExamPlanValidationError("selected_topics must be an array")
            selected = _unique_strings(selected, "selected_topics")

        question_weights = _validate_partial_weights(
            data.get("question_type_weights"), QUESTION_TYPES, "question type"
        )
        difficulty_weights = _validate_partial_weights(
            data.get("difficulty_weights"), DIFFICULTY_WEIGHT_KEYS, "difficulty weight"
        )
        topic_weights = _validate_partial_weights(
            data.get("topic_weights"), None, "topic"
        )

        return cls(
            assistant_message=message.strip()[:2000],
            question_count=count,
            difficulty=difficulty,
            template=template,
            selected_topics=selected,
            question_type_weights=question_weights,
            difficulty_weights=difficulty_weights,
            topic_weights=topic_weights,
        )


def apply_exam_plan_patch(
    current: ExamGenerationPlan,
    patch: ExamPlanPatch,
    available_topics: list[str] | tuple[str, ...],
) -> ExamGenerationPlan:
    """Apply one validated patch while enforcing the active course topic allowlist."""
    allowed = _unique_strings(available_topics, "available_topics")
    allowed_set = set(allowed)
    topics = patch.selected_topics if patch.selected_topics is not None else current.selected_topics
    unknown_topics = [topic for topic in topics if topic not in allowed_set]
    if unknown_topics:
        raise ExamPlanValidationError(f"unknown topic(s): {', '.join(unknown_topics)}")

    question_weights = dict(current.question_type_weights)
    if patch.question_type_weights is not None:
        question_weights.update(patch.question_type_weights)

    difficulty_weights = dict(current.difficulty_weights)
    if patch.difficulty_weights is not None:
        difficulty_weights.update(patch.difficulty_weights)

    if patch.selected_topics is not None:
        topic_weights = _equal_weights(topics)
    else:
        topic_weights = {
            topic: current.topic_weights.get(topic, 0)
            for topic in topics
        }
    if patch.topic_weights is not None:
        unknown_weight_topics = sorted(set(patch.topic_weights) - set(topics))
        if unknown_weight_topics:
            raise ExamPlanValidationError(
                f"unknown topic weight(s): {', '.join(unknown_weight_topics)}"
            )
        topic_weights.update(patch.topic_weights)

    return ExamGenerationPlan(
        question_count=patch.question_count if patch.question_count is not None else current.question_count,
        difficulty=patch.difficulty if patch.difficulty is not None else current.difficulty,
        template=patch.template if patch.template is not None else current.template,
        selected_topics=topics,
        question_type_weights=question_weights,
        difficulty_weights=difficulty_weights,
        topic_weights=topic_weights,
    )


def describe_plan_changes(
    before: ExamGenerationPlan,
    after: ExamGenerationPlan,
) -> list[PlanChange]:
    """Return stable, presentation-neutral differences for the confirmation UI."""
    fields = (
        "question_count",
        "difficulty",
        "template",
        "selected_topics",
        "question_type_weights",
        "difficulty_weights",
        "topic_weights",
    )
    changes = []
    for name in fields:
        old = getattr(before, name)
        new = getattr(after, name)
        if isinstance(old, Mapping):
            old = dict(old)
            new = dict(new)
        if old != new:
            changes.append(PlanChange(name, old, new))
    return changes


def _validate_question_count(value: object):
    if isinstance(value, bool) or not isinstance(value, int) or not 3 <= value <= 60:
        raise ExamPlanValidationError("question_count must be an integer from 3 to 60")


def _unique_strings(values, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ExamPlanValidationError(f"{field_name} must be an array of strings")
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ExamPlanValidationError(f"{field_name} must contain non-empty strings")
        clean = value.strip()
        if clean not in seen:
            result.append(clean)
            seen.add(clean)
    return tuple(result)


def _validate_partial_weights(
    weights: object,
    allowed_keys: tuple[str, ...] | None,
    label: str,
) -> Mapping[str, int] | None:
    if weights is None:
        return None
    if not isinstance(weights, Mapping):
        raise ExamPlanValidationError(f"{label} weights must be an object")
    if allowed_keys is not None:
        unknown = sorted(set(weights) - set(allowed_keys))
        if unknown:
            raise ExamPlanValidationError(f"unknown {label} key(s): {', '.join(unknown)}")
    validated = {}
    for key, value in weights.items():
        if not isinstance(key, str) or not key.strip():
            raise ExamPlanValidationError(f"{label} weight keys must be text")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ExamPlanValidationError(f"{label} weight for {key!r} must be 0 to 100")
        validated[key.strip()] = value
    return MappingProxyType(validated)


def _normalize_weight_group(
    weights: Mapping[str, int],
    keys: tuple[str, ...],
    defaults: Mapping[str, int],
    label: str,
) -> dict[str, int]:
    validated = _validate_partial_weights(weights, keys, label) or {}
    source = {key: validated.get(key, 0) for key in keys}
    if sum(source.values()) <= 0:
        source = {key: int(defaults[key]) for key in keys}
    return _normalize_to_100(source)


def _normalize_topic_weights(
    weights: Mapping[str, int],
    topics: tuple[str, ...],
) -> dict[str, int]:
    if not topics:
        if weights:
            raise ExamPlanValidationError("topic_weights require selected_topics")
        return {}
    validated = _validate_partial_weights(weights, None, "topic") or {}
    unknown = sorted(set(validated) - set(topics))
    if unknown:
        raise ExamPlanValidationError(f"unknown topic weight(s): {', '.join(unknown)}")
    source = {topic: validated.get(topic, 0) for topic in topics}
    if sum(source.values()) <= 0:
        source = {topic: 1 for topic in topics}
    return _normalize_to_100(source)


def _equal_weights(keys: tuple[str, ...]) -> dict[str, int]:
    return _normalize_to_100({key: 1 for key in keys}) if keys else {}


def _normalize_to_100(weights: Mapping[str, int]) -> dict[str, int]:
    total = sum(weights.values())
    if total <= 0:
        return {key: 0 for key in weights}
    raw = {key: value * 100 / total for key, value in weights.items()}
    normalized = {key: floor(value) for key, value in raw.items()}
    remainder = 100 - sum(normalized.values())
    ranked = sorted(
        weights,
        key=lambda key: (-(raw[key] - normalized[key]), list(weights).index(key)),
    )
    for key in ranked[:remainder]:
        normalized[key] += 1
    return normalized
