"""Factories for creating question sets from generated questions."""

from __future__ import annotations

import re

from ai.generation_config import GenerationConfig
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, topic_label, topic_value


def build_ai_question_set(
    questions: list[Question],
    selected_difficulty: str,
    generation_config: GenerationConfig,
    lang: str = "en",
    course_project=None,
    custom_title: str = "",
) -> QuestionSet:
    """Create a question set that preserves the user's AI generation choices."""
    topic_labels_by_id = {
        topic_value(question.topic): topic_label(question.topic, lang)
        for question in questions
    }
    topics = sorted(topic_labels_by_id)
    topic_names = ", ".join(topic_labels_by_id.get(topic, topic) for topic in topics)
    display_difficulty = _display_difficulty(selected_difficulty)
    title = str(custom_title or "").strip()
    default_title_payload = {
        "zh": f"AI生成练习：{topic_names or '综合'}",
        "en": f"AI Practice: {topic_names or 'Mixed'}",
    }
    title_payload = (
        _custom_title_payload(title, default_title_payload)
        if title
        else default_title_payload
    )
    qset = QuestionSet.create_new(
        title=title_payload,
        description={
            "zh": "由当前课程项目生成，已通过本地结构校验。",
            "en": "Generated from the active course project and local validation rules.",
        },
        topics=topics,
        question_ids=[question.question_id for question in questions],
        difficulty=display_difficulty,
        estimated_minutes=max(4, len(questions) * 2),
        source="ai_generated",
    )
    qset.metadata.update(_generation_metadata(selected_difficulty, generation_config))
    qset.metadata.update(_course_metadata(course_project))
    qset.metadata["topic_titles"] = {
        topic: topic_labels_by_id.get(topic, topic)
        for topic in topics
    }
    if title:
        qset.metadata["renamed_by_user"] = True
    return qset


def _display_difficulty(selected_difficulty: str) -> Difficulty:
    """Map the dialog choice to the single difficulty badge stored on QuestionSet."""
    if selected_difficulty in {difficulty.value for difficulty in Difficulty}:
        return Difficulty(selected_difficulty)
    return Difficulty.MEDIUM


def _custom_title_payload(title: str, default_title_payload: dict[str, str]) -> dict[str, str]:
    """Return a bilingual-safe title payload for a user-entered set name."""
    if _contains_cjk(title):
        return {"zh": title, "en": default_title_payload["en"]}
    return {"zh": title, "en": title}


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def _generation_metadata(selected_difficulty: str, generation_config: GenerationConfig) -> dict:
    return {
        "difficulty_mode": selected_difficulty or "medium",
        "generation_template": generation_config.template,
        "question_type_weights": dict(generation_config.question_type_weights),
        "difficulty_weights": dict(generation_config.difficulty_weights),
        "topic_weights": dict(generation_config.topic_weights),
    }


def _course_metadata(course_project) -> dict:
    if course_project is None:
        return {}
    return {
        "course_id": getattr(course_project, "course_id", ""),
        "course_title": getattr(course_project, "title", ""),
        "course_updated_at": getattr(course_project, "updated_at", ""),
    }
