"""Factories for creating question sets from generated questions."""

from __future__ import annotations

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
    topics = sorted({topic_value(question.topic) for question in questions})
    topic_names = ", ".join(topic_label(topic, lang) for topic in topics)
    display_difficulty = _display_difficulty(selected_difficulty)
    title = str(custom_title or "").strip()
    title_payload = (
        {"zh": title, "en": title}
        if title
        else {
            "zh": f"AI生成练习：{topic_names or '综合'}",
            "en": f"AI Practice: {topic_names or 'Mixed'}",
        }
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
    if title:
        qset.metadata["renamed_by_user"] = True
    return qset


def _display_difficulty(selected_difficulty: str) -> Difficulty:
    """Map the dialog choice to the single difficulty badge stored on QuestionSet."""
    if selected_difficulty in {difficulty.value for difficulty in Difficulty}:
        return Difficulty(selected_difficulty)
    return Difficulty.MEDIUM


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
