"""Question and QuestionBank data models."""

from __future__ import annotations

import copy
from pathlib import Path
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.question_index import QuestionIndex
from utils.constants import QuestionType, Difficulty, coerce_topic, topic_label, topic_matches, topic_value
from utils.constants import topic_alias_values
from utils.json_io import read_json, write_json, sanitize_filename_part, list_json_files
from utils.logger import warning


def _coerce_question_type(value) -> QuestionType:
    try:
        return QuestionType(value or QuestionType.MULTIPLE_CHOICE.value)
    except ValueError:
        return QuestionType.MULTIPLE_CHOICE


def _coerce_difficulty(value) -> Difficulty:
    try:
        return Difficulty(value or Difficulty.MEDIUM.value)
    except ValueError:
        return Difficulty.MEDIUM


@dataclass
class Question:
    """A single quiz question with bilingual support."""

    question_id: str
    type: QuestionType
    difficulty: Difficulty
    bilingual: dict  # {"zh": {"stem":"", "options":[], "explanation":""}, "en": {...}}
    correct_answer: Any
    topic: object
    subtopic: str = ""
    metadata: dict = field(default_factory=dict)

    def get_stem(self, lang: str) -> str:
        """Get the question stem in the given language."""
        return self.bilingual.get(lang, {}).get("stem", "")

    def get_options(self, lang: str) -> list:
        """Get options in the given language. Returns empty list for non-choice types."""
        return self.bilingual.get(lang, {}).get("options", [])

    def get_explanation(self, lang: str) -> str:
        """Get the explanation in the given language."""
        return self.bilingual.get(lang, {}).get("explanation", "")

    def topic_id(self) -> str:
        """Return the stable topic identity used for storage and comparison."""
        return topic_value(self.topic)

    def topic_title(self) -> str:
        """Return the best human-readable topic title available for display."""
        title = str((self.metadata or {}).get("topic_title", "") or "").strip()
        return title or topic_label(self.topic)

    def is_auto_gradeable(self) -> bool:
        """Whether this question can be auto-graded."""
        return self.type in {
            QuestionType.MULTIPLE_CHOICE,
            QuestionType.TRUE_FALSE,
            QuestionType.SCENARIO_CHOICE,
            QuestionType.MATCHING,
            QuestionType.ORDERING,
            QuestionType.FILL_IN_BLANK,
        }

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        topic_id = self.topic_id()
        topic_title = self.topic_title()
        metadata = dict(self.metadata)
        if topic_title and topic_title != topic_id:
            metadata.setdefault("topic_title", topic_title)
        return {
            "question_id": self.question_id,
            "type": self.type.value,
            "difficulty": self.difficulty.value,
            "bilingual": self.bilingual,
            "correct_answer": self.correct_answer,
            "topic": topic_id,
            "topic_id": topic_id,
            "topic_title": topic_title,
            "subtopic": self.subtopic,
            "metadata": metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Question:
        """Deserialize from dictionary."""
        metadata = dict(data.get("metadata", {}) or {})
        topic_title = str(data.get("topic_title", "") or "").strip()
        legacy_topic = str(data.get("topic", "") or "").strip()
        if topic_title:
            metadata.setdefault("topic_title", topic_title)
        topic_source = data.get("topic_id") or data.get("topic", "general")
        if not data.get("topic_id") and legacy_topic:
            metadata.setdefault("legacy_topic", legacy_topic)
        return cls(
            question_id=data.get("question_id", ""),
            type=_coerce_question_type(data.get("type", "multiple_choice")),
            difficulty=_coerce_difficulty(data.get("difficulty", "medium")),
            bilingual=data.get("bilingual", {}),
            correct_answer=data.get("correct_answer"),
            topic=coerce_topic(topic_source),
            subtopic=data.get("subtopic", ""),
            metadata=metadata,
        )

    @classmethod
    def create_new(
        cls,
        qtype: QuestionType,
        difficulty: Difficulty,
        bilingual: dict,
        correct_answer: Any,
        topic: object,
        subtopic: str = "",
        source: str = "manual",
    ) -> Question:
        """Factory: create a new question with generated ID and metadata."""
        qid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            question_id=qid,
            type=qtype,
            difficulty=difficulty,
            bilingual=bilingual,
            correct_answer=correct_answer,
            topic=topic,
            subtopic=subtopic,
            metadata={
                "created_at": now,
                "source": source,
                "version": 1,
            },
        )

    def validate(self) -> list[str]:
        """Validate the question data. Returns list of error messages (empty = valid)."""
        errors = []
        if not self.question_id:
            errors.append("question_id is empty")
        if not self.bilingual:
            errors.append("bilingual content is missing")
        else:
            for lang in ("zh", "en"):
                if lang not in self.bilingual:
                    errors.append(f"Missing '{lang}' in bilingual content")
                    continue
                content = self.bilingual[lang]
                if not content.get("stem"):
                    errors.append(f"Missing stem for '{lang}'")
                if not content.get("explanation"):
                    errors.append(f"Missing explanation for '{lang}'")
                # Check options for choice-type questions
                if self.type in (QuestionType.MULTIPLE_CHOICE, QuestionType.SCENARIO_CHOICE):
                    opts = content.get("options", [])
                    if not opts:
                        errors.append(f"Missing options for '{lang}' (type={self.type.value})")
                    elif len(opts) < 2:
                        errors.append(f"Need at least 2 options for '{lang}', got {len(opts)}")
                if self.type == QuestionType.TRUE_FALSE:
                    if not content.get("options"):
                        errors.append(f"Missing options for '{lang}' (type=true_false)")
                if self.type == QuestionType.MATCHING:
                    opts = content.get("options", {})
                    if isinstance(opts, dict):
                        left = opts.get("left", [])
                        right = opts.get("right", [])
                        if len(left) != len(right):
                            errors.append(f"Matching left({len(left)}) and right({len(right)}) counts differ for '{lang}'")

        # Type-specific answer format checks
        if self.correct_answer is None:
            errors.append("correct_answer is None")
        elif self.type in (QuestionType.MULTIPLE_CHOICE, QuestionType.SCENARIO_CHOICE):
            ans = str(self.correct_answer).strip().upper()
            if ans not in {"A", "B", "C", "D"}:
                errors.append(f"Multiple choice answer must be A-D, got: {ans}")
        elif self.type == QuestionType.TRUE_FALSE:
            ans = str(self.correct_answer).strip().lower()
            if ans not in {"true", "false"}:
                errors.append(f"True/false answer must be true/false, got: {ans}")
        elif self.type == QuestionType.FILL_IN_BLANK:
            if not isinstance(self.correct_answer, list):
                errors.append("Fill-in-the-blank answer must be a list of acceptable strings")
            elif not self.correct_answer:
                errors.append("Fill-in-the-blank answer list is empty")

        return errors


