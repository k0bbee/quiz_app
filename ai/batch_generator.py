"""Batch question generator using QThread for non-blocking AI generation."""
from utils.logger import debug, warning, error

import threading
import re
from dataclasses import replace

from PyQt6.QtCore import QThread, pyqtSignal

from ai.llm_client import LLMClient
from ai.generation_config import DIFFICULTY_DEFAULTS, QUESTION_TYPE_DEFAULTS, GenerationConfig, allocate_weighted_counts
from ai.generation_report import GenerationReport
from ai.prompt_templates import PromptBuilder
from ai.question_plan import QuestionPlanItem, build_question_plan
from core.app_errors import AppError
from core.course_index import retrieve_course_context, retrieve_course_source_refs
from models.question import Question
from utils.constants import QuestionType, Difficulty, topic_alias_values, topic_label, topic_value


ACCEPT_TARGET_BATCH_SIZE = 1
MAX_CANDIDATE_BATCH_SIZE = 4
JSON_RECOVERY_BATCH_SIZE = 3
GENERATION_CONTEXT_MAX_CHARS = 12000


def _count_plan_item_values(values, known_keys=None) -> dict[str, int]:
    counts: dict[str, int] = {
        str(key): 0
        for key in (known_keys or [])
        if str(key or "").strip()
    }
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


