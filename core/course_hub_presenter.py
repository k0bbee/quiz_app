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
    path: str = ""
    excerpt: str = ""
    topic_titles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CourseTopicView:
    topic_id: str
    title: str
    in_exam_scope: bool
    source_count: int
    question_count: int
    generation_weight: int = 0
    mastery: str = "—"
    recent_practice: str = "—"
    status: str = "not_started"

    @property
    def exam_weight(self) -> int:
        """Backward-compatible alias for the generation profile weight.

        CourseHubView does not currently persist a separate exam allocation;
        the value shown here comes from the course's question-generation
        profile. Keep the old attribute readable for integrations while
        exposing the accurate semantic name to new callers.
        """
        return self.generation_weight


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
    quality_warning_count: int
    pending_review_question_count: int
    weak_topic_count: int
    summary_source: str
    sources: tuple[CourseSourceView, ...]
    topics: tuple[CourseTopicView, ...]


def build_course_hub_view(
    project,
    question_bank=None,
    *,
    progress_manager=None,
    mastery_overrides=None,
    generation_draft_store=None,
) -> CourseHubView:
    """Combine persisted course metadata with the lightweight question index."""
    topic_counts: Counter[str] = Counter()
    question_ids_by_topic: dict[str, set[str]] = {}
    topic_index = {}
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
        for question_id, row in topic_index.items():
            if not isinstance(row, (tuple, list)) or not row:
                continue
            topic_id = str(row[0] or "").strip()
            if topic_id:
                question_ids_by_topic.setdefault(topic_id, set()).add(
                    str(question_id)
                )

    exam_topic_ids = {
        topic.topic_id
        for topic in project.exam_topics()
        if topic.topic_id
    }
    source_topics: dict[str, list[str]] = {}
    for topic in project.topics:
        for path in topic.source_files:
            normalized = str(path or "").strip().casefold()
            if normalized:
                source_topics.setdefault(normalized, []).append(
                    topic.title or topic.topic_id
                )
    sources = tuple(
        _source_view(document, source_topics=source_topics)
        for document in project.documents
    )
    learning = _topic_learning(
        question_ids_by_topic,
        progress_manager=progress_manager,
    )
    weights = _generation_weights(project)
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
            generation_weight=weights.get(topic.topic_id, 0),
            mastery=_topic_mastery_text(
                project.course_id,
                topic.topic_id,
                learning.get(topic.topic_id),
                mastery_overrides,
            ),
            recent_practice=(
                learning.get(topic.topic_id, {}).get("recent", "") or "—"
            ),
            status=_topic_status(
                project.course_id,
                topic.topic_id,
                question_count=topic_counts[topic.topic_id],
                learning=learning.get(topic.topic_id),
                mastery_overrides=mastery_overrides,
            ),
        )
        for topic in project.topics
    )
    covered_exam_topics = sum(
        topic.in_exam_scope and topic.question_count > 0
        for topic in topics
    )
    quality_warning_count = _quality_warning_count(
        question_bank,
        project.course_id,
        tuple(topic_index) if question_bank is not None else (),
    )
    pending_review_question_count = _pending_review_count(
        generation_draft_store,
        project.course_id,
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
        quality_warning_count=quality_warning_count,
        pending_review_question_count=pending_review_question_count,
        weak_topic_count=sum(topic.status == "weak" for topic in topics),
        summary_source=str(project.summary_source or "local"),
        sources=sources,
        topics=topics,
    )


def _source_view(
    document: dict,
    *,
    source_topics: dict[str, list[str]] | None = None,
) -> CourseSourceView:
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
        path=path or filename,
        excerpt=_document_excerpt(document, pages),
        topic_titles=tuple(
            (source_topics or {}).get((path or filename).casefold(), ())
        ),
    )


def _document_excerpt(document: dict, pages) -> str:
    text = str(
        document.get("text", "")
        or document.get("content", "")
        or ""
    ).strip()
    if not text and isinstance(pages, list):
        text = "\n".join(
            str(page or "").strip()
            for page in pages[:2]
            if str(page or "").strip()
        )
    return text[:500]


def _generation_weights(project) -> dict[str, int]:
    profile = getattr(project, "generation_profile", {}) or {}
    raw = profile.get("topic_weights", {}) if isinstance(profile, dict) else {}
    weights = {}
    if isinstance(raw, dict):
        for topic_id, value in raw.items():
            try:
                numeric = max(0, int(round(float(value))))
            except (TypeError, ValueError):
                continue
            key = str(topic_id or "").strip()
            if key:
                weights[key] = numeric
    return weights


def _topic_learning(question_ids_by_topic, *, progress_manager) -> dict[str, dict]:
    if progress_manager is None:
        return {}
    try:
        records = progress_manager.load_all()
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(records, (list, tuple)):
        return {}
    question_to_topic = {
        question_id: topic_id
        for topic_id, question_ids in question_ids_by_topic.items()
        for question_id in question_ids
    }
    learning: dict[str, dict] = {}
    for record in records or ():
        if getattr(record, "status", "") != "completed":
            continue
        recent = str(
            getattr(record, "completed_at", "")
            or getattr(record, "started_at", "")
            or ""
        )[:10]
        for answer in getattr(record, "answers", ()) or ():
            if getattr(answer, "skipped", False):
                continue
            topic_id = question_to_topic.get(
                str(getattr(answer, "question_id", "") or "")
            )
            if not topic_id:
                continue
            row = learning.setdefault(
                topic_id,
                {"attempts": 0, "correct": 0, "recent": ""},
            )
            row["attempts"] += 1
            row["correct"] += int(bool(getattr(answer, "is_correct", False)))
            row["recent"] = max(row["recent"], recent)
    return learning


def _is_mastered(course_id, topic_id, mastery_overrides) -> bool:
    if mastery_overrides is None:
        return False
    try:
        return bool(mastery_overrides.is_topic_mastered(course_id, topic_id))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _topic_mastery_text(course_id, topic_id, learning, mastery_overrides) -> str:
    if _is_mastered(course_id, topic_id, mastery_overrides):
        return "mastered"
    attempts = int((learning or {}).get("attempts", 0) or 0)
    if not attempts:
        return "—"
    correct = int((learning or {}).get("correct", 0) or 0)
    return f"{correct / attempts:.0%}"


def _topic_status(
    course_id,
    topic_id,
    *,
    question_count,
    learning,
    mastery_overrides,
) -> str:
    if _is_mastered(course_id, topic_id, mastery_overrides):
        return "mastered"
    if not question_count:
        return "uncovered"
    attempts = int((learning or {}).get("attempts", 0) or 0)
    if not attempts:
        return "not_started"
    correct = int((learning or {}).get("correct", 0) or 0)
    return "weak" if correct / attempts < 0.6 else "learning"


def _quality_warning_count(question_bank, course_id: str, question_ids) -> int:
    if question_bank is None or not question_ids:
        return 0
    try:
        questions = question_bank.get_many(
            question_ids,
            course_id=course_id,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return 0
    keys = (
        "quality_warnings",
        "quality_issues",
        "validation_issues",
        "warnings",
    )
    return sum(
        any((getattr(question, "metadata", {}) or {}).get(key) for key in keys)
        for question in questions or ()
    )


def _pending_review_count(store, course_id: str) -> int:
    if store is None:
        return 0
    try:
        draft = store.get(course_id)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0
    return len(getattr(draft, "questions", ()) or ()) if draft else 0


def _non_negative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
