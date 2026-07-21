"""Course project model for generic course ingestion."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config import COURSE_PROJECTS_DIR, CURRENT_COURSE_FILE
from utils.json_io import read_json, write_json, list_json_files, delete_json, sanitize_filename_part
from utils.logger import error


@dataclass
class CourseTopic:
    """A topic inferred from imported course materials."""

    topic_id: str
    title: str
    keywords: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "title": self.title,
            "keywords": self.keywords,
            "source_files": self.source_files,
            "aliases": self.aliases,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CourseTopic":
        return cls(
            topic_id=data.get("topic_id", ""),
            title=data.get("title", ""),
            keywords=data.get("keywords", []),
            source_files=data.get("source_files", []),
            aliases=data.get("aliases", []),
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
    summary_source: str = "local"
    summary_warning: str = ""
    generation_profile: dict = field(default_factory=dict)
    generation_profile_source: str = "local"
    generation_profile_warning: str = ""
    exam_scope_mode: str = "all"
    exam_scope_topic_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize persisted scope data without breaking legacy projects."""
        if self.exam_scope_mode not in {"all", "selected"}:
            self.exam_scope_mode = "all"
        self.exam_scope_topic_ids = self._ordered_topic_ids(self.exam_scope_topic_ids)
        if self.exam_scope_mode == "all":
            self.exam_scope_topic_ids = []

    def exam_topics(self) -> list[CourseTopic]:
        """Return course topics currently included in the exam scope."""
        if self.exam_scope_mode == "all":
            return list(self.topics)
        selected = set(self.exam_scope_topic_ids)
        return [topic for topic in self.topics if topic.topic_id in selected]

    def set_exam_scope(self, mode: str, topic_ids: list[str] | None = None) -> None:
        """Apply a validated exam scope using stable topic identities."""
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in {"all", "selected"}:
            raise ValueError("Exam scope mode must be 'all' or 'selected'")
        if normalized_mode == "all":
            self.exam_scope_mode = "all"
            self.exam_scope_topic_ids = []
            return

        selected_ids = self._ordered_topic_ids(topic_ids or [])
        if self.topics and not selected_ids:
            raise ValueError("Selected exam scope requires at least one topic")
        self.exam_scope_mode = "selected"
        self.exam_scope_topic_ids = selected_ids

    def _ordered_topic_ids(self, topic_ids) -> list[str]:
        requested = {
            str(topic_id or "").strip()
            for topic_id in (topic_ids or [])
            if str(topic_id or "").strip()
        }
        return [
            topic.topic_id
            for topic in self.topics
            if topic.topic_id and topic.topic_id in requested
        ]

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
            "summary_source": self.summary_source,
            "summary_warning": self.summary_warning,
            "generation_profile": self.generation_profile,
            "generation_profile_source": self.generation_profile_source,
            "generation_profile_warning": self.generation_profile_warning,
            "exam_scope_mode": self.exam_scope_mode,
            "exam_scope_topic_ids": list(self.exam_scope_topic_ids),
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
            summary_source=data.get("summary_source", "local"),
            summary_warning=data.get("summary_warning", ""),
            generation_profile=data.get("generation_profile", {}),
            generation_profile_source=data.get("generation_profile_source", "local"),
            generation_profile_warning=data.get("generation_profile_warning", ""),
            exam_scope_mode=data.get("exam_scope_mode", "all"),
            exam_scope_topic_ids=list(data.get("exam_scope_topic_ids", []) or []),
        )