class GenerationQuotaTracker:
    """Track exact marginal quotas for accepted generated questions."""

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
            plan_items = build_question_plan(
                config,
                topic_keys,
                count,
                topic_titles,
            )
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
        """Return positive remaining quota buckets for reports."""
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
        """Return the remaining planned slots for item-level shortfall reports."""
        return list(self.remaining_plan_items)

    def pending_plan_items(self, limit: int) -> list[QuestionPlanItem]:
        """Return the next planned slots for the upcoming LLM request."""
        return list(self.remaining_plan_items[: max(0, int(limit))])

    def pending_plan_summary(self, limit: int) -> str:
        """Return a compact summary of the next plan slots for progress logs."""
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
        bound: list[QuestionPlanItem] = []
        for item in items:
            refs = self.evidence_refs_by_topic.get(item.topic_id, [])
            evidence_chunk_ids = [
                str(ref.get("chunk_id") or "")
                for ref in refs
                if isinstance(ref, dict) and str(ref.get("chunk_id") or "").strip()
            ]
            if evidence_chunk_ids:
                bound.append(replace(item, evidence_chunk_ids=evidence_chunk_ids))
            else:
                bound.append(item)
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
        if index is None:
            return None
        return self.remaining_plan_items[index]

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
        self._cancelled = threading.Event()
        self._cached_context: str | None = None
        self._candidate_batch_limit: int | None = None
        self._last_json_truncation_detail: str = ""
        self._cached_source_refs: list[dict] = []
        self._cached_source_refs_by_topic: dict[str, list[dict]] = {}
        self._source_ref_registry: dict[str, dict] = {}
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
                    try:
                        qdata = self._normalize_raw_question(qdata)
                        ok, reason = self._validate_raw_question(qdata)
                        if not ok:
                            rejected += 1
                            _record_rejection(rejection_reasons, reason)
                            debug(f"Skipping invalid generated question: {reason}")
                            continue

                        q = Question.create_new(
                            qtype=QuestionType(qdata.get("type", "multiple_choice")),
                            difficulty=Difficulty(qdata.get("difficulty", "medium")),
                            bilingual=qdata.get("bilingual", {}),
                            correct_answer=qdata.get("correct_answer"),
                            topic=self._normalize_topic(qdata.get("topic")),
                            subtopic=qdata.get("subtopic", ""),
                            source="ai_generated",
                        )
                        # Set AI model in metadata
                        q.metadata["ai_model"] = self.client.model
                        q.metadata.update(self._course_metadata())
                        errors = q.validate()
                        if not errors:
                            plan_id = _normalize_plan_id(qdata.get("plan_id"))
                            quota_reason = quotas.rejection_reason(
                                q.type.value,
                                q.difficulty.value,
                                topic_value(q.topic),
                                plan_id,
                            )
                            if quota_reason:
                                rejected += 1
                                _record_rejection(rejection_reasons, quota_reason)
                                debug(f"Skipping generated question: {quota_reason}")
                                continue
                            plan_item, plan_match_status = quotas.accept(
                                q.type.value,
                                q.difficulty.value,
                                topic_value(q.topic),
                                plan_id,
                            )
                            if plan_item is not None:
                                q.metadata["plan_id"] = plan_item.plan_id
                                q.metadata["plan_topic_id"] = plan_item.topic_id
                                q.metadata["plan_topic_title"] = plan_item.topic_title
                                q.metadata["target_skill"] = plan_item.target_skill
                                if plan_item.evidence_chunk_ids:
                                    q.metadata["plan_evidence_chunk_ids"] = list(plan_item.evidence_chunk_ids)
                            if plan_match_status:
                                q.metadata["plan_match_status"] = plan_match_status
                            source_refs, source_ref_status, invalid_ref_ids = self._question_source_refs(
                                qdata,
                                plan_item,
                                quotas,
                            )
                            if source_refs:
                                q.metadata["source_refs"] = source_refs
                            if source_ref_status:
                                q.metadata["source_ref_status"] = source_ref_status
                            if invalid_ref_ids:
                                q.metadata["invalid_source_ref_ids"] = invalid_ref_ids
                            batch_questions.append(q)
                        else:
                            rejected += 1
                            _record_rejection(rejection_reasons, "question validation failed")
                            debug(f"Skipping invalid question: {errors}")
                    except (ValueError, KeyError) as e:
                        rejected += 1
                        _record_rejection(rejection_reasons, "malformed question")
                        debug(f"Skipping malformed question: {e}")
                        continue

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
            self._source_ref_registry = _source_ref_registry(
                self._cached_source_refs,
                self._cached_source_refs_by_topic,
            )
            return retrieve_course_context(
                self.course_project,
                topic_keys,
                max_chars=GENERATION_CONTEXT_MAX_CHARS,
            )
        self._cached_source_refs_by_topic = {}
        self._source_ref_registry = {}
        return self.course_content

    def _question_source_refs(
        self,
        qdata: dict,
        plan_item: QuestionPlanItem | None = None,
        quotas: GenerationQuotaTracker | None = None,
    ) -> tuple[list[dict], str, list[str]]:
        """Return sanitized model source refs, falling back to retrieved evidence."""
        refs = qdata.get("source_refs")
        if isinstance(refs, list):
            sanitized = [_sanitize_source_ref(ref) for ref in refs]
            sanitized = [ref for ref in sanitized if ref]
            if sanitized:
                valid_refs, invalid_ref_ids = self._validated_model_source_refs(
                    sanitized,
                    plan_item,
                )
                if valid_refs:
                    status = "valid_model_ref" if not invalid_ref_ids else "partial_model_ref"
                    return valid_refs, status, invalid_ref_ids
                fallback, _fallback_status = self._fallback_source_refs(plan_item, quotas)
                return fallback, "invalid_model_ref", invalid_ref_ids
        fallback, fallback_status = self._fallback_source_refs(plan_item, quotas)
        if fallback:
            return fallback, fallback_status, []
        return [], "", []

    def _fallback_source_refs(
        self,
        plan_item: QuestionPlanItem | None,
        quotas: GenerationQuotaTracker | None,
    ) -> tuple[list[dict], str]:
        if quotas is not None:
            plan_refs = quotas.evidence_refs_for_item(plan_item)
            if plan_refs:
                return plan_refs[:1], "fallback_plan_evidence"
        refs = [dict(ref) for ref in self._cached_source_refs[:1]]
        if refs:
            return refs, "fallback_global_evidence"
        return [], ""

    def _validated_model_source_refs(
        self,
        refs: list[dict],
        plan_item: QuestionPlanItem | None,
    ) -> tuple[list[dict], list[str]]:
        if not self._source_ref_registry:
            return refs, []
        valid: list[dict] = []
        invalid_ids: list[str] = []
        allowed_chunk_ids = set(plan_item.evidence_chunk_ids if plan_item else [])
        for ref in refs:
            chunk_id = str(ref.get("chunk_id") or "").strip()
            if not chunk_id:
                invalid_ids.append("")
                continue
            registered = self._source_ref_registry.get(chunk_id)
            if registered is None:
                invalid_ids.append(chunk_id)
                continue
            if allowed_chunk_ids and chunk_id not in allowed_chunk_ids:
                invalid_ids.append(chunk_id)
                continue
            if not _source_ref_matches_registered(ref, registered):
                invalid_ids.append(chunk_id)
                continue
            valid.append(dict(registered))
        return valid, invalid_ids

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
        if not isinstance(qdata, dict):
            return qdata
        normalized = dict(qdata)
        qtype = normalized.get("type")
        if qtype == QuestionType.FILL_IN_BLANK.value:
            answer = normalized.get("correct_answer")
            if isinstance(answer, str):
                normalized["correct_answer"] = [answer.strip()] if answer.strip() else []
            elif isinstance(answer, (list, tuple)):
                normalized["correct_answer"] = [
                    str(item).strip()
                    for item in answer
                    if str(item).strip()
                ]
        elif qtype == QuestionType.MATCHING.value:
            normalized = _normalize_matching_option_ids(normalized)
        elif qtype == QuestionType.ORDERING.value:
            normalized = _normalize_ordering_option_ids(normalized)
        return normalized

    def _validate_raw_question(self, qdata: dict) -> tuple[bool, str]:
        """Validate raw model output before converting it to a Question."""
        if not isinstance(qdata, dict):
            return False, "question is not an object"

        qtype = qdata.get("type", "multiple_choice")
        try:
            question_type = QuestionType(qtype)
        except ValueError:
            return False, f"unknown question type: {qtype}"

        if question_type == QuestionType.SHORT_ANSWER:
            return False, "short_answer is not suitable for auto-graded quick practice"

        topic = self._normalize_topic(qdata.get("topic"))
        if topic is None:
            return False, f"topic {qdata.get('topic')} was not selected"

        bilingual = qdata.get("bilingual", {})
        if not isinstance(bilingual, dict):
            return False, "bilingual content must be an object"
        for lang in ("zh", "en"):
            content = bilingual.get(lang, {})
            if not isinstance(content, dict):
                return False, f"{lang} content must be an object"
            if not content.get("stem"):
                return False, f"missing {lang} stem"
            if not content.get("explanation") or len(content.get("explanation", "")) < 20:
                return False, f"missing or weak {lang} explanation"

        if question_type in (
            QuestionType.MULTIPLE_CHOICE,
            QuestionType.SCENARIO_CHOICE,
            QuestionType.TRUE_FALSE,
        ):
            answer = str(qdata.get("correct_answer", "")).strip()
            if question_type == QuestionType.TRUE_FALSE:
                if answer.lower() not in {"true", "false"}:
                    return False, "true_false answer must be true/false"
            else:
                if answer.upper() not in {"A", "B", "C", "D"}:
                    return False, "choice answer must be A/B/C/D"
                for lang in ("zh", "en"):
                    options = bilingual.get(lang, {}).get("options", [])
                    if len(options) != 4:
                        return False, f"{lang} choice question must have 4 options"
                if _choice_stem_leaks_correct_answer_keyword(bilingual, answer):
                    return False, "answer keyword leaked in choice stem"
        elif question_type == QuestionType.FILL_IN_BLANK:
            answer = qdata.get("correct_answer")
            if not isinstance(answer, list) or not answer:
                return False, "fill_in_blank answer must be a non-empty list"
        elif question_type == QuestionType.MATCHING:
            for lang in ("zh", "en"):
                options = bilingual.get(lang, {}).get("options", {})
                if not isinstance(options, dict):
                    return False, f"{lang} matching options must contain left/right lists"
                left = options.get("left", [])
                right = options.get("right", [])
                if not left or len(left) != len(right):
                    return False, f"{lang} matching left/right options must be non-empty and equal length"
                if not all(_has_option_id(item) for item in left + right):
                    return False, f"{lang} matching options must have stable ids"
            answer = qdata.get("correct_answer")
            if not isinstance(answer, list) or not answer:
                return False, "matching answer must be a non-empty list of id pairs"
            if not all(isinstance(pair, (list, tuple)) and len(pair) == 2 for pair in answer):
                return False, "matching answer must contain pairs"
        elif question_type == QuestionType.ORDERING:
            for lang in ("zh", "en"):
                options = bilingual.get(lang, {}).get("options", [])
                if not isinstance(options, list) or not options:
                    return False, f"{lang} ordering options must be a non-empty list"
                if not all(_has_option_id(item) for item in options):
                    return False, f"{lang} ordering options must have stable ids"
            answer = qdata.get("correct_answer")
            if not isinstance(answer, list) or not answer:
                return False, "ordering answer must be a non-empty list of item ids"

        return True, ""

    def _normalize_topic(self, raw_topic):
        """Map model topic output to one of the selected topics."""
        if not self.topics:
            return str(raw_topic or "general")
        raw = str(raw_topic or "").strip().lower()
        raw_key = _topic_match_key(raw)
        selected = {value.lower(): t for t in self.topics for value in topic_alias_values(t)}
        if raw in selected:
            return selected[raw]
        canonical_selected = {
            _topic_match_key(value): t
            for t in self.topics
            for value in topic_alias_values(t) | {topic_label(t)}
        }
        if raw_key in canonical_selected:
            return canonical_selected[raw_key]
        for topic in self.topics:
            for label in topic_alias_values(topic) | {topic_label(topic)}:
                label = str(label or "").lower()
                if _topic_tokens_cover(raw_key, _topic_match_key(label)):
                    return topic
        return None


