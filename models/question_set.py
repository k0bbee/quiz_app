"""QuestionSet data model."""

from __future__ import annotations

import uuid
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from models.question import Question
from utils.constants import Difficulty, coerce_topic, topic_label, topic_value
from utils.json_io import read_json, write_json, sanitize_filename_part


def _coerce_bilingual_text(value) -> dict:
    if isinstance(value, dict):
        zh = str(value.get("zh", "") or "")
        en = str(value.get("en", "") or zh)
        return {"zh": zh, "en": en}
    text = str(value or "")
    return {"zh": text, "en": text}


def _coerce_difficulty(value) -> Difficulty:
    try:
        return Difficulty(value or Difficulty.MEDIUM.value)
    except ValueError:
        return Difficulty.MEDIUM


@dataclass
class QuestionSet:
    """A named collection of questions organized by topic/difficulty."""

    set_id: str
    title: dict  # {"zh": "...", "en": "..."}
    description: dict  # {"zh": "...", "en": "..."}
    topics: list[object]
    difficulty: Difficulty
    estimated_minutes: int
    questions: list[str]  # question_id references
    metadata: dict = field(default_factory=dict)
    version: int = 1

    def get_title(self, lang: str) -> str:
        return self.title.get(lang, self.title.get("zh", ""))

    def get_description(self, lang: str) -> str:
        return self.description.get(lang, self.description.get("zh", ""))

    @property
    def question_count(self) -> int:
        return len(self.questions)

    def to_dict(self) -> dict:
        topic_ids = [topic_value(t) for t in self.topics]
        topic_titles = [topic_label(t) for t in self.topics]
        return {
            "set_id": self.set_id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "topics": topic_ids,
            "topic_ids": topic_ids,
            "topic_titles": topic_titles,
            "difficulty": self.difficulty.value,
            "estimated_minutes": self.estimated_minutes,
            "questions": self.questions,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> QuestionSet:
        return cls(
            set_id=data.get("set_id", ""),
            version=data.get("version", 1),
            title=_coerce_bilingual_text(data.get("title", {"zh": "", "en": ""})),
            description=_coerce_bilingual_text(data.get("description", {"zh": "", "en": ""})),
            topics=[coerce_topic(t) for t in data.get("topic_ids") or data.get("topics", [])],
            difficulty=_coerce_difficulty(data.get("difficulty", "medium")),
            estimated_minutes=data.get("estimated_minutes", 15),
            questions=data.get("questions", []),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def create_new(
        cls,
        title: dict,
        description: dict,
        topics: list[object],
        question_ids: list[str],
        difficulty: Difficulty = Difficulty.MEDIUM,
        estimated_minutes: int = 20,
        source: str = "manual",
    ) -> QuestionSet:
        sid = f"set-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            set_id=sid,
            title=title,
            description=description,
            topics=topics,
            difficulty=difficulty,
            estimated_minutes=estimated_minutes,
            questions=question_ids,
            metadata={
                "created_at": now,
                "updated_at": None,
                "source": source,
            },
        )


class SetManager:
    """Manages question set JSON files."""

    def __init__(self, sets_dir: str):
        self._dir = sets_dir
        self._cache: dict[str, QuestionSet] = {}
        self._cache_signatures: dict[str, tuple[int, int]] = {}

    @property
    def directory(self) -> str:
        return self._dir

    def load_all(self) -> list[QuestionSet]:
        """Load all question sets from the directory."""
        from utils.json_io import list_json_files

        sets = []
        seen_ids = set()
        for filename in list_json_files(self._dir):
            filepath = os.path.join(self._dir, filename)
            signature = self._file_signature(filepath)
            data = read_json(filepath)
            if data:
                qs = QuestionSet.from_dict(data)
                self._cache[qs.set_id] = qs
                if signature is not None:
                    self._cache_signatures[qs.set_id] = signature
                seen_ids.add(qs.set_id)
                sets.append(qs)
        for stale_id in list(self._cache):
            if stale_id not in seen_ids:
                self._cache.pop(stale_id, None)
                self._cache_signatures.pop(stale_id, None)
        return sorted(sets, key=lambda s: s.set_id, reverse=True)

    def get(self, set_id: str) -> Optional[QuestionSet]:
        filepath = self._path_for_id(set_id)
        signature = self._file_signature(filepath)
        if signature is None:
            self._cache.pop(set_id, None)
            self._cache_signatures.pop(set_id, None)
            return None
        if (
            set_id in self._cache
            and self._cache_signatures.get(set_id) == signature
        ):
            return self._cache[set_id]
        data = read_json(filepath)
        if data:
            qs = QuestionSet.from_dict(data)
            if qs.set_id != set_id:
                self._cache.pop(set_id, None)
                self._cache_signatures.pop(set_id, None)
            self._cache[qs.set_id] = qs
            self._cache_signatures[qs.set_id] = signature
            return qs
        self._cache.pop(set_id, None)
        self._cache_signatures.pop(set_id, None)
        return None

    def save(self, question_set: QuestionSet) -> bool:
        safe_id = sanitize_filename_part(question_set.set_id)
        filepath = os.path.join(self._dir, f"{safe_id}.json")
        ok = write_json(filepath, question_set.to_dict())
        if ok:
            self._cache[question_set.set_id] = question_set
            signature = self._file_signature(filepath)
            if signature is not None:
                self._cache_signatures[question_set.set_id] = signature
        return ok

    def delete(self, set_id: str) -> bool:
        from utils.json_io import delete_json

        self._cache.pop(set_id, None)
        self._cache_signatures.pop(set_id, None)
        return delete_json(self._path_for_id(set_id))

    def clear_cache(self):
        """Clear cached question sets so future reads hit disk."""
        self._cache.clear()
        self._cache_signatures.clear()

    def _path_for_id(self, set_id: str) -> str:
        return os.path.join(self._dir, f"{sanitize_filename_part(set_id)}.json")

    @staticmethod
    def _file_signature(filepath: str) -> Optional[tuple[int, int]]:
        try:
            stat = os.stat(filepath)
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)
