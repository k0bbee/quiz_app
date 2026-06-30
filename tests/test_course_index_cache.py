import unittest
from unittest.mock import patch

import core.course_index as course_index
from models.course_project import CourseProject, CourseTopic


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

    def test_retrieval_terms_prioritize_topic_terms_over_template_noise(self):
        noisy = "根据课件上下文 关键条件 中间状态 输出结果 整理概念关系 计算步骤 "
        terms = course_index.extract_terms(
            (
                "Cache Mapping splits each byte address into tag, set index, and byte offset. "
                "The cache line tag confirms whether the selected set contains the block. "
                + noisy * 30
            ),
            limit=8,
        )

        for term in ("cache", "tag", "set", "offset"):
            self.assertIn(term, terms)
        for noise in ("根据课件", "关键条件", "中间状态", "输出结果", "整理概念", "计算步骤"):
            self.assertNotIn(noise, terms)

    def test_retrieval_terms_are_not_limited_to_computer_science_vocabulary(self):
        terms = course_index.extract_terms(
            (
                "DNA replication uses polymerase enzymes. DNA strands are copied with ATP energy. "
                "Protein folding depends on enzyme shape, protein charge, and RNA regulation."
            ),
            limit=10,
        )

        for term in ("dna", "atp", "protein", "enzyme", "rna"):
            self.assertIn(term, terms)

    def test_retrieval_uses_project_topic_keywords_to_respect_selected_topic(self):
        summary = (
            "## Cache Mapping\n"
            "This high-level overview names cache mapping but omits address field details.\n\n"
            "## Address Breakdown\n"
            "The tag, set index, and byte offset determine lookup behavior.\n"
        )
        project = CourseProject(
            course_id="course-keywords",
            title="Systems",
            source_folder="",
            summary_markdown=summary,
            summary_path="",
            topics=[
                CourseTopic(
                    topic_id="cache_mapping",
                    title="Cache Mapping",
                    keywords=["tag", "set index", "byte offset"],
                    source_files=["summary.md"],
                )
            ],
            documents=[
                {
                    "path": "summary.md",
                    "title": "summary",
                    "extension": ".md",
                    "_course_index": course_index.build_course_index(summary),
                }
            ],
            created_at="2026-06-26T00:00:00+00:00",
            updated_at="2026-06-26T00:00:00+00:00",
        )

        context = course_index.retrieve_course_context(
            project,
            ["cache mapping"],
            max_chars=260,
        )

        self.assertIn("Address Breakdown", context)
        self.assertIn("byte offset", context)

    def test_course_index_preserves_parent_topic_for_repeated_subheadings(self):
        summary = (
            "## Input Output Improvements\n"
            "### Core Concepts\n"
            "Polling, interrupts, buffers, and DMA reduce CPU overhead for devices.\n\n"
            "## Hard Disks & RAID\n"
            "### Core Concepts\n"
            "Seek time, rotational latency, and RAID levels describe disk storage.\n"
        )

        index = course_index.build_course_index(summary)
        headings = [item["heading"] for item in index]

        self.assertIn("Input Output Improvements / Core Concepts", headings)
        self.assertIn("Hard Disks & RAID / Core Concepts", headings)

    def test_retrieval_for_io_improvements_excludes_disk_and_raid_neighbor_topics(self):
        summary = (
            "## Input Output Improvements\n"
            "### Core Concepts\n"
            "Polling checks device status repeatedly. Interrupt-driven I/O lets the CPU continue "
            "until a device raises an interrupt. Buffers reduce interrupt frequency. DMA transfers "
            "data directly between an I/O device and memory with little CPU involvement.\n\n"
            "## Hard Disks & RAID\n"
            "### Core Concepts\n"
            "Hard disks use platters, tracks, cylinders, seek time, rotational latency, and RAID "
            "levels such as RAID 0, RAID 1, and RAID 5.\n\n"
            "## Disk IO Characteristics and File Allocation\n"
            "### Core Concepts\n"
            "File allocation uses contiguous, linked, and indexed blocks. Random access depends "
            "on logical-to-physical disk block mapping.\n"
        )
        project = CourseProject(
            course_id="course-io-boundary",
            title="Systems",
            source_folder="",
            summary_markdown=summary,
            summary_path="",
            topics=[
                CourseTopic(topic_id="input_output_improvements", title="Input Output Improvements"),
                CourseTopic(topic_id="hard_disks_raid", title="Hard Disks & RAID"),
                CourseTopic(topic_id="disk_io_characteristics", title="Disk IO Characteristics and File Allocation"),
            ],
            documents=[
                {
                    "path": "summary.md",
                    "title": "summary",
                    "extension": ".md",
                    "_course_index": course_index.build_course_index(summary),
                }
            ],
            created_at="2026-06-29T00:00:00+00:00",
            updated_at="2026-06-29T00:00:00+00:00",
        )

        context = course_index.retrieve_course_context(
            project,
            ["Input Output Improvements"],
            max_chars=1400,
        )

        self.assertIn("Polling", context)
        self.assertIn("DMA", context)
        self.assertNotIn("RAID", context)
        self.assertNotIn("seek time", context.lower())
        self.assertNotIn("File allocation", context)

    def test_retrieval_matches_project_topic_keywords_by_topic_id(self):
        summary = (
            "## Cache Mapping\n"
            "This high-level overview names cache mapping but omits address field details.\n\n"
            "## Address Breakdown\n"
            "The tag, set index, and byte offset determine lookup behavior.\n"
        )
        project = CourseProject(
            course_id="course-topic-id-keywords",
            title="Systems",
            source_folder="",
            summary_markdown=summary,
            summary_path="",
            topics=[
                CourseTopic(
                    topic_id="cache_mapping",
                    title="Cache Mapping",
                    keywords=["tag", "set index", "byte offset"],
                    source_files=["summary.md"],
                )
            ],
            documents=[
                {
                    "path": "summary.md",
                    "title": "summary",
                    "extension": ".md",
                    "_course_index": course_index.build_course_index(summary),
                }
            ],
            created_at="2026-06-26T00:00:00+00:00",
            updated_at="2026-06-26T00:00:00+00:00",
        )

        context = course_index.retrieve_course_context(
            project,
            ["cache_mapping"],
            max_chars=180,
        )

        self.assertIn("Address Breakdown", context)
        self.assertIn("byte offset", context)

    def test_retrieval_balances_long_matching_chunks_with_later_key_details(self):
        summary = (
            "## Cache Mapping Overview\n"
            + "cache mapping overview " * 80
            + "\n\n## Byte Offset Detail\n"
            "The byte offset sentinel detail explains which byte inside the cache block is selected.\n"
        )
        project = CourseProject(
            course_id="course-balanced-context",
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
            created_at="2026-06-28T00:00:00+00:00",
            updated_at="2026-06-28T00:00:00+00:00",
        )

        context = course_index.retrieve_course_context(
            project,
            ["cache mapping"],
            max_chars=620,
        )

        self.assertIn("Cache Mapping Overview", context)
        self.assertIn("Byte Offset Detail", context)
        self.assertIn("sentinel detail", context)

    def test_build_source_index_creates_page_level_chunks_with_stable_refs(self):
        project = CourseProject(
            course_id="course-source",
            title="Systems",
            source_folder="",
            summary_markdown="## I/O\nDMA transfers reduce CPU involvement.",
            summary_path="",
            topics=[
                CourseTopic(
                    topic_id="io_improvements",
                    title="Input Output Improvements",
                    keywords=["DMA", "interrupt"],
                    source_files=["io.pdf"],
                )
            ],
            documents=[
                {
                    "path": r"C:\slides\io.pdf",
                    "title": "I/O lecture",
                    "extension": ".pdf",
                    "pages": [
                        "Polling checks device status repeatedly.",
                        "DMA transfers data directly between device and memory.",
                    ],
                }
            ],
            created_at="2026-06-30T00:00:00+00:00",
            updated_at="2026-06-30T00:00:00+00:00",
        )

        index = course_index.build_source_index(project)

        self.assertEqual(2, len(index))
        self.assertEqual("source-0000", index[0]["chunk_id"])
        self.assertEqual("io.pdf", index[0]["source_file"])
        self.assertEqual("pdf", index[0]["source_type"])
        self.assertEqual(1, index[0]["page_or_slide"])
        self.assertIn("content_hash", index[0])
        self.assertEqual(["io_improvements"], index[1]["topic_ids"])
        self.assertIn("DMA", index[1]["text"])

    def test_retrieval_context_includes_source_chunk_references(self):
        project = CourseProject(
            course_id="course-source-context",
            title="Systems",
            source_folder="",
            summary_markdown="## Input Output Improvements\nDMA transfers reduce CPU overhead.",
            summary_path="",
            topics=[
                CourseTopic(
                    topic_id="io_improvements",
                    title="Input Output Improvements",
                    keywords=["DMA"],
                    source_files=["io.pdf"],
                )
            ],
            documents=[
                {
                    "path": "io.pdf",
                    "title": "I/O lecture",
                    "extension": ".pdf",
                    "pages": [
                        "DMA transfers data directly between an I/O device and main memory.",
                    ],
                }
            ],
            created_at="2026-06-30T00:00:00+00:00",
            updated_at="2026-06-30T00:00:00+00:00",
        )

        context = course_index.retrieve_course_context(
            project,
            ["io_improvements"],
            max_chars=800,
        )

        self.assertIn("source-0000", context)
        self.assertIn("io.pdf", context)
        self.assertIn("page 1", context.lower())
        self.assertIn("DMA transfers", context)


if __name__ == "__main__":
    unittest.main()