class CourseProjectManager:
    """Persistence for imported course projects."""

    def __init__(
        self,
        projects_dir: str = COURSE_PROJECTS_DIR,
        *,
        current_course_file: str | Path | None = None,
    ):
        self._dir = projects_dir
        self._injected_current_course_file = (
            Path(current_course_file) if current_course_file is not None else None
        )
        os.makedirs(self._dir, exist_ok=True)

    @property
    def _current_course_file(self) -> Path:
        if self._injected_current_course_file is not None:
            return self._injected_current_course_file
        return Path(CURRENT_COURSE_FILE)

    @property
    def directory(self) -> str:
        return self._dir

    def _summary_path_for(self, safe_id: str) -> Path:
        return Path(self._dir) / f"{safe_id}_summary.md"

    def _normalize_summary_path(self, project: CourseProject, safe_id: str) -> Path:
        expected_path = self._summary_path_for(safe_id)
        if not project.summary_path:
            return expected_path

        summary_path = Path(project.summary_path)
        project_dir = Path(self._dir).resolve()
        try:
            resolved_summary = summary_path.resolve()
        except OSError:
            resolved_summary = summary_path.absolute()

        if resolved_summary == project_dir or project_dir in resolved_summary.parents:
            return summary_path
        return expected_path

    def save(self, project: CourseProject, make_current: bool = True) -> bool:
        safe_id = sanitize_filename_part(project.course_id)
        project_path = Path(self._dir) / f"{safe_id}.json"
        summary_path = self._normalize_summary_path(project, safe_id)
        original_summary_path = project.summary_path
        project.summary_path = str(summary_path)
        try:
            files = [
                (summary_path, project.summary_markdown.encode("utf-8")),
                (project_path, _json_bytes(project.to_dict())),
            ]
            if make_current:
                files.append((
                    self._current_course_file,
                    _json_bytes({"course_id": project.course_id}),
                ))
            return _commit_course_files(files, Path(self._dir).parent)
        except (OSError, TypeError, ValueError) as exc:
            project.summary_path = original_summary_path
            error(f"Failed to save course {project.course_id}: {exc}")
            return False

    def get(self, course_id: str) -> Optional[CourseProject]:
        try:
            safe_id = sanitize_filename_part(course_id)
        except ValueError:
            return None
        data = read_json(os.path.join(self._dir, f"{safe_id}.json"))
        return CourseProject.from_dict(data) if data else None

    def load_all(self) -> list[CourseProject]:
        projects = []
        for filename in list_json_files(self._dir):
            data = read_json(os.path.join(self._dir, filename))
            if data:
                projects.append(CourseProject.from_dict(data))
        return sorted(projects, key=lambda project: project.updated_at, reverse=True)

    def current(self) -> Optional[CourseProject]:
        data = read_json(self._current_course_file)
        if not data:
            return None
        project = self.get(data.get("course_id", ""))
        if project:
            return project
        delete_json(self._current_course_file)
        return None

    def set_current(self, course_id: str) -> bool:
        if not self.get(course_id):
            return False
        return write_json(self._current_course_file, {"course_id": course_id})

    def delete(self, course_id: str) -> bool:
        """Delete a course project and its generated summary file."""
        project = self.get(course_id)
        safe_id = sanitize_filename_part(course_id)
        ok = delete_json(os.path.join(self._dir, f"{safe_id}.json"))
        if project and project.summary_path:
            summary_path = Path(project.summary_path).resolve()
            project_dir = Path(self._dir).resolve()
            if summary_path == project_dir or project_dir in summary_path.parents:
                try:
                    if summary_path.exists():
                        summary_path.unlink()
                except OSError:
                    ok = False
        current = read_json(self._current_course_file) or {}
        if current.get("course_id") == course_id:
            delete_json(self._current_course_file)
        return ok

    @staticmethod
    def new_id() -> str:
        return f"course-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def _json_bytes(data: dict) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")


def _commit_course_files(files: list[tuple[Path, bytes]], transaction_parent: Path) -> bool:
    """Commit all course artifacts or restore their previous contents."""
    destinations = [destination.resolve() for destination, _payload in files]
    if len(set(destinations)) != len(destinations):
        raise ValueError("Course artifact paths must be distinct")

    transaction_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".course-save-",
        dir=transaction_parent,
    ) as temporary_directory:
        transaction_dir = Path(temporary_directory)
        staging_dir = transaction_dir / "staging"
        backup_dir = transaction_dir / "backup"
        staged_files: list[tuple[Path, Path]] = []

        for index, (destination, payload) in enumerate(files):
            staged_path = staging_dir / str(index)
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            staged_path.write_bytes(payload)
            staged_files.append((destination, staged_path))

        backups: list[tuple[Path, Path]] = []
        created_paths: list[Path] = []
        try:
            for index, (destination, staged_path) in enumerate(staged_files):
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    backup_path = backup_dir / str(index)
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup_path)
                    backups.append((destination, backup_path))
                else:
                    created_paths.append(destination)
                os.replace(staged_path, destination)
        except Exception as commit_error:
            recovery_errors = _restore_course_files(backups, created_paths)
            if recovery_errors:
                details = "; ".join(str(recovery_error) for recovery_error in recovery_errors)
                raise RuntimeError(
                    f"Course save failed ({commit_error}); rollback also failed: {details}"
                ) from commit_error
            raise
    return True


def _restore_course_files(
    backups: list[tuple[Path, Path]],
    created_paths: list[Path],
) -> list[Exception]:
    errors: list[Exception] = []
    for path in reversed(created_paths):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(exc)
    for destination, backup_path in reversed(backups):
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, destination)
        except OSError as exc:
            errors.append(exc)
    return errors
