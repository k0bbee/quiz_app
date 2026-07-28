import unittest
from datetime import datetime, timedelta, timezone

from core.study_queue import StudyQueueCategory, build_daily_study_queue
from models.progress import AnswerRecord, ProgressRecord


NOW = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)


def completed_record(
    question_id: str,
    *,
    days_ago: int,
    is_correct: bool,
    confidence: str = "sure",
) -> ProgressRecord:
    attempted_at = (NOW - timedelta(days=days_ago)).isoformat()
    record = ProgressRecord.create_new("daily-queue")
    record.status = "completed"
    record.started_at = attempted_at
    record.completed_at = attempted_at
    record.answers = [
        AnswerRecord(
            question_id=question_id,
            index_in_session=0,
            user_answer="A",
            is_correct=is_correct,
            confidence=confidence,
            attempted_at=attempted_at,
        )
    ]
    return record


class StudyQueueTests(unittest.TestCase):
    def test_queue_prioritizes_due_errors_unsure_stale_and_new_questions(self):
        records = [
            completed_record("q-due", days_ago=10, is_correct=True),
            completed_record("q-wrong", days_ago=0, is_correct=False),
            completed_record(
                "q-unsure",
                days_ago=0,
                is_correct=True,
                confidence="unsure",
            ),
        ]
        records.extend(
            completed_record("q-stale", days_ago=15 + offset, is_correct=True)
            for offset in range(5)
        )

        queue = build_daily_study_queue(
            {
                "q-due",
                "q-wrong",
                "q-unsure",
                "q-stale",
                "q-new",
            },
            records,
            now=NOW,
            daily_limit=10,
            session_size=10,
        )

        self.assertEqual(
            (
                "q-due",
                "q-wrong",
                "q-unsure",
                "q-stale",
                "q-new",
            ),
            queue.question_ids,
        )
        self.assertEqual(
            {
                StudyQueueCategory.DUE: 1,
                StudyQueueCategory.RECENT_ERROR: 1,
                StudyQueueCategory.UNSURE: 1,
                StudyQueueCategory.STALE: 1,
                StudyQueueCategory.NEW: 1,
            },
            dict(queue.category_counts),
        )
        self.assertEqual(queue.question_ids, queue.current_question_ids)
        self.assertEqual((), queue.remaining_question_ids)

    def test_queue_splits_one_daily_plan_into_current_and_remaining_sessions(self):
        queue = build_daily_study_queue(
            {f"q-{index}" for index in range(8)},
            [],
            now=NOW,
            daily_limit=7,
            session_size=3,
        )

        self.assertEqual(7, queue.total_count)
        self.assertEqual(3, len(queue.current_question_ids))
        self.assertEqual(4, len(queue.remaining_question_ids))
        self.assertEqual(
            queue.question_ids,
            queue.current_question_ids + queue.remaining_question_ids,
        )
        self.assertEqual(14, queue.estimated_minutes)

    def test_queue_counts_describe_the_bounded_plan_not_the_entire_backlog(self):
        queue = build_daily_study_queue(
            {f"q-{index:03d}" for index in range(100)},
            [],
            now=NOW,
            daily_limit=15,
        )

        self.assertEqual(
            {StudyQueueCategory.NEW: 15},
            {
                category: count
                for category, count in queue.category_counts.items()
                if count
            },
        )
        self.assertEqual(100, queue.backlog_count)

    def test_latest_answer_replaces_old_error_and_unsure_state(self):
        records = [
            completed_record("q-recovered", days_ago=5, is_correct=False),
            completed_record(
                "q-recovered",
                days_ago=3,
                is_correct=True,
                confidence="unsure",
            ),
            completed_record("q-recovered", days_ago=0, is_correct=True),
        ]

        queue = build_daily_study_queue(
            {"q-recovered"},
            records,
            now=NOW,
        )

        self.assertEqual((), queue.question_ids)
        state = queue.review_states["q-recovered"]
        self.assertEqual(2, state.correct_streak)
        self.assertEqual(0, state.wrong_streak)
        self.assertEqual("sure", state.last_confidence)
        self.assertEqual(2, state.interval_days)

    def test_queue_ignores_answers_outside_candidate_scope(self):
        records = [
            completed_record("q-visible", days_ago=0, is_correct=False),
            completed_record("q-other-course", days_ago=0, is_correct=False),
        ]

        queue = build_daily_study_queue(
            {"q-visible"},
            records,
            now=NOW,
        )

        self.assertEqual(("q-visible",), queue.question_ids)
        self.assertNotIn("q-other-course", queue.review_states)


if __name__ == "__main__":
    unittest.main()
