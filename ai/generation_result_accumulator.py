"""Pure state and report aggregation for a question generation run."""

from __future__ import annotations

from ai.generation_report import GenerationReport
from core.app_errors import AppError


class GenerationResultAccumulator:
    """Track attempts, accepted questions, and stable rejection summaries."""

    def __init__(
        self,
        requested_count: int,
        *,
        max_attempts: int,
        template: str = "",
    ):
        self.requested_count = int(requested_count)
        self.max_attempts = int(max_attempts)
        self.template = str(template or "")
        self.questions: list = []
        self.attempts = 0
        self.rejected_count = 0
        self.rejection_reasons: dict[str, int] = {}

    @property
    def accepted_count(self) -> int:
        return len(self.questions)

    def start_attempt(self) -> int:
        self.attempts += 1
        return self.attempts

    def accept(self, questions: list) -> None:
        self.questions.extend(questions)

    def reject(self, reason: str) -> None:
        self.rejected_count += 1
        key = normalize_rejection_reason(reason)
        self.rejection_reasons[key] = self.rejection_reasons.get(key, 0) + 1

    def build_report(
        self,
        *,
        status: str,
        quotas,
        error: AppError | None = None,
    ) -> GenerationReport:
        return GenerationReport(
            requested_count=self.requested_count,
            accepted_count=self.accepted_count,
            rejected_count=self.rejected_count,
            attempts=self.attempts,
            max_attempts=self.max_attempts,
            status=status,
            missing_quotas=quotas.missing_quotas(),
            failed_plan_items=quotas.missing_plan_items(),
            rejection_reasons=dict(self.rejection_reasons),
            template=self.template,
            error=error,
        )


def normalize_rejection_reason(reason: str) -> str:
    """Collapse detailed candidate failures into useful report categories."""
    normalized = str(reason or "").strip()
    lower = normalized.lower()
    if lower.startswith("quota already filled"):
        return "quota already filled"
    if lower.startswith("no remaining plan slot"):
        return "no remaining plan slot"
    if "not selected" in lower:
        return "topic not selected"
    if "missing" in lower or "weak" in lower:
        return "incomplete question content"
    if "unknown question type" in lower:
        return "unknown question type"
    if not normalized:
        return "unknown rejection"
    return normalized
