import unittest
from types import SimpleNamespace

import pytest

from core.language_manager import LanguageManager
from models.course_project import CourseTopic
from ui.main_window import MainWindow


pytestmark = pytest.mark.qt


class TopicLabelUiTests(unittest.TestCase):
    def test_generation_context_preserves_course_topic_objects_for_labels(self):
        topic = CourseTopic(
            topic_id="cache_mapping",
            title="Cache Mapping",
            keywords=["tag", "set index"],
            source_files=["lecture.md"],
        )
        course = SimpleNamespace(
            summary_markdown="# Cache Mapping",
            topics=[topic],
        )
        shell = SimpleNamespace(
            lang_manager=LanguageManager.instance(),
            course_manager=SimpleNamespace(current=lambda: course),
        )

        content, topics, project = MainWindow._load_generation_context(shell)

        self.assertEqual("# Cache Mapping", content)
        self.assertEqual([topic], topics)
        self.assertIs(course, project)


if __name__ == "__main__":
    unittest.main()
