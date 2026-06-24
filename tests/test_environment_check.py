from contextlib import redirect_stdout
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from core.environment_check import CheckResult, EnvironmentReport, collect_environment_report
from scripts.check_environment import main as environment_check_main


class EnvironmentCheckTests(unittest.TestCase):
    def test_only_required_failures_make_report_unhealthy(self):
        healthy = EnvironmentReport((
            CheckResult("python", True, True, "3.14"),
            CheckResult("tesseract", False, False, "optional executable missing"),
        ))
        unhealthy = EnvironmentReport((
            CheckResult("python", True, True, "3.14"),
            CheckResult("PyQt6", False, True, "package missing"),
        ))

        self.assertTrue(healthy.ok)
        self.assertEqual(0, healthy.exit_code)
        self.assertFalse(unhealthy.ok)
        self.assertEqual(1, unhealthy.exit_code)

    def test_collector_checks_required_packages_and_writable_data_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = collect_environment_report(Path(tmpdir))

        by_name = {check.name: check for check in report.checks}
        for dependency in ("PyQt6", "requests", "keyring", "PyMuPDF", "Pillow", "pytesseract"):
            self.assertIn(dependency, by_name)
            self.assertTrue(by_name[dependency].ok, by_name[dependency].detail)
        self.assertTrue(by_name["data directory"].ok)
        self.assertIn("secure API key persistence", by_name)

    def test_cli_json_report_is_machine_readable_and_contains_no_secret_values(self):
        output = io.StringIO()
        previous_argv = sys.argv
        self.addCleanup(setattr, sys, "argv", previous_argv)
        sys.argv = ["check_environment.py", "--json"]
        with redirect_stdout(output):
            exit_code = environment_check_main()

        rendered = output.getvalue()
        payload = json.loads(rendered)
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertIn("checks", payload)
        self.assertNotIn("api_key", rendered.lower())
        self.assertNotIn("secret", rendered.lower())


if __name__ == "__main__":
    unittest.main()
