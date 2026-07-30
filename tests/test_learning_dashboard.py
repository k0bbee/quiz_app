import unittest
from types import SimpleNamespace

from core.learning_dashboard import build_learning_dashboard


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

    @staticmethod
    def _record(*answers):
        return SimpleNamespace(status="completed", answers=answers)

    @staticmethod
    def _answer(question_id, is_correct, *, confidence="sure", skipped=False):
        return SimpleNamespace(
            question_id=question_id,
            is_correct=is_correct,
            confidence=confidence,
            skipped=skipped,
        )
