"""Portable app data bundle export/import helpers.

Bundles are intended for course/question/progress migration. They deliberately
exclude API key material because secrets already use keyring/DPAPI persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile


BUNDLE_FORMAT = "quiz_app_data_bundle"
BUNDLE_VERSION = 1
DATA_DIRECTORIES = ("courses", "questions", "question_sets", "quiz_snapshots", "progress")
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
    """Atomically import whitelisted runtime data from a bundle into data_dir."""
    target_dir = Path(data_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".app-data-import-",
        dir=target_dir.parent,
    ) as temporary_directory:
        transaction_dir = Path(temporary_directory)
        staging_dir = transaction_dir / "staging"
        backup_dir = transaction_dir / "backup"

        with zipfile.ZipFile(bundle_path) as archive:
            _validate_manifest(archive)
            staged_files, skipped = _prepare_bundle(archive, staging_dir)

        imported = _commit_staged_files(staged_files, target_dir, backup_dir)

    return AppDataImportResult(imported_files=imported, skipped_files=skipped)


def _prepare_bundle(
    archive: zipfile.ZipFile,
    staging_dir: Path,
) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Validate every import candidate and write it only to staging."""
    staged_files: list[tuple[Path, Path]] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for info in archive.infolist():
        name = info.filename
        if info.is_dir() or name == "manifest.json":
            continue
        if not _is_allowed_bundle_member(name):
            skipped.append(name)
            continue
        if name in seen:
            raise ValueError(f"Duplicate data bundle member: {name}")
        seen.add(name)

        relative_path = Path(name)
        staged_path = staging_dir / relative_path
        if not _is_within_directory(staging_dir, staged_path):
            skipped.append(name)
            continue

        payload = archive.read(info)
        if relative_path.suffix.lower() == ".json":
            payload = _validated_json_payload(name, payload)

        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(payload)
        staged_files.append((relative_path, staged_path))

    return staged_files, skipped


def _validated_json_payload(name: str, payload: bytes) -> bytes:
    """Validate JSON payload and sanitize portable settings."""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON data bundle member: {name}") from exc

    if name != "settings.json":
        return payload
    if not isinstance(data, dict):
        raise ValueError("Invalid settings.json in data bundle: expected an object")
    for key in SECRET_SETTING_KEYS:
        data.pop(key, None)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _commit_staged_files(
    staged_files: list[tuple[Path, Path]],
    target_dir: Path,
    backup_dir: Path,
) -> int:
    """Commit staged files, restoring the original target state on failure."""
    backups: list[tuple[Path, Path]] = []
    created_paths: list[Path] = []

    try:
        for relative_path, staged_path in staged_files:
            destination = target_dir / relative_path
            if not _is_within_directory(target_dir, destination):
                raise ValueError(f"Unsafe staged data path: {relative_path.as_posix()}")

            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup_path = backup_dir / relative_path
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_path)
                backups.append((destination, backup_path))
            else:
                created_paths.append(destination)

            os.replace(staged_path, destination)
    except Exception as commit_error:
        recovery_errors = _restore_import_target(backups, created_paths)
        if recovery_errors:
            details = "; ".join(str(error) for error in recovery_errors)
            raise RuntimeError(
                f"App data import failed ({commit_error}); rollback also failed: {details}"
            ) from commit_error
        raise

    return len(staged_files)


def _restore_import_target(
    backups: list[tuple[Path, Path]],
    created_paths: list[Path],
) -> list[Exception]:
    """Best-effort rollback for a failed import commit."""
    errors: list[Exception] = []
    for path in reversed(created_paths):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(exc)
    for destination, backup_path in reversed(backups):
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, destination)
        except OSError as exc:
            errors.append(exc)
    return errors


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
    if sum(info.filename == "manifest.json" for info in archive.infolist()) != 1:
        raise ValueError("Invalid quiz app data bundle manifest")
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
