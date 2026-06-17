"""Progress tracking: load, save, aggregate progress records."""

from __future__ import annotations

import os
from typing import Optional

from models.progress import ProgressRecord, SessionSummary, AnswerRecord
from models.question_set import QuestionSet
from utils.json_io import read_json, write_json, list_json_files, load_all_json, delete_json, sanitize_filename_part


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
        for data in load_all_json(self._dir):
            try:
                records.append(ProgressRecord.from_dict(data))
            except Exception:
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

    def save(self, record: ProgressRecord) -> bool:
        """Save a progress record to JSON."""
        filepath = f"{self._dir}/{record.progress_id}.json"
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

    def get_aggregated_stats(self) -> dict:
        """Compute overall statistics across all sessions."""
        records = self.load_all()
        completed = [r for r in records if r.status == "completed" and r.summary]

        total_sessions = len(completed)
        if total_sessions == 0:
            return {
                "total_sessions": 0,
                "total_questions": 0,
                "total_correct": 0,
                "overall_accuracy": 0.0,
                "per_topic": {},
                "recent_sessions": [],
            }

        total_questions = sum(r.summary.total_questions for r in completed)
        total_correct = sum(r.summary.correct for r in completed)
        overall_accuracy = (total_correct / total_questions * 100) if total_questions > 0 else 0.0

        # Recent sessions (last 20)
        recent = completed[:20]
        recent_sessions = [
            {
                "progress_id": r.progress_id,
                "set_id": r.set_id,
                "started_at": r.started_at,
                "score": r.summary.score_percentage if r.summary else 0,
                "total": r.summary.total_questions if r.summary else 0,
                "correct": r.summary.correct if r.summary else 0,
            }
            for r in recent
        ]

        return {
            "total_sessions": total_sessions,
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
            for answer in record.answers:
                if not answer.is_correct:
                    incorrect.add(answer.question_id)
        return list(incorrect)

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
