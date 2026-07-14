"""Batch question generator using QThread for non-blocking AI generation."""
from utils.logger import debug, warning, error

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from ai.llm_client import LLMClient
from ai.generation_batch_scheduler import GenerationBatchScheduler
from ai.generation_candidate_processor import GenerationCandidateProcessor
from ai.generation_config import GenerationConfig, allocate_weighted_counts
from ai.generation_quota_tracker import GenerationQuotaTracker
from ai.generation_result_accumulator import GenerationResultAccumulator
from ai.generation_source_resolver import GenerationSourceResolver
from ai.prompt_templates import PromptBuilder
from ai.question_generation_service import QuestionGenerationService
from ai.question_plan import QuestionPlanItem
from core.app_errors import AppError
from core.course_index import retrieve_course_context, retrieve_course_source_refs
from utils.constants import topic_value


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
        self._cached_source_refs: list[dict] = []
        self._cached_source_refs_by_topic: dict[str, list[dict]] = {}
        self._source_resolver = GenerationSourceResolver()
        self._runtime_instruction = ""
        self._runtime_instruction_lock = threading.Lock()

    def run(self):
        """Execute generation in background thread."""
        try:
            self.progress.emit("Building prompt...")

            # Cache context once — it doesn't change between batches
            course_context = self._build_course_context()
            scheduler = self._make_batch_scheduler()
            max_attempts = scheduler.max_attempts
            result_state = self._make_result_accumulator(max_attempts)
            quotas = self._make_quota_tracker()
            candidate_processor = self._make_candidate_processor(quotas)

            while (
                result_state.accepted_count < self.count
                and not self._cancelled.is_set()
                and result_state.attempts < max_attempts
            ):
                attempt = result_state.start_attempt()
                remaining = self.count - result_state.accepted_count
                batch_plan = scheduler.plan_next(remaining)
                candidate_count = batch_plan.candidate_count
                plan_summary = quotas.pending_plan_summary(candidate_count)
                self.progress.emit(
                    f"Generating question {result_state.accepted_count + 1}/{self.count}... "
                    f"({self.count} questions total; "
                    f"attempt {attempt}/{max_attempts}; "
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
                    if scheduler.recover_from_failure(detail, candidate_count):
                        self.progress.emit(
                            "AI response looked truncated. Retrying with a smaller batch..."
                        )
                        continue
                    if scheduler.looks_like_json_truncation(detail):
                        self.error.emit(scheduler.truncation_error(detail))
                        return
                    self.error.emit(detail)
                    return
                scheduler.record_success()
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
                        result_state.reject(outcome.rejection_reason)
                        detail = f" ({outcome.detail})" if outcome.detail else ""
                        debug(
                            "Skipping generated question: "
                            f"{outcome.rejection_reason}{detail}"
                        )

                result_state.accept(batch_questions)
                if batch_questions:
                    self.question_ready.emit(batch_questions)
                self.progress.emit(
                    f"Accepted {len(batch_questions)} question(s), rejected {rejected}. "
                    f"Total accepted: {result_state.accepted_count}/{self.count}"
                )

            if self._cancelled.is_set():
                if result_state.questions:
                    report = result_state.build_report(
                        status="cancelled",
                        quotas=quotas,
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
                    self.partial_done.emit(result_state.questions, report)
                return

            if result_state.accepted_count != self.count:
                if scheduler.last_truncation_detail:
                    self.error.emit(
                        scheduler.truncation_error(scheduler.last_truncation_detail)
                    )
                    return
                shortfall = quotas.shortfall_error(
                    result_state.accepted_count,
                    self.count,
                )
                if result_state.questions:
                    report = result_state.build_report(
                        status="partial",
                        quotas=quotas,
                        error=shortfall,
                    )
                    self.progress.emit(report.summary_text("en"))
                    self.partial_done.emit(result_state.questions, report)
                else:
                    self.error.emit(shortfall)
                return
            self.batch_done.emit(result_state.questions)

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

    def _make_result_accumulator(
        self,
        max_attempts: int,
    ) -> GenerationResultAccumulator:
        return GenerationResultAccumulator(
            self.count,
            max_attempts=max_attempts,
            template=self.generation_config.template,
        )

    def _make_batch_scheduler(self) -> GenerationBatchScheduler:
        return GenerationBatchScheduler(self.count)

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
