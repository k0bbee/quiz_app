"""Portable app data bundle export/import helpers.

Bundles are intended for course/question/progress migration. They deliberately
exclude API key material because secrets already use keyring/DPAPI persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import zipfile


BUNDLE_FORMAT = "quiz_app_data_bundle"
BUNDLE_VERSION = 1
DATA_DIRECTORIES = ("courses", "questions", "question_sets", "progress")
DATA_FILES = ("current_course.json", "settings.json", "mastery_overrides.json")
SECRET_FILENAMES = {".api_key.dpapi"}
SECRET_SETTING_KEYS = {"ai_api_key"}


@dataclass(frozen=True)
class AppDataImportResult:
    """Summary returned after importing an app data bundle."""

    imported_files: int
    skipped_files: list[str] = field(default_factory=list)


def export_app_data_bundle(data_dir: str | Path, output_path: str | Path) -> Path:
    """Write a UTF-8 zip bundle containing portable runtime data."""
    source_dir = Path(data_dir)
    bundle_path = Path(output_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "includes": [*DATA_DIRECTORIES, *DATA_FILES],
        "excludes": sorted([*SECRET_FILENAMES, *SECRET_SETTING_KEYS]),
    }

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for directory_name in DATA_DIRECTORIES:
            directory = source_dir / directory_name
            if not directory.exists():
                continue
            for path in sorted(p for p in directory.rglob("*") if p.is_file()):
                if path.name in SECRET_FILENAMES:
                    continue
                archive.write(path, path.relative_to(source_dir).as_posix())

        for filename in DATA_FILES:
            path = source_dir / filename
            if not path.exists() or not path.is_file():
                continue
            if filename == "settings.json":
                archive.writestr(filename, json.dumps(_portable_settings(path), ensure_ascii=False, indent=2))
            else:
                archive.write(path, filename)

    return bundle_path


def import_app_data_bundle(bundle_path: str | Path, data_dir: str | Path) -> AppDataImportResult:
    """Import whitelisted runtime data from a bundle into data_dir."""
    target_dir = Path(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    imported = 0
    skipped: list[str] = []

    with zipfile.ZipFile(bundle_path) as archive:
        _validate_manifest(archive)
        for info in archive.infolist():
            name = info.filename
            if info.is_dir() or name == "manifest.json":
                continue
            if not _is_allowed_bundle_member(name):
                skipped.append(name)
                continue

            relative_path = Path(name)
            output_path = target_dir / relative_path
            if not _is_within_directory(target_dir, output_path):
                skipped.append(name)
                continue

            output_path.parent.mkdir(parents=True, exist_ok=True)
            if name == "settings.json":
                settings = json.loads(archive.read(info).decode("utf-8"))
                for key in SECRET_SETTING_KEYS:
                    settings.pop(key, None)
                output_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                output_path.write_bytes(archive.read(info))
            imported += 1

    return AppDataImportResult(imported_files=imported, skipped_files=skipped)


def _portable_settings(path: Path) -> dict:
    """Load settings and remove secret fields before bundling."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    portable = dict(data)
    for key in SECRET_SETTING_KEYS:
        portable.pop(key, None)
    return portable


def _validate_manifest(archive: zipfile.ZipFile) -> None:
    try:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid quiz app data bundle manifest") from exc
    if manifest.get("format") != BUNDLE_FORMAT:
        raise ValueError("Unsupported data bundle format")
    if manifest.get("version") != BUNDLE_VERSION:
        raise ValueError("Unsupported data bundle version")


def _is_allowed_bundle_member(name: str) -> bool:
    if "\\" in name or name.startswith("/") or ".." in Path(name).parts:
        return False
    if Path(name).name in SECRET_FILENAMES:
        return False
    if name in DATA_FILES:
        return True
    parts = Path(name).parts
    return bool(parts) and parts[0] in DATA_DIRECTORIES


def _is_within_directory(directory: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False
