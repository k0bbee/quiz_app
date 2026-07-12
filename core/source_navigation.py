"""Safely resolve source evidence to files registered by a course project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceLocation:
    path: Path
    page_or_slide: int | None = None
    source_type: str = ""

    @property
    def exists(self) -> bool:
        return self.path.is_file()


def resolve_source_location(project, source_ref: dict) -> SourceLocation | None:
    """Resolve a ref only against paths explicitly registered on the project."""
    if project is None or not isinstance(source_ref, dict):
        return None
    raw_source = str(source_ref.get("source_file", "") or "").strip()
    if not raw_source:
        return None

    registered = []
    for document in getattr(project, "documents", None) or []:
        raw_path = str(document.get("path", "") or "").strip()
        if raw_path:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = Path(getattr(project, "source_folder", "") or ".") / path
            registered.append(path.resolve(strict=False))
    if not registered:
        return None

    requested = Path(raw_source).expanduser()
    matches = []
    if requested.is_absolute():
        normalized = requested.resolve(strict=False)
        matches = [path for path in registered if _path_key(path) == _path_key(normalized)]
    else:
        requested_name = requested.name.casefold()
        matches = [path for path in registered if path.name.casefold() == requested_name]
    if len(matches) != 1:
        return None

    page_or_slide = _positive_int(source_ref.get("page_or_slide"))
    path = matches[0]
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
