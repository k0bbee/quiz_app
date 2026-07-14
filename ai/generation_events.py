"""UI-independent events emitted by a question generation run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from ai.generation_report import GenerationReport


@dataclass(frozen=True)
class ProgressEvent:
    message: str


@dataclass(frozen=True)
class QuestionsReadyEvent:
    questions: tuple

    @classmethod
    def from_questions(cls, questions: list) -> "QuestionsReadyEvent":
        return cls(tuple(questions))


@dataclass(frozen=True)
class CompletedEvent:
    questions: tuple

    @classmethod
    def from_questions(cls, questions: list) -> "CompletedEvent":
        return cls(tuple(questions))


@dataclass(frozen=True)
class PartialResultEvent:
    questions: tuple
    report: GenerationReport

    @classmethod
    def from_questions(
        cls,
        questions: list,
        report: GenerationReport,
    ) -> "PartialResultEvent":
        return cls(tuple(questions), report)


@dataclass(frozen=True)
class FailedEvent:
    error: object


GenerationEvent: TypeAlias = (
    ProgressEvent
    | QuestionsReadyEvent
    | CompletedEvent
    | PartialResultEvent
    | FailedEvent
)
