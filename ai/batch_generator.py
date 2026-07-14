"""Batch question generator using QThread for non-blocking AI generation."""
from utils.logger import debug, warning, error

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from ai.llm_client import LLMClient
from ai.generation_candidate_processor import GenerationCandidateProcessor
from ai.generation_config import GenerationConfig, allocate_weighted_counts
from ai.generation_quota_tracker import GenerationQuotaTracker
from ai.generation_report import GenerationReport
from ai.generation_source_resolver import GenerationSourceResolver
from ai.prompt_templates import PromptBuilder
from ai.question_generation_service import QuestionGenerationService
from ai.question_plan import QuestionPlanItem
from core.app_errors import AppError
from core.course_index import retrieve_course_context, retrieve_course_source_refs
from utils.constants import topic_value


ACCEPT_TARGET_BATCH_SIZE = 1
MAX_CANDIDATE_BATCH_SIZE = 4
JSON_RECOVERY_BATCH_SIZE = 3
GENERATION_CONTEXT_MAX_CHARS = 12000


class GenerationWorker(QThread):
    """Background worker for generating questions via LLM."""

    progress = pyqtSignal(str)  # Status message
    question_ready = pyqtSignal(list)  # Newly accepted Question objects for live preview
    batch_done = pyqtSignal(list)  # List of Question objects
    partial_done = pyqtSignal(list, object)  # Accepted questions plus shortfall reason
    error = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, llm_client: LLMClient, course_content: str,
                 topics: list, count: int, difficulty: str, course_project=None,
                 generation_config: GenerationConfig | None = None,
                 question_plan_items: list[QuestionPlanItem] | None = None):
        super().__init__()
        self.client = llm_client
        self.course_content = course_content
        self.topics = topics
        self.count = count
        self.difficulty = difficulty
        self.course_project = course_project
        self.generation_config = generation_config or GenerationConfig()
        self.question_plan_items = list(question_plan_items or [])
        self._generation_service = QuestionGenerationService(self.topics)
        self._cancelled = threading.Event()
        self._cached_context: str | None = None
        self._candidate_batch_limit: int | None = None
        self._last_json_truncation_detail: str = ""
        self._cached_source_refs: list[dict] = []
        self._cached_source_refs_by_topic: dict[str, list[dict]] = {}
        self._source_resolver = GenerationSourceResolver()
        self._runtime_instruction = ""
        self._runtime_instruction_lock = threading.Lock()

    def run(self):
        """Execute generation in background thread."""
        try:
            self.progress.emit("Building prompt...")

            all_questions = []
            total_rejected = 0
            rejection_reasons: dict[str, int] = {}
            attempts = 0
            # Cache context once — it doesn't change between batches
            course_context = self._build_course_context()
            max_attempts = max(3, (self.count // ACCEPT_TARGET_BATCH_SIZE + 1) * 3)
            quotas = self._make_quota_tracker()
            candidate_processor = self._make_candidate_processor(quotas)

            while len(all_questions) < self.count and not self._cancelled.is_set() and attempts < max_attempts:
                attempts += 1
                remaining = self.count - len(all_questions)
                batch_count = self._accept_target_count(remaining)
                candidate_count = self._candidate_batch_count(batch_count)
                plan_summary = quotas.pending_plan_summary(candidate_count)
                self.progress.emit(
                    f"Generating question {len(all_questions) + 1}/{self.count}... "
                    f"({self.count} questions total; "
                    f"attempt {attempts}/{max_attempts}; "
                    f"requesting {candidate_count} candidate"
                    f"{'s' if candidate_count != 1 else ''})"
                )
                if plan_summary:
                    self.progress.emit(f"Filling plan slots: {plan_summary}")

                messages = PromptBuilder.build_messages(
                    course_context,
                    self.topics,
                    candidate_count,
                    self.difficulty,
                    quotas.remaining_config(),
                    topic_keywords=self._topic_keywords(),
                    question_plan_items=quotas.pending_plan_items(candidate_count),
                    runtime_instruction=self.runtime_instruction(),
                )

                data = self.client.generate_with_json(messages, max_retries=3)

                if data is None:
                    detail = getattr(self.client, "last_error", "") or "Check your API key, model, provider, and network connection."
                    if self._reduce_batch_after_json_truncation(detail, candidate_count):
                        self._last_json_truncation_detail = detail
                        self.progress.emit(
                            "AI response looked truncated. Retrying with a smaller batch..."
                        )
                        continue
                    if self._looks_like_json_truncation(detail):
                        self.error.emit(self._json_truncation_error(detail))
                        return
                    self.error.emit(detail)
                    return
                self._last_json_truncation_detail = ""
                self._candidate_batch_limit = None
                if not isinstance(data, dict):
                    self.error.emit("AI response JSON must be an object with a questions list.")
                    return

                # Parse questions from response
                raw_questions = data.get("questions", [])
                if not raw_questions:
                    self.error.emit("No questions found in the API response.")
                    return

                batch_questions = []
                rejected = 0
                for qdata in raw_questions:
                    if self._cancelled.is_set():
                        break
                    outcome = candidate_processor.process(qdata)
                    if outcome.accepted:
                        batch_questions.append(outcome.question)
                    else:
                        rejected += 1
                        _record_rejection(rejection_reasons, outcome.rejection_reason)
                        detail = f" ({outcome.detail})" if outcome.detail else ""
                        debug(
                            "Skipping generated question: "
                            f"{outcome.rejection_reason}{detail}"
                        )

                all_questions.extend(batch_questions)
                if batch_questions:
                    self.question_ready.emit(batch_questions)
                total_rejected += rejected
                self.progress.emit(
                    f"Accepted {len(batch_questions)} question(s), rejected {rejected}. "
                    f"Total accepted: {len(all_questions)}/{self.count}"
                )

            if self._cancelled.is_set():
                if all_questions:
                    report = GenerationReport(
                        requested_count=self.count,
                        accepted_count=len(all_questions),
                        rejected_count=total_rejected,
                        attempts=attempts,
                        max_attempts=max_attempts,
                        status="cancelled",
                        missing_quotas=quotas.missing_quotas(),
                        failed_plan_items=quotas.missing_plan_items(),
                        rejection_reasons=dict(rejection_reasons),
                        template=self.generation_config.template,
                        error=AppError(
                            code="GEN-CANCEL-001",
                            severity="info",
                            title_zh="生成已取消",
                            title_en="Generation cancelled",
                            message_zh="已保留取消前生成的题目。",
                            message_en="Questions generated before cancellation were preserved.",
                            action_zh="可先审核并保存已生成题目，之后再继续补齐。",
                            action_en="Review and save the generated questions now, then continue later.",
                        ),
                    )
                    self.progress.emit(report.summary_text("en"))
                    self.partial_done.emit(all_questions, report)
                return

            if len(all_questions) != self.count:
                if self._last_json_truncation_detail:
                    self.error.emit(self._json_truncation_error(self._last_json_truncation_detail))
                    return
                shortfall = quotas.shortfall_error(len(all_questions), self.count)
                if all_questions:
                    report = GenerationReport(
                        requested_count=self.count,
                        accepted_count=len(all_questions),
                        rejected_count=total_rejected,
                        attempts=attempts,
                        max_attempts=max_attempts,
                        status="partial",
                        missing_quotas=quotas.missing_quotas(),
                        failed_plan_items=quotas.missing_plan_items(),
                        rejection_reasons=dict(rejection_reasons),
                        template=self.generation_config.template,
                        error=shortfall,
                    )
                    self.progress.emit(report.summary_text("en"))
                    self.partial_done.emit(all_questions, report)
                else:
                    self.error.emit(shortfall)
                return
            self.batch_done.emit(all_questions)

        except Exception as e:
            self.error.emit(f"Unexpected error: {str(e)}")
        finally:
            self.finished.emit()

    def cancel(self):
        """Signal the worker to stop."""
        self._cancelled.set()

    def set_runtime_instruction(self, instruction: str) -> None:
        """Apply a user adjustment to future LLM requests."""
        clean = " ".join(str(instruction or "").split())
        with self._runtime_instruction_lock:
            self._runtime_instruction = clean

    def runtime_instruction(self) -> str:
        """Return the current user adjustment for prompt construction."""
        with self._runtime_instruction_lock:
            return self._runtime_instruction

    def _make_quota_tracker(self) -> GenerationQuotaTracker:
        return GenerationQuotaTracker(
            self.generation_config,
            self.topics,
            self.count,
            self._cached_source_refs_by_topic,
            self.question_plan_items or None,
        )

    def _make_candidate_processor(
        self,
        quotas: GenerationQuotaTracker,
    ) -> GenerationCandidateProcessor:
        resolver = GenerationSourceResolver(
            self._cached_source_refs,
            self._cached_source_refs_by_topic,
        )
        self._source_resolver = resolver
        return GenerationCandidateProcessor(
            self._generation_service,
            quotas,
            resolver,
            ai_model=getattr(self.client, "model", ""),
            course_metadata=self._course_metadata(),
        )

    def _candidate_batch_count(self, accept_target: int) -> int:
        """Request extra candidates so strict quota filtering can recover from model drift.

        The UI/requested total remains self.count. This only enlarges the
        background candidate pool for one LLM call, keeping large generations
        chunked instead of making one huge request.
        """
        if accept_target <= 0:
            return 0
        count = min(MAX_CANDIDATE_BATCH_SIZE, accept_target + 3)
        if self._candidate_batch_limit is not None:
            count = min(count, self._candidate_batch_limit)
        return count

    def _accept_target_count(self, remaining: int) -> int:
        count = min(ACCEPT_TARGET_BATCH_SIZE, remaining)
        if self._candidate_batch_limit is not None:
            count = min(count, self._candidate_batch_limit)
        return count

    def _reduce_batch_after_json_truncation(self, detail: str, candidate_count: int) -> bool:
        """Recover from likely output-token truncation by asking for fewer questions.

        Authentication, network, and quota errors should still surface immediately.
        This recovery is deliberately limited to JSON parse failures that match an
        incomplete response shape.
        """
        if not self._looks_like_json_truncation(detail) or candidate_count <= 1:
            return False

        next_limit = max(1, min(JSON_RECOVERY_BATCH_SIZE, candidate_count // 2))
        if self._candidate_batch_limit is not None and next_limit >= self._candidate_batch_limit:
            next_limit = self._candidate_batch_limit - 1
        if next_limit < 1:
            return False
        self._candidate_batch_limit = next_limit
        return True

    @staticmethod
    def _looks_like_json_truncation(detail: str) -> bool:
        normalized = detail.lower()
        return (
            "json parse error" in normalized
            and (
                "unterminated string" in normalized
                or "expecting value" in normalized
                or "expecting ',' delimiter" in normalized
            )
        )

    @staticmethod
    def _json_truncation_error(detail: str) -> AppError:
        return AppError(
            code="GEN-AI-JSON-001",
            severity="error",
            title_zh="AI 输出解析失败",
            title_en="AI output parse failed",
            message_zh="AI 返回的题目 JSON 可能输出过长或被截断，程序无法安全解析。",
            message_en="The AI returned quiz JSON that appears too long or truncated, so it could not be parsed safely.",
            action_zh="请减少题目数量，缩小知识点/题型覆盖范围，或换用支持更大输出上限的模型后重试。",
            action_en="Reduce the question count, narrow topic/type coverage, or retry with a model/provider that supports a larger output limit.",
            technical_detail=detail,
        )

    def _build_course_context(self) -> str:
        """Retrieve the best context for currently selected topics."""
        if self.course_project is not None:
            topic_keys = [topic_value(t) for t in self.topics]
            self._cached_source_refs = retrieve_course_source_refs(
                self.course_project,
                topic_keys,
            )
            self._cached_source_refs_by_topic = {
                topic_key: retrieve_course_source_refs(
                    self.course_project,
                    [topic_key],
                )
                for topic_key in topic_keys
            }
            self._source_resolver = GenerationSourceResolver(
                self._cached_source_refs,
                self._cached_source_refs_by_topic,
            )
            return retrieve_course_context(
                self.course_project,
                topic_keys,
                max_chars=GENERATION_CONTEXT_MAX_CHARS,
            )
        self._cached_source_refs_by_topic = {}
        self._source_resolver = GenerationSourceResolver()
        return self.course_content

    def _question_source_refs(
        self,
        qdata: dict,
        plan_item: QuestionPlanItem | None = None,
        quotas: GenerationQuotaTracker | None = None,
    ) -> tuple[list[dict], str, list[str]]:
        """Return sanitized model source refs, falling back to retrieved evidence."""
        resolver = self._source_resolver
        if isinstance(resolver, GenerationSourceResolver):
            resolver = GenerationSourceResolver(
                self._cached_source_refs,
                self._cached_source_refs_by_topic,
            )
            self._source_resolver = resolver
        plan_refs = quotas.evidence_refs_for_item(plan_item) if quotas is not None else []
        return resolver.resolve(qdata, plan_item=plan_item, plan_refs=plan_refs)

    def _course_metadata(self) -> dict:
        if self.course_project is None:
            return {}
        return {
            "course_id": getattr(self.course_project, "course_id", ""),
            "course_title": getattr(self.course_project, "title", ""),
            "course_updated_at": getattr(self.course_project, "updated_at", ""),
        }

    def _topic_keywords(self) -> dict[str, list[str]]:
        if self.course_project is None:
            return {}
        keywords: dict[str, list[str]] = {}
        for topic in getattr(self.course_project, "topics", []) or []:
            key = topic_value(topic)
            if key:
                keywords[key] = list(getattr(topic, "keywords", []) or [])
        return keywords

    def _normalize_raw_question(self, qdata):
        return self._generation_service.normalize_raw_question(qdata)

    def _validate_raw_question(self, qdata: dict) -> tuple[bool, str]:
        """Validate raw model output before converting it to a Question."""
        return self._generation_service.validate_raw_question(qdata)

    def _normalize_topic(self, raw_topic):
        """Map model topic output to one of the selected topics."""
        return self._generation_service.normalize_topic(raw_topic)


def _record_rejection(reasons: dict[str, int], reason: str) -> None:
    key = _rejection_reason_key(reason)
    reasons[key] = reasons.get(key, 0) + 1


def _rejection_reason_key(reason: str) -> str:
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
