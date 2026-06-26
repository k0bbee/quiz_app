import unittest

from ai.course_context import _global_key_terms, _topic_terms


class CourseContextTests(unittest.TestCase):
    def test_global_key_terms_share_course_term_noise_filtering(self):
        noisy = "根据课件上下文 关键条件 中间状态 输出结果 整理概念关系 计算步骤 "
        terms = [term.lower() for term in _global_key_terms(
            (
                "DNA replication uses ATP energy. RNA regulation and protein folding "
                "depend on repeated protein-enzyme interactions. "
                + noisy * 20
            ),
            limit=12,
        )]

        for term in ("dna", "atp", "rna", "protein"):
            self.assertIn(term, terms)
        for noise in ("根据课件", "关键条件", "中间状态", "输出结果", "整理概念", "计算步骤"):
            self.assertNotIn(noise, terms)

    def test_topic_terms_match_topic_keywords_case_insensitively(self):
        terms = _topic_terms(
            ["cache mapping"],
            {"Cache Mapping": ["tag", "set index", "byte offset"]},
        )

        self.assertIn("tag", terms)
        self.assertIn("set index", terms)
        self.assertIn("byte offset", terms)

    def test_topic_terms_split_slug_topic_ids_into_matchable_words(self):
        terms = _topic_terms(["cache_mapping"], {})

        self.assertIn("cache", terms)
        self.assertIn("mapping", terms)

    def test_selected_topic_id_context_prefers_matching_heading_over_global_noise(self):
        from ai.course_context import extract_relevant_course_context

        content = (
            "## Cache Mapping\n"
            "Cache mapping explains how an address maps to a cache set.\n\n"
            "## Process Scheduling\n"
            "Process scheduling, thread states, CPU dispatch, ready queue, context switch, "
            "process priority, scheduling fairness, scheduling policy, and process lifecycle "
            "are operating-system concepts.\n"
        )

        context = extract_relevant_course_context(
            content,
            ["cache_mapping"],
            max_chars=900,
        )

        self.assertIn("Cache Mapping", context)
        self.assertNotIn("Process Scheduling", context)

    def test_selected_topic_context_does_not_expand_with_unrelated_global_terms(self):
        from ai.course_context import extract_relevant_course_context

        content = (
            "## Cache Mapping\n"
            "This overview names cache mapping at a high level.\n\n"
            "## Address Breakdown\n"
            "The tag, set index, and byte offset determine lookup behavior.\n\n"
            "## Process Scheduling\n"
            "Process scheduling, thread states, CPU dispatch, ready queue, context switch, "
            "process priority, scheduling fairness, and scheduling policy are OS concepts.\n"
        )

        context = extract_relevant_course_context(
            content,
            ["cache mapping"],
            topic_keywords={"Cache Mapping": ["tag", "set index", "byte offset"]},
            max_chars=800,
        )

        self.assertIn("Cache Mapping", context)
        self.assertIn("Address Breakdown", context)
        self.assertNotIn("Process Scheduling", context)


if __name__ == "__main__":
    unittest.main()
