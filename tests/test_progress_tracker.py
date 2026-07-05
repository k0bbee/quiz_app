import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.progress_tracker import ProgressManager
from models.progress import ProgressRecord
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


if __name__ == "__main__":
    unittest.main()