def _topic_match_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _topic_tokens_cover(raw_key: str, label_key: str) -> bool:
    """Return whether raw and label match by meaningful token boundaries."""
    raw_tokens = {token for token in raw_key.split() if len(token) >= 3}
    label_tokens = {token for token in label_key.split() if len(token) >= 3}
    if not raw_tokens or not label_tokens:
        return False
    return raw_tokens.issuperset(label_tokens) or label_tokens.issuperset(raw_tokens)


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


def _normalize_plan_id(value) -> str:
    return str(value or "").strip()


def _source_ref_registry(refs: list[dict], refs_by_topic: dict[str, list[dict]]) -> dict[str, dict]:
    registry: dict[str, dict] = {}
    for ref in refs:
        _register_source_ref(registry, ref)
    for topic_refs in refs_by_topic.values():
        for ref in topic_refs:
            _register_source_ref(registry, ref)
    return registry


def _register_source_ref(registry: dict[str, dict], ref) -> None:
    clean = _sanitize_source_ref(ref)
    chunk_id = str(clean.get("chunk_id") or "").strip()
    if chunk_id and chunk_id not in registry:
        registry[chunk_id] = clean


def _source_ref_matches_registered(ref: dict, registered: dict) -> bool:
    expected_file = str(registered.get("source_file") or "").strip()
    actual_file = str(ref.get("source_file") or "").strip()
    if actual_file and expected_file and actual_file != expected_file:
        return False
    expected_page = registered.get("page_or_slide")
    actual_page = ref.get("page_or_slide")
    if actual_page is not None and expected_page is not None and actual_page != expected_page:
        return False
    return True


