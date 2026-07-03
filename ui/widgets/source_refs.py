"""Formatting helpers for displaying course source references in UI."""

from html import escape as html_escape


def format_source_refs(
    source_refs,
    label: str = "Source Evidence",
    html: bool = False,
    status: str | None = None,
) -> str:
    """Format stored source_refs without exposing raw JSON."""
    lines = _source_ref_lines(source_refs, html=html)
    status_label = _source_ref_status_label(status)
    if not lines and not status_label:
        return ""
    separator = "<br>" if html else "\n"
    suffix = f" {status_label}" if status_label else ""
    if html:
        title = f"<b>{html_escape(label)}:</b>{html_escape(suffix)}"
    else:
        title = f"{label}:{suffix}"
    return separator.join([title, *lines])


def _source_ref_lines(source_refs, html: bool = False) -> list[str]:
    if not isinstance(source_refs, list):
        return []
    lines = []
    for index, ref in enumerate(source_refs, start=1):
        if not isinstance(ref, dict):
            continue
        source_file = str(ref.get("source_file", "") or "").strip()
        chunk_id = str(ref.get("chunk_id", "") or "").strip()
        heading = str(ref.get("heading", "") or "").strip()
        page_or_slide = ref.get("page_or_slide")
        parts = []
        if source_file:
            parts.append(source_file)
        if page_or_slide not in ("", None):
            parts.append(f"page {page_or_slide}")
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
                lines.append(f"   Excerpt: {excerpt}")
    return lines


def _compact_excerpt(value, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _source_ref_status_label(status: str | None) -> str:
    value = str(status or "").strip().lower()
    labels = {
        "valid_model_ref": "Exact",
        "partial_model_ref": "Partial",
        "fallback_plan_evidence": "Plan Fallback",
        "fallback_global_evidence": "Global Fallback",
        "global_fallback": "Global Fallback",
        "recovered": "Recovered",
        "invalid_model_ref": "Invalid",
        "missing": "Missing",
    }
    if value in labels:
        return labels[value]
    if not value:
        return ""
    return value.replace("_", " ").title()
