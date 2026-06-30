"""Repair legacy question topic fields against stable course topic IDs."""

from __future__ import annotations

from dataclasses import dataclass, field

from models.course_project import CourseProject, CourseTopic
from models.question import Question
from utils.constants import topic_alias_values, topic_label, topic_matches, topic_value


@dataclass(frozen=True)
class UnmatchedTopicQuestion:
    """A question whose legacy topic could not be safely mapped."""

    question_id: str
    topic: str
    reason: str


@dataclass(frozen=True)
class TopicIdentityRepairReport:
    """Summary of one topic-identity repair scan."""

    scanned: int = 0
    updated: int = 0
    already_current: int = 0
    skipped_other_course: int = 0
    save_failed: list[str] = field(default_factory=list)
    unmatched: list[UnmatchedTopicQuestion] = field(default_factory=list)


def repair_question_topic_identities(question_bank, course_project: CourseProject) -> TopicIdentityRepairReport:
    """Backfill question topic_id/topic_title fields from a course project.

    The repair is conservative: questions from another explicit course are
    skipped, unique matches are saved, and unknown/ambiguous legacy topics are
    reported instead of guessed.
    """
    course_id = str(getattr(course_project, "course_id", "") or "").strip()
    topics = list(getattr(course_project, "topics", []) or [])
    scanned = updated = already_current = skipped_other_course = 0
    unmatched: list[UnmatchedTopicQuestion] = []
    save_failed: list[str] = []

    for question in question_bank.load_all():
        question_course_id = str((question.metadata or {}).get("course_id", "") or "").strip()
        if course_id and question_course_id and question_course_id != course_id:
            skipped_other_course += 1
            continue

        scanned += 1
        candidates = _question_topic_candidates(question)
        matches = _matching_topics(candidates, topics)
        if not matches:
            unmatched.append(
                UnmatchedTopicQuestion(
                    question_id=question.question_id,
                    topic=next(iter(candidates), question.topic_id()),
                    reason="unmatched",
                )
            )
            continue
        if len(matches) > 1:
            unmatched.append(
                UnmatchedTopicQuestion(
                    question_id=question.question_id,
                    topic=next(iter(candidates), question.topic_id()),
                    reason="ambiguous",
                )
            )
            continue

        topic = matches[0]
        if _question_matches_stable_topic(question, topic):
            already_current += 1
            continue
        _apply_topic_identity(question, topic)
        if question_bank.save(question):
            updated += 1
        else:
            save_failed.append(question.question_id)

    return TopicIdentityRepairReport(
        scanned=scanned,
        updated=updated,
        already_current=already_current,
        skipped_other_course=skipped_other_course,
        save_failed=save_failed,
        unmatched=unmatched,
    )


def _question_topic_candidates(question: Question) -> set[str]:
    metadata = question.metadata or {}
    candidates = {
        str(question.topic or "").strip(),
        question.topic_id(),
        str(metadata.get("topic_title", "") or "").strip(),
        str(metadata.get("legacy_topic", "") or "").strip(),
    }
    return {candidate for candidate in candidates if candidate}


def _matching_topics(candidates: set[str], topics: list[CourseTopic]) -> list[CourseTopic]:
    matches: list[CourseTopic] = []
    for topic in topics:
        if any(topic_matches(candidate, topic) for candidate in candidates):
            matches.append(topic)
            continue
        topic_aliases = topic_alias_values(topic)
        candidate_aliases = {candidate.strip().lower() for candidate in candidates}
        if topic_aliases & candidate_aliases:
            matches.append(topic)
    return matches


def _question_matches_stable_topic(question: Question, topic: CourseTopic) -> bool:
    return (
        question.topic_id() == topic_value(topic)
        and question.topic_title() == topic_label(topic)
    )


def _apply_topic_identity(question: Question, topic: CourseTopic) -> None:
    old_topic = str(question.topic or "").strip()
    metadata = dict(question.metadata or {})
    stable_id = topic_value(topic)
    display_title = topic_label(topic)
    if old_topic and old_topic.lower() != stable_id:
        metadata.setdefault("legacy_topic", old_topic)
    metadata["topic_title"] = display_title
    question.topic = stable_id
    question.metadata = metadata
