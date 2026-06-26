import unittest
from pathlib import Path


class ProjectMetadataTests(unittest.TestCase):
    def test_requirements_include_document_parser_dependencies(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

        self.assertIn("pymupdf", requirements)
        self.assertIn("pillow", requirements)
        self.assertIn("pytesseract", requirements)
        self.assertIn("keyring", requirements)

    def test_readme_documents_ocr_runtime_prerequisites(self):
        readme = Path("README.md").read_text(encoding="utf-8").lower()

        self.assertIn("tesseract", readme)
        self.assertIn("chi_sim", readme)
        self.assertIn("无可提取文本", readme)
        self.assertIn("winget install -e --id ub-mannheim.tesseractocr", readme)
        self.assertIn("choco install tesseract", readme)
        self.assertIn("data/tessdata", readme)

    def test_readme_documents_install_and_environment_diagnostics(self):
        readme = Path("README.md").read_text(encoding="utf-8").lower()

        self.assertIn("python -m pip install -r requirements.txt", readme)
        self.assertIn("python scripts/check_environment.py", readme)
        self.assertIn("设置 → 运行环境 → 检查环境", readme)
        self.assertIn("练习默认题量/难度/计时器", readme)
        self.assertIn("windows dpapi", readme)
        self.assertIn("keyring backend", readme)


if __name__ == "__main__":
    unittest.main()
