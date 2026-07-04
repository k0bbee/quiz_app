"""Mastery and review-priority calculations for quiz practice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from models.progress import AnswerRecord, ProgressRecord
from models.question import Question
from utils.constants import topic_value


@dataclass(frozen=True)
class MasteryState:
    """Derived learning state for one question."""

    question_id: str
    attempts: int = 0
    correct: int = 0
    ever_wrong: bool = False
    recent_correct_streak: int = 0
    recent_wrong_streak: int = 0
    last_seen_at: str = ""
    last_wrong_at: str = ""
    mastery_score: float = 0.0
    review_priority: float = 0.0


@dataclass(frozen=True)
class TopicMasteryState:
    """Derived learning state for one topic."""

    topic: str
    question_count: int = 0
    attempts: int = 0
    correct: int = 0
    wrong_question_count: int = 0
    mastery_score: float = 0.0


@dataclass
class _Accumulator:
    question_id: str
    attempts: int = 0
    correct: int = 0
    ever_wrong: bool = False
    recent_correct_streak: int = 0
    recent_wrong_streak: int = 0
    last_seen_at: str = ""
    last_wrong_at: str = ""
    sequence: int = 0
    last_wrong_sequence: int = -1

    def add_answer(self, answer: AnswerRecord, timestamp: str, sequence: int) -> None:
        self.attempts += 1
        self.sequence = sequence
        self.last_seen_at = timestamp
        if answer.is_correct:
            self.correct += 1
            self.recent_correct_streak += 1
            self.recent_wrong_streak = 0
        else:
            self.ever_wrong = True
            self.recent_wrong_streak += 1
            self.recent_correct_streak = 0
            self.last_wrong_at = timestamp
            self.last_wrong_sequence = sequence


def build_question_mastery(records: list[ProgressRecord]) -> dict[str, MasteryState]:
    """Build per-question mastery states from progress records."""
    accumulators: dict[str, _Accumulator] = {}
    ordered_answers = _chronological_answers(records)
    total_events = len(ordered_answers)

    for sequence, (record, answer) in enumerate(ordered_answers):
        if not answer.question_id:
            continue
        timestamp = answer.attempted_at or record.completed_at or record.started_at
        accumulator = accumulators.setdefault(answer.question_id, _Accumulator(answer.question_id))
        accumulator.add_answer(answer, timestamp, sequence)

    return {
        question_id: _build_state(accumulator, total_events)
        for question_id, accumulator in accumulators.items()
    }


def build_topic_mastery(records: list[ProgressRecord], questions: list[Question]) -> dict[str, TopicMasteryState]:
    """Build per-topic mastery states from question metadata and progress records."""
    question_states = build_question_mastery(records)
    by_topic: dict[str, list[tuple[Question, MasteryState]]] = {}
    for question in questions:
        topic = topic_value(question.topic)
        state = question_states.get(question.question_id)
        if state is None:
            state = MasteryState(question_id=question.question_id)
        by_topic.setdefault(topic, []).append((question, state))

    topic_states: dict[str, TopicMasteryState] = {}
    for topic, rows in by_topic.items():
        states = [state for _question, state in rows]
        attempts = sum(state.attempts for state in states)
        correct = sum(state.correct for state in states)
        wrong_question_count = sum(1 for state in states if state.ever_wrong)
        answered_states = [state for state in states if state.attempts > 0]
        if answered_states:
            mastery_score = sum(state.mastery_score for state in answered_states) / len(answered_states)
        else:
            mastery_score = 0.0
        topic_states[topic] = TopicMasteryState(
            topic=topic,
            question_count=len(rows),
            attempts=attempts,
            correct=correct,
            wrong_question_count=wrong_question_count,
            mastery_score=round(mastery_score, 3),
        )
    return topic_states


def prioritize_review_question_ids(
    records: list[ProgressRecord],
    candidate_question_ids: list[str] | set[str] | None = None,
) -> list[str]:
    """Return historically wrong question IDs ordered by review priority."""
    states = build_question_mastery(records)
    candidates = set(candidate_question_ids) if candidate_question_ids is not None else None
    reviewable = [
        state
        for state in states.values()
        if state.ever_wrong and (candidates is None or state.question_id in candidates)
    ]
    reviewable.sort(
        key=lambda state: (
            -state.review_priority,
            state.mastery_score,
            -_timestamp_sort_key(state.last_wrong_at),
            state.question_id,
        )
    )
    return [state.question_id for state in reviewable]


def _build_state(accumulator: _Accumulator, total_events: int) -> MasteryState:
    accuracy = accumulator.correct / accumulator.attempts if accumulator.attempts else 0.0
    correct_streak_bonus = min(accumulator.recent_correct_streak, 3) / 3 * 0.25
    wrong_streak_penalty = min(accumulator.recent_wrong_streak, 3) / 3 * 0.35
    confidence_bonus = min(accumulator.attempts, 5) / 5 * 0.1
    mastery_score = _clamp(accuracy * 0.65 + correct_streak_bonus + confidence_bonus - wrong_streak_penalty)

    recent_wrong_bonus = 0.0
    if accumulator.last_wrong_sequence >= 0 and total_events > 1:
        recent_wrong_bonus = accumulator.last_wrong_sequence / (total_events - 1) * 20.0
    repeated_wrong_bonus = max(0, accumulator.attempts - accumulator.correct - 1) * 12.0
    active_wrong_bonus = accumulator.recent_wrong_streak * 25.0
    recovery_discount = accumulator.recent_correct_streak * 8.0
    review_priority = (
        (1.0 - mastery_score) * 100.0
        + repeated_wrong_bonus
        + active_wrong_bonus
        + recent_wrong_bonus
        - recovery_discount
    )

    return MasteryState(
        question_id=accumulator.question_id,
        attempts=accumulator.attempts,
        correct=accumulator.correct,
        ever_wrong=accumulator.ever_wrong,
        recent_correct_streak=accumulator.recent_correct_streak,
        recent_wrong_streak=accumulator.recent_wrong_streak,
        last_seen_at=accumulator.last_seen_at,
        last_wrong_at=accumulator.last_wrong_at,
        mastery_score=round(mastery_score, 3),
        review_priority=round(review_priority, 3),
    )


def _chronological_answers(records: list[ProgressRecord]) -> list[tuple[ProgressRecord, AnswerRecord]]:
    rows: list[tuple[datetime, int, int, ProgressRecord, AnswerRecord]] = []
    for record_index, record in enumerate(records):
        record_time = _parse_timestamp(record.completed_at or record.started_at)
        for answer_index, answer in enumerate(record.answers):
            answer_time = _parse_timestamp(answer.attempted_at) if answer.attempted_at else record_time
            rows.append((answer_time, record_index, answer_index, record, answer))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return [(record, answer) for _time, _record_index, _answer_index, record, answer in rows]


def _parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.max.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _timestamp_sort_key(value: str) -> float:
    return _parse_timestamp(value).timestamp()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
