"""Formatting helpers for displaying course source references in UI."""

from html import escape as html_escape

from core.display_time import format_local_timestamp


def format_source_refs(
    source_refs,
    label: str = "Source Evidence",
    html: bool = False,
    status: str | None = None,
    language: str = "en",
) -> str:
    """Format stored source_refs without exposing raw JSON."""
    lines = _source_ref_lines(source_refs, html=html, language=language)
    status_label = _source_ref_status_label(status, language=language)
    if not lines and not status_label:
        return ""
    separator = "<br>" if html else "\n"
    suffix = f" {status_label}" if status_label else ""
    if html:
        title = f"<b>{html_escape(label)}:</b>{html_escape(suffix)}"
    else:
        title = f"{label}:{suffix}"
    return separator.join([title, *lines])


def _source_ref_lines(source_refs, html: bool = False, language: str = "en") -> list[str]:
    if not isinstance(source_refs, list):
        return []
    lines = []
    for index, ref in enumerate(source_refs, start=1):
        if not isinstance(ref, dict):
            continue
        if str(ref.get("source_kind", "") or "").strip() == "current_event":
            lines.extend(
                _current_event_ref_lines(
                    index,
                    ref,
                    html=html,
                    language=language,
                )
            )
            continue
        source_file = str(ref.get("source_file", "") or "").strip()
        chunk_id = str(ref.get("chunk_id", "") or "").strip()
        heading = str(ref.get("heading", "") or "").strip()
        page_or_slide = ref.get("page_or_slide")
        parts = []
        if source_file:
            parts.append(source_file)
        if page_or_slide not in ("", None):
            page_label = "页码/幻灯片" if language == "zh" else "page"
            parts.append(f"{page_label} {page_or_slide}")
        if chunk_id:
            parts.append(chunk_id)
        if heading:
            parts.append(heading)
        if parts:
            if html:
                parts = [html_escape(str(part)) for part in parts]
            lines.append(f"{index}. " + " · ".join(parts))
            excerpt = _compact_excerpt(ref.get("excerpt", ""))
            if excerpt:
                if html:
                    excerpt = html_escape(excerpt)
                excerpt_label = "摘录" if language == "zh" else "Excerpt"
                lines.append(f"   {excerpt_label}: {excerpt}")
    return lines


def _current_event_ref_lines(
    index: int,
    ref: dict,
    *,
    html: bool,
    language: str,
) -> list[str]:
    title = str(ref.get("title", "") or "").strip()
    domain = str(ref.get("domain", "") or "").strip()
    seen_at = format_local_timestamp(ref.get("seen_at", ""))
    retrieved_at = format_local_timestamp(ref.get("retrieved_at", ""))
    topics = (
        _string_list(ref.get("matched_topics"))
        or _string_list(ref.get("matched_topic_ids"))
    )
    parts = [part for part in (title, domain) if part]
    reported_label = "报道时间" if language == "zh" else "Reported"
    retrieved_label = "检索时间" if language == "zh" else "Retrieved"
    topics_label = "命中主题" if language == "zh" else "Matched topics"
    if seen_at:
        parts.append(f"{reported_label} {seen_at}")
    if retrieved_at:
        parts.append(f"{retrieved_label} {retrieved_at}")
    if topics:
        parts.append(f"{topics_label} {', '.join(topics)}")
    if html:
        parts = [html_escape(part) for part in parts]
    lines = [f"{index}. " + " · ".join(parts)] if parts else []
    excerpt = _compact_excerpt(ref.get("excerpt", ""))
    if excerpt:
        excerpt_label = "摘录" if language == "zh" else "Excerpt"
        lines.append(
            f"   {excerpt_label}: {html_escape(excerpt) if html else excerpt}"
        )
    return lines


def _string_list(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        text
        for text in (" ".join(str(item or "").split()) for item in value)
        if text
    ]


def _compact_excerpt(value, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _source_ref_status_label(status: str | None, language: str = "en") -> str:
    value = str(status or "").strip().lower()
    labels = {
        "valid_model_ref": ("精确来源", "Exact"),
        "partial_model_ref": ("部分匹配", "Partial"),
        "fallback_plan_evidence": ("计划证据补全", "Plan Fallback"),
        "fallback_global_evidence": ("全局检索补全", "Global Fallback"),
        "global_fallback": ("全局检索补全", "Global Fallback"),
        "recovered": ("已恢复旧来源", "Recovered"),
        "invalid_model_ref": ("无效来源", "Invalid"),
        "missing": ("缺少来源", "Missing"),
    }
    if value in labels:
        return labels[value][0 if language == "zh" else 1]
    if not value:
        return ""
    readable = value.replace("_", " ").title()
    return f"未知状态（{readable}）" if language == "zh" else readable
