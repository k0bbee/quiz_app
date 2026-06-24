"""Runtime environment diagnostics without reading or printing secret values."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from core.windows_dpapi_store import WindowsDPAPISecretStore


PYTHON_DEPENDENCIES = (
    ("PyQt6", "PyQt6"),
    ("requests", "requests"),
    ("keyring", "keyring"),
    ("PyMuPDF", "fitz"),
    ("Pillow", "PIL"),
    ("pytesseract", "pytesseract"),
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EnvironmentReport:
    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok or not check.required for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
        }


def collect_environment_report(project_root: str | Path) -> EnvironmentReport:
    """Collect package, persistence, OCR and write-access diagnostics."""
    root = Path(project_root).resolve()
    checks = [
        CheckResult(
            "Python",
            sys.version_info >= (3, 10),
            True,
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    ]

    package_status = {}
    for distribution, module_name in PYTHON_DEPENDENCIES:
        try:
            importlib.import_module(module_name)
            version = importlib.metadata.version(distribution)
            result = CheckResult(distribution, True, True, version)
        except Exception as exc:
            result = CheckResult(
                distribution,
                False,
                True,
                f"{type(exc).__name__}: install with python -m pip install -r requirements.txt",
            )
        checks.append(result)
        package_status[distribution] = result

    keyring_ok = False
    keyring_detail = "keyring package unavailable"
    if package_status["keyring"].ok:
        try:
            keyring = importlib.import_module("keyring")
            backend = keyring.get_keyring()
            priority = float(getattr(backend, "priority", 0))
            keyring_ok = priority > 0
            keyring_detail = (
                f"{backend.__class__.__module__}.{backend.__class__.__name__} "
                f"(priority {priority:g})"
            )
        except Exception as exc:
            keyring_detail = f"{type(exc).__name__}: {exc}"
    checks.append(CheckResult("keyring backend", keyring_ok, False, keyring_detail))

    dpapi_ok = WindowsDPAPISecretStore.is_available()
    persistence_ok = keyring_ok or dpapi_ok
    persistence_detail = (
        "system keyring"
        if keyring_ok
        else "Windows DPAPI encrypted fallback"
        if dpapi_ok
        else "session-only; install/configure a keyring backend"
    )
    checks.append(
        CheckResult(
            "secure API key persistence",
            persistence_ok,
            False,
            persistence_detail,
        )
    )

    checks.append(_check_tesseract())
    checks.append(_check_data_directory(root / "data"))
    return EnvironmentReport(tuple(checks))


def _check_tesseract() -> CheckResult:
    executable = shutil.which("tesseract")
    if not executable:
        return CheckResult(
            "Tesseract OCR",
            False,
            False,
            "optional system executable not found; scanned PDF OCR is unavailable",
        )
    try:
        result = subprocess.run(
            [executable, "--list-langs"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        languages = {
            line.strip()
            for line in result.stdout.splitlines()[1:]
            if line.strip()
        }
        expected = {"eng", "chi_sim"}
        missing = sorted(expected - languages)
        if result.returncode != 0:
            return CheckResult(
                "Tesseract OCR",
                False,
                False,
                f"executable failed with exit code {result.returncode}",
            )
        if missing:
            return CheckResult(
                "Tesseract OCR",
                False,
                False,
                "missing optional language packs: " + ", ".join(missing),
            )
        return CheckResult(
            "Tesseract OCR",
            True,
            False,
            f"{executable}; eng and chi_sim available",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("Tesseract OCR", False, False, f"{type(exc).__name__}: {exc}")


def _check_data_directory(data_dir: Path) -> CheckResult:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        descriptor, probe_path = tempfile.mkstemp(prefix=".write-probe-", dir=data_dir)
        os.close(descriptor)
        Path(probe_path).unlink(missing_ok=True)
        return CheckResult("data directory", True, True, f"writable: {data_dir}")
    except OSError as exc:
        return CheckResult("data directory", False, True, f"not writable: {exc}")


def format_environment_report(report: EnvironmentReport) -> str:
    lines = ["Environment check: PASS" if report.ok else "Environment check: FAIL"]
    for check in report.checks:
        status = "OK" if check.ok else "WARN" if not check.required else "FAIL"
        lines.append(f"[{status}] {check.name}: {check.detail}")
    return "\n".join(lines)
