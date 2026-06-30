import unittest
from types import SimpleNamespace

from core.language_manager import LanguageManager
from models.course_project import CourseTopic
from ui.main_window import MainWindow
from utils.constants import topic_label, topic_matches, topic_value


class TopicLabelTests(unittest.TestCase):
    def test_course_topic_uses_title_for_display_and_topic_id_for_storage_key(self):
        topic = CourseTopic(
            topic_id="cache_mapping",
            title="Cache Mapping",
            keywords=["tag", "set index"],
            source_files=["lecture.md"],
        )

        self.assertEqual("Cache Mapping", topic_label(topic))
        self.assertEqual("cache_mapping", topic_value(topic))

    def test_course_topic_matches_legacy_title_alias_after_rename(self):
        topic = CourseTopic(
            topic_id="cache_mapping",
            title="Cache Address Mapping",
            keywords=["tag", "set index"],
            source_files=["lecture.md"],
            aliases=["Cache Mapping"],
        )

        self.assertTrue(topic_matches("Cache Mapping", topic))
        self.assertTrue(topic_matches("cache_mapping", topic))
        self.assertFalse(topic_matches("Pipeline", topic))

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
