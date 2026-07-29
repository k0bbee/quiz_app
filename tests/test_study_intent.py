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
            set_id=" set-os ",
            topic_ids=[" cache ", "cache", ""],
            question_ids=["q-1", " q-1 ", "q-2"],
            remaining_question_ids=["q-3", " q-3 ", "q-4"],
            question_count="6",
            submission_mode=" exam ",
            source=" today_plan ",
            plan_id=" 2026-07-28:course-os ",
        )

        self.assertIs(StudyAction.DAILY_QUEUE, intent.action)
        self.assertEqual("course-os", intent.course_id)
        self.assertEqual("set-os", intent.set_id)
        self.assertEqual(("cache",), intent.topic_ids)
        self.assertEqual(("q-1", "q-2"), intent.question_ids)
        self.assertEqual(("q-3", "q-4"), intent.remaining_question_ids)
        self.assertEqual(6, intent.question_count)
        self.assertEqual("exam", intent.submission_mode)
        self.assertEqual("today_plan", intent.source)
        self.assertEqual("2026-07-28:course-os", intent.plan_id)
        with self.assertRaises(FrozenInstanceError):
            intent.question_count = 10

    def test_intent_round_trip_preserves_set_and_normalizes_invalid_mode(self):
        from core.study_intent import StudyAction, StudyIntent

        intent = StudyIntent(
            course_id="course-os",
            action=StudyAction.CUSTOM_PRACTICE,
            set_id="set-os",
            question_ids=("q-1",),
            submission_mode="unsupported",
        )

        self.assertEqual("practice", intent.submission_mode)
        restored = StudyIntent.from_dict(intent.to_dict())
        self.assertEqual("set-os", restored.set_id)
        self.assertEqual("practice", restored.submission_mode)


if __name__ == "__main__":
    unittest.main()
