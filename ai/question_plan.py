"""Deterministic plan items for AI question generation."""

from __future__ import annotations

from dataclasses import dataclass, field

from ai.generation_config import GenerationConfig, allocate_weighted_counts


SKILL_WEIGHT_DEFAULTS: dict[str, dict[str, int]] = {
    "quick_review": {
        "definition": 60,
        "comparison": 25,
        "application": 15,
        "scenario": 0,
        "calculation": 0,
        "debugging": 0,
    },
    "final_exam": {
        "application": 30,
        "scenario": 30,
        "comparison": 20,
        "calculation": 10,
        "definition": 10,
        "debugging": 0,
    },
    "calculation_practice": {
        "calculation": 55,
        "application": 20,
        "scenario": 15,
        "comparison": 5,
        "definition": 5,
        "debugging": 0,
    },
}


@dataclass(frozen=True)
class QuestionPlanItem:
    """One planned question slot before asking the LLM to generate content."""

    plan_id: str
    topic_id: str
    topic_title: str
    question_type: str
    difficulty: str
    target_skill: str
    evidence_chunk_ids: list[str] = field(default_factory=list)
    status: str = "pending"


def build_question_plan(
    config: GenerationConfig,
    topics: list[str],
    count: int,
    topic_titles: dict[str, str] | None = None,
) -> list[QuestionPlanItem]:
    """Build deterministic question slots from generation weights."""
    if count < 0:
        raise ValueError("count must not be negative")
    if not topics or count == 0:
        return []

    topic_titles = topic_titles or {}
    topic_keys = [str(topic) for topic in topics]
    topic_sequence = _spread_counts(
        allocate_weighted_counts(config.normalized_topic_weights(topic_keys), count)
    )
    type_sequence = _spread_counts(
        allocate_weighted_counts(config.normalized_type_weights(), count)
    )
    difficulty_sequence = _spread_counts(
        allocate_weighted_counts(config.normalized_difficulty_weights(), count)
    )
    skill_sequence = _spread_counts(_skill_counts(config.template, count))

    return [
        QuestionPlanItem(
            plan_id=f"plan-{index + 1:03d}",
            topic_id=topic_sequence[index],
            topic_title=topic_titles.get(topic_sequence[index], topic_sequence[index]),
            question_type=type_sequence[index],
            difficulty=difficulty_sequence[index],
            target_skill=skill_sequence[index],
        )
        for index in range(count)
    ]


def summarize_plan_items(
    items: list[QuestionPlanItem],
) -> dict[str, dict[tuple[str, str, str], int]]:
    """Group plan items by topic and question shape for preview/shortfall text."""
    summary: dict[str, dict[tuple[str, str, str], int]] = {}
    for item in items:
        shape = (item.question_type, item.difficulty, item.target_skill)
        topic_summary = summary.setdefault(item.topic_id, {})
        topic_summary[shape] = topic_summary.get(shape, 0) + 1
    return summary


def _skill_counts(template: str, count: int) -> dict[str, int]:
    weights = SKILL_WEIGHT_DEFAULTS.get(template, SKILL_WEIGHT_DEFAULTS["quick_review"])
    return allocate_weighted_counts(weights, count)


def _spread_counts(counts: dict[str, int]) -> list[str]:
    source = {key: max(0, int(value)) for key, value in counts.items()}
    remaining = dict(source)
    order = list(source)
    total = sum(source.values())
    assigned = {key: 0 for key in order}
    sequence: list[str] = []
    for slot in range(total):
        candidates = [key for key in order if remaining[key] > 0]
        ranked = sorted(
            candidates,
            key=lambda key: (
                -(source[key] * (slot + 1) / total - assigned[key]),
                -source[key],
                order.index(key),
            ),
        )
        key = ranked[0]
        sequence.append(key)
        assigned[key] += 1
        remaining[key] -= 1
    return sequence
