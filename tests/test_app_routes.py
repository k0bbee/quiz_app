import unittest


class AppRouteTests(unittest.TestCase):
    def test_route_factories_define_stable_workspace_tabs_and_screen_keys(self):
        from ui.navigation.routes import Route, ScreenKey, Workspace

        self.assertEqual(
            (Workspace.STUDY, "today", ScreenKey.HOME),
            (
                Route.study("today").workspace,
                Route.study("today").tab,
                Route.study("today").screen,
            ),
        )
        self.assertEqual(ScreenKey.TOPIC_SELECTION, Route.study("practice").screen)
        self.assertEqual(ScreenKey.PROGRESS, Route.study("analysis").screen)
        self.assertEqual(ScreenKey.COURSES, Route.course("course-1").screen)
        self.assertEqual(
            ScreenKey.GENERATION,
            Route.course("course-1", tab="generation").screen,
        )
        self.assertEqual(ScreenKey.QUESTION_BANK, Route.library("sets").screen)
        self.assertEqual(ScreenKey.PAST_EXAMS, Route.library("past_exams").screen)
        self.assertEqual(ScreenKey.QUIZ, Route.focus("quiz").screen)

    def test_route_metadata_owns_titles_focus_and_internal_navigation(self):
        from ui.navigation.routes import (
            Route,
            Workspace,
            route_spec,
            workspace_tabs,
        )

        study = route_spec(Route.study("practice"))
        self.assertEqual(Workspace.STUDY, study.workspace)
        self.assertEqual(("学习", "Study"), (study.title_zh, study.title_en))
        self.assertFalse(study.focus)
        self.assertEqual(
            ["today", "practice", "analysis"],
            [tab.route.tab for tab in workspace_tabs(Workspace.STUDY)],
        )

        library = workspace_tabs(Workspace.LIBRARY)
        self.assertEqual(
            ["questions", "sets", "past_exams"],
            [tab.route.tab for tab in library],
        )
        self.assertEqual(
            ["题目", "题目集", "历史真题"],
            [tab.label_zh for tab in library],
        )

        focus = route_spec(Route.focus("results"))
        self.assertTrue(focus.focus)
        self.assertEqual(("练习结果", "Results"), (focus.title_zh, focus.title_en))

        generation = route_spec(Route.course("course-1", tab="generation"))
        self.assertEqual(
            ("课程", "Courses"),
            (generation.title_zh, generation.title_en),
        )

    def test_invalid_route_tabs_are_rejected_at_the_boundary(self):
        from ui.navigation.routes import Route

        with self.assertRaises(ValueError):
            Route.study("unknown")
        with self.assertRaises(ValueError):
            Route.library("unknown")
        with self.assertRaises(ValueError):
            Route.focus("unknown")


if __name__ == "__main__":
    unittest.main()
