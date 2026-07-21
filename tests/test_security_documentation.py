import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SecurityDocumentationTests(unittest.TestCase):
    def test_default_security_policy_is_complete_chinese_version(self):
        policy = (PROJECT_ROOT / "SECURITY.md").read_text(encoding="utf-8")

        self.assertTrue(policy.startswith("# 安全策略"))
        self.assertIn("[English](SECURITY.en.md)", policy)
        for heading in (
            "## 支持版本",
            "## 报告安全漏洞",
            "## 安全敏感区域",
            "## 通常不在受理范围",
            "## 处理敏感测试材料",
        ):
            self.assertIn(heading, policy)

    def test_english_security_policy_is_preserved_and_links_to_chinese(self):
        policy = (PROJECT_ROOT / "SECURITY.en.md").read_text(encoding="utf-8")

        self.assertTrue(policy.startswith("# Security Policy"))
        self.assertIn("[简体中文](SECURITY.md)", policy)
        self.assertIn("## Reporting a vulnerability", policy)
        self.assertIn("## Security-sensitive areas", policy)

    def test_readmes_link_to_matching_security_policy_language(self):
        chinese_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        english_readme = (PROJECT_ROOT / "README.en.md").read_text(encoding="utf-8")

        self.assertIn("[SECURITY.md](SECURITY.md)", chinese_readme)
        self.assertIn("[SECURITY.en.md](SECURITY.en.md)", english_readme)


if __name__ == "__main__":
    unittest.main()
