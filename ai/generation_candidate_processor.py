"""Convert one generated payload into an accepted question or a stable rejection."""

from __future__ import annotations

from dataclasses import dataclass

from ai.generation_quota_tracker import GenerationQuotaTracker
from ai.generation_source_resolver import GenerationSourceResolver
from ai.question_generation_service import QuestionGenerationService
from models.question import Question
from utils.constants import Difficulty, QuestionType, topic_value


@dataclass(frozen=True)
class CandidateProcessingResult:
    """Outcome of processing one model-generated candidate."""

    question: Question | None = None
    rejection_reason: str = ""
    detail: str = ""

    @property
    def accepted(self) -> bool:
        return self.question is not None


class GenerationCandidateProcessor:
    """Apply generation policy to candidates without Qt or network dependencies."""

    def __init__(
        self,
        generation_service: QuestionGenerationService,
        quota_tracker: GenerationQuotaTracker,
        source_resolver: GenerationSourceResolver,
        *,
        ai_model: str,
        course_metadata: dict | None = None,
    ):
        self.generation_service = generation_service
        self.quota_tracker = quota_tracker
        self.source_resolver = source_resolver
        self.ai_model = str(ai_model or "")
        self.course_metadata = dict(course_metadata or {})

    def process(self, raw_question) -> CandidateProcessingResult:
        """Process one raw payload and consume quota only when it is accepted."""
        try:
            prepared, reason = self.generation_service.prepare_raw_question(raw_question)
            if prepared is None:
                return CandidateProcessingResult(rejection_reason=reason)

            question = Question.create_new(
                qtype=QuestionType(prepared.get("type", "multiple_choice")),
                difficulty=Difficulty(prepared.get("difficulty", "medium")),
                bilingual=prepared.get("bilingual", {}),
                correct_answer=prepared.get("correct_answer"),
                topic=prepared.get("topic"),
                subtopic=prepared.get("subtopic", ""),
                source="ai_generated",
            )
            question.metadata["ai_model"] = self.ai_model
            question.metadata.update(self.course_metadata)

            validation_errors = question.validate()
            if validation_errors:
                return CandidateProcessingResult(
                    rejection_reason="question validation failed",
                    detail="; ".join(validation_errors),
                )

            plan_id = str(prepared.get("plan_id") or "").strip()
            quota_reason = self.quota_tracker.rejection_reason(
                question.type.value,
                question.difficulty.value,
                topic_value(question.topic),
                plan_id,
            )
            if quota_reason:
                return CandidateProcessingResult(rejection_reason=quota_reason)

            plan_item, plan_match_status = self.quota_tracker.accept(
                question.type.value,
                question.difficulty.value,
                topic_value(question.topic),
                plan_id,
            )
            _attach_plan_metadata(question, plan_item, plan_match_status)

            plan_refs = self.quota_tracker.evidence_refs_for_item(plan_item)
            source_refs, source_ref_status, invalid_ref_ids = self.source_resolver.resolve(
                prepared,
                plan_item=plan_item,
                plan_refs=plan_refs,
            )
            if source_refs:
                question.metadata["source_refs"] = source_refs
            if source_ref_status:
                question.metadata["source_ref_status"] = source_ref_status
            if invalid_ref_ids:
                question.metadata["invalid_source_ref_ids"] = invalid_ref_ids
            return CandidateProcessingResult(question=question)
        except (ValueError, KeyError) as exc:
            return CandidateProcessingResult(
                rejection_reason="malformed question",
                detail=str(exc),
            )


def _attach_plan_metadata(question: Question, plan_item, plan_match_status: str) -> None:
    if plan_item is not None:
        question.metadata["plan_id"] = plan_item.plan_id
        question.metadata["plan_topic_id"] = plan_item.topic_id
        question.metadata["plan_topic_title"] = plan_item.topic_title
        question.metadata["target_skill"] = plan_item.target_skill
        if plan_item.evidence_chunk_ids:
            question.metadata["plan_evidence_chunk_ids"] = list(
                plan_item.evidence_chunk_ids
            )
    if plan_match_status:
        question.metadata["plan_match_status"] = plan_match_status
