from contextlib import redirect_stdout
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.environment_check import CheckResult, EnvironmentReport, collect_environment_report, _check_data_directory, _check_tesseract
from core.environment_check import format_environment_report
from scripts.check_environment import main as environment_check_main


class EnvironmentCheckTests(unittest.TestCase):
    def test_only_required_failures_make_report_unhealthy(self):
        healthy = EnvironmentReport((
            CheckResult("python", True, True, "3.14"),
            CheckResult(
                "tesseract",
                False,
                False,
                "optional executable missing",
                "install tesseract",
            ),
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

    def test_collector_exposes_remediation_for_missing_required_python_packages(self):
        original_import_module = __import__("importlib").import_module

        def import_module(name):
            if name == "requests":
                raise ModuleNotFoundError("No module named requests")
            return original_import_module(name)

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("core.environment_check.importlib.import_module", side_effect=import_module), \
             patch("core.environment_check._check_tesseract", return_value=CheckResult("Tesseract OCR", True, False, "available")):
            report = collect_environment_report(Path(tmpdir))

        by_name = {check.name: check for check in report.checks}
        self.assertFalse(report.ok)
        self.assertFalse(by_name["requests"].ok)
        self.assertEqual("python -m pip install -r requirements.txt", by_name["requests"].remediation)
        self.assertIn("Fix: python -m pip install -r requirements.txt", format_environment_report(report))

    def test_data_directory_check_exposes_remediation_when_not_writable(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("core.environment_check.tempfile.mkstemp", side_effect=OSError("denied")):
            result = _check_data_directory(Path(tmpdir) / "data")

        self.assertFalse(result.ok)
        self.assertTrue(result.required)
        self.assertIn("not writable", result.detail)
        self.assertIn("choose a writable project location", result.remediation)
        self.assertIn("Fix: " + result.remediation, format_environment_report(EnvironmentReport((result,))))

    def test_key_persistence_checks_expose_remediation_when_no_backend_is_available(self):
        original_import_module = __import__("importlib").import_module

        class NullKeyring:
            priority = 0

        class FakeKeyringModule:
            @staticmethod
            def get_keyring():
                return NullKeyring()

        def import_module(name):
            if name == "keyring":
                return FakeKeyringModule()
            return original_import_module(name)

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("core.environment_check.importlib.import_module", side_effect=import_module), \
             patch("core.environment_check.WindowsDPAPISecretStore.is_available", return_value=False), \
             patch("core.environment_check._check_tesseract", return_value=CheckResult("Tesseract OCR", True, False, "available")):
            report = collect_environment_report(Path(tmpdir))

        by_name = {check.name: check for check in report.checks}
        self.assertFalse(by_name["keyring backend"].ok)
        self.assertFalse(by_name["secure API key persistence"].ok)
        self.assertIn("configure a usable keyring backend", by_name["keyring backend"].remediation)
        self.assertIn("configure a usable keyring backend", by_name["secure API key persistence"].remediation)
        self.assertIn("Fix: " + by_name["secure API key persistence"].remediation, format_environment_report(report))

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

    def test_text_report_includes_optional_ocr_remediation_options(self):
        report = EnvironmentReport((
            CheckResult("Python", True, True, "3.14"),
            CheckResult(
                "Tesseract OCR",
                False,
                False,
                "optional system executable not found; scanned PDF OCR is unavailable",
                "Windows: winget install -e --id UB-Mannheim.TesseractOCR",
            ),
        ))

        from core.environment_check import format_environment_report

        rendered = format_environment_report(report)

        self.assertIn("[WARN] Tesseract OCR", rendered)
        self.assertIn("Fix: Windows: winget install -e --id UB-Mannheim.TesseractOCR", rendered)

    def test_json_report_exposes_remediation_without_secret_values(self):
        report = EnvironmentReport((
            CheckResult(
                "Tesseract OCR",
                False,
                False,
                "optional system executable not found",
                "Windows: winget install -e --id UB-Mannheim.TesseractOCR",
            ),
        ))

        payload = report.to_dict()

        self.assertEqual(
            "Windows: winget install -e --id UB-Mannheim.TesseractOCR",
            payload["checks"][0]["remediation"],
        )

    def test_tesseract_check_uses_common_install_path_and_project_tessdata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tessdata = root / "data" / "tessdata"
            tessdata.mkdir(parents=True)
            (tessdata / "eng.traineddata").write_text("fake", encoding="utf-8")
            (tessdata / "chi_sim.traineddata").write_text("fake", encoding="utf-8")

            with patch("core.environment_check.find_tesseract_executable", return_value=r"C:\Program Files\Tesseract-OCR\tesseract.exe"), \
                 patch("core.environment_check._run_tesseract_list_langs", return_value=(0, "List of available languages:\neng\nchi_sim\n")):
                result = _check_tesseract(root)

        self.assertTrue(result.ok, result.detail)
        self.assertIn("data", result.detail)


if __name__ == "__main__":
    unittest.main()
