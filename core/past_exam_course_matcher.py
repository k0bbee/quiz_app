"""Explainable, conservative course matching for imported historical exams."""

from __future__ import annotations

from dataclasses import dataclass
import re


AUTO_ASSIGN_THRESHOLD = 0.35
AUTO_ASSIGN_MARGIN = 0.12


@dataclass(frozen=True)
class CourseMatchCandidate:
    course_id: str
    course_title: str
    score: float
    matched_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "course_id": self.course_id,
            "course_title": self.course_title,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class CourseMatchResult:
    assigned_course_id: str
    candidates: tuple[CourseMatchCandidate, ...] = ()


def match_exam_to_courses(title: str, text: str, courses) -> CourseMatchResult:
    """Rank courses and auto-assign only when the best match is unambiguous."""
    normalized_title = _normalize(title)
    normalized_text = _normalize(text)
    candidates = [
        _score_course(course, normalized_title, normalized_text)
        for course in courses or []
        if str(getattr(course, "course_id", "") or "").strip()
    ]
    candidates.sort(key=lambda item: (-item.score, item.course_title.casefold(), item.course_id))
    candidates = candidates[:5]

    assigned_course_id = ""
    if candidates:
        best = candidates[0]
        runner_up_score = candidates[1].score if len(candidates) > 1 else 0.0
        if (
            best.score >= AUTO_ASSIGN_THRESHOLD
            and best.score - runner_up_score >= AUTO_ASSIGN_MARGIN
        ):
            assigned_course_id = best.course_id
    return CourseMatchResult(assigned_course_id, tuple(candidates))


def _score_course(course, title: str, text: str) -> CourseMatchCandidate:
    weighted_terms: dict[str, tuple[float, float]] = {}

    def add(value, title_weight: float, text_weight: float):
        term = _normalize(value)
        if not _useful_term(term):
            return
        previous = weighted_terms.get(term, (0.0, 0.0))
        weighted_terms[term] = (
            max(previous[0], title_weight),
            max(previous[1], text_weight),
        )

    add(getattr(course, "title", ""), 8.0, 4.0)
    for topic in getattr(course, "topics", []) or []:
        add(getattr(topic, "title", ""), 5.0, 3.0)
        add(str(getattr(topic, "topic_id", "") or "").replace("_", " "), 4.0, 2.0)
        for alias in getattr(topic, "aliases", []) or []:
            add(alias, 5.0, 3.0)
        for keyword in getattr(topic, "keywords", []) or []:
            add(keyword, 3.0, 1.0)

    points = 0.0
    matched_terms = []
    for term, (title_weight, text_weight) in weighted_terms.items():
        matched = False
        if _contains(title, term):
            points += title_weight
            matched = True
        elif _contains(text, term):
            points += text_weight
            matched = True
        if matched:
            matched_terms.append(term)

    return CourseMatchCandidate(
        course_id=str(getattr(course, "course_id", "") or "").strip(),
        course_title=str(getattr(course, "title", "") or "").strip(),
        score=round(min(1.0, points / 15.0), 3),
        matched_terms=tuple(sorted(matched_terms)),
    )


def _normalize(value) -> str:
    text = str(value or "").casefold().replace("/", " ").replace("_", " ")
    text = re.sub(r"[^\w\u3400-\u9fff]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _useful_term(term: str) -> bool:
    if not term:
        return False
    compact = term.replace(" ", "")
    if any("\u3400" <= char <= "\u9fff" for char in compact):
        return len(compact) >= 2
    return len(compact) >= 3


def _contains(haystack: str, term: str) -> bool:
    if not haystack or not term:
        return False
    if any("\u3400" <= char <= "\u9fff" for char in term):
        return term in haystack
    return f" {term} " in f" {haystack} "
