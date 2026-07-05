"""Persistent course retrieval index with in-memory query caching."""

from __future__ import annotations

import re
import hashlib
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


@dataclass
class SourceChunk:
    """A page/slide-level chunk tied to an original course source file."""

    chunk_id: str
    course_id: str
    source_file: str
    source_type: str
    page_or_slide: int | None
    heading: str
    text: str
    terms: list[str]
    topic_ids: list[str]
    content_hash: str

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "course_id": self.course_id,
            "source_file": self.source_file,
            "source_type": self.source_type,
            "page_or_slide": self.page_or_slide,
            "heading": self.heading,
            "text": self.text,
            "terms": self.terms,
            "topic_ids": self.topic_ids,
            "content_hash": self.content_hash,
        }

    def to_ref(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source_file": self.source_file,
            "page_or_slide": self.page_or_slide,
            "heading": self.heading,
            "excerpt": _ref_excerpt(self.text),
            "content_hash": self.content_hash[:12],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SourceChunk":
        return cls(
            chunk_id=data.get("chunk_id", ""),
            course_id=data.get("course_id", ""),
            source_file=data.get("source_file", ""),
            source_type=data.get("source_type", ""),
            page_or_slide=data.get("page_or_slide"),
            heading=data.get("heading", ""),
            text=data.get("text", ""),
            terms=data.get("terms", []),
            topic_ids=data.get("topic_ids", []),
            content_hash=data.get("content_hash", ""),
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


def build_source_index(project: CourseProject) -> list[dict]:
    """Build page/slide-level chunks from original document text stored on a project."""
    stored_index = [
        item
        for document in getattr(project, "documents", []) or []
        for item in (document.get("_source_index", []) or [])
        if isinstance(item, dict)
    ]
    if stored_index:
        return stored_index

    chunks: list[SourceChunk] = []
    for document in getattr(project, "documents", []) or []:
        pages = document.get("pages", []) or []
        if not pages:
            continue
        source_file = _source_file_name(document)
        source_type = _source_type(document)
        title = str(document.get("title") or source_file or "source").strip()
        for page_index, page_text in enumerate(pages, start=1):
            text = str(page_text or "").strip()
            if not text:
                continue
            content_hash = _content_hash(text)
            chunk_id = _source_chunk_id(source_file, page_index, content_hash)
            heading = f"{title} {_page_label(source_type, page_index)}"
            chunks.append(SourceChunk(
                chunk_id=chunk_id,
                course_id=getattr(project, "course_id", ""),
                source_file=source_file,
                source_type=source_type,
                page_or_slide=page_index,
                heading=heading,
                text=text,
                terms=extract_terms(f"{heading}\n{text}", limit=24),
                topic_ids=_source_topic_ids(project, source_file, text),
                content_hash=content_hash,
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


def retrieve_course_source_refs(
    project: CourseProject,
    selected_topics: list[str],
    limit: int = 3,
) -> list[dict]:
    """Return the strongest original-source references for selected topics."""
    source_chunks = _source_chunks_for_project(project)
    if not source_chunks:
        return []
    topic_values = {str(topic or "").strip() for topic in selected_topics if str(topic or "").strip()}
    topic_keys = {_match_key(topic) for topic in topic_values}
    terms: list[str] = []
    for topic in topic_values:
        terms.extend(extract_terms(topic, limit=12))
        terms.append(topic.lower())
    topic_keywords = _topic_keyword_payload(project)
    for topic in topic_values:
        terms.extend(_expanded_terms(topic_keywords.get(topic, [])))
        terms.extend(_expanded_terms(topic_keywords.get(topic.lower(), [])))
    term_set = {term.lower() for term in terms if term}
    scored = _score_source_chunks(source_chunks, topic_keys, term_set, allow_fallback=False)
    return [chunk.to_ref() for _, chunk in scored[:limit]]


def resolve_course_source_ref(project: CourseProject, source_ref: dict) -> dict:
    """Resolve a stored source_ref against the current course source index.

    Prefer the current chunk_id when it still exists. If the chunk_id changed
    after re-import or source-index rebuild, recover by source_file,
    page_or_slide, and content_hash.
    """
    if not isinstance(source_ref, dict):
        return {}
    source_chunks = _source_chunks_for_project(project)
    if not source_chunks:
        return {}

    chunk_id = str(source_ref.get("chunk_id", "") or "").strip()
    for chunk in source_chunks:
        if chunk.chunk_id == chunk_id:
            return _resolved_ref(chunk, source_ref)

    for chunk in source_chunks:
        if _source_ref_matches_chunk_identity(source_ref, chunk):
            return _resolved_ref(chunk, source_ref)
    return {}


def enrich_course_source_refs(project: CourseProject, source_refs) -> list[dict]:
    """Return source_refs enriched from the current source index when possible."""
    if not isinstance(source_refs, list):
        return []
    enriched: list[dict] = []
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        resolved = resolve_course_source_ref(project, ref)
        enriched.append(resolved or dict(ref))
    return enriched


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
    source_chunks = [SourceChunk.from_dict(item) for item in data.get("source_index", [])]
    if not chunks and not source_chunks:
        return data.get("summary", "")[:max_chars]

    terms = []
    topic_keywords = data.get("topic_keywords", {})
    selected_topic_keys = {_match_key(topic) for topic in topic_key}
    other_topic_keys = {
        _match_key(topic)
        for topic in data.get("topic_titles", [])
        if _match_key(topic) not in selected_topic_keys
    }
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
        if _heading_matches_any_topic(chunk.heading, other_topic_keys):
            continue
        text_lower = f"{chunk.heading}\n{chunk.text}".lower()
        score = 0
        if _heading_matches_any_topic(chunk.heading, selected_topic_keys):
            score += 20
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
    scored_sources = _score_source_chunks(source_chunks, selected_topic_keys, term_set)

    parts = ["以下是当前课程项目中与所选主题最相关的缓存检索片段："]
    used = len(parts[0])
    combined_count = len(scored) + len(scored_sources)
    excerpt_count = max(1, min(combined_count or 1, 5))
    per_chunk_budget = max(180, max_chars // excerpt_count)
    combined = [("summary", score, chunk) for score, chunk in scored[:3]]
    combined.extend(("source", score, chunk) for score, chunk in scored_sources[:3])
    combined.sort(key=lambda item: item[1], reverse=True)
    for index, (kind, _, chunk) in enumerate(combined):
        remaining = max_chars - used
        if remaining <= 0:
            break
        block_budget = remaining
        if index < len(combined) - 1:
            block_budget = min(remaining, per_chunk_budget)
        if kind == "source":
            block = _source_chunk_block(chunk, term_set, block_budget)
        else:
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


def _source_chunk_block(chunk: SourceChunk, term_set: set[str], budget: int) -> str:
    """Format a source chunk with stable evidence metadata."""
    location = ""
    if chunk.page_or_slide:
        label = "slide" if chunk.source_type == "pptx" else "page"
        location = f" {label} {chunk.page_or_slide}"
    heading = f"\n\n## Evidence {chunk.chunk_id} — {chunk.source_file}{location}\n\n"
    if budget <= len(heading):
        return heading[:budget]
    body_budget = budget - len(heading)
    text = chunk.text.strip()
    if len(text) <= body_budget:
        return f"{heading}{text}"
    return f"{heading}{_focused_excerpt(text, term_set, body_budget)}"


def _ref_excerpt(text: str, limit: int = 320) -> str:
    """Return a compact source snippet suitable for persisted source_refs."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "…"


def _project_payload(project: CourseProject) -> str:
    """Serialize stable fields for cache key payload."""
    import json

    return json.dumps(
        {
            "summary": project.summary_markdown,
            "index": build_course_index(project.summary_markdown),
            "source_index": build_source_index(project),
            "topic_keywords": _topic_keyword_payload(project),
            "topic_titles": _topic_title_payload(project),
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


def _topic_title_payload(project: CourseProject) -> list[str]:
    titles: list[str] = []
    for topic in getattr(project, "topics", []) or []:
        for value in (
            str(getattr(topic, "title", "") or "").strip(),
            str(getattr(topic, "topic_id", "") or "").strip(),
        ):
            if value and value not in titles:
                titles.append(value)
    return titles


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
    source_index = build_source_index(project)
    if not project.documents:
        project.documents = [{"path": "", "title": "summary", "extension": ".md"}]
    project.documents[0]["_course_index"] = index
    project.documents[0]["_source_index"] = source_index
    return project


def extract_terms(text: str, limit: int = 20) -> list[str]:
    """Extract high-value terms from arbitrary course text."""
    return list(extract_course_terms(text, limit=limit))


def _split_chunks(markdown: str) -> list[tuple[str, str]]:
    """Split Markdown by headings into bounded chunks."""
    chunks: list[tuple[str, str]] = []
    heading_stack: list[tuple[int, str]] = [(0, "Course Summary")]
    lines: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if match:
            if lines:
                chunks.extend(_bounded_chunks(_current_heading(heading_stack), "\n".join(lines).strip()))
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack = [
                (existing_level, existing_title)
                for existing_level, existing_title in heading_stack
                if existing_level < level
            ]
            heading_stack.append((level, title))
            lines = []
        else:
            lines.append(line)
    if lines:
        chunks.extend(_bounded_chunks(_current_heading(heading_stack), "\n".join(lines).strip()))
    return [(h, t) for h, t in chunks if t]


def _current_heading(heading_stack: list[tuple[int, str]]) -> str:
    titles = [title for level, title in heading_stack if level > 0 and title]
    return " / ".join(titles) if titles else "Course Summary"


def _bounded_chunks(heading: str, text: str, size: int = 1800) -> list[tuple[str, str]]:
    if len(text) <= size:
        return [(heading, text)]
    parts = []
    for i in range(0, len(text), size):
        parts.append((f"{heading} ({i // size + 1})", text[i:i + size]))
    return parts


def _match_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9\u4e00-\u9fff]+", str(value or "").lower()))


def _heading_matches_any_topic(heading: str, topic_keys: set[str]) -> bool:
    heading_key = _match_key(heading)
    if not heading_key:
        return False
    return any(topic_key and topic_key in heading_key for topic_key in topic_keys)


def _source_chunks_for_project(project: CourseProject) -> list[SourceChunk]:
    return [SourceChunk.from_dict(item) for item in build_source_index(project)]


def _resolved_ref(chunk: SourceChunk, original_ref: dict) -> dict:
    ref = chunk.to_ref()
    old_chunk_id = str(original_ref.get("chunk_id", "") or "").strip()
    if old_chunk_id and old_chunk_id != chunk.chunk_id:
        ref["resolved_from_chunk_id"] = old_chunk_id
    return ref


def _source_ref_matches_chunk_identity(source_ref: dict, chunk: SourceChunk) -> bool:
    ref_hash = str(source_ref.get("content_hash", "") or "").strip().lower()
    if not ref_hash or not chunk.content_hash.startswith(ref_hash):
        return False
    ref_file = _source_ref_file_name(source_ref)
    if ref_file and ref_file != chunk.source_file.lower():
        return False
    ref_page = source_ref.get("page_or_slide")
    if ref_page not in ("", None):
        try:
            if int(ref_page) != chunk.page_or_slide:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _source_ref_file_name(source_ref: dict) -> str:
    source_file = str(source_ref.get("source_file", "") or "").strip().lower()
    if not source_file:
        return ""
    return re.split(r"[\\/]", source_file)[-1]


def _score_source_chunks(
    source_chunks: list[SourceChunk],
    selected_topic_keys: set[str],
    term_set: set[str],
    allow_fallback: bool = True,
) -> list[tuple[int, SourceChunk]]:
    scored: list[tuple[int, SourceChunk]] = []
    for chunk in source_chunks:
        text_lower = f"{chunk.heading}\n{chunk.text}".lower()
        score = 0
        chunk_topic_keys = {_match_key(topic_id) for topic_id in chunk.topic_ids}
        if selected_topic_keys & chunk_topic_keys:
            score += 30
        for term in term_set:
            if term in chunk.terms:
                score += 8
            count = text_lower.count(term)
            if count:
                score += min(count, 5)
        if score > 0:
            scored.append((score, chunk))
    if not scored and allow_fallback and not selected_topic_keys:
        scored = [(1, chunk) for chunk in source_chunks[:3]]
    return sorted(scored, key=lambda item: item[0], reverse=True)


def _source_file_name(document: dict) -> str:
    path = str(document.get("path") or "").strip()
    if not path:
        return str(document.get("title") or "source").strip()
    return re.split(r"[\\/]", path)[-1]


def _source_type(document: dict) -> str:
    extension = str(document.get("extension") or "").strip().lower().lstrip(".")
    if extension:
        return extension
    source_file = _source_file_name(document)
    if "." in source_file:
        return source_file.rsplit(".", 1)[-1].lower()
    return "text"


def _page_label(source_type: str, number: int) -> str:
    if source_type == "pptx":
        return f"slide {number}"
    if source_type in {"docx", "txt", "md"}:
        return f"section {number}"
    return f"page {number}"


def _source_topic_ids(project: CourseProject, source_file: str, text: str) -> list[str]:
    matches: list[str] = []
    source_key = source_file.lower()
    text_lower = text.lower()
    for topic in getattr(project, "topics", []) or []:
        topic_id = str(getattr(topic, "topic_id", "") or "").strip()
        if not topic_id:
            continue
        source_files = [str(value or "").lower() for value in getattr(topic, "source_files", []) or []]
        keywords = [str(value or "").lower() for value in getattr(topic, "keywords", []) or []]
        if any(source_key == re.split(r"[\\/]", value)[-1] for value in source_files):
            matches.append(topic_id)
        elif any(keyword and keyword in text_lower for keyword in keywords):
            matches.append(topic_id)
    return matches


def _content_hash(text: str) -> str:
    normalized = _match_key(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_chunk_id(source_file: str, page_or_slide: int | None, content_hash: str) -> str:
    payload = "|".join(
        [
            str(source_file or "").strip().lower(),
            str(page_or_slide or ""),
            str(content_hash or "").strip().lower(),
        ]
    )
    return f"source-{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:10]}"
