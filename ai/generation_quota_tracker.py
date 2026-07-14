"""Pure-Python quota and plan-slot state for question generation."""

from __future__ import annotations

from dataclasses import replace

from ai.generation_config import (
    DIFFICULTY_DEFAULTS,
    QUESTION_TYPE_DEFAULTS,
    GenerationConfig,
    allocate_weighted_counts,
)
from ai.question_plan import QuestionPlanItem, build_question_plan
from core.app_errors import AppError
from utils.constants import topic_label, topic_value


def _count_plan_item_values(values, known_keys=None) -> dict[str, int]:
    counts: dict[str, int] = {
        str(key): 0
        for key in (known_keys or [])
        if str(key or "").strip()
    }
    for value in values:
        key = str(value or "").strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


class GenerationQuotaTracker:
    """Track exact marginal quotas and item-level generation plan slots."""

    def __init__(
        self,
        config: GenerationConfig,
        topics: list,
        count: int,
        evidence_refs_by_topic: dict[str, list[dict]] | None = None,
        question_plan_items: list[QuestionPlanItem] | None = None,
    ):
        self.template = config.template
        self.evidence_refs_by_topic = evidence_refs_by_topic or {}
        topic_keys = [topic_value(topic) for topic in topics]
        if question_plan_items is None:
            self.remaining_types = allocate_weighted_counts(
                config.normalized_type_weights(), count
            )
            self.remaining_difficulties = allocate_weighted_counts(
                config.normalized_difficulty_weights(), count
            )
            self.remaining_topics = allocate_weighted_counts(
                config.normalized_topic_weights(topic_keys), count
            )
            topic_titles = {topic_value(topic): topic_label(topic) for topic in topics}
            plan_items = build_question_plan(config, topic_keys, count, topic_titles)
        else:
            plan_items = list(question_plan_items)
            self.remaining_types = _count_plan_item_values(
                (item.question_type for item in plan_items),
                list(QUESTION_TYPE_DEFAULTS) + list(config.question_type_weights),
            )
            self.remaining_difficulties = _count_plan_item_values(
                (item.difficulty for item in plan_items),
                list(DIFFICULTY_DEFAULTS) + list(config.difficulty_weights),
            )
            self.remaining_topics = _count_plan_item_values(
                item.topic_id for item in plan_items
            )
        self.remaining_plan_items = self._bind_plan_evidence(plan_items)

    def rejection_reason(
        self,
        qtype: str,
        difficulty: str,
        topic: str,
        plan_id: str | None = None,
    ) -> str:
        if plan_id:
            plan_item = self._plan_item_by_id(plan_id)
            if plan_item is None:
                return f"unknown plan slot {plan_id}"
            if not self._plan_item_matches(plan_item, qtype, difficulty, topic):
                return (
                    f"plan slot {plan_id} mismatch for "
                    f"topic {topic}, question type {qtype}, difficulty {difficulty}"
                )
        filled = []
        if self.remaining_types.get(qtype, 0) <= 0:
            filled.append(f"question type {qtype}")
        if self.remaining_difficulties.get(difficulty, 0) <= 0:
            filled.append(f"difficulty {difficulty}")
        if self.remaining_topics.get(topic, 0) <= 0:
            filled.append(f"topic {topic}")
        if filled:
            return f"quota already filled for {', '.join(filled)}"
        if self._matching_plan_item_index(qtype, difficulty, topic) is None:
            return (
                "no remaining plan slot for "
                f"topic {topic}, question type {qtype}, difficulty {difficulty}"
            )
        return ""

    def accept(
        self,
        qtype: str,
        difficulty: str,
        topic: str,
        plan_id: str | None = None,
    ) -> tuple[QuestionPlanItem | None, str]:
        reason = self.rejection_reason(qtype, difficulty, topic)
        if reason:
            raise ValueError(reason)
        self.remaining_types[qtype] -= 1
        self.remaining_difficulties[difficulty] -= 1
        self.remaining_topics[topic] -= 1
        return self._mark_plan_item_accepted(qtype, difficulty, topic, plan_id)

    def remaining_config(self) -> GenerationConfig:
        return GenerationConfig(
            question_type_weights=dict(self.remaining_types),
            difficulty_weights=dict(self.remaining_difficulties),
            topic_weights=dict(self.remaining_topics),
            template=self.template,
        )

    def shortfall_message(self, accepted: int, requested: int) -> str:
        groups = []
        for label, values in self.missing_quotas().items():
            missing = ", ".join(
                f"{key}: {value}" for key, value in values.items() if value > 0
            )
            if missing:
                groups.append(f"{label} [{missing}]")
        detail = "; ".join(groups) or "unknown quota"
        return (
            "Generation stopped before satisfying the requested distribution "
            f"({accepted}/{requested} accepted). Missing: {detail}. "
            "Try again, reduce the requested count, or relax the weights."
        )

    def shortfall_error(self, accepted: int, requested: int) -> AppError:
        return AppError(
            code="GEN-QUOTA-001",
            severity="error",
            title_zh="生成未完成",
            title_en="Generation incomplete",
            message_zh=f"已接受 {accepted}/{requested} 道题，但仍有部分题型、难度或知识点没有满足当前分布设置。",
            message_en=f"Accepted {accepted}/{requested} questions, but some question type, difficulty, or topic quotas are still unmet.",
            action_zh="请重试，或减少题目数量，或放宽题型/难度/知识点权重。",
            action_en="Try again, reduce the requested count, or relax the question type, difficulty, or topic weights.",
            technical_detail=self.shortfall_message(accepted, requested),
        )

    def missing_quotas(self) -> dict[str, dict[str, int]]:
        return {
            "question_types": {
                key: value for key, value in self.remaining_types.items() if value > 0
            },
            "difficulties": {
                key: value for key, value in self.remaining_difficulties.items() if value > 0
            },
            "topics": {
                key: value for key, value in self.remaining_topics.items() if value > 0
            },
        }

    def missing_plan_items(self) -> list[QuestionPlanItem]:
        return list(self.remaining_plan_items)

    def pending_plan_items(self, limit: int) -> list[QuestionPlanItem]:
        return list(self.remaining_plan_items[: max(0, int(limit))])

    def pending_plan_summary(self, limit: int) -> str:
        pending = self.pending_plan_items(limit)
        if not pending:
            return ""
        topic_titles = []
        for item in pending:
            title = item.topic_title or item.topic_id
            if title not in topic_titles:
                topic_titles.append(title)
        return f"{len(pending)} planned slot(s) across {', '.join(topic_titles[:3])}"

    def evidence_refs_for_item(self, item: QuestionPlanItem | None) -> list[dict]:
        if item is None:
            return []
        refs_by_id = {
            str(ref.get("chunk_id") or ""): ref
            for ref in self.evidence_refs_by_topic.get(item.topic_id, [])
            if isinstance(ref, dict)
        }
        return [
            dict(refs_by_id[chunk_id])
            for chunk_id in item.evidence_chunk_ids
            if chunk_id in refs_by_id
        ]

    def _bind_plan_evidence(self, items: list[QuestionPlanItem]) -> list[QuestionPlanItem]:
        bound = []
        for item in items:
            refs = self.evidence_refs_by_topic.get(item.topic_id, [])
            evidence_chunk_ids = [
                str(ref.get("chunk_id") or "")
                for ref in refs
                if isinstance(ref, dict) and str(ref.get("chunk_id") or "").strip()
            ]
            bound.append(
                replace(item, evidence_chunk_ids=evidence_chunk_ids)
                if evidence_chunk_ids else item
            )
        return bound

    def _mark_plan_item_accepted(
        self,
        qtype: str,
        difficulty: str,
        topic: str,
        plan_id: str | None = None,
    ) -> tuple[QuestionPlanItem | None, str]:
        if not self.remaining_plan_items:
            return None, ""
        if plan_id:
            exact_plan_index = self._plan_item_id_index(plan_id)
            if exact_plan_index is not None:
                return self.remaining_plan_items.pop(exact_plan_index), "matched_by_plan_id"
        exact_index = self._matching_plan_item_index(qtype, difficulty, topic)
        if exact_index is not None:
            return self.remaining_plan_items.pop(exact_index), "matched_by_shape"
        return None, ""

    def _matching_plan_item_index(self, qtype: str, difficulty: str, topic: str) -> int | None:
        return next(
            (
                index
                for index, item in enumerate(self.remaining_plan_items)
                if item.question_type == qtype
                and item.difficulty == difficulty
                and item.topic_id == topic
            ),
            None,
        )

    def _plan_item_id_index(self, plan_id: str) -> int | None:
        return next(
            (
                index
                for index, item in enumerate(self.remaining_plan_items)
                if item.plan_id == plan_id
            ),
            None,
        )

    def _plan_item_by_id(self, plan_id: str) -> QuestionPlanItem | None:
        index = self._plan_item_id_index(plan_id)
        return None if index is None else self.remaining_plan_items[index]

    @staticmethod
    def _plan_item_matches(
        item: QuestionPlanItem,
        qtype: str,
        difficulty: str,
        topic: str,
    ) -> bool:
        return (
            item.question_type == qtype
            and item.difficulty == difficulty
            and item.topic_id == topic
        )
