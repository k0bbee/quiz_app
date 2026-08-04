"""Shared asset scope used by both sides of the library workspace."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LibraryScopeKind(str, Enum):
    COURSE = "course"
    EMPTY = "empty"


@dataclass(frozen=True)
class LibraryAssetScope:
    kind: LibraryScopeKind
    course_id: str = ""

    def __post_init__(self) -> None:
        kind = LibraryScopeKind(self.kind)
        course_id = str(self.course_id or "").strip()
        if kind is not LibraryScopeKind.COURSE:
            course_id = ""
        elif not course_id:
            kind = LibraryScopeKind.EMPTY
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "course_id", course_id)

    @classmethod
    def course(cls, course_id: str) -> "LibraryAssetScope":
        return cls(LibraryScopeKind.COURSE, course_id)

    @classmethod
    def empty(cls) -> "LibraryAssetScope":
        return cls(LibraryScopeKind.EMPTY)

    def matches(self, asset) -> bool:
        metadata = getattr(asset, "metadata", {}) or {}
        source_course_id = (
            str(metadata.get("course_id", "") or "").strip()
            if isinstance(metadata, dict)
            else ""
        )
        if self.kind is LibraryScopeKind.COURSE:
            return source_course_id == self.course_id
        return False
