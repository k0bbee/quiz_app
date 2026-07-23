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
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "memory.pdf"
            path.write_bytes(
                _minimal_text_pdf(
                    "Virtual memory maps pages through a page table."
                )
            )

            document = DocumentParser().parse_file(path)

            self.assertIn("Virtual memory maps pages", document.text)
            self.assertEqual([], document.warnings)
            self.assertEqual(1, len(document.pages))

    def test_real_image_pdf_runs_render_to_ocr_fallback_pipeline(self):
        import pypdfium2 as pdfium
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "scan.png"
            image = Image.new("RGB", (600, 200), "white")
            ImageDraw.Draw(image).text((30, 70), "Scanned cache hierarchy", fill="black")
            jpeg_path = root / "scan.jpg"
            image.save(jpeg_path, format="JPEG")

            pdf_path = root / "scan.pdf"
            pdf = pdfium.PdfDocument.new()
            page = pdf.new_page(600, 200)
            image_object = pdfium.PdfImage.new(pdf)
            image_object.load_jpeg(jpeg_path)
            page.insert_obj(image_object)
            page.gen_content()
            pdf.save(pdf_path)
            image_object.close()
            page.close()
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


def _minimal_text_pdf(text: str) -> bytes:
    """Return a one-page PDF with a standard-font text content stream."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
    )
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


if __name__ == "__main__":
    unittest.main()
