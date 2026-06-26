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


if __name__ == "__main__":
    unittest.main()
