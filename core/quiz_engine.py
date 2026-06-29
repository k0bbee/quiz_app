"""Quiz session state machine."""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from models.question import Question
from models.question_set import QuestionSet
from models.progress import AnswerRecord, ProgressRecord, SessionSummary
from core.grader import Grader
from utils.constants import QuizState


class QuizSession(QObject):
    """Manages a single quiz attempt: navigation, grading, progress recording."""

    # Signals
    state_changed = pyqtSignal(str)  # QuizState value
    question_changed = pyqtSignal(int, int)  # current_index, total
    question_graded = pyqtSignal(str, bool)  # question_id, is_correct
    session_completed = pyqtSignal(str)  # progress_id
    error_occurred = pyqtSignal(str)  # error message

    def __init__(self):
        super().__init__()
        self._state = QuizState.NOT_STARTED
        self._set: Optional[QuestionSet] = None
        self._questions: list[Question] = []
        self._current_index: int = 0
        self._answers: list[AnswerRecord] = []
        self._language: str = "zh"
        self._start_time: float = 0.0
        self._question_start_time: float = 0.0
        self._progress_id: str = ""
        self._in_submit: bool = False  # re-entrancy guard

    # --- Properties ---

    @property
    def state(self) -> QuizState:
        return self._state

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def total_questions(self) -> int:
        return len(self._questions)

    @property
    def language(self) -> str:
        return self._language

    @property
    def progress_id(self) -> str:
        return self._progress_id

    @property
    def is_completed(self) -> bool:
        return self._state == QuizState.COMPLETED

    @property
    def current_question(self) -> Optional[Question]:
        if 0 <= self._current_index < len(self._questions):
            return self._questions[self._current_index]
        return None

    @property
    def questions(self) -> list[Question]:
        """Return the current session question order."""
        return list(self._questions)

    @property
    def answers(self) -> list[AnswerRecord]:
        return list(self._answers)

    @property
    def correct_count(self) -> int:
        return sum(1 for a in self._answers if a.is_correct)

    @property
    def answered_count(self) -> int:
        return len(self._answers)

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time == 0:
            return 0.0
        return time.time() - self._start_time

    @property
    def started_at_iso(self) -> str:
        """Return the session start timestamp as ISO text."""
        if self._start_time == 0:
            return ""
        return datetime.fromtimestamp(self._start_time, tz=timezone.utc).isoformat()

    # --- Session lifecycle ---

    def start(self, question_set: QuestionSet, questions: list[Question], language: str = "zh"):
        """Initialize and start a new quiz session."""
        self._start_session(question_set, questions, language=language, shuffle=True)

    def start_fixed_order(self, question_set: QuestionSet, questions: list[Question], language: str = "zh"):
        """Start a quiz session without shuffling; used for snapshot restore."""
        self._start_session(question_set, questions, language=language, shuffle=False)

    def _start_session(
        self,
        question_set: QuestionSet | None,
        questions: list[Question],
        language: str = "zh",
        shuffle: bool = True,
        set_id: str = "",
    ):
        if self._state == QuizState.IN_PROGRESS:
            self.error_occurred.emit("A quiz session is already in progress.")
            return
        if not questions:
            self.error_occurred.emit("No questions available.")
            return

        self._set = question_set
        self._questions = list(questions)  # copy
        if shuffle:
            random.shuffle(self._questions)  # shuffle for fresh experience
        self._current_index = 0
        self._answers.clear()
        self._language = language
        self._start_time = time.time()

        # Create progress record
        sid = question_set.set_id if question_set else (set_id or f"custom-{datetime.now(timezone.utc).strftime('%Y%m%d')}")
        record = ProgressRecord.create_new(sid, language)
        self._progress_id = record.progress_id

        self._set_state(QuizState.IN_PROGRESS)
        self._question_start_time = time.time()
        self.question_changed.emit(self._current_index + 1, len(self._questions))

    def start_with_questions(self, questions: list[Question], language: str = "zh", set_id: str = ""):
        """Start a session with a direct list of questions (e.g., retry incorrect)."""
        self._start_session(None, questions, language=language, shuffle=True, set_id=set_id)

    def restore(
        self,
        question_set: QuestionSet,
        questions: list[Question],
        current_index: int,
        answers: list[AnswerRecord],
        language: str,
        progress_id: str,
        elapsed_seconds: float = 0.0,
    ):
        """Restore an in-progress session from a persisted snapshot."""
        if not questions:
            self.error_occurred.emit("No questions available.")
            return
        self._set = question_set
        self._questions = list(questions)
        self._current_index = max(0, min(current_index, len(self._questions) - 1))
        self._answers = list(answers)
        self._language = language if language in ("zh", "en") else "zh"
        self._progress_id = progress_id
        self._start_time = time.time() - max(0.0, float(elapsed_seconds or 0.0))
        self._question_start_time = time.time()
        current = self.current_question
        self._set_state(
            QuizState.SHOWING_FEEDBACK
            if current is not None and self.answer_for_question_id(current.question_id)
            else QuizState.IN_PROGRESS
        )
        self.question_changed.emit(self._current_index + 1, len(self._questions))

    def submit_answer(self, user_answer, confidence: str = "sure") -> tuple[bool, object]:
        """Submit an answer for the current question. Returns (is_correct, normalized_answer)."""
        # Guard: reject if not in IN_PROGRESS (prevents double-submit)
        if self._state != QuizState.IN_PROGRESS:
            return False, None

        question = self.current_question
        if question is None:
            self.error_occurred.emit("No current question.")
            return False, None
        existing = self.answer_for_question_id(question.question_id)
        if existing is not None:
            self._set_state(QuizState.SHOWING_FEEDBACK)
            return existing.is_correct, existing.user_answer

        # Re-entrancy guard: prevent signal handlers from calling
        # next_question() mid-submit (which would corrupt the index).
        self._in_submit = True

        is_correct, normalized = Grader.grade(question, user_answer)
        time_spent = time.time() - self._question_start_time

        record = AnswerRecord(
            question_id=question.question_id,
            index_in_session=self._current_index,
            user_answer=normalized,
            is_correct=is_correct,
            confidence=confidence if confidence in ("sure", "unsure") else "sure",
            time_spent_seconds=round(time_spent, 1),
            attempted_at=datetime.now(timezone.utc).isoformat(),
        )
        self._answers.append(record)

        self.question_graded.emit(question.question_id, is_correct)

        # Auto-advance to feedback
        self._set_state(QuizState.SHOWING_FEEDBACK)
        self._in_submit = False
        return is_correct, normalized

    def next_question(self) -> bool:
        """Advance to the next question. Returns False if quiz is complete."""
        # Re-entrancy guard: if we're inside submit_answer(), block
        # external calls that would corrupt the question index.
        if self._in_submit:
            return False
        # Only allow advancing from SHOWING_FEEDBACK (after user has seen result)
        if self._state != QuizState.SHOWING_FEEDBACK:
            return False

        self._current_index += 1
        if self._current_index >= len(self._questions):
            self.finalize()
            return False

        self._set_state(QuizState.IN_PROGRESS)
        self._question_start_time = time.time()
        self.question_changed.emit(self._current_index + 1, len(self._questions))
        return True

    def skip_question(self):
        """Skip the current question without answering."""
        if self._state != QuizState.IN_PROGRESS:
            return
        question = self.current_question
        if question is not None:
            time_spent = time.time() - self._question_start_time
            self._answers.append(AnswerRecord(
                question_id=question.question_id,
                index_in_session=self._current_index,
                user_answer="",
                is_correct=False,
                skipped=True,
                time_spent_seconds=round(time_spent, 1),
                attempted_at=datetime.now(timezone.utc).isoformat(),
            ))
        self._current_index += 1
        if self._current_index >= len(self._questions):
            self.finalize()
            return
        self._set_state(QuizState.IN_PROGRESS)
        self._question_start_time = time.time()
        self.question_changed.emit(self._current_index + 1, len(self._questions))

    def jump_to(self, index: int) -> bool:
        """Jump to a question index without implicitly submitting or finalizing."""
        if not (0 <= index < len(self._questions)):
            return False
        if self._state not in (
            QuizState.IN_PROGRESS,
            QuizState.SHOWING_FEEDBACK,
            QuizState.COMPLETED,
        ):
            return False

        self._current_index = index
        if self._state != QuizState.COMPLETED:
            question = self.current_question
            if question is not None and self.answer_for_question_id(question.question_id):
                self._set_state(QuizState.SHOWING_FEEDBACK)
            else:
                self._set_state(QuizState.IN_PROGRESS)
                self._question_start_time = time.time()
        self.question_changed.emit(index + 1, len(self._questions))
        return True

    def previous_question(self) -> bool:
        """Jump to the previous question in the session order."""
        return self.jump_to(self._current_index - 1)

    def preview_next_question(self) -> bool:
        """Jump to the next question for preview/navigation without finishing the quiz."""
        return self.jump_to(self._current_index + 1)

    def answer_for_question_id(self, question_id: str) -> Optional[AnswerRecord]:
        """Return the latest submitted/skipped answer for a question, if any."""
        for answer in reversed(self._answers):
            if answer.question_id == question_id:
                return answer
        return None

    def set_answer_confidence(self, question_id: str, confidence: str) -> bool:
        """Update confidence for an already submitted answer."""
        if confidence not in ("sure", "unsure"):
            return False
        for answer in reversed(self._answers):
            if answer.question_id == question_id:
                answer.confidence = confidence
                return True
        return False

    def finalize(self):
        """Complete the session, compute summary, save progress.
        Safe to call multiple times; second call is a no-op."""
        if self._state == QuizState.COMPLETED:
            return
        total_time = self.elapsed_seconds
        summary = SessionSummary.compute(self._answers, len(self._questions), total_time)

        record = ProgressRecord(
            progress_id=self._progress_id,
            set_id=self._set.set_id if self._set else "",
            language=self._language,
            started_at=datetime.fromtimestamp(self._start_time, tz=timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            status="completed",
            answers=list(self._answers),
            summary=summary,
        )
        # Store the record for later retrieval
        self._final_record = record
        self._set_state(QuizState.COMPLETED)
        self.session_completed.emit(self._progress_id)

    def get_progress_record(self) -> Optional[ProgressRecord]:
        """Get the completed progress record (only available after finalize)."""
        return getattr(self, "_final_record", None)

    def abandon(self) -> ProgressRecord:
        """Finish the current session as abandoned and return a progress record."""
        record = self.get_progress_record()
        if self._state == QuizState.COMPLETED and record is not None:
            record.status = "abandoned"
            return record

        total_time = self.elapsed_seconds
        summary = SessionSummary.compute(self._answers, len(self._questions), total_time)
        record = ProgressRecord(
            progress_id=self._progress_id,
            set_id=self._set.set_id if self._set else "",
            language=self._language,
            started_at=datetime.fromtimestamp(self._start_time, tz=timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            status="abandoned",
            answers=list(self._answers),
            summary=summary,
        )
        self._set_state(QuizState.COMPLETED)
        self._final_record = record
        return record

    def set_language(self, lang: str):
        """Switch display language mid-session."""
        if lang in ("zh", "en"):
            self._language = lang

    # --- Internal ---

    def _set_state(self, new_state: QuizState):
        if self._state == new_state:
            return  # avoid redundant signals
        self._state = new_state
        self.state_changed.emit(new_state.value)
