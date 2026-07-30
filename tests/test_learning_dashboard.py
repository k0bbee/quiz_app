import unittest
from datetime import date
from types import SimpleNamespace

from core.learning_dashboard import (
    LearningDashboardViewModel,
    build_learning_dashboard,
)
from core.today_learning_plan import LearningPlanAction, TodayLearningPlan


class LearningDashboardTests(unittest.TestCase):
    def test_focuses_the_two_topics_with_the_most_actionable_weakness(self):
        dashboard = build_learning_dashboard(
            {
                "cache-1": ("cache", "高速缓存"),
                "cache-2": ("cache", "高速缓存"),
                "io-1": ("io", "输入输出"),
                "io-2": ("io", "输入输出"),
                "process-1": ("process", "进程"),
            },
            records=[
                self._record(
                    self._answer("cache-1", False),
                    self._answer("cache-2", True),
                    self._answer("io-1", False, confidence="unsure"),
                    self._answer("io-2", False),
                    self._answer("process-1", True),
                )
            ],
        )

        self.assertEqual(("io", "cache"), dashboard.focus_topic_ids)
        io_focus, cache_focus = dashboard.focus_topics
        self.assertEqual("输入输出", io_focus.title)
        self.assertEqual(2, io_focus.incorrect_count)
        self.assertEqual(1, io_focus.unsure_count)
        self.assertEqual(0.0, io_focus.accuracy)
        self.assertEqual("高速缓存", cache_focus.title)
        self.assertEqual(1, cache_focus.incorrect_count)
        self.assertEqual(0.5, cache_focus.accuracy)

    def test_ignores_unattempted_and_skipped_topics(self):
        dashboard = build_learning_dashboard(
            {
                "cache-1": ("cache", "高速缓存"),
                "io-1": ("io", "输入输出"),
            },
            records=[self._record(self._answer("cache-1", False, skipped=True))],
        )

        self.assertEqual((), dashboard.focus_topics)

    def test_does_not_label_a_fully_correct_topic_as_a_weakness(self):
        dashboard = build_learning_dashboard(
            {"cache-1": ("cache", "高速缓存")},
            records=[self._record(self._answer("cache-1", True))],
        )

        self.assertEqual((), dashboard.focus_topics)

    def test_builds_one_read_only_view_model_for_home_and_analysis(self):
        records = [
            self._record(
                self._answer("cache-1", True),
                self._answer("io-1", False, confidence="unsure"),
                started_at="2026-07-28T09:00:00+08:00",
            ),
            self._record(
                self._answer("cache-1", True),
                started_at="2026-07-30T09:00:00+08:00",
            ),
        ]
        plan = TodayLearningPlan(
            action=LearningPlanAction.START_DAILY_QUEUE,
            target_question_count=9,
            estimated_minutes=18,
            plan_id="2026-07-30:course-a",
            plan_total_count=15,
            backlog_count=38,
            completed_count=6,
        )

        dashboard = build_learning_dashboard(
            {
                "cache-1": ("cache", "高速缓存"),
                "io-1": ("io", "输入输出"),
            },
            records=records,
            daily_plan=plan,
            reference_date=date(2026, 7, 30),
            max_focus_topics=3,
        )

        self.assertIsInstance(dashboard, LearningDashboardViewModel)
        self.assertIs(plan, dashboard.daily_plan)
        self.assertEqual(6, dashboard.plan_progress.completed_count)
        self.assertEqual(15, dashboard.plan_progress.total_count)
        self.assertEqual(9, dashboard.plan_progress.current_group_count)
        self.assertEqual(0, dashboard.plan_progress.remaining_after_current_group)
        self.assertEqual(18, dashboard.estimated_minutes)
        self.assertEqual(2, dashboard.weekly_summary.study_days)
        self.assertEqual(3, dashboard.weekly_summary.completed_questions)
        self.assertEqual(2, dashboard.weekly_summary.correct_questions)
        self.assertAlmostEqual(2 / 3, dashboard.weekly_summary.accuracy)
        self.assertEqual(15, dashboard.next_day_preview.question_count)
        self.assertFalse(dashboard.exam_status.configured)

    @staticmethod
    def _record(*answers, started_at=""):
        return SimpleNamespace(
            status="completed",
            answers=answers,
            started_at=started_at,
            completed_at=started_at,
        )

    @staticmethod
    def _answer(question_id, is_correct, *, confidence="sure", skipped=False):
        return SimpleNamespace(
            question_id=question_id,
            is_correct=is_correct,
            confidence=confidence,
            skipped=skipped,
        )
