"""Small, dependency-free helpers for human-readable persisted timestamps."""

from __future__ import annotations

from datetime import datetime


def format_local_timestamp(value: str, *, include_seconds: bool = False) -> str:
    """Format an ISO timestamp in the user's local timezone.

    Invalid legacy values are returned unchanged so old records remain visible
    instead of disappearing from the interface.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        pattern = "%Y-%m-%d %H:%M:%S" if include_seconds else "%Y-%m-%d %H:%M"
        return parsed.strftime(pattern)
    except ValueError:
        return raw
