"""User-managed mastery overrides."""

from __future__ import annotations

from pathlib import Path

from config import MASTERY_OVERRIDES_FILE
from utils.constants import topic_value
from utils.json_io import read_json, write_json


class MasteryOverrideStore:
    """Persists topics the user explicitly marked as fully mastered."""

    def __init__(self, filepath: str | Path = MASTERY_OVERRIDES_FILE):
        self._path = str(filepath)

    def is_topic_mastered(self, course_id: str | None, topic: object) -> bool:
        """Return whether a topic is explicitly marked as fully mastered."""
        return self._topic_key(topic) in self.mastered_topics(course_id)

    def mastered_topics(self, course_id: str | None) -> set[str]:
        """Return normalized mastered topic keys for one course."""
        data = self._load()
        values = data.get("courses", {}).get(self._course_key(course_id), [])
        if not isinstance(values, list):
            return set()
        return {self._topic_key(value) for value in values}

    def mark_topic_mastered(self, course_id: str | None, topic: object) -> bool:
        """Persistently mark a topic as fully mastered."""
        data = self._load()
        courses = data.setdefault("courses", {})
        course_key = self._course_key(course_id)
        topics = set(courses.get(course_key, []))
        topics.add(self._topic_key(topic))
        courses[course_key] = sorted(topics)
        return write_json(self._path, data)

    def unmark_topic_mastered(self, course_id: str | None, topic: object) -> bool:
        """Remove the fully-mastered override for one topic."""
        data = self._load()
        courses = data.setdefault("courses", {})
        course_key = self._course_key(course_id)
        topics = set(courses.get(course_key, []))
        topics.discard(self._topic_key(topic))
        if topics:
            courses[course_key] = sorted(topics)
        else:
            courses.pop(course_key, None)
        return write_json(self._path, data)

    def clear(self) -> bool:
        """Remove all mastery overrides."""
        return write_json(self._path, {"courses": {}})

    def replace_course_topics(self, replacements: dict[str, set[str]]) -> bool:
        """Replace several course overrides with one atomic file write."""
        data = self._load()
        courses = data.setdefault("courses", {})
        for course_id, topics in replacements.items():
            course_key = self._course_key(course_id)
            normalized = sorted({
                self._topic_key(topic)
                for topic in topics
                if self._topic_key(topic)
            })
            if normalized:
                courses[course_key] = normalized
            else:
                courses.pop(course_key, None)
        return write_json(self._path, data)

    def _load(self) -> dict:
        data = read_json(self._path) or {}
        if not isinstance(data, dict):
            return {"courses": {}}
        if not isinstance(data.get("courses", {}), dict):
            data["courses"] = {}
        return data

    @staticmethod
    def _course_key(course_id: str | None) -> str:
        return (course_id or "__global__").strip() or "__global__"

    @staticmethod
    def _topic_key(topic: object) -> str:
        return topic_value(topic)
