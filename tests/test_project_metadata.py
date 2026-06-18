import unittest
from pathlib import Path


class ProjectMetadataTests(unittest.TestCase):
    def test_requirements_include_document_parser_dependencies(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

        self.assertIn("pymupdf", requirements)
        self.assertIn("pillow", requirements)
        self.assertIn("pytesseract", requirements)


if __name__ == "__main__":
    unittest.main()
