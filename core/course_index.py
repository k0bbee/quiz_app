"""Persistent course retrieval index with in-memory query caching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from core.term_extraction import extract_course_terms
from models.course_project import CourseProject

_MAX_PAYLOAD_CACHE_SIZE = 24
_PAYLOAD_CACHE: dict[tuple[str, str], str] = {}


@dataclass
class CourseChunk:
    """A retrievable course-content chunk."""

    chunk_id: str
    source: str
    heading: str
    text: str
    terms: list[str]

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "heading": self.heading,
            "text": self.text,
            "terms": self.terms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CourseChunk":
        return cls(
            chunk_id=data.get("chunk_id", ""),
            source=data.get("source", ""),
            heading=data.get("heading", ""),
            text=data.get("text", ""),
            terms=data.get("terms", []),
        )


def build_course_index(summary_markdown: str, documents: list[dict] | None = None) -> list[dict]:
    """Build serialized chunk index from summary Markdown.

    The index is intentionally simple and portable: chunk text plus top terms.
    This is fast enough for local course notes and can later be swapped for an
    embedding index without changing project persistence.
    """
    chunks: list[CourseChunk] = []
    for i, (heading, text) in enumerate(_split_chunks(summary_markdown)):
        terms = extract_terms(f"{heading}\n{text}", limit=24)
        chunks.append(CourseChunk(
            chunk_id=f"chunk-{i:04d}",
            source="summary",
            heading=heading,
            text=text,
            terms=terms,
        ))
    return [chunk.to_dict() for chunk in chunks]


def retrieve_course_context(
    project: CourseProject,
    selected_topics: list[str],
    max_chars: int = 22000,
) -> str:
    """Retrieve relevant context from a project, using cached scoring."""
    topic_key = tuple(sorted(str(t) for t in selected_topics))
    payload_key = (project.course_id, project.updated_at)
    if payload_key not in _PAYLOAD_CACHE:
        _PAYLOAD_CACHE[payload_key] = _project_payload(project)
        _trim_payload_cache()
    return _retrieve_cached(project.course_id, project.updated_at, topic_key, max_chars)


@lru_cache(maxsize=128)
def _retrieve_cached(
    course_id: str,
    updated_at: str,
    topic_key: tuple[str, ...],
    max_chars: int,
) -> str:
    """Cached retrieval; payload is a compact serialized index/summary string."""
    import json

    payload = _PAYLOAD_CACHE.get((course_id, updated_at), "")
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return ""
    chunks = [CourseChunk.from_dict(item) for item in data.get("index", [])]
    if not chunks:
        return data.get("summary", "")[:max_chars]

    terms = []
    topic_keywords = data.get("topic_keywords", {})
    for topic in topic_key:
        terms.extend(extract_terms(topic, limit=12))
        terms.append(topic.lower())
        terms.extend(_expanded_terms(topic_keywords.get(topic, [])))
        terms.extend(_expanded_terms(topic_keywords.get(topic.lower(), [])))

    if not terms:
        terms = extract_terms(data.get("summary", ""), limit=24)

    scored = []
    term_set = {t.lower() for t in terms if t}
    for chunk in chunks:
        text_lower = f"{chunk.heading}\n{chunk.text}".lower()
        score = 0
        for term in term_set:
            if term in chunk.terms:
                score += 8
            count = text_lower.count(term)
            if count:
                score += min(count, 5)
        if score > 0:
            scored.append((score, chunk))

    if not scored:
        scored = [(1, chunk) for chunk in chunks[:8]]
    scored.sort(key=lambda item: item[0], reverse=True)

    parts = ["以下是当前课程项目中与所选主题最相关的缓存检索片段："]
    used = len(parts[0])
    excerpt_count = max(1, min(len(scored), 4))
    per_chunk_budget = max(180, max_chars // excerpt_count)
    for index, (_, chunk) in enumerate(scored):
        remaining = max_chars - used
        if remaining <= 0:
            break
        block_budget = remaining
        if index < len(scored) - 1:
            block_budget = min(remaining, per_chunk_budget)
        block = _chunk_block(chunk, term_set, block_budget)
        if block.strip():
            parts.append(block)
            used += len(block)
        if used >= max_chars:
            break
    return "".join(parts)


def _chunk_block(chunk: CourseChunk, term_set: set[str], budget: int) -> str:
    """Format a chunk within budget while preserving its heading and a focused body."""
    heading = f"\n\n## {chunk.heading}\n\n"
    if budget <= len(heading):
        return heading[:budget]
    body_budget = budget - len(heading)
    text = chunk.text.strip()
    if len(text) <= body_budget:
        return f"{heading}{text}"
    return f"{heading}{_focused_excerpt(text, term_set, body_budget)}"


def _focused_excerpt(text: str, term_set: set[str], limit: int) -> str:
    """Return a compact excerpt around the earliest selected-topic match."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text

    lowered = text.lower()
    positions = [
        position
        for term in term_set
        if term
        for position in [lowered.find(term)]
        if position >= 0
    ]
    anchor = min(positions) if positions else 0

    ellipsis_budget = 2
    window = max(1, limit - ellipsis_budget)
    start = max(0, anchor - window // 4)
    end = min(len(text), start + window)
    start = max(0, end - window)
    excerpt = text[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"[:limit]


def _project_payload(project: CourseProject) -> str:
    """Serialize stable fields for cache key payload."""
    import json

    return json.dumps(
        {
            "summary": project.summary_markdown,
            "index": project.documents[0].get("_course_index", []) if project.documents else [],
            "topic_keywords": _topic_keyword_payload(project),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _topic_keyword_payload(project: CourseProject) -> dict[str, list[str]]:
    topic_keywords: dict[str, list[str]] = {}
    for topic in getattr(project, "topics", []) or []:
        title = str(getattr(topic, "title", "")).strip()
        keywords = list(getattr(topic, "keywords", []) or [])
        for key in _topic_lookup_keys(
            title,
            str(getattr(topic, "topic_id", "")).strip(),
        ):
            topic_keywords[key] = keywords
    return topic_keywords


def _expanded_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    for value in values or []:
        clean = str(value or "").strip()
        if not clean:
            continue
        terms.append(clean.lower())
        terms.extend(extract_terms(clean, limit=12))
    return terms


def _topic_lookup_keys(*values: str) -> list[str]:
    keys: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean:
            continue
        slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", clean).strip("_").lower()
        for candidate in (clean, clean.lower(), slug):
            if candidate and candidate not in keys:
                keys.append(candidate)
    return keys


def _trim_payload_cache() -> None:
    """Keep only recent course payloads; retrieval results are separately LRU-cached."""
    while len(_PAYLOAD_CACHE) > _MAX_PAYLOAD_CACHE_SIZE:
        oldest_key = next(iter(_PAYLOAD_CACHE))
        _PAYLOAD_CACHE.pop(oldest_key, None)


def attach_index_to_project(project: CourseProject) -> CourseProject:
    """Attach/rebuild retrieval index inside project metadata."""
    index = build_course_index(project.summary_markdown, project.documents)
    if not project.documents:
        project.documents = [{"path": "", "title": "summary", "extension": ".md"}]
    project.documents[0]["_course_index"] = index
    return project


def extract_terms(text: str, limit: int = 20) -> list[str]:
    """Extract high-value terms from arbitrary course text."""
    return list(extract_course_terms(text, limit=limit))


def _split_chunks(markdown: str) -> list[tuple[str, str]]:
    """Split Markdown by headings into bounded chunks."""
    chunks: list[tuple[str, str]] = []
    heading = "Course Summary"
    lines: list[str] = []
    for line in markdown.splitlines():
        if re.match(r"^#{1,4}\s+", line):
            if lines:
                chunks.extend(_bounded_chunks(heading, "\n".join(lines).strip()))
            heading = re.sub(r"^#{1,4}\s+", "", line).strip()
            lines = []
        else:
            lines.append(line)
    if lines:
        chunks.extend(_bounded_chunks(heading, "\n".join(lines).strip()))
    return [(h, t) for h, t in chunks if t]


def _bounded_chunks(heading: str, text: str, size: int = 1800) -> list[tuple[str, str]]:
    if len(text) <= size:
        return [(heading, text)]
    parts = []
    for i in range(0, len(text), size):
        parts.append((f"{heading} ({i // size + 1})", text[i:i + size]))
    return parts
