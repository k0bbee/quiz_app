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

    def test_security_workflow_bounds_and_identifies_stuck_tests(self):
        workflow = self._root / ".github/workflows/security.yml"
        text = workflow.read_text(encoding="utf-8")

        self.assertIn("timeout-minutes:", text)
        self.assertIn("pytest-timeout", text)
        self.assertIn("pytest -vv", text)
        self.assertIn("--timeout=", text)

    def test_release_dependencies_are_pinned_and_audited(self):
        lock_file = self._root / "requirements-release.txt"
        self.assertTrue(
            lock_file.exists(),
            "requirements-release.txt must define the reproducible release environment",
        )
        pinned = [
            line.strip()
            for line in lock_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(pinned)
        self.assertTrue(
            all("==" in line.split(";", 1)[0] for line in pinned),
            "every release dependency must use an exact version",
        )

        workflow = (
            self._root / ".github/workflows/security.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("pip install -r requirements-release.txt", workflow)
        self.assertIn("pip_audit -r requirements-release.txt", workflow)
        self.assertIn("Audit release lock", workflow)

    def test_dependabot_config_exists(self):
        config = self._root / ".github/dependabot.yml"
        self.assertTrue(config.exists(), "dependabot.yml must exist")


if __name__ == "__main__":
    unittest.main()
