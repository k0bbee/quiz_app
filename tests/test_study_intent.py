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
            action="practice_topic",
            topic_ids=[" cache ", "cache", ""],
            question_ids=["q-1", " q-1 ", "q-2"],
            question_count="6",
            source=" today_plan ",
        )

        self.assertIs(StudyAction.PRACTICE_TOPIC, intent.action)
        self.assertEqual("course-os", intent.course_id)
        self.assertEqual(("cache",), intent.topic_ids)
        self.assertEqual(("q-1", "q-2"), intent.question_ids)
        self.assertEqual(6, intent.question_count)
        self.assertEqual("today_plan", intent.source)
        with self.assertRaises(FrozenInstanceError):
            intent.question_count = 10


if __name__ == "__main__":
    unittest.main()
