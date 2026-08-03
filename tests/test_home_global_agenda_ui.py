import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.screens.home_screen import HomeScreen


_APP = QApplication.instance() or QApplication([])


class _Progress:
    def load_all(self):
        return []

    def get_aggregated_stats(self, _ids, *, records=None):
        return {"total_sessions": 0}


class _Questions:
    def __init__(self):
        self._rows = {
            "course-a": {
                "ids": ["a-1"],
                "scheduling": {"a-1": ("topic-a", "主题 A", "medium")},
            },
            "course-b": {
                "ids": ["b-1", "b-2"],
                "scheduling": {
                    "b-1": ("topic-b", "主题 B", "medium"),
                    "b-2": ("topic-b", "主题 B", "easy"),
                },
            },
        }

    def question_ids(self, *, course_id):
        return list(self._rows[course_id]["ids"])

    def scheduling_index(self, *, course_id):
        return dict(self._rows[course_id]["scheduling"])

    def topic_index(self, *, course_id):
        return {
            question_id: (row[0], row[1])
            for question_id, row in self._rows[course_id]["scheduling"].items()
        }

    def count(self, *, course_id):
        return len(self._rows[course_id]["ids"])


class _Courses:
    def load_all(self):
        return [
            SimpleNamespace(
                course_id="course-a",
                title="课程 A",
                exam_scope_mode="all",
                topics=[],
                generation_profile={},
            ),
            SimpleNamespace(
                course_id="course-b",
                title="课程 B",
                exam_scope_mode="all",
                topics=[],
                generation_profile={},
            ),
        ]


class HomeGlobalAgendaUiTests(unittest.TestCase):
    def test_home_uses_current_course_plan_without_cross_course_agenda(self):
        home = HomeScreen(
            _Progress(),
            _Questions(),
            course_manager=_Courses(),
        )

        home.set_current_course("course-a", "课程 A")

        self.assertFalse(hasattr(home, "agenda_frame"))
        self.assertFalse(hasattr(home, "open_course_requested"))


if __name__ == "__main__":
    unittest.main()
