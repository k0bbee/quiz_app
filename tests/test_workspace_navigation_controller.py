import unittest
from types import SimpleNamespace

from ui.navigation import Route, ScreenKey
from ui.workspace_navigation_controller import WorkspaceNavigationController


class WorkspaceNavigationControllerTests(unittest.TestCase):
    def test_default_generation_route_uses_the_current_course_identity(self):
        host = SimpleNamespace(
            SCREEN_HOME=0,
            SCREEN_TOPIC_SELECTION=1,
            SCREEN_QUIZ=2,
            SCREEN_RESULTS=3,
            SCREEN_PROGRESS=4,
            SCREEN_COURSES=5,
            SCREEN_QUESTION_BANK=6,
            SCREEN_PAST_EXAMS=7,
            SCREEN_GENERATION=8,
            SCREEN_INDEX_BY_KEY={ScreenKey.GENERATION: 8},
            _current_course_id=lambda: "course-current",
        )

        route = WorkspaceNavigationController(host).default_route(8)

        self.assertEqual(
            Route.course("course-current", tab="generation"),
            route,
        )


if __name__ == "__main__":
    unittest.main()
