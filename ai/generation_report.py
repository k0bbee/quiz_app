"""Structured reports for AI question generation runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from ai.generation_config import DIFFICULTY_DEFAULTS, QUESTION_TYPE_DEFAULTS, GenerationConfig
from ai.question_plan import QuestionPlanItem, plan_value_label, summarize_plan_items
from core.app_errors import AppError


@dataclass(frozen=True)
class GenerationRetryPlan:
    """Focused follow-up request derived from failed generation slots."""

    count: int
    topics: list[str]
    plan_items: list[QuestionPlanItem]
    config: GenerationConfig


@dataclass(frozen=True)
class GenerationReport:
    """User-facing summary of a generation attempt."""

    requested_count: int
    accepted_count: int
    rejected_count: int = 0
    attempts: int = 0
    max_attempts: int = 0
    status: str = "complete"
    missing_quotas: dict[str, dict[str, int]] = field(default_factory=dict)
    failed_plan_items: list[QuestionPlanItem] = field(default_factory=list)
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    template: str = "quick_review"
    error: AppError | None = None

    @property
    def shortfall(self) -> int:
        """Return how many requested questions are still missing."""
        return max(0, self.requested_count - self.accepted_count)

    def summary_text(self, lang: str = "zh") -> str:
        """Return a compact localized report suitable for status labels."""
        if lang == "zh":
            lines = [
                f"已生成 {self.accepted_count}/{self.requested_count} 道题",
                f"未完成 {self.shortfall} 道",
            ]
            if self.rejected_count:
                lines.append(f"已拒绝候选 {self.rejected_count} 个")
            reasons = self._rejection_summary(lang)
            if reasons:
                lines.append(f"拒绝原因: {reasons}")
            missing = self._missing_summary(lang)
            if missing:
                lines.append(f"缺口: {missing}")
            failed = self._failed_plan_summary(lang)
            if failed:
                lines.append(f"失败组合: {failed}")
            if self.error and self.error.action_zh:
                lines.append(f"建议: {self.error.action_zh}")
            return "；".join(lines)

        lines = [
            f"Generated {self.accepted_count}/{self.requested_count} questions",
            f"Shortfall: {self.shortfall}",
        ]
        if self.rejected_count:
            lines.append(f"Rejected candidates: {self.rejected_count}")
        reasons = self._rejection_summary(lang)
        if reasons:
            lines.append(f"Rejected reasons: {reasons}")
        missing = self._missing_summary(lang)
        if missing:
            lines.append(f"Missing: {missing}")
        failed = self._failed_plan_summary(lang)
        if failed:
            lines.append(f"Failed combinations: {failed}")
        if self.error and self.error.action_en:
            lines.append(f"Suggestion: {self.error.action_en}")
        return "; ".join(lines)

    def retry_plan(self) -> GenerationRetryPlan:
        """Return a focused generation request for the remaining failed slots."""
        topics = _ordered_counts(item.topic_id for item in self.failed_plan_items)
        return GenerationRetryPlan(
            count=len(self.failed_plan_items),
            topics=list(topics),
            plan_items=list(self.failed_plan_items),
            config=GenerationConfig(
                question_type_weights=_exclusive_counts(
                    QUESTION_TYPE_DEFAULTS,
                    (item.question_type for item in self.failed_plan_items),
                ),
                difficulty_weights=_exclusive_counts(
                    DIFFICULTY_DEFAULTS,
                    (item.difficulty for item in self.failed_plan_items),
                ),
                topic_weights=dict(topics),
                template=self.template,
            ),
        )

    def _rejection_summary(self, lang: str) -> str:
        reason_labels = {
            "quota already filled": ("已满足配额", "Quota already filled"),
            "no remaining plan slot": ("没有剩余计划槽位", "No remaining plan slot"),
            "topic not selected": ("主题未选中", "Topic not selected"),
            "incomplete question content": ("题目内容不完整", "Incomplete question content"),
            "unknown question type": ("未知题型", "Unknown question type"),
            "unknown rejection": ("未知原因", "Unknown rejection"),
        }
        reasons = [
            (reason, count)
            for reason, count in self.rejection_reasons.items()
            if count > 0
        ]
        reasons.sort(key=lambda item: (-item[1], item[0]))
        rendered = []
        for reason, count in reasons[:3]:
            pair = reason_labels.get(reason)
            if pair is None:
                label = reason
            else:
                label = pair[0] if lang == "zh" else pair[1]
            rendered.append(f"{label}: {count}")
        return ", ".join(rendered)

    def _missing_summary(self, lang: str) -> str:
        group_labels = {
            "question_types": ("题型", "Question types"),
            "difficulties": ("难度", "Difficulties"),
            "topics": ("主题", "Topics"),
        }
        value_kinds = {
            "question_types": "question_type",
            "difficulties": "difficulty",
        }
        topic_titles = {
            item.topic_id: item.topic_title
            for item in self.failed_plan_items
            if item.topic_title
        }
        groups = []
        for group_name, values in self.missing_quotas.items():
            group_pair = group_labels.get(group_name, (group_name, group_name))
            group_label = group_pair[0] if lang == "zh" else group_pair[1]
            value_kind = value_kinds.get(group_name)
            missing_parts = []
            for key, count in values.items():
                if count <= 0:
                    continue
                if group_name == "topics":
                    label = topic_titles.get(str(key), str(key))
                else:
                    label = plan_value_label(key, value_kind, lang) if value_kind else key
                missing_parts.append(f"{label}: {count}")
            missing = ", ".join(missing_parts)
            if missing:
                groups.append(f"{group_label} [{missing}]")
        return "; ".join(groups)

    def _failed_plan_summary(self, lang: str) -> str:
        if not self.failed_plan_items:
            return ""
        topic_titles = {
            item.topic_id: item.topic_title or item.topic_id
            for item in self.failed_plan_items
        }
        groups = []
        for topic_id, values in summarize_plan_items(self.failed_plan_items).items():
            topic_title = topic_titles.get(topic_id, topic_id)
            for (question_type, difficulty, skill), count in values.items():
                if count <= 0:
                    continue
                groups.append(
                    f"{topic_title} "
                    f"{plan_value_label(difficulty, 'difficulty', lang)} / "
                    f"{plan_value_label(question_type, 'question_type', lang)} / "
                    f"{plan_value_label(skill, 'skill', lang)}: {count}"
                )
        return "; ".join(groups)


def _ordered_counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _exclusive_counts(known_weights: dict[str, int], values) -> dict[str, int]:
    counts = {key: 0 for key in known_weights}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts
