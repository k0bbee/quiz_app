import unittest
from dataclasses import FrozenInstanceError


class StudyIntentTests(unittest.TestCase):
    def test_intent_is_typed_normalized_and_immutable(self):
        try:
            from core.study_intent import StudyAction, StudyIntent
        except ModuleNotFoundError as exc:
            self.fail(f"typed study intent is missing: {exc}")

        intent = StudyIntent(
            course_id=" course-os ",
            action="daily_queue",
            topic_ids=[" cache ", "cache", ""],
            question_ids=["q-1", " q-1 ", "q-2"],
            remaining_question_ids=["q-3", " q-3 ", "q-4"],
            question_count="6",
            source=" today_plan ",
            plan_id=" 2026-07-28:course-os ",
        )

        self.assertIs(StudyAction.DAILY_QUEUE, intent.action)
        self.assertEqual("course-os", intent.course_id)
        self.assertEqual(("cache",), intent.topic_ids)
        self.assertEqual(("q-1", "q-2"), intent.question_ids)
        self.assertEqual(("q-3", "q-4"), intent.remaining_question_ids)
        self.assertEqual(6, intent.question_count)
        self.assertEqual("today_plan", intent.source)
        self.assertEqual("2026-07-28:course-os", intent.plan_id)
        with self.assertRaises(FrozenInstanceError):
            intent.question_count = 10


if __name__ == "__main__":
    unittest.main()
