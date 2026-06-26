"""Runtime helpers for locating and configuring Tesseract OCR."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from config import DATA_DIR


COMMON_TESSERACT_EXECUTABLES = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)

OCR_REMEDIATION = (
    "Windows: winget install -e --id UB-Mannheim.TesseractOCR "
    "--accept-package-agreements --accept-source-agreements; "
    "Alternative: choco install tesseract; "
    "Language data fallback: put eng.traineddata and chi_sim.traineddata in data/tessdata; "
    "then reopen the terminal and rerun python scripts/check_environment.py."
)


def find_tesseract_executable() -> str:
    """Return a usable Tesseract executable from PATH or common Windows paths."""
    executable = shutil.which("tesseract")
    if executable:
        return executable
    for candidate in COMMON_TESSERACT_EXECUTABLES:
        if candidate.exists():
            return str(candidate)
    return ""


def find_tessdata_dir(project_root: str | Path | None = None) -> str:
    """Return app-provided tessdata first, falling back to the installer tessdata."""
    roots = []
    if project_root is not None:
        roots.append(Path(project_root).resolve() / "data" / "tessdata")
    roots.append(Path(DATA_DIR).resolve() / "tessdata")

    executable = find_tesseract_executable()
    if executable:
        roots.append(Path(executable).resolve().parent / "tessdata")

    for candidate in roots:
        if candidate.exists():
            return str(candidate)
    return ""


def configure_pytesseract(pytesseract_module, project_root: str | Path | None = None) -> str:
    """Configure pytesseract for bundled/installed OCR resources.

    Returns an optional config string to pass to ``image_to_string``.
    """
    executable = find_tesseract_executable()
    pytesseract_api = getattr(pytesseract_module, "pytesseract", None)
    if executable and pytesseract_api is not None:
        pytesseract_api.tesseract_cmd = executable

    tessdata = find_tessdata_dir(project_root)
    if not tessdata:
        return ""
    os.environ.setdefault("TESSDATA_PREFIX", tessdata)
    return f"--tessdata-dir {tessdata}"
