import unittest
from pathlib import Path


class PublicReleasePolicyTests(unittest.TestCase):
    def setUp(self):
        self._root = Path(__file__).resolve().parent.parent

    def test_quizdata_pattern_is_ignored_by_git(self):
        """*.quizdata must be git-ignored to prevent accidental publication."""
        gitignore = self._root / ".gitignore"
        text = gitignore.read_text(encoding="utf-8")
        self.assertIn("*.quizdata", text, "*.quizdata must be listed in .gitignore")

    def test_security_workflow_exists_and_runs_pytest_and_pip_audit(self):
        workflow = self._root / ".github/workflows/security.yml"
        self.assertTrue(workflow.exists(), "security.yml must exist")
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("pip-audit", text)
        self.assertIn("pytest", text)

    def test_dependabot_config_exists(self):
        config = self._root / ".github/dependabot.yml"
        self.assertTrue(config.exists(), "dependabot.yml must exist")


if __name__ == "__main__":
    unittest.main()
