"""Structured evidence for generating targeted reinforcement questions."""

from __future__ import annotations

import json
from dataclasses import dataclass


def _clean_ids(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(value or "").strip()
        for value in (values or ())
        if str(value or "").strip()
    ))


def answer_text(value) -> str:
    """Serialize a user's answer without leaking an unbounded object repr."""
    if value is None:
        return "未作答"
    if isinstance(value, str):
        return value.strip()[:240] or "未作答"
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    return str(text).strip()[:240] or "未作答"


@dataclass(frozen=True, slots=True)
class TopicSignal:
    """Observed answer evidence grouped by one stable course topic."""

    topic_id: str
    question_ids: tuple[str, ...] = ()
    observed_wrong_answers: tuple[str, ...] = ()
    unsure_question_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "topic_id", str(self.topic_id or "").strip())
        object.__setattr__(self, "question_ids", _clean_ids(self.question_ids))
        object.__setattr__(
            self,
            "observed_wrong_answers",
            tuple(dict.fromkeys(
                answer_text(value)
                for value in (self.observed_wrong_answers or ())
                if answer_text(value)
            )),
        )
        object.__setattr__(self, "unsure_question_ids", _clean_ids(self.unsure_question_ids))
        object.__setattr__(self, "source_refs", _clean_ids(self.source_refs)[:4])

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "question_ids": list(self.question_ids),
            "observed_wrong_answers": list(self.observed_wrong_answers),
            "unsure_question_ids": list(self.unsure_question_ids),
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_mapping(cls, value) -> "TopicSignal | None":
        if not isinstance(value, dict):
            return None
        topic_id = str(value.get("topic_id", "") or "").strip()
        if not topic_id:
            return None
        return cls(
            topic_id=topic_id,
            question_ids=value.get("question_ids", ()),
            observed_wrong_answers=value.get("observed_wrong_answers", ()),
            unsure_question_ids=value.get("unsure_question_ids", ()),
            source_refs=value.get("source_refs", ()),
        )


@dataclass(frozen=True, slots=True)
class RemediationRequest:
    """Bounded, serializable context for a targeted reinforcement run."""

    course_id: str
    signals: tuple[TopicSignal, ...] = ()
    max_questions: int = 8
    destination: str = "practice_now"

    def __post_init__(self) -> None:
        object.__setattr__(self, "course_id", str(self.course_id or "").strip())
        normalized = tuple(signal for signal in (self.signals or ()) if isinstance(signal, TopicSignal))
        object.__setattr__(self, "signals", normalized[:3])
        try:
            count = int(self.max_questions)
        except (TypeError, ValueError):
            count = 8
        object.__setattr__(self, "max_questions", max(1, min(60, count)))
        object.__setattr__(
            self,
            "destination",
            str(self.destination or "practice_now").strip() or "practice_now",
        )

    @property
    def topic_ids(self) -> tuple[str, ...]:
        return tuple(signal.topic_id for signal in self.signals if signal.topic_id)

    def to_dict(self) -> dict:
        return {
            "course_id": self.course_id,
            "topic_ids": list(self.topic_ids),
            "question_count": self.max_questions,
            "max_questions": self.max_questions,
            "destination": self.destination,
            "signals": [signal.to_dict() for signal in self.signals],
        }

    @classmethod
    def from_mapping(cls, value) -> "RemediationRequest | None":
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            return None
        signals = tuple(
            signal
            for raw in (value.get("signals", ()) or ())
            if (signal := TopicSignal.from_mapping(raw)) is not None
        )
        if not signals:
            signals = tuple(
                TopicSignal(topic_id=topic_id)
                for topic_id in _clean_ids(value.get("topic_ids", ()))
            )
        return cls(
            course_id=value.get("course_id", ""),
            signals=signals,
            max_questions=value.get("max_questions", value.get("question_count", 8)),
            destination=value.get("destination", "practice_now"),
        )

    def instruction(self, language: str = "zh") -> str:
        """Return a concise editable instruction for the next AI request."""
        if language != "zh":
            lines = [
                "Targeted reinforcement: address the observed mistakes below.",
                "Do not repeat the original questions; vary the scenario while preserving course evidence.",
            ]
            for signal in self.signals:
                detail = f"topic={signal.topic_id}"
                if signal.question_ids:
                    detail += f", question_ids={', '.join(signal.question_ids)}"
                if signal.observed_wrong_answers:
                    detail += f", wrong_answers={'; '.join(signal.observed_wrong_answers)}"
                if signal.unsure_question_ids:
                    detail += f", unsure_ids={', '.join(signal.unsure_question_ids)}"
                if signal.source_refs:
                    detail += f", source_refs={', '.join(signal.source_refs)}"
                lines.append(detail)
            return "\n".join(lines)

        lines = [
            "针对以下具体答题表现生成补强题：定位相同误解，改换场景或数字，保持课程资料约束。",
            "不要复述原题，也不要只重复术语定义。",
        ]
        for signal in self.signals:
            detail = f"知识点：{signal.topic_id}"
            if signal.question_ids:
                detail += f"；相关题目：{', '.join(signal.question_ids)}"
            if signal.observed_wrong_answers:
                detail += f"；用户错误答案：{'；'.join(signal.observed_wrong_answers)}"
            if signal.unsure_question_ids:
                detail += f"；不确定题：{', '.join(signal.unsure_question_ids)}"
            if signal.source_refs:
                detail += f"；课程来源：{'、'.join(signal.source_refs)}"
            lines.append(detail)
        return "\n".join(lines)
