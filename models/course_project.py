"""Course project model for generic course ingestion."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config import COURSE_PROJECTS_DIR, CURRENT_COURSE_FILE
from utils.json_io import read_json, write_json, list_json_files


@dataclass
class CourseTopic:
    """A topic inferred from imported course materials."""

    topic_id: str
    title: str
    keywords: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "title": self.title,
            "keywords": self.keywords,
            "source_files": self.source_files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CourseTopic":
        return cls(
            topic_id=data.get("topic_id", ""),
            title=data.get("title", ""),
            keywords=data.get("keywords", []),
            source_files=data.get("source_files", []),
        )


@dataclass
class CourseProject:
    """A reusable course knowledge base built from imported materials."""

    course_id: str
    title: str
    source_folder: str
    summary_markdown: str
    summary_path: str
    topics: list[CourseTopic]
    documents: list[dict]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "course_id": self.course_id,
            "title": self.title,
            "source_folder": self.source_folder,
            "summary_markdown": self.summary_markdown,
            "summary_path": self.summary_path,
            "topics": [topic.to_dict() for topic in self.topics],
            "documents": self.documents,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CourseProject":
        return cls(
            course_id=data.get("course_id", ""),
            title=data.get("title", ""),
            source_folder=data.get("source_folder", ""),
            summary_markdown=data.get("summary_markdown", ""),
            summary_path=data.get("summary_path", ""),
            topics=[CourseTopic.from_dict(t) for t in data.get("topics", [])],
            documents=data.get("documents", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class CourseProjectManager:
    """Persistence for imported course projects."""

    def __init__(self, projects_dir: str = COURSE_PROJECTS_DIR):
        self._dir = projects_dir
        os.makedirs(self._dir, exist_ok=True)

    def save(self, project: CourseProject, make_current: bool = True) -> bool:
        from utils.json_io import sanitize_filename_part
        safe_id = sanitize_filename_part(project.course_id)
        path = os.path.join(self._dir, f"{safe_id}.json")
        if not project.summary_path:
            project.summary_path = os.path.join(self._dir, f"{safe_id}_summary.md")
        with open(project.summary_path, "w", encoding="utf-8") as f:
            f.write(project.summary_markdown)
        ok = write_json(path, project.to_dict())
        if ok and make_current:
            write_json(CURRENT_COURSE_FILE, {"course_id": project.course_id})
        return ok

    def get(self, course_id: str) -> Optional[CourseProject]:
        data = read_json(os.path.join(self._dir, f"{course_id}.json"))
        return CourseProject.from_dict(data) if data else None

    def load_all(self) -> list[CourseProject]:
        projects = []
        for filename in list_json_files(self._dir):
            data = read_json(os.path.join(self._dir, filename))
            if data:
                projects.append(CourseProject.from_dict(data))
        return sorted(projects, key=lambda project: project.updated_at, reverse=True)

    def current(self) -> Optional[CourseProject]:
        data = read_json(CURRENT_COURSE_FILE)
        if not data:
            projects = self.load_all()
            return projects[0] if projects else None
        return self.get(data.get("course_id", ""))

    def set_current(self, course_id: str) -> bool:
        if not self.get(course_id):
            return False
        return write_json(CURRENT_COURSE_FILE, {"course_id": course_id})

    @staticmethod
    def new_id() -> str:
        return f"course-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