def _normalize_matching_option_ids(qdata: dict) -> dict:
    normalized = dict(qdata)
    bilingual = dict(normalized.get("bilingual", {}) or {})
    left_ids = _stable_ids_for_parallel_options(
        [bilingual.get(lang, {}).get("options", {}).get("left", []) for lang in ("zh", "en")],
        "left",
    )
    right_ids = _stable_ids_for_parallel_options(
        [bilingual.get(lang, {}).get("options", {}).get("right", []) for lang in ("zh", "en")],
        "right",
    )
    label_to_id: dict[str, str] = {}

    for lang in ("zh", "en"):
        content = dict(bilingual.get(lang, {}) or {})
        options = dict(content.get("options", {}) or {})
        left = options.get("left", []) or []
        right = options.get("right", []) or []
        options["left"] = _normalize_option_list(left, left_ids, label_to_id, lang)
        options["right"] = _normalize_option_list(right, right_ids, label_to_id, lang)
        content["options"] = options
        bilingual[lang] = content

    answer = normalized.get("correct_answer")
    if isinstance(answer, list):
        normalized["correct_answer"] = [
            [
                _normalize_answer_token(pair[0], label_to_id),
                _normalize_answer_token(pair[1], label_to_id),
            ]
            for pair in answer
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        ]
    normalized["bilingual"] = bilingual
    return normalized


