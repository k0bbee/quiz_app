import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.json_io import read_json, write_json


class JsonIoTests(unittest.TestCase):
    def test_write_json_replaces_file_atomically_on_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text('{"version": 1}', encoding="utf-8")

            ok = write_json(str(path), {"version": 2, "name": "课程"})

            self.assertTrue(ok)
            self.assertEqual({"version": 2, "name": "课程"}, read_json(str(path)))

    def test_write_json_preserves_existing_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            original = {"progress_id": "old", "answers": [1, 2, 3]}
            path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

            with patch("utils.json_io.os.replace", side_effect=OSError("simulated replace failure")):
                ok = write_json(str(path), {"progress_id": "new"})

            self.assertFalse(ok)
            self.assertEqual(original, read_json(str(path)))
            self.assertEqual(["progress.json"], [item.name for item in Path(tmpdir).iterdir()])

    def test_write_json_preserves_existing_file_when_data_is_not_serializable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "question.json"
            original = {"question_id": "q1"}
            path.write_text(json.dumps(original), encoding="utf-8")

            ok = write_json(str(path), {"bad": {object()}})

            self.assertFalse(ok)
            self.assertEqual(original, read_json(str(path)))
            self.assertEqual(["question.json"], [item.name for item in Path(tmpdir).iterdir()])


if __name__ == "__main__":
    unittest.main()
