"""Build lightweight, render-ready data for the course workspace."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CourseSourceView:
    name: str
    extension: str
    page_count: int
    word_count: int
    warning: str


@dataclass(frozen=True, slots=True)
class CourseTopicView:
    topic_id: str
    title: str
    in_exam_scope: bool
    source_count: int
    question_count: int


@dataclass(frozen=True, slots=True)
class CourseHubView:
    title: str
    document_count: int
    topic_count: int
    exam_topic_count: int
    question_count: int
    warning_count: int
    covered_exam_topic_count: int
    uncovered_exam_topic_count: int
    summary_source: str
    sources: tuple[CourseSourceView, ...]
    topics: tuple[CourseTopicView, ...]


def build_course_hub_view(project, question_bank=None) -> CourseHubView:
    """Combine persisted course metadata with the lightweight question index."""
    topic_counts: Counter[str] = Counter()
    question_count = 0
    if question_bank is not None:
        try:
            topic_index = question_bank.topic_index(course_id=project.course_id)
        except Exception:
            topic_index = {}
        if not isinstance(topic_index, Mapping):
            topic_index = {}
        question_count = len(topic_index)
        topic_counts.update(
            str(topic_id or "").strip()
            for topic_id, _title in topic_index.values()
            if str(topic_id or "").strip()
        )

    exam_topic_ids = {
        topic.topic_id
        for topic in project.exam_topics()
        if topic.topic_id
    }
    sources = tuple(_source_view(document) for document in project.documents)
    topics = tuple(
        CourseTopicView(
            topic_id=topic.topic_id,
            title=topic.title or topic.topic_id,
            in_exam_scope=topic.topic_id in exam_topic_ids,
            source_count=len({
                str(path or "").strip()
                for path in topic.source_files
                if str(path or "").strip()
            }),
            question_count=topic_counts[topic.topic_id],
        )
        for topic in project.topics
    )
    covered_exam_topics = sum(
        topic.in_exam_scope and topic.question_count > 0
        for topic in topics
    )
    return CourseHubView(
        title=project.title,
        document_count=len(sources),
        topic_count=len(topics),
        exam_topic_count=len(exam_topic_ids),
        question_count=question_count,
        warning_count=sum(bool(source.warning) for source in sources),
        covered_exam_topic_count=covered_exam_topics,
        uncovered_exam_topic_count=max(
            0,
            len(exam_topic_ids) - covered_exam_topics,
        ),
        summary_source=str(project.summary_source or "local"),
        sources=sources,
        topics=topics,
    )


def _source_view(document: dict) -> CourseSourceView:
    path = str(document.get("path", "") or "").strip()
    title = str(document.get("title", "") or "").strip()
    filename = str(document.get("filename", "") or "").strip()
    extension = str(document.get("extension", "") or "").strip()
    warnings = document.get("warnings", [])
    if isinstance(warnings, str):
        warning = warnings.strip()
    else:
        warning = "; ".join(
            str(item or "").strip()
            for item in (warnings or [])
            if str(item or "").strip()
        )
    pages = document.get("pages", [])
    page_count = _non_negative_int(
        document.get("page_count", len(pages) if isinstance(pages, list) else 0)
    )
    return CourseSourceView(
        name=title or Path(path).name or filename or "Unknown source",
        extension=extension or Path(path or filename).suffix,
        page_count=page_count,
        word_count=_non_negative_int(document.get("word_count", 0)),
        warning=warning,
    )


def _non_negative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