class QuestionBank:
    """Manages a collection of questions stored as individual JSON files."""

    def __init__(self, questions_dir: str):
        self._dir = questions_dir
        self._index = QuestionIndex(questions_dir)
        self._cache: dict[str, Question] = {}
        self._load_cache: list[Question] | None = None
        self._load_cache_signature: tuple[tuple[str, int, int], ...] | None = None

    @property
    def directory(self) -> str:
        return self._dir

    def load_all(self) -> list[Question]:
        """Load all questions from the questions directory."""
        from utils.json_io import list_json_files

        signature = self._directory_signature()
        if self._load_cache is not None and signature == self._load_cache_signature:
            return [copy.deepcopy(q) for q in self._load_cache]

        questions = []
        for filename in list_json_files(self._dir):
            filepath = f"{self._dir}/{filename}"
            data = read_json(filepath)
            if data:
                q = Question.from_dict(data)
                self._cache[q.question_id] = q
                questions.append(q)
        self._load_cache = [copy.deepcopy(q) for q in questions]
        self._load_cache_signature = signature
        return questions

    def get(self, question_id: str) -> Optional[Question]:
        """Get a question by ID. Checks cache first, then disk."""
        if question_id in self._cache:
            return self._cache[question_id]

        filepath = f"{self._dir}/{sanitize_filename_part(question_id)}.json"
        data = read_json(filepath)
        if data:
            q = Question.from_dict(data)
            self._cache[q.question_id] = q
            return q
        return None

    def get_many(self, question_ids: list[str], course_id: str | None = None) -> list[Question]:
        """Get multiple questions by ID. Skips missing ones."""
        questions = []
        for qid in question_ids:
            q = self.get(qid)
            if q:
                if self._matches_course(q, course_id):
                    questions.append(q)
        return questions

    def save(self, question: Question) -> bool:
        """Save a question to its JSON file."""
        safe_id = sanitize_filename_part(question.question_id)
        filepath = f"{self._dir}/{safe_id}.json"
        self._try_ensure_index_current()
        ok = write_json(filepath, question.to_dict())
        if ok:
            self._cache[question.question_id] = question
            self._invalidate_load_cache()
            try:
                self._sync_index_file(safe_id, question.to_dict())
            except Exception as exc:
                warning(f"Question index update skipped after saving {safe_id}: {exc}")
        return ok

    def save_many(self, questions: list[Question]) -> int:
        """Save multiple JSON records and update the derived index once."""
        if not questions:
            return 0

        index_current = self._try_ensure_index_current()
        indexed_records: list[tuple[str, dict, int, int]] = []
        count = 0
        for question in questions:
            safe_id = sanitize_filename_part(question.question_id)
            filepath = Path(self._dir) / f"{safe_id}.json"
            data = question.to_dict()
            if not write_json(str(filepath), data):
                continue
            self._cache[question.question_id] = question
            count += 1
            if index_current:
                try:
                    stat = filepath.stat()
                    indexed_records.append((filepath.name, data, stat.st_mtime_ns, stat.st_size))
                except OSError as exc:
                    warning(f"Question index metadata unavailable after saving {safe_id}: {exc}")

        if count:
            self._invalidate_load_cache()
        if indexed_records:
            try:
                self._index.upsert_many(indexed_records)
            except Exception as exc:
                warning(f"Question index batch update skipped after saving {count} questions: {exc}")
        return count

    def delete(self, question_id: str) -> bool:
        """Delete a question by ID."""
        from utils.json_io import delete_json

        safe_id = sanitize_filename_part(question_id)
        self._try_ensure_index_current()
        self._cache.pop(question_id, None)
        ok = delete_json(f"{self._dir}/{safe_id}.json")
        if ok:
            self._invalidate_load_cache()
            try:
                self._index.delete(f"{safe_id}.json")
            except Exception as exc:
                warning(f"Question index update skipped after deleting {safe_id}: {exc}")
        return ok

    def filter_by_topic(self, topic: object, course_id: str | None = None) -> list[Question]:
        """Get all questions for a specific topic, optionally scoped to a course."""
        return self._filter_by_topics_indexed([topic], course_id)

    def filter_by_topics(self, topics: list, course_id: str | None = None) -> list[Question]:
        """Get all questions matching any topic, optionally scoped to a course."""
        if not topics:
            return []
        return self._filter_by_topics_indexed(topics, course_id)

    def search(
        self,
        query: str = "",
        topic: object = None,
        difficulty: Difficulty | str | None = None,
        course_id: str | None = None,
        unassigned_only: bool = False,
        offset: int = 0,
        limit: int = 50,
        metadata_filter: Callable[[Question], bool] | None = None,
    ) -> tuple[list[Question], int]:
        """Search questions with pagination. Returns (page_items, total_matches)."""
        query = query.strip().lower()
        topic_filter = topic_value(topic) if topic is not None else None
        difficulty_filter = difficulty.value if isinstance(difficulty, Difficulty) else difficulty
        course_filter = (course_id or "").strip()

        try:
            self._ensure_index_current()
            topic_values = topic_alias_values(topic) if topic is not None else set()
            indexed_offset = offset if metadata_filter is None else 0
            indexed_limit = limit if metadata_filter is None else None
            candidate_ids, indexed_total = self._index.query_ids(
                query=query,
                topic_values=topic_values,
                difficulty=str(difficulty_filter or ""),
                course_id=course_filter,
                unassigned_only=bool(unassigned_only),
                offset=indexed_offset,
                limit=indexed_limit,
            )
        except Exception as exc:
            warning(f"Question index search unavailable; using JSON fallback: {exc}")
            return self._search_json(
                query=query,
                topic=topic,
                difficulty_filter=difficulty_filter,
                course_filter=course_filter,
                unassigned_only=bool(unassigned_only),
                offset=offset,
                limit=limit,
                metadata_filter=metadata_filter,
            )
        candidates = self.get_many(candidate_ids)
        if metadata_filter is None:
            return candidates, indexed_total

        matches: list[Question] = []
        for q in candidates:
            if topic_filter is not None and not topic_matches(q.topic, topic):
                continue
            if difficulty_filter and q.difficulty.value != difficulty_filter:
                continue
            if course_filter:
                if not self._matches_course(q, course_filter):
                    continue
            if metadata_filter is not None and not metadata_filter(q):
                continue
            if query:
                haystack = " ".join([
                    q.get_stem("zh"),
                    q.get_stem("en"),
                    q.get_explanation("zh"),
                    q.get_explanation("en"),
                    q.subtopic,
                    topic_value(q.topic),
                    str((q.metadata or {}).get("topic_title", "")),
                    str((q.metadata or {}).get("legacy_topic", "")),
                ]).lower()
                if query not in haystack:
                    continue
            matches.append(q)

        total = len(matches)
        return matches[offset:offset + limit], total

    def question_ids(self, course_id: str | None = None) -> list[str]:
        """Return matching question IDs without constructing Question objects."""
        try:
            self._ensure_index_current()
            ids, _total = self._index.query_ids(course_id=(course_id or "").strip())
            return ids
        except Exception as exc:
            warning(f"Question index IDs unavailable; using JSON fallback: {exc}")
            ids: list[str] = []
            for filename in list_json_files(self._dir):
                data = read_json(f"{self._dir}/{filename}")
                if not isinstance(data, dict) or not self._matches_course_data(data, course_id):
                    continue
                question_id = str(data.get("question_id", "") or "").strip()
                if question_id:
                    ids.append(question_id)
            return ids

    def topic_index(self, course_id: str | None = None) -> dict[str, tuple[str, str]]:
        """Return lightweight question-to-topic labels without constructing models."""
        try:
            self._ensure_index_current()
            return {
                question_id: (topic_id, topic_title)
                for question_id, topic_id, topic_title in self._index.topic_rows(
                    (course_id or "").strip()
                )
            }
        except Exception as exc:
            warning(f"Question topic index unavailable; using JSON fallback: {exc}")
            return self._topic_index_from_json(course_id)

    def scheduling_index(
        self,
        course_id: str | None = None,
    ) -> dict[str, tuple[str, str, str]]:
        """Return topic and difficulty metadata without loading Question models."""
        try:
            self._ensure_index_current()
            return {
                question_id: (topic_id, topic_title, difficulty)
                for question_id, topic_id, topic_title, difficulty
                in self._index.scheduling_rows((course_id or "").strip())
            }
        except Exception as exc:
            warning(
                "Question scheduling index unavailable; "
                f"using JSON fallback: {exc}"
            )
            return self._scheduling_index_from_json(course_id)

    def count(self, course_id: str | None = None) -> int:
        """Return a lightweight count of matching question records."""
        return len(self.question_ids(course_id=course_id))

    def count_existing(self, question_ids: list[str] | set[str], course_id: str | None = None) -> int:
        """Count existing question IDs matching the optional course without loading Question objects."""
        count = 0
        for question_id in dict.fromkeys(question_ids):
            try:
                safe_id = sanitize_filename_part(str(question_id))
            except ValueError:
                continue
            data = read_json(f"{self._dir}/{safe_id}.json")
            if isinstance(data, dict) and self._matches_course_data(data, course_id):
                count += 1
        return count

    def clear_cache(self):
        """Clear the in-memory cache."""
        self._cache.clear()
        self._invalidate_load_cache()

    def __len__(self) -> int:
        return len(self.load_all())

    def _directory_signature(self) -> tuple[tuple[str, int, int], ...]:
        directory = Path(self._dir)
        if not directory.exists():
            return ()
        signature = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
            try:
                stat = path.stat()
            except OSError:
                continue
            signature.append((path.name, stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _invalidate_load_cache(self) -> None:
        self._load_cache = None
        self._load_cache_signature = None

    def _ensure_index_current(self) -> None:
        self._index.ensure_current(
            lambda filename: read_json(f"{self._dir}/{filename}"),
        )

    def _try_ensure_index_current(self) -> bool:
        try:
            self._ensure_index_current()
            return True
        except Exception as exc:
            warning(f"Question index unavailable; continuing with JSON store: {exc}")
            return False

    def _sync_index_file(self, safe_id: str, data: dict) -> None:
        path = Path(self._dir) / f"{safe_id}.json"
        stat = path.stat()
        self._index.upsert(path.name, data, stat.st_mtime_ns, stat.st_size)

    def _search_json(
        self,
        *,
        query: str,
        topic: object,
        difficulty_filter: str | None,
        course_filter: str,
        unassigned_only: bool,
        offset: int,
        limit: int,
        metadata_filter: Callable[[Question], bool] | None,
    ) -> tuple[list[Question], int]:
        matches: list[Question] = []
        for question in self.load_all():
            if topic is not None and not topic_matches(question.topic, topic):
                continue
            if difficulty_filter and question.difficulty.value != difficulty_filter:
                continue
            if course_filter and not self._matches_course(question, course_filter):
                continue
            if unassigned_only and self._metadata_course_id(question):
                continue
            if metadata_filter is not None and not metadata_filter(question):
                continue
            if query:
                haystack = " ".join([
                    question.get_stem("zh"),
                    question.get_stem("en"),
                    question.get_explanation("zh"),
                    question.get_explanation("en"),
                    question.subtopic,
                    topic_value(question.topic),
                    str((question.metadata or {}).get("topic_title", "")),
                    str((question.metadata or {}).get("legacy_topic", "")),
                ]).lower()
                if query not in haystack:
                    continue
            matches.append(question)
        return matches[offset:offset + limit], len(matches)

    @staticmethod
    def _metadata_course_id(question: Question) -> str:
        metadata = question.metadata or {}
        return (
            str(metadata.get("course_id", "") or "").strip()
            if isinstance(metadata, dict)
            else ""
        )

    def _topic_index_from_json(self, course_id: str | None) -> dict[str, tuple[str, str]]:
        index: dict[str, tuple[str, str]] = {}
        for filename in list_json_files(self._dir):
            data = read_json(f"{self._dir}/{filename}")
            if not isinstance(data, dict) or not self._matches_course_data(data, course_id):
                continue
            question_id = str(data.get("question_id", "") or "").strip()
            topic_id = str(data.get("topic_id") or data.get("topic") or "").strip()
            if not question_id or not topic_id:
                continue
            metadata = data.get("metadata", {}) or {}
            metadata_title = metadata.get("topic_title", "") if isinstance(metadata, dict) else ""
            topic_title = str(data.get("topic_title") or metadata_title or topic_id).strip() or topic_id
            index[question_id] = (topic_id, topic_title)
        return index

    def _scheduling_index_from_json(
        self,
        course_id: str | None,
    ) -> dict[str, tuple[str, str, str]]:
        index: dict[str, tuple[str, str, str]] = {}
        for filename in list_json_files(self._dir):
            data = read_json(f"{self._dir}/{filename}")
            if (
                not isinstance(data, dict)
                or not self._matches_course_data(data, course_id)
            ):
                continue
            question_id = str(data.get("question_id", "") or "").strip()
            topic_id = str(
                data.get("topic_id") or data.get("topic") or ""
            ).strip()
            if not question_id or not topic_id:
                continue
            metadata = data.get("metadata", {}) or {}
            metadata_title = (
                metadata.get("topic_title", "")
                if isinstance(metadata, dict)
                else ""
            )
            topic_title = str(
                data.get("topic_title") or metadata_title or topic_id
            ).strip() or topic_id
            difficulty = str(data.get("difficulty", "medium") or "medium")
            index[question_id] = (topic_id, topic_title, difficulty)
        return index

    def _filter_by_topics_indexed(
        self, topics: list[object], course_id: str | None
    ) -> list[Question]:
        try:
            self._ensure_index_current()
            aliases: set[str] = set()
            for topic in topics:
                aliases.update(topic_alias_values(topic))
            question_ids, _total = self._index.query_ids(
                topic_values=aliases,
                course_id=(course_id or "").strip(),
            )
            return self.get_many(question_ids, course_id=course_id)
        except Exception as exc:
            warning(f"Question topic filtering unavailable; using JSON fallback: {exc}")
            return [
                question
                for question in self.load_all()
                if self._matches_course(question, course_id)
                and any(topic_matches(question.topic, selected) for selected in topics)
            ]

    @staticmethod
    def _matches_course(question: Question, course_id: str | None) -> bool:
        course_filter = (course_id or "").strip()
        if not course_filter:
            return True
        source_course_id = (question.metadata or {}).get("course_id", "")
        return source_course_id == course_filter

    @staticmethod
    def _matches_course_data(data: dict, course_id: str | None) -> bool:
        course_filter = (course_id or "").strip()
        if not course_filter:
            return True
        metadata = data.get("metadata", {}) or {}
        source_course_id = metadata.get("course_id", "") if isinstance(metadata, dict) else ""
        return source_course_id == course_filter
