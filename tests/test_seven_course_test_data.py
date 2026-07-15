from __future__ import annotations

import tempfile
import unittest
import json
import subprocess
import sys
from pathlib import Path

from core.seven_course_test_data import (
    SEVEN_COURSE_IDS,
    SEVEN_COURSE_SOURCES,
    audit_seven_course_data,
    seed_seven_course_data,
)
from utils.constants import QuestionType


class SevenCourseTestDataTests(unittest.TestCase):
    def test_seed_pack_builds_seven_runnable_cross_discipline_courses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "seven-course-data"
            source_root = Path(tmpdir) / "original-sources"
            self._write_original_sources(source_root)

            seeded = seed_seven_course_data(root, source_root=source_root)
            audit = audit_seven_course_data(root)

            self.assertEqual(7, seeded.course_count)
            self.assertEqual(set(SEVEN_COURSE_IDS), set(audit.course_ids))
            self.assertEqual(21, audit.question_count)
            self.assertEqual(7, audit.question_set_count)
            self.assertTrue(all(count == 3 for count in audit.questions_per_course.values()))
            self.assertTrue(all(count == 1 for count in audit.sets_per_course.values()))
            self.assertEqual(set(QuestionType), set(audit.question_types))
            self.assertEqual((), audit.stale_question_refs)
            self.assertEqual((), audit.orphan_course_refs)
            self.assertEqual((), audit.structurally_invalid_question_ids)
            self.assertTrue(all(count >= 1 for count in audit.documents_per_course.values()))
            self.assertTrue(all(count >= 1 for count in audit.source_chunks_per_course.values()))

            repeated = seed_seven_course_data(root, source_root=source_root)
            repeated_audit = audit_seven_course_data(root)
            self.assertEqual(seeded, repeated)
            self.assertEqual(21, repeated_audit.question_count)
            self.assertEqual(7, repeated_audit.question_set_count)

    def test_cli_clean_rebuild_prints_json_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "seven-course-runtime"
            source_root = Path(tmpdir) / "original-sources"
            self._write_original_sources(source_root)
            stale = root / "questions" / "stale.json"
            stale.parent.mkdir(parents=True)
            stale.write_text("{}", encoding="utf-8")
            script = Path(__file__).parents[1] / "scripts" / "seed_seven_course_test_data.py"

            completed = subprocess.run(
                [
                    sys.executable, str(script),
                    "--root", str(root),
                    "--source-root", str(source_root),
                    "--clean",
                ],
                cwd=script.parents[1],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(7, report["course_count"])
            self.assertEqual(21, report["question_count"])
            self.assertEqual(7, report["question_set_count"])
            self.assertEqual([], report["stale_question_refs"])
            self.assertFalse(stale.exists())

    @staticmethod
    def _write_original_sources(source_root: Path) -> None:
        source_root.mkdir(parents=True)
        for slug, filenames in SEVEN_COURSE_SOURCES.items():
            filename = filenames[-1]
            topic = slug.replace("-", " ")
            sentences = [
                f"{topic} source section {index} explains a domain concept, its conditions, process, evidence, and limitations."
                for index in range(1, 18)
            ]
            (source_root / filename).write_text("\n".join(sentences), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
