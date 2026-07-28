import unittest
from datetime import datetime, timedelta, timezone
from itertools import groupby

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

    def test_queue_rotates_topics_while_alternatives_remain(self):
        question_ids = {
            *(f"q-memory-{index}" for index in range(6)),
            *(f"q-process-{index}" for index in range(6)),
        }
        topic_index = {
            question_id: (
                "memory" if "memory" in question_id else "process",
                "Memory" if "memory" in question_id else "Process",
            )
            for question_id in question_ids
        }

        queue = build_daily_study_queue(
            question_ids,
            [],
            now=NOW,
            daily_limit=8,
            topic_index=topic_index,
        )

        topics = [topic_index[question_id][0] for question_id in queue.question_ids]
        self.assertEqual({"memory", "process"}, set(topics))
        self.assertLessEqual(
            max(len(list(run)) for _topic, run in groupby(topics)),
            2,
        )

    def test_new_queue_prefers_topics_the_user_has_not_covered(self):
        records = [
            completed_record(
                "q-memory-covered",
                days_ago=0,
                is_correct=True,
            )
        ]
        topic_index = {
            "q-memory-covered": ("memory", "Memory"),
            "q-memory-new": ("memory", "Memory"),
            "q-process-new": ("process", "Process"),
        }

        queue = build_daily_study_queue(
            set(topic_index),
            records,
            now=NOW,
            daily_limit=2,
            topic_index=topic_index,
        )

        self.assertEqual("q-process-new", queue.question_ids[0])

    def test_recent_error_keeps_priority_over_new_topic_rotation(self):
        records = [
            completed_record(
                "q-memory-error",
                days_ago=0,
                is_correct=False,
            )
        ]
        topic_index = {
            "q-memory-error": ("memory", "Memory"),
            "q-process-new": ("process", "Process"),
        }

        queue = build_daily_study_queue(
            set(topic_index),
            records,
            now=NOW,
            topic_index=topic_index,
        )

        self.assertEqual("q-memory-error", queue.question_ids[0])

    def test_queue_uses_easy_medium_hard_gradient_when_available(self):
        question_ids = {"q-hard", "q-easy", "q-medium"}
        topic_index = {
            question_id: ("physics", "Physics")
            for question_id in question_ids
        }
        difficulty_index = {
            "q-hard": "hard",
            "q-easy": "easy",
            "q-medium": "medium",
        }

        queue = build_daily_study_queue(
            question_ids,
            [],
            now=NOW,
            daily_limit=3,
            topic_index=topic_index,
            difficulty_index=difficulty_index,
        )

        self.assertEqual(
            ("q-easy", "q-medium", "q-hard"),
            queue.question_ids,
        )

    def test_exam_scope_weights_bias_selection_without_topic_bursts(self):
        question_ids = {
            *(f"q-major-{index}" for index in range(6)),
            *(f"q-minor-{index}" for index in range(6)),
        }
        topic_index = {
            question_id: (
                "major" if "major" in question_id else "minor",
                "Major" if "major" in question_id else "Minor",
            )
            for question_id in question_ids
        }

        queue = build_daily_study_queue(
            question_ids,
            [],
            now=NOW,
            daily_limit=5,
            topic_index=topic_index,
            exam_scope_weights={"major": 80, "minor": 20},
        )

        selected_topics = [
            topic_index[question_id][0]
            for question_id in queue.question_ids
        ]
        self.assertEqual(4, selected_topics.count("major"))
        self.assertEqual(1, selected_topics.count("minor"))
        self.assertNotIn(["major", "major", "major"], [
            selected_topics[index:index + 3]
            for index in range(len(selected_topics) - 2)
        ])

    def test_balanced_queue_is_deterministic(self):
        question_ids = {
            "q-memory-hard",
            "q-memory-easy",
            "q-process-medium",
            "q-process-hard",
        }
        topic_index = {
            question_id: (
                "memory" if "memory" in question_id else "process",
                "Memory" if "memory" in question_id else "Process",
            )
            for question_id in question_ids
        }
        difficulty_index = {
            question_id: question_id.rsplit("-", 1)[-1]
            for question_id in question_ids
        }
        kwargs = {
            "now": NOW,
            "topic_index": topic_index,
            "difficulty_index": difficulty_index,
            "exam_scope_weights": {"memory": 60, "process": 40},
        }

        first = build_daily_study_queue(question_ids, [], **kwargs)
        second = build_daily_study_queue(question_ids, [], **kwargs)

        self.assertEqual(first.question_ids, second.question_ids)


if __name__ == "__main__":
    unittest.main()
