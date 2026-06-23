import unittest
from unittest.mock import patch

import core.course_index as course_index
from models.course_project import CourseProject


class CourseIndexCacheTests(unittest.TestCase):
    def setUp(self):
        if hasattr(course_index._retrieve_cached, "cache_clear"):
            course_index._retrieve_cached.cache_clear()
        if hasattr(course_index, "_PAYLOAD_CACHE"):
            course_index._PAYLOAD_CACHE.clear()

    def _project(self, updated_at: str = "2026-06-18T00:00:00+00:00") -> CourseProject:
        summary = (
            "## Cache Mapping\n"
            "A byte address is split into tag, set, and byte offset. "
            "The set narrows the search and the tag confirms the block.\n"
        ) * 20
        return CourseProject(
            course_id="course-cache",
            title="Systems",
            source_folder="",
            summary_markdown=summary,
            summary_path="",
            topics=[],
            documents=[
                {
                    "path": "summary.md",
                    "title": "summary",
                    "extension": ".md",
                    "_course_index": course_index.build_course_index(summary),
                }
            ],
            created_at="2026-06-18T00:00:00+00:00",
            updated_at=updated_at,
        )

    def test_repeated_retrieval_reuses_serialized_project_payload(self):
        project = self._project()

        with patch("core.course_index._project_payload", wraps=course_index._project_payload) as build_payload:
            first = course_index.retrieve_course_context(project, ["cache mapping"], max_chars=800)
            second = course_index.retrieve_course_context(project, ["cache mapping"], max_chars=800)

        self.assertIn("Cache Mapping", first)
        self.assertEqual(first, second)
        self.assertEqual(1, build_payload.call_count)

    def test_summary_section_labels_are_not_retrieval_terms(self):
        terms = course_index.extract_terms(
            "核心概念 推演流程 实际例子 可考方向 答题要点 cache mapping",
            limit=20,
        )

        self.assertIn("cache", terms)
        for label in ("推演流程", "实际例子", "答题要点"):
            self.assertNotIn(label, terms)


if __name__ == "__main__":
    unittest.main()
