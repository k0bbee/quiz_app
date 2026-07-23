import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.document_parser import DocumentParser


class DocumentParserQualityTests(unittest.TestCase):
    def test_source_paths_skip_symbolic_linked_course_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            safe = root / "safe.md"
            linked = root / "linked.md"
            safe.write_text("safe course content", encoding="utf-8")
            linked.write_text("simulated linked content", encoding="utf-8")
            original_is_symlink = Path.is_symlink

            def is_symlink(path):
                if path == linked:
                    return True
                return original_is_symlink(path)

            with patch.object(Path, "is_symlink", is_symlink):
                paths = DocumentParser().source_paths(str(root))

        self.assertEqual([safe], paths)

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


class DocumentParserBudgetTests(unittest.TestCase):
    def test_oversized_docx_xml_is_rejected_before_member_read(self):
        from core.input_limits import MAX_OFFICE_XML_ENTRY_BYTES

        info = types.SimpleNamespace(
            filename="word/document.xml",
            file_size=MAX_OFFICE_XML_ENTRY_BYTES + 1,
        )

        class FakeArchive:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getinfo(self, _name):
                return info

            def open(self, *_args, **_kwargs):
                raise AssertionError("oversized XML must not be opened")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "oversized.docx"
            path.write_bytes(b"PK")
            with patch("core.document_parser.zipfile.ZipFile", return_value=FakeArchive()):
                document = DocumentParser().parse_file(path)

        self.assertEqual("", document.text)
        self.assertIn("exceeds limit", "\n".join(document.warnings))

    def test_docx_xml_is_read_through_a_bounded_stream(self):
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>bounded text</w:t></w:r></w:p></w:body>"
            "</w:document>"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bounded.docx"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("word/document.xml", xml)

            with patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("unbounded read")):
                document = DocumentParser().parse_file(path)

        self.assertEqual("bounded text", document.text)

    def test_pptx_pages_stop_at_extracted_text_budget(self):
        slide_xml = (
            '<p:sld xmlns:p="urn:p" xmlns:a="urn:a">'
            "<a:t>abcdefgh</a:t></p:sld>"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bounded.pptx"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("ppt/slides/slide1.xml", slide_xml)
                archive.writestr("ppt/slides/slide2.xml", slide_xml)

            with patch("core.input_limits.MAX_EXTRACTED_TEXT_CHARS", 10):
                document = DocumentParser().parse_file(path)

        self.assertLessEqual(sum(map(len, document.pages)), 10)
        self.assertIn("text", "\n".join(document.warnings).lower())

    def test_pdf_pages_stop_at_extracted_text_budget(self):
        class FakeTextPage:
            def get_text_range(self):
                return "abcdefgh"

            def close(self):
                pass

        class FakePage:
            def get_textpage(self):
                return FakeTextPage()

            def close(self):
                pass

        class FakePdf:
            def __len__(self):
                return 2

            def __getitem__(self, _index):
                return FakePage()

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bounded.pdf"
            path.write_bytes(b"%PDF")
            with patch("pypdfium2.PdfDocument", return_value=FakePdf()), \
                 patch("core.input_limits.MAX_EXTRACTED_TEXT_CHARS", 10):
                document = DocumentParser().parse_file(path)

        self.assertLessEqual(sum(map(len, document.pages)), 10)
        self.assertIn("text", "\n".join(document.warnings).lower())

    def test_oversized_file_is_rejected_with_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "huge.pdf"
            path.write_bytes(b"%PDF-huge")
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value = types.SimpleNamespace(
                    st_size=300 * 1024 * 1024,  # > 256 MiB
                    st_mtime_ns=0,
                )
                doc = DocumentParser().parse_file(path)
            self.assertIn("File exceeds size limit", "\n".join(doc.warnings))

    def test_pdf_page_count_beyond_limit_produces_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "many-pages.pdf"
            path.write_bytes(b"%PDF-many")

            class FakePdf:
                def __len__(self):
                    return 2500  # exceeds MAX_PDF_PAGES
                def __getitem__(self, i):
                    return FakePage()
                def close(self):
                    pass

            class FakePage:
                def get_textpage(self):
                    return FakeTextPage()
                def close(self):
                    pass

            class FakeTextPage:
                def get_text_range(self):
                    return "text"
                def close(self):
                    pass

            with patch("pypdfium2.PdfDocument", return_value=FakePdf()):
                doc = DocumentParser().parse_file(path)
            self.assertIn("exceeding limit", "\n".join(doc.warnings))

    def test_ocr_called_with_timeout(self):
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            self.skipTest("pytesseract not available")
        page = types.SimpleNamespace()
        page.render = lambda scale: types.SimpleNamespace(
            width=100, height=100,
            to_pil=lambda: types.SimpleNamespace(
                convert=lambda mode: types.SimpleNamespace(copy=lambda: None)
            ),
            close=None,
        )

        with patch(
            "pytesseract.image_to_string", return_value=""
        ) as mock_ocr, patch(
            "core.document_parser.configure_pytesseract", return_value=""
        ):
            from core.document_parser import _ocr_pdf_page
            _ocr_pdf_page(page, 1, [])
            self.assertTrue(mock_ocr.called)
            call_kwargs = mock_ocr.call_args.kwargs
            self.assertIn("timeout", call_kwargs)
            self.assertGreater(call_kwargs["timeout"], 0)


if __name__ == "__main__":
    unittest.main()
