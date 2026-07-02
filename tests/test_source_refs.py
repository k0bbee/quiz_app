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


if __name__ == "__main__":
    unittest.main()
