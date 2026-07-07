import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.progress_tracker import ProgressManager
from models.progress import AnswerRecord, ProgressRecord, SessionSummary
from utils.json_io import write_json


class ProgressTrackerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
