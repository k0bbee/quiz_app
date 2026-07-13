"""Explainable local structure and course-topic analysis for historical exams."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import math
import re

from models.past_exam import (
    PastExamAnalysis,
    PastExamQuestionTypeProfile,
    PastExamTopicProfile,
)


_SECTION_TYPES = (
    ("scenario_choice", ("情境选择题", "场景选择题", "scenario choice")),
    ("multiple_choice", ("单项选择题", "多项选择题", "选择题", "multiple choice")),
    ("true_false", ("判断题", "正误题", "true false", "true/false")),
    ("fill_in_blank", ("填空题", "fill in the blank")),
    ("matching", ("匹配题", "配对题", "matching")),
    ("ordering", ("排序题", "ordering")),
    (
        "short_answer",
        (
            "简答题", "论述题", "材料分析题", "案例分析题", "名词解释",
            "计算题", "short answer", "essay", "case analysis",
        ),
    ),
)
_SECTION_PREFIX = re.compile(
    r"^(?:第?\s*[一二三四五六七八九十百\d]+\s*[、.．:：)）]|"
    r"[（(]?\s*[一二三四五六七八九十百\d]+\s*[)）]\s*|part\s+[ivx\d]+\b)",
    re.IGNORECASE,
)
_QUESTION_NUMBER = re.compile(
    r"^\s*(?:\d{1,3}\s*[.、．)）]|[（(]\s*\d{1,3}\s*[)）]|"
    r"[一二三四五六七八九十]{1,3}\s*[、.．)）])"
)
_EXPLICIT_COUNT = re.compile(r"(?:共\s*)?(\d{1,3})\s*题")


class PastExamAnalyzer:
    """Build a deterministic profile without inventing unavailable structure."""

    def analyze(self, text: str, course, *, source_sha256: str, task=None) -> PastExamAnalysis:
        normalized_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        _task_report(task, "analyzing_structure", 0, 2)
        question_types, type_warnings = _analyze_sections(normalized_text)
        _task_report(task, "analyzing_topics", 1, 2)
        topic_profile, topic_warnings = _analyze_topics(normalized_text, course)
        _task_check(task)
        return PastExamAnalysis(
            source_sha256=str(source_sha256 or ""),
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            detected_question_count=sum(item.count for item in question_types),
            question_types=tuple(question_types),
            topic_profile=tuple(topic_profile),
            warnings=tuple(type_warnings + topic_warnings),
        )


class PastExamAnalysisService:
    """Load the assigned course and persist a fresh analysis for one exam."""

    def __init__(self, exam_manager, course_manager, analyzer=None):
        self.exam_manager = exam_manager
        self.course_manager = course_manager
        self.analyzer = analyzer or PastExamAnalyzer()

    def analyze(self, exam_id: str, task=None) -> PastExamAnalysis:
        _task_report(task, "loading_exam", 0, 3)
        record = self.exam_manager.get(exam_id)
        if record is None:
            raise ValueError("Historical exam does not exist")
        if not record.course_id:
            raise ValueError("Historical exam requires an assigned course")
        course = self.course_manager.get(record.course_id)
        if course is None:
            raise ValueError("Historical exam assigned course does not exist")
        content = self.exam_manager.get_content(exam_id)
        if content is None or not content.text.strip():
            raise ValueError("Historical exam has no extracted text")

        analysis = self.analyzer.analyze(
            content.text,
            course,
            source_sha256=record.source_sha256,
            task=task,
        )
        _task_report(task, "saving_analysis", 2, 3)
        if not self.exam_manager.save_analysis(exam_id, analysis):
            raise OSError("Failed to save historical exam analysis")
        completed = replace(record, analysis_status="complete")
        if not self.exam_manager.save_record(completed):
            raise OSError("Failed to mark historical exam analysis complete")
        if task is not None:
            task.complete("analysis_complete")
        return analysis


def _analyze_sections(text: str):
    lines = [line.strip() for line in text.splitlines()]
    headings = []
    for index, line in enumerate(lines):
        question_type = _heading_type(line)
        if question_type:
            headings.append((index, question_type, line[:160]))

    profiles = []
    warnings = []
    for position, (start, question_type, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        numbered_count = sum(bool(_QUESTION_NUMBER.match(line)) for line in lines[start + 1:end])
        explicit_match = _EXPLICIT_COUNT.search(heading)
        explicit_count = int(explicit_match.group(1)) if explicit_match else 0
        count = numbered_count or explicit_count
        if count <= 0:
            continue
        confidence = 0.95 if numbered_count and explicit_count == numbered_count else 0.84
        if numbered_count and explicit_count and numbered_count != explicit_count:
            warnings.append(
                f"Section count differs from numbered questions: {heading} "
                f"({explicit_count} vs {numbered_count})"
            )
            confidence = 0.72
        evidence = [heading]
        evidence.extend(line[:160] for line in lines[start + 1:end] if _QUESTION_NUMBER.match(line))
        profiles.append(
            PastExamQuestionTypeProfile(
                question_type=question_type,
                count=count,
                confidence=confidence,
                evidence=tuple(evidence[:4]),
            )
        )

    combined = {}
    for profile in profiles:
        previous = combined.get(profile.question_type)
        if previous is None:
            combined[profile.question_type] = profile
        else:
            combined[profile.question_type] = PastExamQuestionTypeProfile(
                question_type=profile.question_type,
                count=previous.count + profile.count,
                confidence=min(previous.confidence, profile.confidence),
                evidence=(previous.evidence + profile.evidence)[:6],
            )
    if not combined:
        warnings.append("No explicit question-type sections were detected")
    return list(combined.values()), warnings


def _heading_type(line: str):
    normalized = _normalize(line)
    if not normalized or len(line) > 160:
        return None
    for question_type, labels in _SECTION_TYPES:
        for label in labels:
            normalized_label = _normalize(label)
            if normalized_label not in normalized:
                continue
            starts_with_label = normalized.startswith(normalized_label)
            if starts_with_label or _SECTION_PREFIX.match(line.strip()):
                return question_type
    return None


def _analyze_topics(text: str, course):
    topics = list(getattr(course, "topics", []) or [])
    if not topics:
        return [], ["Assigned course has no topics to match"]
    normalized_text = _normalize(text)
    topic_terms = []
    owners = defaultdict(set)
    for topic in topics:
        topic_id = str(getattr(topic, "topic_id", "") or "").strip()
        terms = {}

        def add(value, weight):
            normalized = _normalize(value)
            if _useful_term(normalized):
                terms[normalized] = max(weight, terms.get(normalized, 0.0))

        add(getattr(topic, "title", ""), 4.0)
        add(topic_id.replace("_", " "), 2.5)
        for alias in getattr(topic, "aliases", []) or []:
            add(alias, 3.5)
        for keyword in getattr(topic, "keywords", []) or []:
            add(keyword, 1.0)
        topic_terms.append((topic, topic_id, terms))
        for term in terms:
            owners[term].add(topic_id)

    scored = []
    for topic, topic_id, terms in topic_terms:
        score = 0.0
        match_count = 0
        matched_terms = []
        for term, importance in terms.items():
            if len(owners[term]) > 1:
                continue
            occurrences = _term_count(normalized_text, term)
            if occurrences:
                match_count += occurrences
                score += importance * (1.0 + math.log2(occurrences))
                matched_terms.append(term)
        scored.append((topic, topic_id, score, match_count, tuple(sorted(matched_terms))))

    weights = _percentage_weights([item[2] for item in scored])
    profiles = [
        PastExamTopicProfile(
            topic_id=topic_id,
            topic_title=str(getattr(topic, "title", "") or topic_id),
            weight=weight,
            match_count=match_count,
            matched_terms=matched_terms,
        )
        for (topic, topic_id, _score, match_count, matched_terms), weight in zip(scored, weights)
    ]
    profiles.sort(key=lambda item: (-item.weight, item.topic_title.casefold(), item.topic_id))
    warnings = [] if any(weights) else ["No course-topic evidence was detected"]
    return profiles, warnings


def _percentage_weights(scores):
    total = sum(scores)
    if total <= 0:
        return [0 for _score in scores]
    raw = [score * 100.0 / total for score in scores]
    result = [int(value) for value in raw]
    remaining = 100 - sum(result)
    order = sorted(range(len(raw)), key=lambda index: (-(raw[index] - result[index]), index))
    for index in order[:remaining]:
        result[index] += 1
    return result


def _normalize(value) -> str:
    text = str(value or "").casefold().replace("_", " ").replace("/", " ")
    text = re.sub(r"[^\w\u3400-\u9fff]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _useful_term(term: str) -> bool:
    compact = term.replace(" ", "")
    if any("\u3400" <= char <= "\u9fff" for char in compact):
        return len(compact) >= 2
    return len(compact) >= 3


def _term_count(text: str, term: str) -> int:
    if not text or not term:
        return 0
    if any("\u3400" <= char <= "\u9fff" for char in term):
        return text.count(term)
    return len(re.findall(rf"(?<!\w){re.escape(term)}(?!\w)", text))


def _task_check(task):
    if task is not None:
        task.check_cancelled()


def _task_report(task, stage, current=0, total=0):
    if task is not None:
        task.report(stage, current=current, total=total)
