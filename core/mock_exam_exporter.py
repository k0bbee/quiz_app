"""Markdown export for question sets as mock exam papers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from models.question import Question
from models.question_set import QuestionSet
from utils.constants import topic_label, topic_value


def render_mock_exam_markdown(
    question_set: QuestionSet,
    questions: Iterable[Question],
    lang: str = "zh",
    include_answers: bool = True,
) -> str:
    """Render a question set and its questions as a UTF-8 Markdown exam paper."""
    ordered_questions = list(questions)
    title = question_set.get_title(lang) or question_set.get_title("zh") or "Mock Exam"
    description = question_set.get_description(lang) or question_set.get_description("zh")
    lines: list[str] = [
        f"# {title}",
        "",
        f"- 预计时间: {question_set.estimated_minutes} min",
        f"- 难度: {question_set.difficulty.value}",
        f"- 题量: {len(ordered_questions)}",
        f"- 知识点: {', '.join(topic_label(topic, lang) for topic in question_set.topics) or 'general'}",
    ]
    if description:
        lines.extend(["", description])

    lines.append("")
    question_numbers: dict[str, int] = {}
    number = 1
    for module_number, (topic, topic_questions) in enumerate(_group_by_topic(ordered_questions), start=1):
        lines.extend([f"## 模块 {module_number}: {topic_label(topic, lang)}", ""])
        for question in topic_questions:
            question_numbers[question.question_id] = number
            lines.extend(_render_question(number, question, lang))
            number += 1

    if include_answers:
        lines.extend(["## 答案与解析", ""])
        for question in ordered_questions:
            qnum = question_numbers.get(question.question_id)
            if qnum is None:
                continue
            explanation = question.get_explanation(lang) or question.get_explanation("zh")
            lines.append(f"{qnum}. {question.correct_answer}")
            if explanation:
                lines.append(f"   - 解析: {explanation}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


class MockExamExporter:
    """Writes mock exam Markdown files."""

    @staticmethod
    def write_markdown(
        output_path: str | Path,
        question_set: QuestionSet,
        questions: Iterable[Question],
        lang: str = "zh",
        include_answers: bool = True,
    ) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        markdown = render_mock_exam_markdown(
            question_set,
            questions,
            lang=lang,
            include_answers=include_answers,
        )
        path.write_text(markdown, encoding="utf-8", newline="\n")
        return path


def _group_by_topic(questions: list[Question]) -> list[tuple[object, list[Question]]]:
    grouped: dict[str, tuple[object, list[Question]]] = {}
    for question in questions:
        key = topic_value(question.topic)
        if key not in grouped:
            grouped[key] = (question.topic, [])
        grouped[key][1].append(question)
    return list(grouped.values())


def _render_question(number: int, question: Question, lang: str) -> list[str]:
    stem = question.get_stem(lang) or question.get_stem("zh") or question.get_stem("en")
    lines = [
        f"### {number}. {stem}",
        "",
        f"- 类型: {question.type.value}",
        f"- 难度: {question.difficulty.value}",
    ]
    if question.subtopic:
        lines.append(f"- 子知识点: {question.subtopic}")
    lines.append("")

    options = question.get_options(lang) or question.get_options("zh") or question.get_options("en")
    if isinstance(options, dict):
        for key, values in options.items():
            lines.append(f"**{key}**")
            for value in values:
                lines.append(f"- {value}")
            lines.append("")
    else:
        for option in options:
            lines.append(f"- {option}")
        if options:
            lines.append("")
    return lines
