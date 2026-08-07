"""Parse common text/OCR exam layouts into reviewable question candidates.

This module deliberately stops at parsing.  It does not persist questions, infer
course ownership from filenames, or silently repair incomplete blocks.  Callers
can send the returned questions through the existing review dialog before saving.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from models.question import Question
from utils.constants import Difficulty, QuestionType


@dataclass(frozen=True)
class HistoricalQuestionParseResult:
    """Safe parser output: valid candidates plus bounded block-level warnings."""

    questions: tuple[Question, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class _QuestionBlock:
    number: int
    line_start: int
    lines: list[str] = field(default_factory=list)
    stem_lines: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)
    answer_text: str = ""
    explanation_lines: list[str] = field(default_factory=list)
    in_explanation: bool = False


_QUESTION_RE = re.compile(r"^\s*(\d{1,4})\s*[.)、．:：]\s*(.*?)\s*$")
_OPTION_RE = re.compile(r"^\s*([A-Da-d])\s*[.)、．:：]\s*(.*?)\s*$")
_ANSWER_RE = re.compile(
    r"^\s*(?:答案|参考答案|answer|correct\s+answer)\s*(?::|：|=)?\s*(.*?)\s*$",
    re.IGNORECASE,
)
_EXPLANATION_RE = re.compile(
    r"^\s*(?:解析|答案解析|explanation|analysis)\s*(?::|：|=)?\s*(.*?)\s*$",
    re.IGNORECASE,
)
_TRUE_WORDS = {"true", "yes", "正确", "对", "是", "√", "t"}
_FALSE_WORDS = {"false", "no", "错误", "错", "否", "×", "f"}


def parse_historical_questions(
    text: str,
    *,
    source_file: str = "",
    course_id: str = "",
    topic_id: str = "general",
    topic_title: str = "",
    course_topics=None,
) -> HistoricalQuestionParseResult:
    """Parse numbered multiple-choice/true-false questions from plain text.

    The parser accepts common Word/PDF/OCR punctuation variants.  A block is
    emitted only when it has a stem, at least two options, and an unambiguous
    answer; incomplete blocks are reported in ``warnings`` instead.
    """

    lines = _normalized_lines(text)
    blocks: list[_QuestionBlock] = []
    current: _QuestionBlock | None = None
    for line_number, line in enumerate(lines, start=1):
        match = _QUESTION_RE.match(line)
        if match:
            if current is not None:
                blocks.append(current)
            current = _QuestionBlock(
                number=int(match.group(1)),
                line_start=line_number,
                lines=[line],
                stem_lines=[match.group(2).strip()] if match.group(2).strip() else [],
            )
            continue
        if current is None:
            continue
        current.lines.append(line)
        option = _OPTION_RE.match(line)
        if option:
            current.options[option.group(1).upper()] = option.group(2).strip()
            current.in_explanation = False
            continue
        answer = _ANSWER_RE.match(line)
        if answer:
            current.answer_text = answer.group(1).strip()
            current.in_explanation = False
            continue
        explanation = _EXPLANATION_RE.match(line)
        if explanation:
            current.in_explanation = True
            if explanation.group(1).strip():
                current.explanation_lines.append(explanation.group(1).strip())
            continue
        if current.in_explanation:
            if line.strip():
                current.explanation_lines.append(line.strip())
        elif not current.options and line.strip():
            current.stem_lines.append(line.strip())
    if current is not None:
        blocks.append(current)

    questions: list[Question] = []
    warnings: list[str] = []
    for block in blocks:
        question, block_warnings = _build_question(
            block,
            lines,
            source_file=source_file,
            course_id=course_id,
            topic_id=topic_id,
            topic_title=topic_title,
            course_topics=course_topics,
        )
        warnings.extend(
            f"question {block.number}: {warning}" for warning in block_warnings
        )
        if question is not None:
            questions.append(question)
    return HistoricalQuestionParseResult(tuple(questions), tuple(warnings))


def parse_historical_document(
    path: str | Path,
    *,
    course_id: str = "",
    course_topics=None,
    task=None,
) -> HistoricalQuestionParseResult:
    """Extract a supported local document, then parse its question blocks.

    ``DocumentParser`` owns PDF/DOCX/PPTX/OCR limits and cancellation checks;
    this function only adds its extraction warnings to the review result.
    """

    from core.document_parser import DocumentParser

    document = DocumentParser().parse_file(Path(path), task=task)
    result = parse_historical_questions(
        document.text,
        source_file=document.path,
        course_id=course_id,
        course_topics=course_topics,
    )
    extraction_warnings = tuple(str(warning) for warning in document.warnings if str(warning).strip())
    return HistoricalQuestionParseResult(
        questions=result.questions,
        warnings=extraction_warnings + result.warnings,
    )


def _normalized_lines(text: str) -> list[str]:
    value = str(text or "").replace("\ufeff", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return [line.replace("\u200b", "").replace("\u00a0", " ").strip() for line in value.split("\n")]


def _build_question(
    block: _QuestionBlock,
    lines: list[str],
    *,
    source_file: str,
    course_id: str,
    topic_id: str,
    topic_title: str,
    course_topics,
) -> tuple[Question | None, list[str]]:
    warnings: list[str] = []
    stem = " ".join(part for part in block.stem_lines if part).strip()
    if not stem:
        warnings.append("missing stem")
    if len(block.options) < 2:
        warnings.append("missing options")
    answer = _answer_value(block.answer_text)
    if not answer:
        warnings.append("missing answer")
    if warnings:
        return None, warnings

    option_keys = tuple(sorted(block.options))
    option_values = [block.options[key] for key in option_keys]
    true_false = _looks_like_true_false(option_values, answer)
    if true_false:
        correct_answer = _true_false_answer(answer, option_values)
        if not correct_answer:
            return None, ["ambiguous true/false answer"]
        qtype = QuestionType.TRUE_FALSE
    else:
        correct_answer = answer.upper()
        if correct_answer not in option_keys:
            return None, ["answer does not match options"]
        qtype = QuestionType.MULTIPLE_CHOICE

    options = [f"{key}. {block.options[key]}" for key in option_keys]
    explanation = " ".join(block.explanation_lines).strip()
    if not explanation:
        explanation = "Imported from the source text; verify the answer and explanation before use."
    zh_content = {"stem": stem, "options": options, "explanation": explanation}
    en_content = dict(zh_content)
    question = Question.create_new(
        qtype=qtype,
        difficulty=Difficulty.MEDIUM,
        bilingual={"zh": zh_content, "en": en_content},
        correct_answer=correct_answer,
        topic=topic_id or "general",
        source="historical_import",
    )
    metadata = question.metadata
    metadata.update(
        {
            "historical_import": True,
            "source_question_number": block.number,
            "translation_missing": True,
            "import_review_required": True,
            "source_ref_status": "imported_text",
            "source_refs": [
                {
                    "source_file": str(source_file or "").strip(),
                    "line_start": block.line_start,
                    "line_end": block.line_start + len(block.lines) - 1,
                    "excerpt": " ".join(block.lines).strip()[:320],
                }
            ],
        }
    )
    if course_id:
        metadata["course_id"] = str(course_id).strip()
    if topic_title:
        metadata["topic_title"] = str(topic_title).strip()
    inferred_id, inferred_title, match_status = _infer_topic(
        stem,
        option_values,
        topic_id=topic_id,
        topic_title=topic_title,
        course_topics=course_topics,
    )
    question.topic = inferred_id
    metadata["topic_match_status"] = match_status
    if inferred_title:
        metadata["topic_title"] = inferred_title
    return question, []


def _infer_topic(
    stem: str,
    options: list[str],
    *,
    topic_id: str,
    topic_title: str,
    course_topics,
) -> tuple[str, str, str]:
    """Return a topic only when a course term produces a clear match."""
    fallback_id = str(topic_id or "general").strip().lower() or "general"
    fallback_title = str(topic_title or "").strip()
    topics = list(course_topics or [])
    if not topics:
        return fallback_id, fallback_title, "unavailable"
    text = " ".join([stem, *options]).casefold()
    scored: list[tuple[int, str, str]] = []
    for topic in topics:
        current_id = str(getattr(topic, "topic_id", "") or "").strip().lower()
        current_title = str(getattr(topic, "title", "") or current_id).strip()
        if not current_id:
            continue
        terms = [
            (current_title, 4),
            (current_id, 3),
            *[(str(value or "").strip(), 2) for value in getattr(topic, "keywords", []) or []],
            *[(str(value or "").strip(), 2) for value in getattr(topic, "aliases", []) or []],
        ]
        score = 0
        seen: set[str] = set()
        for term, weight in terms:
            normalized = term.casefold()
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            if normalized in text:
                score += weight
        if score:
            scored.append((score, current_id, current_title))
    if not scored:
        return fallback_id, fallback_title, "unmatched"
    scored.sort(reverse=True)
    best = scored[0]
    if len(scored) > 1 and scored[1][0] == best[0]:
        return fallback_id, fallback_title, "ambiguous"
    return best[1], best[2], "matched"


def _answer_value(value: str) -> str:
    clean = " ".join(str(value or "").strip().split())
    if not clean:
        return ""
    letter = re.match(r"^([A-Da-d])(?:\b|[.)、．:：])", clean)
    if letter:
        return letter.group(1).upper()
    lowered = clean.casefold().strip("。.!！?？")
    if lowered in _TRUE_WORDS:
        return "true"
    if lowered in _FALSE_WORDS:
        return "false"
    return ""


def _looks_like_true_false(options: list[str], answer: str) -> bool:
    if answer in {"true", "false"}:
        return True
    if len(options) != 2:
        return False
    normalized = {_normalize_boolean_word(option) for option in options}
    return normalized == {"true", "false"}


def _normalize_boolean_word(value: str) -> str:
    clean = re.sub(r"^[A-Da-d]\s*[.)、．:：]?\s*", "", str(value or ""))
    lowered = clean.casefold().strip("。.!！?？ ")
    if lowered in _TRUE_WORDS:
        return "true"
    if lowered in _FALSE_WORDS:
        return "false"
    return lowered


def _true_false_answer(answer: str, options: list[str]) -> str:
    if answer in {"true", "false"}:
        return answer
    if len(options) < 2 or len(answer) != 1:
        return ""
    index = ord(answer.upper()) - ord("A")
    if index < 0 or index >= len(options):
        return ""
    normalized = _normalize_boolean_word(options[index])
    return normalized if normalized in {"true", "false"} else ""
