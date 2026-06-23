"""Course-specific default quiz configuration with validated LLM suggestions."""

from __future__ import annotations

import json
import re

from ai.exam_plan import (
    DIFFICULTY_WEIGHT_KEYS,
    QUESTION_TYPES,
    ExamGenerationPlan,
    ExamPlanPatch,
    ExamPlanValidationError,
    apply_exam_plan_patch,
)
from models.course_project import CourseTopic


class CourseGenerationProfileGenerator:
    """Generate a safe course-level default plan, with a local fallback."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.profile_source = "local"
        self.profile_warning = ""

    def generate(
        self,
        title: str,
        topics: list[CourseTopic],
        summary_markdown: str,
    ) -> ExamGenerationPlan:
        self.profile_source = "local"
        self.profile_warning = ""
        local_plan = build_local_course_profile(topics, summary_markdown)
        if self.llm_client is None:
            return local_plan

        base_url = str(getattr(self.llm_client, "base_url", "")).lower()
        if not (base_url.startswith("https://") or base_url.startswith("http://")):
            self.profile_warning = (
                "Local agent profile generation is disabled for safety; "
                "saved deterministic local defaults."
            )
            return local_plan

        messages = self.build_messages(title, topics, summary_markdown, local_plan)
        try:
            data = self.llm_client.generate_with_json(
                messages,
                temperature=0.1,
                max_tokens=1800,
                max_retries=1,
            )
        except Exception as exc:
            self.profile_warning = f"Course profile LLM request failed: {exc}"
            return local_plan
        if data is None:
            detail = str(getattr(self.llm_client, "last_error", "") or "empty JSON response")
            self.profile_warning = f"Course profile LLM request failed: {detail}"
            return local_plan

        try:
            patch = ExamPlanPatch.from_mapping(data)
            plan = apply_exam_plan_patch(
                local_plan,
                patch,
                [topic.title for topic in topics],
            )
        except ExamPlanValidationError as exc:
            self.profile_warning = f"Course profile LLM returned invalid configuration: {exc}"
            return local_plan
        self.profile_source = "llm"
        return plan

    @staticmethod
    def build_messages(
        title: str,
        topics: list[CourseTopic],
        summary_markdown: str,
        local_plan: ExamGenerationPlan,
    ) -> list[dict]:
        allowed_topics = [topic.title for topic in topics]
        schema = {
            "question_count": "integer 3..60",
            "difficulty": "easy|medium|hard|mixed",
            "template": "quick_review|final_exam|calculation_practice",
            "selected_topics": allowed_topics,
            "question_type_weights": {key: "integer 0..100" for key in QUESTION_TYPES},
            "difficulty_weights": {key: "integer 0..100" for key in DIFFICULTY_WEIGHT_KEYS},
            "topic_weights": {topic: "integer 0..100" for topic in allowed_topics},
        }
        topic_context = [
            {
                "title": topic.title,
                "keywords": topic.keywords[:8],
                "source_file_count": len(set(topic.source_files)),
            }
            for topic in topics
        ]
        system = (
            "Recommend one reusable default quiz-generation profile for this course. "
            "Return one JSON object only, omit unchanged fields, and never add fields, "
            "questions, commands, paths, or prose outside JSON. "
            f"STRICT_JSON_PROFILE={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
        )
        user = (
            f"COURSE_TITLE={title}\n"
            f"COURSE_TOPICS={json.dumps(topic_context, ensure_ascii=False)}\n"
            f"LOCAL_DEFAULT={json.dumps(local_plan.to_dict(), ensure_ascii=False, sort_keys=True)}\n"
            f"COURSE_SUMMARY_EXCERPT={summary_markdown[:8000]}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]


def build_local_course_profile(
    topics: list[CourseTopic],
    summary_markdown: str,
) -> ExamGenerationPlan:
    """Build deterministic defaults that remain useful without an LLM."""
    selected = tuple(topic.title for topic in topics[:6])
    scores = {
        topic.title: max(1, len(set(topic.source_files)) * 3 + len(set(topic.keywords)))
        for topic in topics[:6]
    }
    calculation_markers = re.compile(
        r"公式|计算|推导|矩阵|数值|formula|equation|calculation|numeric|matrix",
        re.IGNORECASE,
    )
    template = (
        "calculation_practice"
        if calculation_markers.search(summary_markdown or "")
        else "quick_review"
    )
    return ExamGenerationPlan(
        question_count=15,
        difficulty="mixed",
        template=template,
        selected_topics=selected,
        topic_weights=scores,
    )
