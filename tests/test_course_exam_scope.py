"""Course exam-scope persistence and behavior tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.course_initializer import CourseInitializer
from core.document_parser import ExtractedDocument
from models.course_project import CourseProject, CourseTopic


def _project(**overrides) -> CourseProject:
    values = {
        "course_id": "course-systems",
        "title": "Systems",
        "source_folder": "",
        "summary_markdown": "# Systems",
        "summary_path": "",
        "topics": [
            CourseTopic(topic_id="io", title="I/O"),
            CourseTopic(topic_id="memory", title="Memory"),
            CourseTopic(topic_id="concurrency", title="Concurrency"),
        ],
        "documents": [],
        "created_at": "2026-07-14T00:00:00+00:00",
        "updated_at": "2026-07-14T00:00:00+00:00",
    }
    values.update(overrides)
    return CourseProject(**values)


class CourseExamScopeModelTests(unittest.TestCase):
    def test_legacy_payload_defaults_to_all_topics(self):
        payload = _project().to_dict()
        payload.pop("exam_scope_mode", None)
        payload.pop("exam_scope_topic_ids", None)

        restored = CourseProject.from_dict(payload)

        self.assertEqual("all", restored.exam_scope_mode)
        self.assertEqual([], restored.exam_scope_topic_ids)
        self.assertEqual(["io", "memory", "concurrency"], [topic.topic_id for topic in restored.exam_topics()])

    def test_selected_scope_uses_course_order_and_discards_unknown_or_duplicate_ids(self):
        project = _project()

        project.set_exam_scope("selected", ["concurrency", "missing", "io", "concurrency"])

        self.assertEqual("selected", project.exam_scope_mode)
        self.assertEqual(["io", "concurrency"], project.exam_scope_topic_ids)
        self.assertEqual(["io", "concurrency"], [topic.topic_id for topic in project.exam_topics()])

    def test_invalid_persisted_mode_falls_back_to_all(self):
        payload = _project().to_dict()
        payload["exam_scope_mode"] = "mystery"
        payload["exam_scope_topic_ids"] = ["io"]

        restored = CourseProject.from_dict(payload)

        self.assertEqual("all", restored.exam_scope_mode)
        self.assertEqual([], restored.exam_scope_topic_ids)
        self.assertEqual(3, len(restored.exam_topics()))

    def test_nonempty_course_rejects_empty_selected_scope(self):
        project = _project()

        with self.assertRaisesRegex(ValueError, "at least one topic"):
            project.set_exam_scope("selected", [])

    def test_empty_course_allows_empty_selected_scope(self):
        project = _project(topics=[])

        project.set_exam_scope("selected", [])

        self.assertEqual("selected", project.exam_scope_mode)
        self.assertEqual([], project.exam_topics())

    def test_scope_round_trip_preserves_stable_topic_ids(self):
        project = _project()
        project.set_exam_scope("selected", ["memory", "io"])

        restored = CourseProject.from_dict(project.to_dict())

        self.assertEqual("selected", restored.exam_scope_mode)
        self.assertEqual(["io", "memory"], restored.exam_scope_topic_ids)
        self.assertEqual(["io", "memory"], [topic.topic_id for topic in restored.exam_topics()])


class CourseExamScopeRegenerationTests(unittest.TestCase):
    def test_regeneration_preserves_selected_stable_ids_and_drops_removed_topics(self):
        project = _project(source_folder="source")
        project.set_exam_scope("selected", ["io", "memory"])
        document = ExtractedDocument(
            path="source/systems.md",
            title="Systems",
            extension=".md",
            text="I/O interrupt DMA processor scheduling " * 20,
            pages=["I/O interrupt DMA processor scheduling " * 20],
        )

        class Parser:
            @staticmethod
            def parse_folder(_folder, task=None):
                return [document]

        class Manager:
            @staticmethod
            def save(_project, make_current=True):
                return True

        initializer = CourseInitializer(manager=Manager())
        initializer.parser = Parser()
        regenerated_topics = [
            CourseTopic(topic_id="io", title="Input and Output"),
            CourseTopic(topic_id="cpu", title="Processor"),
        ]

        with patch(
            "core.course_initializer.reconcile_topic_identities",
            return_value=regenerated_topics,
        ), patch.object(
            initializer,
            "_generate_profile",
            return_value=({}, "local", ""),
        ):
            updated = initializer.regenerate_summary(project, make_current=False)

        self.assertEqual("selected", updated.exam_scope_mode)
        self.assertEqual(["io"], updated.exam_scope_topic_ids)
        self.assertEqual(["io"], [topic.topic_id for topic in updated.exam_topics()])


if __name__ == "__main__":
    unittest.main()
