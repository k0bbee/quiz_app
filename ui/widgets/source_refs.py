"""Formatting helpers for displaying course source references in UI."""

from html import escape as html_escape



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
        line_start = _positive_int(ref.get("line_start"))
        line_end = _positive_int(ref.get("line_end"))
        if line_start is not None:
            line_label = "行" if language == "zh" else "line"
            end = line_end if line_end is not None and line_end >= line_start else line_start
            parts.append(
                f"{line_label} {line_start}-{end}"
                if end != line_start
                else f"{line_label} {line_start}"
            )
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


def _compact_excerpt(value, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


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
        "uncited": (
            "回答未明确引用提供的资料",
            "The answer did not explicitly cite the provided sources",
        ),
        "invalid": ("未找到有效引用", "No valid citation found"),
    }
    if value in labels:
        return labels[value][0 if language == "zh" else 1]
    if not value:
        return ""
    readable = value.replace("_", " ").title()
    return f"未知状态（{readable}）" if language == "zh" else readable
