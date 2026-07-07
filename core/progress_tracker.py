"""Progress tracking: load, save, aggregate progress records."""

from __future__ import annotations

import os
from typing import Optional

from models.progress import ProgressRecord, SessionSummary, AnswerRecord
from models.question_set import QuestionSet
from core.mastery import prioritize_review_question_ids
from utils.json_io import read_json, write_json, list_json_files, delete_json, sanitize_filename_part
from utils.logger import warning


class ProgressManager:
    """Manages progress records: CRUD, aggregation, and analysis."""

    def __init__(self, progress_dir: str):
        self._dir = progress_dir
        os.makedirs(self._dir, exist_ok=True)

    @property
    def directory(self) -> str:
        return self._dir

    # --- CRUD ---

    def load_all(self) -> list[ProgressRecord]:
        """Load all progress records, sorted by date (newest first)."""
        records = []
        for filename in list_json_files(self._dir):
            filepath = os.path.join(self._dir, filename)
            data = read_json(filepath)
            if data is None:
                continue
            try:
                if not isinstance(data, dict):
                    raise TypeError(f"expected object, got {type(data).__name__}")
                records.append(ProgressRecord.from_dict(data))
            except Exception as exc:
                warning(f"Skipped invalid progress record {filename}: {exc}")
                continue
        records.sort(key=lambda r: r.started_at, reverse=True)
        return records

    def load_for_set(self, set_id: str) -> list[ProgressRecord]:
        """Load all attempts for a specific question set."""
        return [r for r in self.load_all() if r.set_id == set_id]

    def get(self, progress_id: str) -> Optional[ProgressRecord]:
        """Get a specific progress record by ID."""
        filepath = f"{self._dir}/{sanitize_filename_part(progress_id)}.json"
        data = read_json(filepath)
        if data:
            return ProgressRecord.from_dict(data)
        return None

    def get_latest_abandoned_record(self) -> Optional[ProgressRecord]:
        """Return the newest abandoned quiz draft, if any."""
        abandoned = [record for record in self.load_all() if record.status == "abandoned"]
        return abandoned[0] if abandoned else None

    def save(self, record: ProgressRecord) -> bool:
        """Save a progress record to JSON."""
        safe_id = sanitize_filename_part(record.progress_id)
        filepath = f"{self._dir}/{safe_id}.json"
        return write_json(filepath, record.to_dict())

    def delete(self, progress_id: str) -> bool:
        """Delete a progress record."""
        return delete_json(f"{self._dir}/{sanitize_filename_part(progress_id)}.json")

    def delete_for_set(self, set_id: str):
        """Delete all progress records for a set."""
        for r in self.load_for_set(set_id):
            self.delete(r.progress_id)

    def reset_all(self):
        """Delete all progress records."""
        for filename in list_json_files(self._dir):
            delete_json(f"{self._dir}/{filename}")

    # --- Aggregation ---

    def get_aggregated_stats(self, question_ids: set[str] | None = None) -> dict:
        """Compute overall statistics across all sessions."""
        records = self.load_all()
        completed = [r for r in records if r.status == "completed" and r.summary]
        partial_sessions = 0
        if question_ids is not None:
            filtered = []
            for record in completed:
                answers = [answer for answer in record.answers if answer.question_id in question_ids]
                if not answers:
                    continue
                summary = SessionSummary.compute(answers, len(answers), sum(
                    answer.time_spent_seconds for answer in answers
                ))
                session_total = record.summary.total_questions if record.summary else len(record.answers)
                is_partial = summary.total_questions != session_total
                if is_partial:
                    partial_sessions += 1
                filtered.append((record, summary, session_total, is_partial))
        else:
            filtered = [
                (record, record.summary, record.summary.total_questions, False)
                for record in completed
                if record.summary
            ]

        total_sessions = len(filtered)
        if total_sessions == 0:
            return {
                "total_sessions": 0,
                "partial_sessions": 0,
                "total_questions": 0,
                "total_correct": 0,
                "overall_accuracy": 0.0,
                "per_topic": {},
                "recent_sessions": [],
            }

        total_questions = sum(summary.total_questions for _record, summary, _session_total, _is_partial in filtered)
        total_correct = sum(summary.correct for _record, summary, _session_total, _is_partial in filtered)
        overall_accuracy = (total_correct / total_questions * 100) if total_questions > 0 else 0.0

        # Recent sessions (last 20)
        recent = filtered[:20]
        recent_sessions = [
            {
                "progress_id": r.progress_id,
                "set_id": r.set_id,
                "started_at": r.started_at,
                "score": summary.score_percentage,
                "total": summary.total_questions,
                "correct": summary.correct,
                "matched_total": summary.total_questions,
                "session_total": session_total,
                "is_partial": is_partial,
            }
            for r, summary, session_total, is_partial in recent
        ]

        return {
            "total_sessions": total_sessions,
            "partial_sessions": partial_sessions,
            "total_questions": total_questions,
            "total_correct": total_correct,
            "overall_accuracy": round(overall_accuracy, 1),
            "per_topic": {},  # populated externally with topic info from question sets
            "recent_sessions": recent_sessions,
        }

    def get_incorrect_question_ids(self) -> list[str]:
        """Get all question IDs that were answered incorrectly across all sessions."""
        incorrect = set()
        for record in self.load_all():
            if record.status != "completed":
                continue
            for answer in record.answers:
                if not answer.is_correct:
                    incorrect.add(answer.question_id)
        return sorted(incorrect)

    def get_prioritized_review_question_ids(
        self,
        candidate_question_ids: list[str] | set[str] | None = None,
    ) -> list[str]:
        """Get historically wrong question IDs ordered by review priority."""
        return prioritize_review_question_ids(self.load_all(), candidate_question_ids)

    def get_incorrect_for_topics(
        self, question_ids_by_topic: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """Group incorrect question IDs by topic.
        question_ids_by_topic: {topic: [question_id, ...]} mapping.
        Returns: {topic: [incorrect_question_id, ...]}"""
        all_incorrect = set(self.get_incorrect_question_ids())
        result = {}
        for topic, qids in question_ids_by_topic.items():
            topic_incorrect = [qid for qid in qids if qid in all_incorrect]
            if topic_incorrect:
                result[topic] = topic_incorrect
        return result