def _normalize_ordering_option_ids(qdata: dict) -> dict:
    normalized = dict(qdata)
    bilingual = dict(normalized.get("bilingual", {}) or {})
    item_ids = _stable_ids_for_parallel_options(
        [bilingual.get(lang, {}).get("options", []) for lang in ("zh", "en")],
        "item",
    )
    label_to_id: dict[str, str] = {}

    for lang in ("zh", "en"):
        content = dict(bilingual.get(lang, {}) or {})
        options = content.get("options", []) or []
        content["options"] = _normalize_option_list(options, item_ids, label_to_id, lang)
        bilingual[lang] = content

    answer = normalized.get("correct_answer")
    if isinstance(answer, list):
        normalized["correct_answer"] = [
            _normalize_answer_token(item, label_to_id)
            for item in answer
        ]
    normalized["bilingual"] = bilingual
    return normalized


def _stable_ids_for_parallel_options(option_lists: list[list], prefix: str) -> list[str]:
    max_count = max((len(options or []) for options in option_lists), default=0)
    ids: list[str] = []
    for index in range(max_count):
        found = ""
        for options in option_lists:
            if index < len(options or []):
                found = _raw_option_id(options[index])
                if found:
                    break
        ids.append(found or f"{prefix}_{index + 1}")
    return ids


def _normalize_option_list(options: list, ids: list[str], label_to_id: dict[str, str], lang: str) -> list[dict]:
    normalized = []
    for index, option in enumerate(options or []):
        option_id = ids[index] if index < len(ids) else _raw_option_id(option) or f"item_{index + 1}"
        label = _raw_option_label(option, lang)
        normalized.append({"id": option_id, "text": label})
        for alias in _raw_option_aliases(option, label):
            if alias:
                label_to_id.setdefault(alias.strip().lower(), option_id)
        label_to_id.setdefault(option_id.strip().lower(), option_id)
    return normalized


def _raw_option_id(option) -> str:
    if isinstance(option, dict):
        for key in ("id", "value", "key"):
            value = option.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _raw_option_label(option, lang: str = "") -> str:
    if isinstance(option, dict):
        for key in (lang, "text", "label", "title", "name", "value", "id"):
            value = option.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return str(option)


def _raw_option_aliases(option, label: str) -> list[str]:
    aliases = [label]
    if isinstance(option, dict):
        for key in ("id", "value", "key", "text", "label", "title", "name", "zh", "en"):
            value = option.get(key)
            if value is not None and str(value).strip():
                aliases.append(str(value).strip())
    else:
        aliases.append(str(option))
    return aliases


