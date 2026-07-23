import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.document_parser import DocumentParser


class DocumentParserQualityTests(unittest.TestCase):
    def test_explicit_data_folder_root_is_not_skipped_as_its_own_ancestor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            root.mkdir()
            (root / "source.md").write_text("Original course material", encoding="utf-8")
            generated = root / "generated"
            generated.mkdir()
            (generated / "ignored.md").write_text("Generated output", encoding="utf-8")

            documents = DocumentParser().parse_folder(str(root))

            self.assertEqual(["source"], [document.title for document in documents])

    def test_parse_text_recovers_gb18030_content_and_reports_encoding_fallback(self):
        content = "微观经济学：需求、供给、价格弹性与消费者选择。"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "economics-notes.txt"
            path.write_bytes(content.encode("gb18030"))

            document = DocumentParser().parse_file(path)

        self.assertEqual(content, document.text)
        self.assertIn("GB18030", "\n".join(document.warnings))

    def test_parse_file_caches_unchanged_files_without_returning_shared_document(self):
        class CountingParser(DocumentParser):
            calls = 0

            def _parse_text(self, path):
                CountingParser.calls += 1
                return super()._parse_text(path)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.md"
            path.write_text("Cache mapping content with enough text to parse.", encoding="utf-8")

            first = CountingParser().parse_file(path)
            first.warnings.append("caller mutation")
            second = CountingParser().parse_file(path)

        self.assertEqual(1, CountingParser.calls)
        self.assertEqual("Cache mapping content with enough text to parse.", second.text)
        self.assertNotIn("caller mutation", second.warnings)

    def test_parse_folder_skips_generated_noise_and_duplicate_text(self):
        repeated = (
            "Cache mapping explains how a byte address is split into tag, set, "
            "and byte offset. This lecture text is intentionally repeated so "
            "duplicate imported copies can be detected reliably.\n"
        ) * 8

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2. Cache mapping.md").write_text(repeated, encoding="utf-8")
            (root / "diff.md").write_text(repeated, encoding="utf-8")
            (root / "2. Cache mapping copy.md").write_text(repeated, encoding="utf-8")
            (root / "standard.md").write_text("HC Computer System 出题标准 " * 20, encoding="utf-8")
            (root / "marking-rubric.md").write_text(
                "marking rubric grading feedback answer key " * 20,
                encoding="utf-8",
            )
            (root / "复习辅助.md").write_text("课程内容整理标准 辅助提示词模板 " * 20, encoding="utf-8")
            (root / "课程内容.md").write_text("核心概念 推演流程 答题要点 " * 20, encoding="utf-8")
            (root / "例题与讲解.md").write_text("用途：把高频考点转化为可推理的题。变式提示 " * 20, encoding="utf-8")
            (root / "考前40分钟中文摘要.md").write_text(
                "依据：模拟卷与课程内容的高频核心概念。最后 40 分钟优先级 " * 20,
                encoding="utf-8",
            )
            (root / "data").mkdir()
            (root / "data" / "course-20260617_summary.md").write_text(repeated, encoding="utf-8")

            docs = DocumentParser().parse_folder(str(root))

        self.assertEqual([Path(doc.path).name for doc in docs], ["2. Cache mapping.md"])
        self.assertTrue(docs[0].warnings == [] or all("duplicate" not in w.lower() for w in docs[0].warnings))

    def test_pdf_empty_text_page_records_ocr_unavailable_warning(self):
        class FakeTextPage:
            def get_text_range(self):
                return ""

        class FakePage:
            def get_textpage(self):
                return FakeTextPage()

        class FakeDoc:
            def __init__(self, _path):
                self.pages = [FakePage()]

            def __len__(self):
                return len(self.pages)

            def __getitem__(self, index):
                return self.pages[index]

        fake_pdfium = types.SimpleNamespace(PdfDocument=FakeDoc)

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "scan.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake")
            with patch.dict(
                "sys.modules",
                {"pypdfium2": fake_pdfium, "pytesseract": None},
            ):
                doc = DocumentParser().parse_file(pdf_path)

        self.assertIn("Page 1 has no extractable text", "\n".join(doc.warnings))
        self.assertIn("OCR fallback unavailable", "\n".join(doc.warnings))

    def test_pdf_page_labels_preserve_original_page_numbers_when_empty_pages_are_skipped(self):
        class FakeTextPage:
            def __init__(self, text):
                self.text = text

            def get_text_range(self):
                return self.text

        class EmptyPage:
            def get_textpage(self):
                return FakeTextPage("")

        class TextPage:
            def get_textpage(self):
                return FakeTextPage("Second page content")

        class FakeDoc:
            def __init__(self, _path):
                self.pages = [EmptyPage(), TextPage()]

            def __len__(self):
                return len(self.pages)

            def __getitem__(self, index):
                return self.pages[index]

        fake_pdfium = types.SimpleNamespace(PdfDocument=FakeDoc)

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "partial.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake")
            with patch.dict(
                "sys.modules",
                {"pypdfium2": fake_pdfium, "pytesseract": None},
            ):
                doc = DocumentParser().parse_file(pdf_path)

        self.assertIn("[Page 2]\nSecond page content", doc.text)
        self.assertNotIn("[Page 1]\nSecond page content", doc.text)


if __name__ == "__main__":
    unittest.main()
