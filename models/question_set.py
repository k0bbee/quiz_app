"""QuestionSet data model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from models.question import Question
from utils.constants import Difficulty, coerce_topic, topic_label, topic_value
from utils.json_io import read_json, write_json, sanitize_filename_part


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
            title=data.get("title", {"zh": "", "en": ""}),
            description=data.get("description", {"zh": "", "en": ""}),
            topics=[coerce_topic(t) for t in data.get("topic_ids") or data.get("topics", [])],
            difficulty=Difficulty(data.get("difficulty", "medium")),
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

    @property
    def directory(self) -> str:
        return self._dir

    def load_all(self) -> list[QuestionSet]:
        """Load all question sets from the directory."""
        from utils.json_io import list_json_files

        sets = []
        for filename in list_json_files(self._dir):
            filepath = f"{self._dir}/{filename}"
            data = read_json(filepath)
            if data:
                qs = QuestionSet.from_dict(data)
                self._cache[qs.set_id] = qs
                sets.append(qs)
        return sorted(sets, key=lambda s: s.set_id, reverse=True)

    def get(self, set_id: str) -> Optional[QuestionSet]:
        if set_id in self._cache:
            return self._cache[set_id]
        filepath = f"{self._dir}/{sanitize_filename_part(set_id)}.json"
        data = read_json(filepath)
        if data:
            qs = QuestionSet.from_dict(data)
            self._cache[qs.set_id] = qs
            return qs
        return None

    def save(self, question_set: QuestionSet) -> bool:
        safe_id = sanitize_filename_part(question_set.set_id)
        filepath = f"{self._dir}/{safe_id}.json"
        self._cache[question_set.set_id] = question_set
        return write_json(filepath, question_set.to_dict())

    def delete(self, set_id: str) -> bool:
        from utils.json_io import delete_json

        self._cache.pop(set_id, None)
        return delete_json(f"{self._dir}/{sanitize_filename_part(set_id)}.json")
