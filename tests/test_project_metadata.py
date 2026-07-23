import unittest
from pathlib import Path


class ProjectMetadataTests(unittest.TestCase):
    def test_requirements_include_document_parser_dependencies(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

        self.assertNotIn("pymupdf", requirements)
        self.assertIn("pypdfium2", requirements)
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

    def test_public_readmes_do_not_document_local_copyright_application_tools(self):
        private_tool_references = (
            "build_copyright_",
            "check_copyright_submission",
            "copyright-submission/",
            "docs/copyright/",
        )

        for readme_path in (Path("README.md"), Path("README.en.md")):
            with self.subTest(readme=readme_path.name):
                readme = readme_path.read_text(encoding="utf-8").lower()
                for reference in private_tool_references:
                    self.assertNotIn(reference, readme)

    def test_public_metadata_uses_identity_neutral_provenance_wording(self):
        copyright_notice = Path("COPYRIGHT.md").read_text(encoding="utf-8")

        self.assertIn("Git提交记录仅用于追溯代码变更和技术来源", copyright_notice)
        self.assertNotIn("当前 Git 历史记录的提交作者", copyright_notice)


if __name__ == "__main__":
    unittest.main()
