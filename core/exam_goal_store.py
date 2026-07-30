"""Course-scoped exam goals used for planning and load forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from utils.json_io import read_json, write_json


@dataclass(frozen=True)
class ExamGoal:
    course_id: str
    exam_date: str
    daily_minutes: int
    target_mastery: float
    included_topic_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        course_id = str(self.course_id or "").strip()
        if not course_id:
            raise ValueError("course_id is required")
        try:
            date.fromisoformat(str(self.exam_date or ""))
        except ValueError as exc:
            raise ValueError("exam_date must use YYYY-MM-DD") from exc
        daily_minutes = int(self.daily_minutes or 0)
        if daily_minutes <= 0:
            raise ValueError("daily_minutes must be positive")
        target = float(self.target_mastery)
        if not 0 < target <= 1:
            raise ValueError("target_mastery must be between 0 and 1")
        object.__setattr__(self, "course_id", course_id)
        object.__setattr__(self, "exam_date", str(self.exam_date))
        object.__setattr__(self, "daily_minutes", daily_minutes)
        object.__setattr__(self, "target_mastery", target)
        object.__setattr__(
            self,
            "included_topic_ids",
            tuple(dict.fromkeys(
                text
                for value in (self.included_topic_ids or ())
                if (text := str(value or "").strip())
            )),
        )

    def days_remaining(self, today: date | None = None) -> int:
        return max(
            0,
            (date.fromisoformat(self.exam_date) - (today or date.today())).days,
        )

    def to_dict(self) -> dict:
        return {
            "course_id": self.course_id,
            "exam_date": self.exam_date,
            "daily_minutes": self.daily_minutes,
            "target_mastery": self.target_mastery,
            "included_topic_ids": list(self.included_topic_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExamGoal":
        return cls(
            course_id=data.get("course_id", ""),
            exam_date=data.get("exam_date", ""),
            daily_minutes=data.get("daily_minutes", 0),
            target_mastery=data.get("target_mastery", 0),
            included_topic_ids=data.get("included_topic_ids", ()),
        )


class ExamGoalStore:
    def __init__(self, filepath: str | Path):
        self._path = str(filepath)

    def get(self, course_id: str) -> ExamGoal | None:
        row = self._payload()["goals"].get(str(course_id or "").strip())
        if not isinstance(row, dict):
            return None
        try:
            return ExamGoal.from_dict(row)
        except (TypeError, ValueError):
            return None

    def save(self, goal: ExamGoal) -> None:
        if not isinstance(goal, ExamGoal):
            raise TypeError("goal must be an ExamGoal")
        payload = self._payload()
        payload["goals"][goal.course_id] = goal.to_dict()
        if not write_json(self._path, payload):
            raise OSError("failed to persist exam goal")

    def delete(self, course_id: str) -> bool:
        payload = self._payload()
        removed = payload["goals"].pop(str(course_id or "").strip(), None)
        if removed is None:
            return False
        if not write_json(self._path, payload):
            raise OSError("failed to persist exam goal")
        return True

    def _payload(self) -> dict:
        data = read_json(self._path) or {}
        goals = data.get("goals", {}) if isinstance(data, dict) else {}
        return {
            "schema_version": 1,
            "goals": dict(goals) if isinstance(goals, dict) else {},
        }
