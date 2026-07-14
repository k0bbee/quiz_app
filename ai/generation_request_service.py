"""Prompt construction and one-shot LLM requests without Qt dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field

from ai.generation_config import GenerationConfig
from ai.prompt_templates import PromptBuilder
from ai.question_plan import QuestionPlanItem


DEFAULT_REQUEST_ERROR = (
    "Check your API key, model, provider, and network connection."
)


@dataclass(frozen=True)
class GenerationRequestResult:
    """Validated envelope returned by one LLM generation request."""

    questions: list = field(default_factory=list)
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return not self.error


class GenerationRequestService:
    """Build prompts, call the configured client, and validate response shape."""

    def __init__(
        self,
        client,
        *,
        course_context: str,
        topics: list,
        difficulty: str,
        topic_keywords: dict[str, list[str]] | None = None,
    ):
        self.client = client
        self.course_context = course_context
        self.topics = list(topics)
        self.difficulty = str(difficulty or "medium")
        self.topic_keywords = dict(topic_keywords or {})

    def request(
        self,
        candidate_count: int,
        generation_config: GenerationConfig,
        question_plan_items: list[QuestionPlanItem] | None = None,
        runtime_instruction: str = "",
    ) -> GenerationRequestResult:
        messages = PromptBuilder.build_messages(
            self.course_context,
            self.topics,
            candidate_count,
            self.difficulty,
            generation_config,
            topic_keywords=self.topic_keywords,
            question_plan_items=question_plan_items,
            runtime_instruction=runtime_instruction,
        )
        data = self.client.generate_with_json(messages, max_retries=3)
        if data is None:
            detail = str(getattr(self.client, "last_error", "") or "").strip()
            return GenerationRequestResult(error=detail or DEFAULT_REQUEST_ERROR)
        if not isinstance(data, dict):
            return GenerationRequestResult(
                error="AI response JSON must be an object with a questions list."
            )

        questions = data.get("questions", [])
        if not isinstance(questions, list) or not questions:
            return GenerationRequestResult(
                error="No questions found in the API response."
            )
        return GenerationRequestResult(questions=list(questions))
