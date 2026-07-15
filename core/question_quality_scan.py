"""Cancellable, UI-independent quality scans for stored question banks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from core.background_task import TaskControl
from core.question_validation import validate_question_quality
from models.question import Question
from utils.json_io import list_json_files, read_json


@dataclass(frozen=True)
class QuestionQualityResult:
    question_id: str
    structural_errors: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()

    @property
    def has_issues(self) -> bool:
        return bool(self.structural_errors or self.issue_codes)


@dataclass(frozen=True)
class QuestionQualityScanReport:
    scanned_count: int
    results: tuple[QuestionQualityResult, ...]
    issue_counts: tuple[tuple[str, int], ...] = ()

    @property
    def issue_question_ids(self) -> tuple[str, ...]:
        return tuple(result.question_id for result in self.results if result.has_issues)

    @property
    def issue_question_count(self) -> int:
        return len(self.issue_question_ids)

    def result_for(self, question_id: str) -> QuestionQualityResult | None:
        return next(
            (result for result in self.results if result.question_id == question_id),
            None,
        )


def scan_question_bank_quality(
    question_bank,
    *,
    course_id: str = "",
    task: TaskControl | None = None,
) -> QuestionQualityScanReport:
    """Validate one course scope in deterministic, cancellable question units."""
    directory = str(question_bank.directory)
    filenames = list_json_files(directory)
    total = len(filenames)
    _report(task, "discovering_questions", total=total, detail=course_id)
    results: list[QuestionQualityResult] = []
    counts: Counter[str] = Counter()
    matched_count = 0

    for index, filename in enumerate(filenames, start=1):
        _report(task, "loading_question", index, total, filename)
        data = read_json(str(Path(directory) / filename))
        if not isinstance(data, dict):
            if course_id:
                continue
            question_id = Path(filename).stem
            counts["unreadable_question"] += 1
            results.append(QuestionQualityResult(
                question_id=question_id,
                structural_errors=("Question record could not be loaded",),
                issue_codes=("unreadable_question",),
            ))
            continue
        metadata = data.get("metadata", {}) or {}
        record_course_id = (
            str(metadata.get("course_id", "") or "").strip()
            if isinstance(metadata, dict)
            else ""
        )
        if course_id and record_course_id != course_id:
            continue
        try:
            question = Question.from_dict(data)
        except (TypeError, ValueError):
            question_id = str(data.get("question_id") or Path(filename).stem)
            counts["unreadable_question"] += 1
            results.append(QuestionQualityResult(
                question_id=question_id,
                structural_errors=("Question record could not be loaded",),
                issue_codes=("unreadable_question",),
            ))
            continue

        matched_count += 1
        question_id = question.question_id or Path(filename).stem
        _report(task, "validating_question", matched_count, 0, question_id)
        structural_errors = tuple(question.validate())
        issue_codes = _question_issue_codes(question)
        if structural_errors:
            counts["structural_error"] += 1
        counts.update(issue_codes)
        results.append(QuestionQualityResult(
            question_id=question_id,
            structural_errors=structural_errors,
            issue_codes=issue_codes,
        ))

    report = QuestionQualityScanReport(
        scanned_count=len(results),
        results=tuple(results),
        issue_counts=tuple(sorted(counts.items())),
    )
    if task is not None:
        task.complete(
            "validated",
            detail=f"{report.issue_question_count}/{report.scanned_count}",
        )
    return report


def _question_issue_codes(question) -> tuple[str, ...]:
    codes = [issue.code for issue in validate_question_quality(question)]
    metadata = question.metadata or {}
    if any(_has_stored_warning(metadata.get(key)) for key in (
        "quality_warnings",
        "quality_issues",
        "validation_issues",
        "warnings",
    )):
        codes.append("stored_quality_warning")
    if metadata.get("invalid_source_ref_ids"):
        codes.append("invalid_source_ref_ids")
    return tuple(dict.fromkeys(codes))


def _has_stored_warning(value) -> bool:
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return isinstance(value, str) and bool(value.strip())


def _report(
    task: TaskControl | None,
    stage: str,
    current: int = 0,
    total: int = 0,
    detail: str = "",
) -> None:
    if task is not None:
        task.report(stage, current, total, detail)
