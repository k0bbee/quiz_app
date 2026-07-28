import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from core.study_queue import build_daily_study_queue
from models.progress import AnswerRecord


NOW = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)


def load_plan_api():
    try:
        from core.daily_study_plan_store import DailyStudyPlanStore
        from models.daily_study_plan import DailyStudyPlan
    except ImportError as exc:
        raise AssertionError("persistent daily study plan API is missing") from exc
    return DailyStudyPlan, DailyStudyPlanStore


class DailyStudyPlanTests(unittest.TestCase):
    def test_existing_plan_survives_restart_and_new_queue_candidates(self):
        DailyStudyPlan, DailyStudyPlanStore = load_plan_api()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "daily-plans.json"
            initial_queue = build_daily_study_queue(
                {"q-1", "q-2"},
                [],
                now=NOW,
            )
            plan = DailyStudyPlanStore(path).get_or_create(
                plan_id="2026-07-28:course-a",
                plan_date="2026-07-28",
                course_id="course-a",
                queue=initial_queue,
                valid_question_ids={"q-1", "q-2"},
            )

            changed_queue = build_daily_study_queue(
                {"q-1", "q-2", "q-new"},
                [],
                now=NOW,
            )
            restored = DailyStudyPlanStore(path).get_or_create(
                plan_id=plan.plan_id,
                plan_date="2026-07-28",
                course_id="course-a",
                queue=changed_queue,
                valid_question_ids={"q-1", "q-2", "q-new"},
            )

            self.assertIsInstance(restored, DailyStudyPlan)
            self.assertEqual(("q-1", "q-2"), restored.planned_ids)
            self.assertEqual(("q-1", "q-2"), restored.pending_ids)
            self.assertNotIn("q-new", restored.planned_ids)

    def test_first_failure_gets_one_remediation_and_second_failure_is_deferred(self):
        _DailyStudyPlan, DailyStudyPlanStore = load_plan_api()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DailyStudyPlanStore(Path(tmpdir) / "daily-plans.json")
            queue = build_daily_study_queue({"q-1"}, [], now=NOW)
            plan = store.get_or_create(
                plan_id="2026-07-28:course-a",
                plan_date="2026-07-28",
                course_id="course-a",
                queue=queue,
                valid_question_ids={"q-1"},
            )

            plan = store.record_completion(
                plan.plan_id,
                current_question_ids=("q-1",),
                answers=[self._answer("q-1", is_correct=False)],
            )
            self.assertEqual(("q-1",), plan.completed_ids)
            self.assertEqual(("q-1",), plan.remediation_ids)
            self.assertEqual(("q-1",), plan.pending_ids)
            self.assertFalse(plan.is_complete)

            plan = store.record_completion(
                plan.plan_id,
                current_question_ids=("q-1",),
                answers=[self._answer("q-1", is_correct=False)],
            )
            self.assertEqual((), plan.remediation_ids)
            self.assertEqual((), plan.pending_ids)
            self.assertEqual(("q-1",), plan.deferred_ids)
            self.assertTrue(plan.is_complete)

    def test_remediation_tail_is_bounded_to_five_questions(self):
        _DailyStudyPlan, DailyStudyPlanStore = load_plan_api()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DailyStudyPlanStore(Path(tmpdir) / "daily-plans.json")
            question_ids = tuple(f"q-{index}" for index in range(7))
            queue = build_daily_study_queue(question_ids, [], now=NOW)
            plan = store.get_or_create(
                plan_id="2026-07-28:course-a",
                plan_date="2026-07-28",
                course_id="course-a",
                queue=queue,
                valid_question_ids=set(question_ids),
            )

            plan = store.record_completion(
                plan.plan_id,
                current_question_ids=question_ids,
                answers=[
                    self._answer(question_id, is_correct=False)
                    for question_id in question_ids
                ],
            )

            self.assertEqual(question_ids[:5], plan.remediation_ids)
            self.assertEqual(question_ids[:5], plan.pending_ids)
            self.assertEqual(question_ids[5:], plan.deferred_ids)

    def test_unchanged_reload_does_not_rewrite_the_plan_file(self):
        _DailyStudyPlan, DailyStudyPlanStore = load_plan_api()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "daily-plans.json"
            store = DailyStudyPlanStore(path)
            queue = build_daily_study_queue({"q-1"}, [], now=NOW)
            store.get_or_create(
                plan_id="2026-07-28:course-a",
                plan_date="2026-07-28",
                course_id="course-a",
                queue=queue,
                valid_question_ids={"q-1"},
            )
            before = path.read_bytes()

            store.get_or_create(
                plan_id="2026-07-28:course-a",
                plan_date="2026-07-28",
                course_id="course-a",
                queue=queue,
                valid_question_ids={"q-1"},
            )

            self.assertEqual(before, path.read_bytes())

    def test_duplicate_completion_is_idempotent(self):
        _DailyStudyPlan, DailyStudyPlanStore = load_plan_api()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "daily-plans.json"
            store = DailyStudyPlanStore(path)
            queue = build_daily_study_queue({"q-1"}, [], now=NOW)
            plan = store.get_or_create(
                plan_id="2026-07-28:course-a",
                plan_date="2026-07-28",
                course_id="course-a",
                queue=queue,
                valid_question_ids={"q-1"},
            )
            answer = self._answer("q-1", is_correct=True)
            completed = store.record_completion(
                plan.plan_id,
                current_question_ids=("q-1",),
                answers=[answer],
            )
            before = path.read_bytes()

            duplicate = store.record_completion(
                plan.plan_id,
                current_question_ids=("q-1",),
                answers=[answer],
            )

            self.assertEqual(completed, duplicate)
            self.assertEqual(before, path.read_bytes())

    @staticmethod
    def _answer(
        question_id: str,
        *,
        is_correct: bool,
        confidence: str = "sure",
    ) -> AnswerRecord:
        return AnswerRecord(
            question_id=question_id,
            index_in_session=0,
            user_answer="A",
            is_correct=is_correct,
            confidence=confidence,
        )


if __name__ == "__main__":
    unittest.main()
