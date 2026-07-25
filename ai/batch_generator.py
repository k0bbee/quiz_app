"""Batch question generator using QThread for non-blocking AI generation."""

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from ai.llm_client import LLMClient
from ai.generation_batch_scheduler import GenerationBatchScheduler
from ai.generation_candidate_processor import GenerationCandidateProcessor
from ai.generation_config import GenerationConfig, allocate_weighted_counts
from ai.generation_events import (
    CompletedEvent,
    FailedEvent,
    PartialResultEvent,
    ProgressEvent,
    QuestionsReadyEvent,
)
from ai.generation_quota_tracker import GenerationQuotaTracker
from ai.generation_request_service import GenerationRequestService
from ai.generation_result_accumulator import GenerationResultAccumulator
from ai.generation_runner import GenerationRunner
from ai.generation_source_resolver import GenerationSourceResolver
from ai.generation_task_bridge import GenerationTaskBridge
from ai.question_generation_service import QuestionGenerationService
from ai.question_plan import QuestionPlanItem
from core.course_index import retrieve_course_context, retrieve_course_source_refs
from core.current_events import material_pack_prompt, material_pack_source_refs
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
                 question_plan_items: list[QuestionPlanItem] | None = None,
                 task_center=None, task_id: str | None = None,
                 material_pack=None):
        super().__init__()
        if (task_center is None) != (task_id is None):
            raise ValueError("task_center and task_id must be provided together")
        self.client = llm_client
        self.course_content = course_content
        self.topics = topics
        self.count = count
        self.difficulty = difficulty
        self.course_project = course_project
        self.generation_config = generation_config or GenerationConfig()
        self.question_plan_items = list(question_plan_items or [])
        self.material_pack = material_pack
        self._generation_service = QuestionGenerationService(self.topics)
        self._cancelled = threading.Event()
        self._cached_context: str | None = None
        self._cached_source_refs: list[dict] = []
        self._cached_source_refs_by_topic: dict[str, list[dict]] = {}
        self._source_resolver = GenerationSourceResolver()
        self._runtime_instruction = ""
        self._runtime_instruction_lock = threading.Lock()
        self._task_bridge = (
            GenerationTaskBridge(task_center, task_id, requested_count=count)
            if task_center is not None
            else None
        )

    def run(self):
        """Execute generation in background thread."""
        try:
            if self._task_bridge is not None:
                if not self._task_bridge.start(self._request_cancel):
                    return
            self._emit_generation_event(ProgressEvent("Building prompt..."))
            course_context = self._build_course_context()
            runner = self._make_runner(course_context)
            for event in runner.events():
                self._emit_generation_event(event)
        except Exception as e:
            if self._task_bridge is not None:
                self._task_bridge.fail(e)
            self.error.emit(f"Unexpected error: {str(e)}")
        finally:
            if self._task_bridge is not None and not self._task_bridge.is_terminal:
                if self._cancelled.is_set():
                    self._task_bridge.finish_cancelled()
                else:
                    self._task_bridge.fail("Generation ended without a terminal result")
            self.finished.emit()

    def _emit_generation_event(self, event) -> None:
        if self._task_bridge is not None:
            self._task_bridge.handle(event)
        if isinstance(event, ProgressEvent):
            self.progress.emit(event.message)
        elif isinstance(event, QuestionsReadyEvent):
            self.question_ready.emit(list(event.questions))
        elif isinstance(event, CompletedEvent):
            self.batch_done.emit(list(event.questions))
        elif isinstance(event, PartialResultEvent):
            self.partial_done.emit(list(event.questions), event.report)
        elif isinstance(event, FailedEvent):
            self.error.emit(event.error)
        else:
            raise TypeError(f"Unsupported generation event: {type(event).__name__}")

    def cancel(self):
        """Signal the worker to stop."""
        if self._task_bridge is None:
            self._request_cancel()
            return
        try:
            self._task_bridge.task_center.request_cancel(self._task_bridge.task_id)
        except (KeyError, ValueError):
            self._request_cancel()

    def _request_cancel(self) -> None:
        self._cancelled.set()
        cancel_client = getattr(self.client, "cancel", None)
        if callable(cancel_client):
            cancel_client()

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

    def _make_runner(self, course_context: str) -> GenerationRunner:
        scheduler = self._make_batch_scheduler()
        quotas = self._make_quota_tracker()
        return GenerationRunner(
            requested_count=self.count,
            scheduler=scheduler,
            result_state=self._make_result_accumulator(scheduler.max_attempts),
            quotas=quotas,
            candidate_processor=self._make_candidate_processor(quotas),
            request_service=self._make_request_service(course_context),
            is_cancelled=self._cancelled.is_set,
            runtime_instruction=self.runtime_instruction,
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

    def _make_request_service(self, course_context: str) -> GenerationRequestService:
        return GenerationRequestService(
            self.client,
            course_context=course_context,
            topics=self.topics,
            difficulty=self.difficulty,
            topic_keywords=self._topic_keywords(),
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

    def _build_course_context(self) -> str:
        """Retrieve the best context for currently selected topics."""
        course_context = self.course_content
        if self.course_project is not None:
            topic_keys = [topic_value(t) for t in self.topics]
            course_refs = retrieve_course_source_refs(
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
            course_context = retrieve_course_context(
                self.course_project,
                topic_keys,
                max_chars=GENERATION_CONTEXT_MAX_CHARS,
            )
        else:
            course_refs = []
            self._cached_source_refs_by_topic = {}
        event_refs = (
            material_pack_source_refs(
                self.material_pack,
                course_project=self.course_project,
            )
            if self.material_pack is not None
            else []
        )
        self._cached_source_refs = [*event_refs, *course_refs]
        self._source_resolver = GenerationSourceResolver(
            self._cached_source_refs,
            self._cached_source_refs_by_topic,
        )
        if self.material_pack is None:
            return course_context
        return (
            f"{course_context}\n\n"
            "## 用户审阅的热点材料（用于课程知识应用题）\n"
            f"{material_pack_prompt(self.material_pack, max_chars=6000)}"
        )

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
        metadata = {}
        if self.course_project is not None:
            metadata.update({
                "course_id": getattr(self.course_project, "course_id", ""),
                "course_title": getattr(self.course_project, "title", ""),
                "course_updated_at": getattr(self.course_project, "updated_at", ""),
            })
        if self.material_pack is not None:
            metadata["material_pack_id"] = getattr(self.material_pack, "pack_id", "")
        return metadata

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
