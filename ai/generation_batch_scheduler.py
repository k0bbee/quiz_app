"""Pure batch sizing and truncated-JSON recovery for question generation."""

from __future__ import annotations

from dataclasses import dataclass

from core.app_errors import AppError


ACCEPT_TARGET_BATCH_SIZE = 1
MAX_CANDIDATE_BATCH_SIZE = 4
JSON_RECOVERY_BATCH_SIZE = 3


@dataclass(frozen=True)
class GenerationBatchPlan:
    """Sizes for one generation request and its accepted result target."""

    accept_target: int
    candidate_count: int


class GenerationBatchScheduler:
    """Plan bounded requests and progressively recover from truncated JSON."""

    def __init__(self, requested_count: int):
        self.requested_count = max(0, int(requested_count))
        self.max_attempts = max(
            3,
            (self.requested_count // ACCEPT_TARGET_BATCH_SIZE + 1) * 3,
        )
        self._candidate_batch_limit: int | None = None
        self.last_truncation_detail = ""

    def plan_next(self, remaining: int) -> GenerationBatchPlan:
        accept_target = min(ACCEPT_TARGET_BATCH_SIZE, max(0, int(remaining)))
        if self._candidate_batch_limit is not None:
            accept_target = min(accept_target, self._candidate_batch_limit)
        if accept_target <= 0:
            return GenerationBatchPlan(0, 0)

        candidate_count = min(
            MAX_CANDIDATE_BATCH_SIZE,
            accept_target + 3,
        )
        if self._candidate_batch_limit is not None:
            candidate_count = min(candidate_count, self._candidate_batch_limit)
        return GenerationBatchPlan(accept_target, candidate_count)

    def recover_from_failure(self, detail: str, candidate_count: int) -> bool:
        """Reduce the next request only for likely truncated JSON responses."""
        if not self.looks_like_json_truncation(detail) or candidate_count <= 1:
            return False

        next_limit = max(
            1,
            min(JSON_RECOVERY_BATCH_SIZE, int(candidate_count) // 2),
        )
        if (
            self._candidate_batch_limit is not None
            and next_limit >= self._candidate_batch_limit
        ):
            next_limit = self._candidate_batch_limit - 1
        if next_limit < 1:
            return False

        self._candidate_batch_limit = next_limit
        self.last_truncation_detail = str(detail or "")
        return True

    def record_success(self) -> None:
        self._candidate_batch_limit = None
        self.last_truncation_detail = ""

    @staticmethod
    def looks_like_json_truncation(detail: str) -> bool:
        normalized = str(detail or "").lower()
        return (
            "json parse error" in normalized
            and (
                "unterminated string" in normalized
                or "expecting value" in normalized
                or "expecting ',' delimiter" in normalized
            )
        )

    @staticmethod
    def truncation_error(detail: str) -> AppError:
        return AppError(
            code="GEN-AI-JSON-001",
            severity="error",
            title_zh="AI 输出解析失败",
            title_en="AI output parse failed",
            message_zh="AI 返回的题目 JSON 可能输出过长或被截断，程序无法安全解析。",
            message_en="The AI returned quiz JSON that appears too long or truncated, so it could not be parsed safely.",
            action_zh="请减少题目数量，缩小知识点/题型覆盖范围，或换用支持更大输出上限的模型后重试。",
            action_en="Reduce the question count, narrow topic/type coverage, or retry with a model/provider that supports a larger output limit.",
            technical_detail=str(detail or ""),
        )
