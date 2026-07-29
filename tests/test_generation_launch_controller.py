import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ui.generation_launch_controller import (
    GenerationLaunchController,
    GenerationLaunchIssue,
    generation_launch_copy,
)


class FakeDialog:
    def __init__(self, content, settings, parent, **kwargs):
        self.content = content
        self.settings = settings
        self.parent = parent
        self.kwargs = kwargs
        self.profile = None

    def configure_from_course_profile(self, course_project):
        self.profile = course_project


class GenerationLaunchControllerTests(unittest.TestCase):
    def test_issue_copy_distinguishes_create_and_regenerate_actions(self):
        create = generation_launch_copy(
            GenerationLaunchIssue.EMPTY_EXAM_SCOPE,
            purpose="create",
        )
        regenerate = generation_launch_copy(
            GenerationLaunchIssue.EMPTY_EXAM_SCOPE,
            purpose="regenerate",
        )

        self.assertIn("再出题", create.detail_zh)
        self.assertIn("重新生成题目", regenerate.detail_zh)

    def test_local_generation_prepares_dialog_without_reading_secret(self):
        secret_provider = Mock(side_effect=AssertionError("secret must not be read"))
        course = SimpleNamespace(summary_markdown="# Course", topics=["io"])
        controller = GenerationLaunchController(
            settings_provider=lambda: {"ai_provider": "local_agent"},
            course_context_provider=lambda: ("# Course", ["io"], course),
            task_center="tasks",
            api_key_required=lambda _settings: False,
            settings_validator=lambda _settings, api_key: "" if api_key == "" else "bad",
            secret_provider=secret_provider,
            dialog_factory=FakeDialog,
        )

        result = controller.prepare("parent")

        self.assertTrue(result.ok)
        self.assertIs(course, result.course_project)
        self.assertEqual("# Course", result.dialog.content)
        self.assertEqual(["io"], result.dialog.kwargs["available_topics"])
        self.assertEqual("tasks", result.dialog.kwargs["task_center"])
        self.assertIs(course, result.dialog.profile)
        secret_provider.assert_not_called()

    def test_missing_content_stops_before_settings_and_dialog_work(self):
        validator = Mock(side_effect=AssertionError("settings must not be validated"))
        dialog_factory = Mock(side_effect=AssertionError("dialog must not be created"))
        controller = GenerationLaunchController(
            settings_provider=lambda: {},
            course_context_provider=lambda: ("", [], None),
            settings_validator=validator,
            dialog_factory=dialog_factory,
        )

        result = controller.prepare("parent")

        self.assertFalse(result.ok)
        self.assertEqual(GenerationLaunchIssue.MISSING_COURSE_CONTENT, result.issue)
        validator.assert_not_called()
        dialog_factory.assert_not_called()

    def test_course_override_respects_empty_selected_exam_scope(self):
        course = SimpleNamespace(
            summary_markdown="# Course",
            topics=["outside"],
            exam_scope_mode="selected",
            exam_topics=lambda: [],
        )
        controller = GenerationLaunchController(
            settings_provider=lambda: {},
            course_context_provider=lambda: ("unexpected", ["unexpected"], None),
            dialog_factory=FakeDialog,
        )

        result = controller.prepare("parent", course_override=course)

        self.assertFalse(result.ok)
        self.assertEqual(GenerationLaunchIssue.EMPTY_EXAM_SCOPE, result.issue)
        self.assertIs(course, result.course_project)

    def test_review_only_launch_does_not_require_secret_or_valid_ai_settings(self):
        course = SimpleNamespace(
            summary_markdown="# Course",
            topics=["io"],
            exam_scope_mode="all",
        )
        secret_provider = Mock(
            side_effect=AssertionError("review must not read the API key")
        )
        validator = Mock(
            side_effect=AssertionError("review must not validate AI settings")
        )
        controller = GenerationLaunchController(
            settings_provider=lambda: {"ai_provider": "anthropic"},
            course_context_provider=lambda: ("# Course", ["io"], course),
            api_key_required=lambda _settings: True,
            settings_validator=validator,
            secret_provider=secret_provider,
            dialog_factory=FakeDialog,
        )

        result = controller.prepare(
            "parent",
            allow_review_without_ai=True,
        )

        self.assertTrue(result.ok)
        secret_provider.assert_not_called()
        validator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
