import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from core.document_parser import DocumentParser


class DocumentParserFixtureTests(unittest.TestCase):
    def test_minimal_real_docx_extracts_paragraphs_in_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "systems.docx"
            document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Cache Mapping</w:t></w:r></w:p>
    <w:p><w:r><w:t>Tag, set, and byte offset determine a cache lookup.</w:t></w:r></w:p>
  </w:body>
</w:document>"""
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", document_xml.encode("utf-8"))

            document = DocumentParser().parse_file(path)

            self.assertEqual(".docx", document.extension)
            self.assertEqual([], document.warnings)
            self.assertEqual(1, len(document.pages))
            self.assertIn("Cache Mapping\nTag, set", document.text)

    def test_minimal_real_pptx_extracts_slides_in_numeric_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scheduling.pptx"
            slide = lambda text: f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>"""
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ppt/slides/slide10.xml", slide("Tenth slide"))
                archive.writestr("ppt/slides/slide2.xml", slide("Second slide"))
                archive.writestr("ppt/slides/slide1.xml", slide("First slide"))

            document = DocumentParser().parse_file(path)

            self.assertEqual(["First slide", "Second slide", "Tenth slide"], document.pages)
            self.assertLess(document.text.index("[Slide 1]"), document.text.index("[Slide 2]"))
            self.assertIn("[Slide 3]\nTenth slide", document.text)

    def test_real_text_pdf_extracts_page_text(self):
        import fitz

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "memory.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((72, 72), "Virtual memory maps pages through a page table.")
            pdf.save(path)
            pdf.close()

            document = DocumentParser().parse_file(path)

            self.assertIn("Virtual memory maps pages", document.text)
            self.assertEqual([], document.warnings)
            self.assertEqual(1, len(document.pages))

    def test_real_image_pdf_runs_render_to_ocr_fallback_pipeline(self):
        import fitz
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "scan.png"
            image = Image.new("RGB", (600, 200), "white")
            ImageDraw.Draw(image).text((30, 70), "Scanned cache hierarchy", fill="black")
            image.save(image_path)

            pdf_path = root / "scan.pdf"
            pdf = fitz.open()
            page = pdf.new_page(width=600, height=200)
            page.insert_image(page.rect, filename=str(image_path))
            pdf.save(pdf_path)
            pdf.close()

            ocr = Mock(return_value="Recovered OCR cache hierarchy")
            fake_pytesseract = types.SimpleNamespace(image_to_string=ocr)
            with patch.dict("sys.modules", {"pytesseract": fake_pytesseract}):
                document = DocumentParser().parse_file(pdf_path)

            self.assertTrue(ocr.called)
            rendered_image = ocr.call_args.args[0]
            self.assertGreater(rendered_image.width, 0)
            self.assertGreater(rendered_image.height, 0)
            self.assertIn("Recovered OCR cache hierarchy", document.text)
            self.assertIn("text recovered by OCR fallback", "\n".join(document.warnings))


if __name__ == "__main__":
    unittest.main()
