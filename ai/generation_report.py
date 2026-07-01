"""Structured reports for AI question generation runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from ai.question_plan import QuestionPlanItem, summarize_plan_items
from core.app_errors import AppError


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
            missing = self._missing_summary()
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
        missing = self._missing_summary()
        if missing:
            lines.append(f"Missing: {missing}")
        failed = self._failed_plan_summary(lang)
        if failed:
            lines.append(f"Failed combinations: {failed}")
        if self.error and self.error.action_en:
            lines.append(f"Suggestion: {self.error.action_en}")
        return "; ".join(lines)

    def _missing_summary(self) -> str:
        groups = []
        for group_name, values in self.missing_quotas.items():
            missing = ", ".join(
                f"{key}: {count}"
                for key, count in values.items()
                if count > 0
            )
            if missing:
                groups.append(f"{group_name} [{missing}]")
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
                if lang == "zh":
                    groups.append(
                        f"{topic_title} {difficulty} / {question_type} / {skill}: {count}"
                    )
                else:
                    groups.append(
                        f"{topic_title} {difficulty} / {question_type} / {skill}: {count}"
                    )
        return "; ".join(groups)
