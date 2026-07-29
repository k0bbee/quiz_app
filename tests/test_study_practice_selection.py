import unittest


class PracticeQuestionSelectionTests(unittest.TestCase):
    def test_selection_rotates_topics_and_respects_difficulty(self):
        from core.practice_selection import select_practice_question_ids

        scheduling_index = {
            "q-cache-1": ("cache", "Cache", "medium"),
            "q-cache-2": ("cache", "Cache", "medium"),
            "q-cache-3": ("cache", "Cache", "easy"),
            "q-io-1": ("io", "I/O", "medium"),
            "q-io-2": ("io", "I/O", "medium"),
            "q-process-1": ("process", "Process", "medium"),
        }

        selected = select_practice_question_ids(
            scheduling_index,
            topic_ids=("cache", "io", "process"),
            difficulty="medium",
            limit=5,
        )

        self.assertEqual(
            ["q-cache-1", "q-io-1", "q-process-1", "q-cache-2", "q-io-2"],
            selected,
        )

    def test_selection_uses_all_available_topics_when_scope_is_empty(self):
        from core.practice_selection import select_practice_question_ids

        scheduling_index = {
            "q-b-2": ("b", "B", "hard"),
            "q-a-2": ("a", "A", "easy"),
            "q-b-1": ("b", "B", "easy"),
            "q-a-1": ("a", "A", "hard"),
        }

        selected = select_practice_question_ids(
            scheduling_index,
            limit=3,
        )

        self.assertEqual(["q-a-1", "q-b-1", "q-a-2"], selected)


if __name__ == "__main__":
    unittest.main()
