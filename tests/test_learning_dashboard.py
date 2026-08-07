import unittest
from dataclasses import fields
from datetime import date
from inspect import signature
from types import SimpleNamespace

from core.learning_dashboard import (
    LearningDashboardViewModel,
    build_learning_dashboard,
)
from core.today_learning_plan import (
    TodayLearningPlan,
    build_topic_learning,
)


class LearningDashboardTests(unittest.TestCase):
    def test_topic_learning_is_one_shared_performance_index(self):
        learning = build_topic_learning(
            {
                "cache-1": ("cache", "高速缓存"),
                "cache-2": ("cache", "高速缓存"),
                "io-1": ("io", "输入输出"),
            },
            [
                self._record(
                    self._answer("cache-1", True),
                    self._answer("cache-2", False, confidence="unsure"),
                    self._answer("unknown", False),
                    started_at="2026-07-30T09:00:00+08:00",
                ),
                self._record(
                    self._answer("cache-1", False, skipped=True),
                    started_at="2026-07-31T09:00:00+08:00",
                ),
            ],
        )

        self.assertEqual(2, learning["cache"]["question_count"])
        self.assertEqual(2, learning["cache"]["attempts"])
        self.assertEqual(1, learning["cache"]["correct"])
        self.assertEqual(1, learning["cache"]["incorrect"])
        self.assertEqual(1, learning["cache"]["unsure"])
        self.assertEqual("2026-07-30", learning["cache"]["recent"])
        self.assertEqual(1, learning["io"]["question_count"])
        self.assertEqual(0, learning["io"]["attempts"])

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
                    self._answer(
                        "io-1",
                        False,
                        confidence="unsure",
                        error_reason="concept_gap",
                    ),
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
        self.assertEqual((("concept_gap", 1),), io_focus.error_reason_counts)
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

    def test_focus_topics_keep_reason_counts_for_incorrect_answers(self):
        dashboard = build_learning_dashboard(
            {"cache-1": ("cache", "高速缓存")},
            records=[
                self._record(
                    self._answer("cache-1", False, error_reason="misread"),
                    self._answer("cache-1", False, error_reason="concept_gap"),
                    self._answer("cache-1", False, error_reason="concept_gap"),
                )
            ],
        )

        self.assertEqual(
            (("concept_gap", 2), ("misread", 1)),
            dashboard.focus_topics[0].error_reason_counts,
        )

    def test_learning_views_do_not_retain_removed_persistent_plan_state(self):
        self.assertNotIn("daily_plan", signature(build_learning_dashboard).parameters)
        self.assertNotIn("daily_plan", {field.name for field in fields(LearningDashboardViewModel)})
        self.assertNotIn("plan_id", {field.name for field in fields(TodayLearningPlan)})
        self.assertNotIn("deferred_count", {field.name for field in fields(TodayLearningPlan)})

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
        dashboard = build_learning_dashboard(
            {
                "cache-1": ("cache", "高速缓存"),
                "io-1": ("io", "输入输出"),
            },
            records=records,
            reference_date=date(2026, 7, 30),
            max_focus_topics=3,
        )

        self.assertIsInstance(dashboard, LearningDashboardViewModel)
        self.assertEqual(2, dashboard.weekly_summary.study_days)
        self.assertEqual(3, dashboard.weekly_summary.completed_questions)
        self.assertEqual(2, dashboard.weekly_summary.correct_questions)
        self.assertAlmostEqual(2 / 3, dashboard.weekly_summary.accuracy)

    @staticmethod
    def _record(*answers, started_at=""):
        return SimpleNamespace(
            status="completed",
            answers=answers,
            started_at=started_at,
            completed_at=started_at,
        )

    @staticmethod
    def _answer(
        question_id,
        is_correct,
        *,
        confidence="sure",
        skipped=False,
        error_reason="",
    ):
        return SimpleNamespace(
            question_id=question_id,
            is_correct=is_correct,
            confidence=confidence,
            skipped=skipped,
            error_reason=error_reason,
        )
