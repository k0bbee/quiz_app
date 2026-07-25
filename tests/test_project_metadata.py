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

    def test_readme_documents_installation_runtime_and_environment_diagnostics(self):
        readme = Path("README.md").read_text(encoding="utf-8").lower()
        required_fragments = (
            "tesseract",
            "chi_sim",
            "无可提取文本",
            "winget install -e --id ub-mannheim.tesseractocr",
            "choco install tesseract",
            "data/tessdata",
            "python -m pip install -r requirements.txt",
            "python scripts/check_environment.py",
            "设置 → 运行环境 → 检查环境",
            "练习默认题量/难度/计时器",
            "windows dpapi",
            "keyring backend",
        )

        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, readme)

    def test_readmes_document_opt_in_network_and_safe_task_recovery(self):
        chinese = Path("README.md").read_text(encoding="utf-8")
        english = Path("README.en.md").read_text(encoding="utf-8")
        contracts = (
            (
                "current_events",
                chinese,
                ("打开窗口不会自动联网", "只有勾选材料进入出题"),
            ),
            (
                "current_events",
                english,
                (
                    "opening the dialog never starts a search",
                    "only selected items enter generation",
                ),
            ),
            (
                "task_recovery",
                chinese,
                ("“打开任务页面”只导航", "只有恢复字段完整时"),
            ),
            (
                "task_recovery",
                english,
                (
                    "Open Task Page only navigates",
                    "recovery metadata is complete",
                ),
            ),
        )

        for feature, document, fragments in contracts:
            with self.subTest(feature=feature, fragments=fragments):
                for fragment in fragments:
                    self.assertIn(fragment, document)

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
