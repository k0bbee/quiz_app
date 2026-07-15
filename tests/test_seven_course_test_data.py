from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.seven_course_test_data import (
    SEVEN_COURSE_IDS,
    audit_seven_course_data,
    seed_seven_course_data,
)
from utils.constants import QuestionType


class SevenCourseTestDataTests(unittest.TestCase):
    def test_seed_pack_builds_seven_runnable_cross_discipline_courses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "seven-course-data"

            seeded = seed_seven_course_data(root)
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

            repeated = seed_seven_course_data(root)
            repeated_audit = audit_seven_course_data(root)
            self.assertEqual(seeded, repeated)
            self.assertEqual(21, repeated_audit.question_count)
            self.assertEqual(7, repeated_audit.question_set_count)


if __name__ == "__main__":
    unittest.main()
