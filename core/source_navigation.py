"""Safely resolve source evidence to files registered by a course project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

OPENABLE_SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {".md", ".txt", ".pdf", ".pptx", ".docx"}
)


@dataclass(frozen=True)
class SourceLocation:
    path: Path
    page_or_slide: int | None = None
    source_type: str = ""

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def is_openable(self) -> bool:
        return self.path.suffix.lower() in OPENABLE_SOURCE_SUFFIXES


def _is_remote_or_device_path(raw: str) -> bool:
    """Return True if *raw* is a UNC, device, or URI path that must not be resolved."""
    lower = raw.strip().lower()
    if lower.startswith("\\\\"):
        return True  # UNC or device namespace (\\server, \\?\, \\.\)
    if "://" in lower:
        return True  # URI scheme
    return False


def _safe_resolve(path: Path) -> Path | None:
    """Resolve *path* without blocking on remote filesystems. Returns None on OSError."""
    if _is_remote_or_device_path(str(path)):
        return None
    try:
        return path.resolve(strict=False)
    except OSError:
        return None


def resolve_source_location(project, source_ref: dict) -> SourceLocation | None:
    """Resolve a ref only against paths explicitly registered on the project.

    Remote, device, and URI paths are rejected before any filesystem call.
    """
    if project is None or not isinstance(source_ref, dict):
        return None
    raw_source = str(source_ref.get("source_file", "") or "").strip()
    if not raw_source:
        return None
    if _is_remote_or_device_path(raw_source):
        return None

    registered = []
    for document in getattr(project, "documents", None) or []:
        raw_path = str(document.get("path", "") or "").strip()
        if not raw_path:
            continue
        if _is_remote_or_device_path(raw_path):
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path(getattr(project, "source_folder", "") or ".") / path
        resolved = _safe_resolve(path)
        if resolved is not None:
            registered.append(resolved)
    if not registered:
        return None

    requested = Path(raw_source).expanduser()
    matches = []
    if requested.is_absolute():
        normalized = _safe_resolve(requested)
        if normalized is None:
            return None
        matches = [path for path in registered if _path_key(path) == _path_key(normalized)]
    else:
        requested_name = requested.name.casefold()
        matches = [path for path in registered if path.name.casefold() == requested_name]
    if len(matches) != 1:
        return None

    page_or_slide = _positive_int(source_ref.get("page_or_slide"))
    path = matches[0]
    if path.suffix.lower() not in OPENABLE_SOURCE_SUFFIXES:
        return None
    return SourceLocation(path, page_or_slide, path.suffix.lower().lstrip("."))


def format_source_location(location: SourceLocation, language: str = "en") -> str:
    text = str(location.path)
    if location.page_or_slide is not None:
        label = "页码/幻灯片" if language == "zh" else "page/slide"
        text += f" · {label} {location.page_or_slide}"
    return text


def _positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _path_key(path: Path) -> str:
    return str(path).replace("\\", "/").casefold()
