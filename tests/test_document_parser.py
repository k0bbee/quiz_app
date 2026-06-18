import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.document_parser import DocumentParser


class DocumentParserQualityTests(unittest.TestCase):
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
            (root / "data").mkdir()
            (root / "data" / "course-20260617_summary.md").write_text(repeated, encoding="utf-8")

            docs = DocumentParser().parse_folder(str(root))

        self.assertEqual([Path(doc.path).name for doc in docs], ["2. Cache mapping.md"])
        self.assertTrue(docs[0].warnings == [] or all("duplicate" not in w.lower() for w in docs[0].warnings))

    def test_pdf_empty_text_page_records_ocr_unavailable_warning(self):
        class FakePage:
            def get_text(self, _kind):
                return ""

        class FakeDoc:
            def __enter__(self):
                return [FakePage()]

            def __exit__(self, *_args):
                return False

        fake_fitz = types.SimpleNamespace(open=lambda _path: FakeDoc())

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "scan.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake")
            with patch.dict("sys.modules", {"fitz": fake_fitz, "pytesseract": None}):
                doc = DocumentParser().parse_file(pdf_path)

        self.assertIn("Page 1 has no extractable text", "\n".join(doc.warnings))
        self.assertIn("OCR fallback unavailable", "\n".join(doc.warnings))


if __name__ == "__main__":
    unittest.main()
