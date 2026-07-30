import unittest

from core.practice_plan_preview import build_practice_plan_preview


class PracticePlanPreviewTests(unittest.TestCase):
    def test_preview_summarizes_ready_questions_and_the_remaining_gap(self):
        preview = build_practice_plan_preview(
            {
                "q-cache": ("cache", "高速缓存", "medium"),
                "q-io": ("io", "输入输出", "medium"),
                "q-process": ("process", "进程", "hard"),
            },
            question_ids=("q-cache", "q-io", "q-process"),
            requested_count=5,
        )

        self.assertEqual(5, preview.requested_count)
        self.assertEqual(3, preview.ready_count)
        self.assertEqual(2, preview.missing_count)
        self.assertEqual(6, preview.ready_minutes)
        self.assertEqual(10, preview.target_minutes)
        self.assertEqual(
            (("高速缓存", 1), ("输入输出", 1), ("进程", 1)),
            preview.topic_counts,
        )
        self.assertEqual(
            (("medium", 2), ("hard", 1)),
            preview.difficulty_counts,
        )

    def test_preview_ignores_missing_or_duplicate_question_ids(self):
        preview = build_practice_plan_preview(
            {"q-cache": ("cache", "高速缓存", "easy")},
            question_ids=("q-cache", "missing", "q-cache"),
            requested_count=2,
        )

        self.assertEqual(1, preview.ready_count)
        self.assertEqual(1, preview.missing_count)
        self.assertEqual((("高速缓存", 1),), preview.topic_counts)


if __name__ == "__main__":
    unittest.main()
