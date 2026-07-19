"""Shared semantic build stages for course initialization and regeneration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from ai.course_generation_profile import build_local_course_profile
from core.background_task import TaskControl
from core.document_parser import ExtractedDocument
from models.course_project import CourseTopic


@dataclass(frozen=True)
class CourseBuildArtifacts:
    """Semantic artifacts produced before persistence and retrieval indexing."""

    topics: list[CourseTopic]
    summary_markdown: str
    summary_source: str
    summary_warning: str
    generation_profile: dict
    generation_profile_source: str
    generation_profile_warning: str


class CourseBuildPipeline:
    """Build course topics, summary, and generation defaults in one workflow."""

    def __init__(
        self,
        *,
        topic_inferer: Callable[[list[ExtractedDocument]], list[CourseTopic]],
        summary_builder: Callable[
            [str, list[ExtractedDocument], list[CourseTopic]], str
        ],
        topic_reconciler: Callable[
            [Sequence[CourseTopic], list[CourseTopic]], list[CourseTopic]
        ],
        summary_generator=None,
        profile_generator=None,
    ) -> None:
        self._topic_inferer = topic_inferer
        self._summary_builder = summary_builder
        self._topic_reconciler = topic_reconciler
        self._summary_generator = summary_generator
        self._profile_generator = profile_generator

    def build(
        self,
        title: str,
        documents: list[ExtractedDocument],
        *,
        previous_topics: Sequence[CourseTopic] | None,
        task: TaskControl | None,
    ) -> CourseBuildArtifacts:
        self._report(task, "topics")
        topics = self._topic_inferer(documents)
        if previous_topics is not None:
            topics = self._topic_reconciler(previous_topics, topics)

        self._report(task, "summary")
        summary = self._summary_builder(title, documents, topics)
        summary_source = "local"
        summary_warning = ""
        if self._summary_generator is not None:
            self._report(task, "summary_ai")
            summary = self._summary_generator.generate(title, documents, topics, summary)
            self._check(task)
            summary_source = getattr(self._summary_generator, "summary_source", "llm")
            summary_warning = getattr(self._summary_generator, "summary_warning", "")

        self._report(task, "profile")
        profile, profile_source, profile_warning = self._generate_profile(
            title, topics, summary
        )
        self._check(task)
        return CourseBuildArtifacts(
            topics=topics,
            summary_markdown=summary,
            summary_source=summary_source,
            summary_warning=summary_warning,
            generation_profile=profile,
            generation_profile_source=profile_source,
            generation_profile_warning=profile_warning,
        )

    def _generate_profile(
        self,
        title: str,
        topics: list[CourseTopic],
        summary: str,
    ) -> tuple[dict, str, str]:
        """Keep an optional profile-model failure from blocking course import."""
        try:
            plan = self._profile_generator.generate(title, topics, summary)
            source = getattr(self._profile_generator, "profile_source", "local")
            warning = getattr(self._profile_generator, "profile_warning", "")
        except Exception as exc:
            plan = build_local_course_profile(topics, summary)
            source = "local"
            warning = f"Course generation profile failed: {exc}"
        return plan.to_dict(), source, warning

    @staticmethod
    def _check(task: TaskControl | None) -> None:
        if task is not None:
            task.check_cancelled()

    @staticmethod
    def _report(task: TaskControl | None, stage: str) -> None:
        if task is not None:
            task.report(stage)
