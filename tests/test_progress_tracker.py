import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.progress_tracker import ProgressManager
from models.progress import AnswerRecord, ProgressRecord, SessionSummary
from utils.json_io import write_json


class ProgressTrackerTests(unittest.TestCase):
    def test_session_summary_distinguishes_skipped_from_incorrect_answers(self):
        answers = [
            AnswerRecord("q-right", 0, "A", True),
            AnswerRecord("q-wrong", 1, "B", False),
            AnswerRecord("q-skip", 2, None, False, skipped=True),
        ]

        summary = SessionSummary.compute(answers, total_questions=3, total_time=30)

        self.assertEqual(2, summary.answered)
        self.assertEqual(1, summary.correct)
        self.assertEqual(1, summary.incorrect)
        self.assertEqual(1, summary.skipped)
        self.assertEqual(33.3, summary.to_dict()["score_percentage"])

    def test_load_all_logs_invalid_progress_records_with_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_dir = Path(tmpdir) / "progress"
            manager = ProgressManager(str(progress_dir))
            valid = ProgressRecord.create_new("set-ok")
            manager.save(valid)
            write_json(str(progress_dir / "bad-progress.json"), "not a progress object")

            with patch("core.progress_tracker.warning", create=True) as warn:
                records = manager.load_all()

            self.assertEqual([valid.progress_id], [record.progress_id for record in records])
            self.assertEqual(1, warn.call_count)
            message = warn.call_args.args[0]
            self.assertIn("bad-progress.json", message)
            self.assertIn("invalid progress record", message)

    def test_get_incorrect_question_ids_ignores_abandoned_and_in_progress_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_dir = Path(tmpdir) / "progress"
            manager = ProgressManager(str(progress_dir))

            completed = ProgressRecord.create_new("set-ok")
            completed.status = "completed"
            completed.summary = SessionSummary(total_questions=1, answered=1, correct=0, incorrect=1)
            completed.answers = [
                AnswerRecord(
                    question_id="q-completed-wrong",
                    index_in_session=0,
                    user_answer="B",
                    is_correct=False,
                )
            ]
            manager.save(completed)

            abandoned = ProgressRecord.create_new("set-draft")
            abandoned.status = "abandoned"
            abandoned.answers = [
                AnswerRecord(
                    question_id="q-abandoned-wrong",
                    index_in_session=0,
                    user_answer="B",
                    is_correct=False,
                )
            ]
            manager.save(abandoned)

            in_progress = ProgressRecord.create_new("set-live")
            in_progress.status = "in_progress"
            in_progress.answers = [
                AnswerRecord(
                    question_id="q-in-progress-wrong",
                    index_in_session=0,
                    user_answer="B",
                    is_correct=False,
                )
            ]
            manager.save(in_progress)

            incorrect = manager.get_incorrect_question_ids()

            self.assertEqual({"q-completed-wrong"}, set(incorrect))

    def test_get_incorrect_question_ids_excludes_skipped_answers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProgressManager(str(Path(tmpdir) / "progress"))
            completed = ProgressRecord.create_new("set-ok")
            completed.status = "completed"
            completed.answers = [
                AnswerRecord("q-skipped", 0, None, False, skipped=True),
                AnswerRecord("q-wrong", 1, "B", False),
            ]
            completed.summary = SessionSummary.compute(
                completed.answers, total_questions=2, total_time=10
            )
            manager.save(completed)

            self.assertEqual(["q-wrong"], manager.get_incorrect_question_ids())

    def test_get_latest_abandoned_record_scans_files_without_loading_all_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_dir = Path(tmpdir) / "progress"
            manager = ProgressManager(str(progress_dir))

            older_abandoned = ProgressRecord.create_new("set-draft-old")
            older_abandoned.progress_id = "progress-old-abandoned"
            older_abandoned.started_at = "2026-01-01T00:00:00+00:00"
            older_abandoned.status = "abandoned"
            manager.save(older_abandoned)

            completed = ProgressRecord.create_new("set-completed")
            completed.progress_id = "progress-new-completed"
            completed.started_at = "2026-01-03T00:00:00+00:00"
            completed.status = "completed"
            manager.save(completed)

            newer_abandoned = ProgressRecord.create_new("set-draft-new")
            newer_abandoned.progress_id = "progress-new-abandoned"
            newer_abandoned.started_at = "2026-01-02T00:00:00+00:00"
            newer_abandoned.status = "abandoned"
            manager.save(newer_abandoned)

            with patch.object(manager, "load_all", side_effect=AssertionError("should not load all progress records")):
                latest = manager.get_latest_abandoned_record()

            self.assertIsNotNone(latest)
            self.assertEqual("progress-new-abandoned", latest.progress_id)


if __name__ == "__main__":
    unittest.main()
