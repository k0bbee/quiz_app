"""UI-independent orchestration for one question generation run."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from ai.generation_events import (
    CompletedEvent,
    FailedEvent,
    GenerationEvent,
    PartialResultEvent,
    ProgressEvent,
    QuestionsReadyEvent,
)
from core.app_errors import AppError
from utils.logger import debug


class GenerationRunner:
    """Coordinate generation services and yield transport-neutral events."""

    def __init__(
        self,
        *,
        requested_count: int,
        scheduler,
        result_state,
        quotas,
        candidate_processor,
        request_service,
        is_cancelled: Callable[[], bool],
        runtime_instruction: Callable[[], str],
    ):
        self.requested_count = int(requested_count)
        self.scheduler = scheduler
        self.result_state = result_state
        self.quotas = quotas
        self.candidate_processor = candidate_processor
        self.request_service = request_service
        self.is_cancelled = is_cancelled
        self.runtime_instruction = runtime_instruction

    def events(self) -> Iterator[GenerationEvent]:
        """Run generation synchronously and yield progress/result events."""
        while (
            self.result_state.accepted_count < self.requested_count
            and not self.is_cancelled()
            and self.result_state.attempts < self.scheduler.max_attempts
        ):
            attempt = self.result_state.start_attempt()
            remaining = self.requested_count - self.result_state.accepted_count
            batch_plan = self.scheduler.plan_next(remaining)
            candidate_count = batch_plan.candidate_count

            yield ProgressEvent(
                f"Generating question {self.result_state.accepted_count + 1}/"
                f"{self.requested_count}... "
                f"({self.requested_count} questions total; "
                f"attempt {attempt}/{self.scheduler.max_attempts}; "
                f"requesting {candidate_count} candidate"
                f"{'s' if candidate_count != 1 else ''})"
            )
            plan_summary = self.quotas.pending_plan_summary(candidate_count)
            if plan_summary:
                yield ProgressEvent(f"Filling plan slots: {plan_summary}")

            request_result = self.request_service.request(
                candidate_count,
                self.quotas.remaining_config(),
                self.quotas.pending_plan_items(candidate_count),
                self.runtime_instruction(),
            )
            if not request_result.succeeded:
                detail = request_result.error
                if self.scheduler.recover_from_failure(detail, candidate_count):
                    yield ProgressEvent(
                        "AI response looked truncated. Retrying with a smaller batch..."
                    )
                    continue
                if self.scheduler.looks_like_json_truncation(detail):
                    yield FailedEvent(self.scheduler.truncation_error(detail))
                else:
                    yield FailedEvent(detail)
                return

            self.scheduler.record_success()
            batch_questions = []
            rejected = 0
            for raw_question in request_result.questions:
                if self.is_cancelled() or len(batch_questions) >= batch_plan.accept_target:
                    break
                outcome = self.candidate_processor.process(raw_question)
                if outcome.accepted:
                    batch_questions.append(outcome.question)
                    continue
                rejected += 1
                self.result_state.reject(outcome.rejection_reason)
                detail = f" ({outcome.detail})" if outcome.detail else ""
                debug(
                    "Skipping generated question: "
                    f"{outcome.rejection_reason}{detail}"
                )

            self.result_state.accept(batch_questions)
            if batch_questions:
                yield QuestionsReadyEvent.from_questions(batch_questions)
            yield ProgressEvent(
                f"Accepted {len(batch_questions)} question(s), rejected {rejected}. "
                f"Total accepted: {self.result_state.accepted_count}/"
                f"{self.requested_count}"
            )

        yield from self._terminal_events()

    def _terminal_events(self) -> Iterator[GenerationEvent]:
        if self.is_cancelled():
            if self.result_state.questions:
                report = self.result_state.build_report(
                    status="cancelled",
                    quotas=self.quotas,
                    error=_cancelled_error(),
                )
                yield ProgressEvent(report.summary_text("en"))
                yield PartialResultEvent.from_questions(
                    self.result_state.questions,
                    report,
                )
            return

        if self.result_state.accepted_count != self.requested_count:
            if self.scheduler.last_truncation_detail:
                yield FailedEvent(
                    self.scheduler.truncation_error(
                        self.scheduler.last_truncation_detail
                    )
                )
                return
            shortfall = self.quotas.shortfall_error(
                self.result_state.accepted_count,
                self.requested_count,
            )
            if self.result_state.questions:
                report = self.result_state.build_report(
                    status="partial",
                    quotas=self.quotas,
                    error=shortfall,
                )
                yield ProgressEvent(report.summary_text("en"))
                yield PartialResultEvent.from_questions(
                    self.result_state.questions,
                    report,
                )
            else:
                yield FailedEvent(shortfall)
            return

        yield CompletedEvent.from_questions(self.result_state.questions)


def _cancelled_error() -> AppError:
    return AppError(
        code="GEN-CANCEL-001",
        severity="info",
        title_zh="生成已取消",
        title_en="Generation cancelled",
        message_zh="已保留取消前生成的题目。",
        message_en="Questions generated before cancellation were preserved.",
        action_zh="可先审核并保存已生成题目，之后再继续补齐。",
        action_en="Review and save the generated questions now, then continue later.",
    )
