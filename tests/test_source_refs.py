import unittest

from ui.widgets.source_refs import format_source_refs


class SourceRefsFormattingTests(unittest.TestCase):
    def test_format_source_refs_includes_short_excerpt_when_available(self):
        text = format_source_refs(
            [
                {
                    "chunk_id": "source-0007",
                    "source_file": "io.pdf",
                    "page_or_slide": 8,
                    "heading": "DMA",
                    "excerpt": "DMA transfers data directly between a device and memory, reducing CPU copying.",
                    "content_hash": "abcdef123456",
                }
            ]
        )

        self.assertIn("io.pdf", text)
        self.assertIn("page 8", text)
        self.assertIn("DMA transfers data directly", text)
        self.assertNotIn("abcdef123456", text)

    def test_format_source_refs_truncates_long_excerpt(self):
        long_excerpt = "x" * 200

        text = format_source_refs(
            [
                {
                    "chunk_id": "source-0001",
                    "source_file": "lecture.pdf",
                    "excerpt": long_excerpt,
                }
            ]
        )

        self.assertLess(len(text), 190)
        self.assertIn("…", text)

    def test_format_source_refs_includes_readable_confidence_status(self):
        text = format_source_refs(
            [
                {
                    "chunk_id": "source-0002",
                    "source_file": "cache.pdf",
                }
            ],
            status="fallback_plan_evidence",
        )

        self.assertIn("Source Evidence: Plan Fallback", text)
        self.assertNotIn("fallback_plan_evidence", text)

    def test_format_source_refs_includes_html_confidence_status(self):
        text = format_source_refs(
            [
                {
                    "chunk_id": "source-0003",
                    "source_file": "io.pdf",
                }
            ],
            label="来源",
            html=True,
            status="valid_model_ref",
        )

        self.assertIn("<b>来源:</b> Exact", text)
        self.assertIn("<br>", text)

    def test_format_source_refs_localizes_chinese_status_page_and_excerpt(self):
        statuses = {
            "valid_model_ref": "精确来源",
            "partial_model_ref": "部分匹配",
            "fallback_plan_evidence": "计划证据补全",
            "fallback_global_evidence": "全局检索补全",
            "global_fallback": "全局检索补全",
            "recovered": "已恢复旧来源",
            "invalid_model_ref": "无效来源",
            "missing": "缺少来源",
        }
        for status, expected in statuses.items():
            with self.subTest(status=status):
                text = format_source_refs(
                    [{
                        "source_file": "课件.pdf",
                        "page_or_slide": 12,
                        "excerpt": "中断驱动输入输出",
                    }],
                    label="来源",
                    status=status,
                    language="zh",
                )
                self.assertIn(f"来源: {expected}", text)
                self.assertIn("页码/幻灯片 12", text)
                self.assertIn("摘录: 中断驱动输入输出", text)
                self.assertNotIn("Excerpt", text)

    def test_format_source_refs_localizes_chinese_html_status(self):
        text = format_source_refs(
            [{"source_file": "课件.pdf"}],
            label="来源",
            html=True,
            status="valid_model_ref",
            language="zh",
        )

        self.assertIn("<b>来源:</b> 精确来源", text)

    def test_format_source_refs_escapes_generated_values_in_html_mode(self):
        text = format_source_refs(
            [
                {
                    "chunk_id": "source-<7>",
                    "source_file": "<img src=x onerror=alert(1)>",
                    "heading": "DMA <b>unsafe</b>",
                    "excerpt": "<script>alert(1)</script>",
                }
            ],
            label="来源",
            html=True,
        )

        self.assertIn("&lt;img", text)
        self.assertIn("DMA &lt;b&gt;unsafe&lt;/b&gt;", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertNotIn("<img", text)
        self.assertNotIn("<script>", text)


if __name__ == "__main__":
    unittest.main()
