import unittest
from types import SimpleNamespace

from core.today_learning_plan import (
    DraftLearningState,
    LearningPlanAction,
    build_today_learning_plan,
)


class TodayLearningPlanTests(unittest.TestCase):
    def test_draft_has_priority_over_review_and_regular_practice(self):
        plan = build_today_learning_plan(
            total_questions=40,
            incorrect_question_ids=["q-wrong"],
            topic_index={},
            progress_records=[],
            draft=DraftLearningState("模拟卷一", remaining_count=8, mode="exam"),
        )

        self.assertEqual(LearningPlanAction.RESUME_DRAFT, plan.action)
        self.assertEqual("模拟卷一", plan.draft_title)
        self.assertEqual(8, plan.target_question_count)
        self.assertEqual(16, plan.estimated_minutes)

    def test_incorrect_questions_are_next_priority_and_are_bounded(self):
        plan = build_today_learning_plan(
            total_questions=40,
            incorrect_question_ids=[f"q-{index}" for index in range(16)],
            topic_index={},
            progress_records=[],
        )

        self.assertEqual(LearningPlanAction.REVIEW_INCORRECT, plan.action)
        self.assertEqual(10, plan.target_question_count)
        self.assertEqual(16, plan.review_question_count)
        self.assertEqual(20, plan.estimated_minutes)

    def test_regular_plan_names_the_weakest_attempted_topic(self):
        records = [SimpleNamespace(
            status="completed",
            answers=[
                self._answer("q-cache-1", True),
                self._answer("q-cache-2", False),
                self._answer("q-process-1", True),
                self._answer("q-process-2", True),
            ],
        )]
        topic_index = {
            "q-cache-1": ("cache", "Cache Mapping"),
            "q-cache-2": ("cache", "Cache Mapping"),
            "q-process-1": ("process", "Process Scheduling"),
            "q-process-2": ("process", "Process Scheduling"),
        }

        plan = build_today_learning_plan(
            total_questions=4,
            incorrect_question_ids=[],
            topic_index=topic_index,
            progress_records=records,
        )

        self.assertEqual(LearningPlanAction.START_PRACTICE, plan.action)
        self.assertEqual("cache", plan.weak_topic_id)
        self.assertEqual("Cache Mapping", plan.weak_topic_title)
        self.assertEqual(4, plan.target_question_count)

    def test_empty_question_bank_recommends_generation(self):
        plan = build_today_learning_plan(
            total_questions=0,
            incorrect_question_ids=[],
            topic_index={},
            progress_records=[],
        )

        self.assertEqual(LearningPlanAction.GENERATE_QUESTIONS, plan.action)
        self.assertEqual(0, plan.target_question_count)
        self.assertEqual(0, plan.estimated_minutes)

    def test_missing_course_recommends_import_before_generation(self):
        plan = build_today_learning_plan(
            total_questions=0,
            incorrect_question_ids=[],
            topic_index={},
            progress_records=[],
            has_course=False,
        )

        self.assertEqual(LearningPlanAction.IMPORT_COURSE, plan.action)

    @staticmethod
    def _answer(question_id, is_correct):
        return SimpleNamespace(
            question_id=question_id,
            is_correct=is_correct,
            skipped=False,
        )


if __name__ == "__main__":
    unittest.main()
