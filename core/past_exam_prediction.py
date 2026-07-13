"""Aggregate historical-exam profiles into a reviewable generation plan."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median

from ai.exam_plan import ExamGenerationPlan
from config import DEFAULT_DIFFICULTY_WEIGHTS, DEFAULT_QUESTION_TYPE_WEIGHTS


_SUPPORTED_TYPES = tuple(DEFAULT_QUESTION_TYPE_WEIGHTS)


@dataclass(frozen=True)
class PastExamPrediction:
    course_id: str
    exam_ids: tuple[str, ...]
    plan: ExamGenerationPlan
    warnings: tuple[str, ...] = ()

    @property
    def source_count(self) -> int:
        return len(self.exam_ids)


class PastExamPredictionPlanner:
    """Use observed distributions as evidence, not as a claim of future certainty."""

    def __init__(self, exam_manager):
        self.exam_manager = exam_manager

    def build(self, course) -> PastExamPrediction:
        course_id = str(getattr(course, "course_id", "") or "").strip()
        if not course_id:
            raise ValueError("Prediction requires a course")

        profiles = []
        for record in self.exam_manager.load_all():
            if record.course_id != course_id or record.analysis_status != "complete":
                continue
            analysis = self.exam_manager.get_analysis(record.exam_id)
            if analysis is not None:
                profiles.append((record, analysis))
        if not profiles:
            raise ValueError("No completed historical exam profiles are available for this course")

        available_topics = [
            str(getattr(topic, "topic_id", "") or "").strip()
            for topic in getattr(course, "topics", []) or []
        ]
        available_topics = [topic_id for topic_id in available_topics if topic_id]
        topic_totals = Counter()
        type_totals = Counter()
        unsupported_types = Counter()
        question_counts = []
        for _record, analysis in profiles:
            if analysis.detected_question_count > 0:
                question_counts.append(analysis.detected_question_count)
            for item in analysis.question_types:
                if item.question_type in _SUPPORTED_TYPES:
                    type_totals[item.question_type] += item.count
                elif item.count > 0:
                    unsupported_types[item.question_type] += item.count
            for item in analysis.topic_profile:
                if item.topic_id in available_topics and item.weight > 0:
                    topic_totals[item.topic_id] += item.weight

        selected_topics = tuple(topic_id for topic_id in available_topics if topic_totals[topic_id] > 0)
        if not selected_topics:
            raise ValueError("Historical exam profiles contain no reliable course-topic evidence")

        question_count = 15
        if question_counts:
            question_count = max(3, min(60, int(median(question_counts) + 0.5)))
        question_type_weights = {
            key: type_totals[key]
            for key in _SUPPORTED_TYPES
        }
        if not any(question_type_weights.values()):
            question_type_weights = dict(DEFAULT_QUESTION_TYPE_WEIGHTS)

        warnings = []
        if unsupported_types:
            details = ", ".join(
                f"{key}={unsupported_types[key]}"
                for key in sorted(unsupported_types)
            )
            warnings.append(
                "Observed types are not available in the current AI generation controls and "
                f"were excluded: {details}"
            )
        plan = ExamGenerationPlan(
            question_count=question_count,
            difficulty="mixed",
            template="final_exam",
            selected_topics=selected_topics,
            question_type_weights=question_type_weights,
            difficulty_weights=dict(DEFAULT_DIFFICULTY_WEIGHTS),
            topic_weights={topic_id: topic_totals[topic_id] for topic_id in selected_topics},
        )
        return PastExamPrediction(
            course_id=course_id,
            exam_ids=tuple(sorted(record.exam_id for record, _analysis in profiles)),
            plan=plan,
            warnings=tuple(warnings),
        )
