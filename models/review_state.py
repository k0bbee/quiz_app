"""Derived per-question scheduling state for the daily study queue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewState:
    """Scheduler-neutral state rebuilt from completed progress records."""

    question_id: str
    attempts: int = 0
    last_reviewed_at: str = ""
    next_due_at: str = ""
    correct_streak: int = 0
    wrong_streak: int = 0
    interval_days: int = 0
    last_confidence: str = "sure"

