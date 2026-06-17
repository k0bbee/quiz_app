"""Batch question generator using QThread for non-blocking AI generation."""
from utils.logger import debug, warning, error

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from ai.llm_client import LLMClient
from ai.generation_config import GenerationConfig
from ai.prompt_templates import PromptBuilder
from core.course_index import retrieve_course_context
from models.question import Question
from utils.constants import QuestionType, Difficulty, topic_value


class GenerationWorker(QThread):
    """Background worker for generating questions via LLM."""

    progress = pyqtSignal(str)  # Status message
    batch_done = pyqtSignal(list)  # List of Question objects
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, llm_client: LLMClient, course_content: str,
                 topics: list, count: int, difficulty: str, course_project=None,
                 generation_config: GenerationConfig | None = None):
        super().__init__()
        self.client = llm_client
        self.course_content = course_content
        self.topics = topics
        self.count = count
        self.difficulty = difficulty
        self.course_project = course_project
        self.generation_config = generation_config or GenerationConfig()
        self._cancelled = threading.Event()
        self._cached_context: str | None = None

    def run(self):
        """Execute generation in background thread."""
        try:
            self.progress.emit("Building prompt...")

            batch_size = 10
            all_questions = []
            attempts = 0
            max_attempts = max(3, (self.count // batch_size + 1) * 3)

            # Cache context once — it doesn't change between batches
            course_context = self._build_course_context()

            while len(all_questions) < self.count and not self._cancelled.is_set() and attempts < max_attempts:
                attempts += 1
                batch_count = min(batch_size, self.count - len(all_questions))
                self.progress.emit(f"Generating {batch_count} questions... ({len(all_questions)}/{self.count} accepted)")

                messages = PromptBuilder.build_messages(
                    course_context,
                    self.topics,
                    batch_count,
                    self.difficulty,
                    self.generation_config,
                )

                data = self.client.generate_with_json(messages, max_retries=3)

                if data is None:
                    self.error.emit("Failed to generate questions. Check your API key and connection.")
                    return

                # Parse questions from response
                raw_questions = data.get("questions", [])
                if not raw_questions:
                    self.error.emit("No questions found in the API response.")
                    return

                batch_questions = []
                rejected = 0
                for qdata in raw_questions:
                    if self._cancelled.is_set():
                        break
                    try:
                        ok, reason = self._validate_raw_question(qdata)
                        if not ok:
                            rejected += 1
                            debug(f"Skipping invalid generated question: {reason}")
                            continue

                        q = Question.create_new(
                            qtype=QuestionType(qdata.get("type", "multiple_choice")),
                            difficulty=Difficulty(qdata.get("difficulty", "medium")),
                            bilingual=qdata.get("bilingual", {}),
                            correct_answer=qdata.get("correct_answer"),
                            topic=self._normalize_topic(qdata.get("topic")),
                            subtopic=qdata.get("subtopic", ""),
                            source="ai_generated",
                        )
                        # Set AI model in metadata
                        q.metadata["ai_model"] = self.client.model
                        errors = q.validate()
                        if not errors:
                            batch_questions.append(q)
                        else:
                            rejected += 1
                            debug(f"Skipping invalid question: {errors}")
                    except (ValueError, KeyError) as e:
                        rejected += 1
                        debug(f"Skipping malformed question: {e}")
                        continue

                all_questions.extend(batch_questions)
                self.progress.emit(
                    f"Accepted {len(batch_questions)} question(s), rejected {rejected}. "
                    f"Total accepted: {len(all_questions)}/{self.count}"
                )

            if not self._cancelled.is_set():
                self.batch_done.emit(all_questions[:self.count])

        except Exception as e:
            self.error.emit(f"Unexpected error: {str(e)}")
        finally:
            self.finished.emit()

    def cancel(self):
        """Signal the worker to stop."""
        self._cancelled.set()

    def _build_course_context(self) -> str:
        """Retrieve the best context for currently selected topics."""
        if self.course_project is not None:
            return retrieve_course_context(
                self.course_project,
                [topic_value(t) for t in self.topics],
                max_chars=30000,
            )
        return self.course_content

    def _validate_raw_question(self, qdata: dict) -> tuple[bool, str]:
        """Validate raw model output before converting it to a Question."""
        if not isinstance(qdata, dict):
            return False, "question is not an object"

        qtype = qdata.get("type", "multiple_choice")
        try:
            question_type = QuestionType(qtype)
        except ValueError:
            return False, f"unknown question type: {qtype}"

        if question_type == QuestionType.SHORT_ANSWER:
            return False, "short_answer is not suitable for auto-graded quick practice"

        topic = self._normalize_topic(qdata.get("topic"))
        if topic is None:
            return False, f"topic {qdata.get('topic')} was not selected"

        bilingual = qdata.get("bilingual", {})
        for lang in ("zh", "en"):
            content = bilingual.get(lang, {})
            if not content.get("stem"):
                return False, f"missing {lang} stem"
            if not content.get("explanation") or len(content.get("explanation", "")) < 20:
                return False, f"missing or weak {lang} explanation"

        if question_type in (
            QuestionType.MULTIPLE_CHOICE,
            QuestionType.SCENARIO_CHOICE,
            QuestionType.TRUE_FALSE,
        ):
            answer = str(qdata.get("correct_answer", "")).strip()
            if question_type == QuestionType.TRUE_FALSE:
                if answer.lower() not in {"true", "false"}:
                    return False, "true_false answer must be true/false"
            else:
                if answer.upper() not in {"A", "B", "C", "D"}:
                    return False, "choice answer must be A/B/C/D"
                for lang in ("zh", "en"):
                    options = bilingual.get(lang, {}).get("options", [])
                    if len(options) != 4:
                        return False, f"{lang} choice question must have 4 options"

        return True, ""

    def _normalize_topic(self, raw_topic):
        """Map model topic output to one of the selected topics."""
        if not self.topics:
            return str(raw_topic or "general")
        raw = str(raw_topic or "").strip().lower()
        selected = {topic_value(t).lower(): t for t in self.topics}
        if raw in selected:
            return selected[raw]
        for topic in self.topics:
            label = topic_value(topic).lower()
            if raw and (raw in label or label in raw):
                return topic
        return None
