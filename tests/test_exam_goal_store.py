import tempfile
import unittest
from datetime import date
from pathlib import Path

from core.exam_goal_store import ExamGoal, ExamGoalStore


class ExamGoalStoreTests(unittest.TestCase):
    def test_persists_one_valid_goal_per_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ExamGoalStore(Path(tmpdir) / "exam-goals.json")
            goal = ExamGoal(
                course_id="course-a",
                exam_date="2026-08-17",
                daily_minutes=45,
                target_mastery=0.8,
                included_topic_ids=("io", "memory"),
            )

            store.save(goal)
            restored = ExamGoalStore(
                Path(tmpdir) / "exam-goals.json"
            ).get("course-a")

        self.assertEqual(goal, restored)
        self.assertEqual(18, restored.days_remaining(date(2026, 7, 30)))

    def test_rejects_invalid_dates_and_daily_time(self):
        with self.assertRaises(ValueError):
            ExamGoal("course-a", "not-a-date", 30, 0.8)
        with self.assertRaises(ValueError):
            ExamGoal("course-a", "2026-08-01", 0, 0.8)


if __name__ == "__main__":
    unittest.main()