def _normalize_answer_token(value, label_to_id: dict[str, str]) -> str:
    text = str(value or "").strip()
    return label_to_id.get(text.lower(), text)


def _has_option_id(option) -> bool:
    return isinstance(option, dict) and bool(str(option.get("id", "") or "").strip())


def _choice_stem_leaks_correct_answer_keyword(bilingual: dict, answer: str) -> bool:
    answer = str(answer or "").strip().upper()
    if answer not in {"A", "B", "C", "D"}:
        return False
    for lang in ("zh", "en"):
        content = bilingual.get(lang, {}) or {}
        options = content.get("options", []) or []
        option_text = _choice_option_text(options, answer)
        if not option_text:
            continue
        stem_tokens = _answer_leak_tokens(content.get("stem", ""))
        correct_tokens = _answer_leak_tokens(option_text)
        wrong_tokens = set()
        for index, option in enumerate(options):
            if index == ord(answer) - ord("A"):
                continue
            wrong_tokens.update(_answer_leak_tokens(option))
        leaked = [
            token
            for token in correct_tokens
            if token in stem_tokens and token not in wrong_tokens
        ]
        if leaked:
            return True
    return False


def _choice_option_text(options, answer: str) -> str:
    if not isinstance(options, list):
        return ""
    index = ord(answer) - ord("A")
    if index < 0 or index >= len(options):
        return ""
    return _strip_choice_prefix(_raw_option_label(options[index]))


def _strip_choice_prefix(text: str) -> str:
    return re.sub(r"^\s*[A-Da-d][\.\)、)]\s*", "", str(text or "")).strip()


def _answer_leak_tokens(value) -> set[str]:
    text = str(value or "").lower()
    tokens: set[str] = set()
    for token in re.findall(r"[a-z][a-z\-]{2,}", text):
        normalized = token.strip("-")
        if normalized not in _ANSWER_LEAK_STOPWORDS:
            tokens.add(normalized)
        if "-" in normalized:
            for part in normalized.split("-"):
                if len(part) >= 4 and part not in _ANSWER_LEAK_STOPWORDS:
                    tokens.add(part)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if chunk not in _ANSWER_LEAK_STOPWORDS:
            tokens.add(chunk)
        max_n = min(4, len(chunk))
        for size in range(2, max_n + 1):
            for start in range(0, len(chunk) - size + 1):
                token = chunk[start:start + size]
                if token not in _ANSWER_LEAK_STOPWORDS:
                    tokens.add(token)
    return tokens


_ANSWER_LEAK_STOPWORDS = {
    "the", "and", "for", "with", "which", "what", "when", "where",
    "question", "answer", "option",
    "statement", "correct", "right", "wrong",
    "cpu", "io", "i/o", "方式", "以下", "哪种", "通知", "完成",
    "同步", "直接", "存储", "数据", "工作", "正确", "错误", "说法",
}


def _sanitize_source_ref(ref) -> dict:
    if not isinstance(ref, dict):
        return {}
    chunk_id = str(ref.get("chunk_id", "") or "").strip()
    source_file = str(ref.get("source_file", "") or "").strip()
    if not chunk_id and not source_file:
        return {}
    page_or_slide = ref.get("page_or_slide")
    if page_or_slide is not None:
        try:
            page_or_slide = int(page_or_slide)
        except (TypeError, ValueError):
            page_or_slide = None
    clean = {
        "chunk_id": chunk_id,
        "source_file": source_file,
        "page_or_slide": page_or_slide,
        "heading": str(ref.get("heading", "") or "").strip(),
        "excerpt": _compact_source_excerpt(ref.get("excerpt", "")),
        "content_hash": str(ref.get("content_hash", "") or "").strip(),
    }
    return {key: value for key, value in clean.items() if value not in ("", None)}


def _compact_source_excerpt(value, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"
