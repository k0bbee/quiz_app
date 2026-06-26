import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.ocr_runtime import configure_pytesseract


class OCRRuntimeTests(unittest.TestCase):
    def test_configure_pytesseract_uses_unquoted_tessdata_config(self):
        fake_pytesseract = types.SimpleNamespace(
            pytesseract=types.SimpleNamespace(tesseract_cmd="")
        )

        with patch("core.ocr_runtime.find_tesseract_executable", return_value=r"C:\Program Files\Tesseract-OCR\tesseract.exe"), \
             patch("core.ocr_runtime.find_tessdata_dir", return_value=str(Path("data") / "tessdata")):
            config = configure_pytesseract(fake_pytesseract)

        self.assertEqual(r"C:\Program Files\Tesseract-OCR\tesseract.exe", fake_pytesseract.pytesseract.tesseract_cmd)
        self.assertEqual("--tessdata-dir data\\tessdata", config)
        self.assertNotIn('"', config)


if __name__ == "__main__":
    unittest.main()
