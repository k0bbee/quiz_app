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

from core.background_task import TaskControl
from core.question_index import INDEX_FILENAME


BUNDLE_FORMAT = "quiz_app_data_bundle"
BUNDLE_VERSION = 1
DATA_DIRECTORIES = (
    "courses",
    "questions",
    "question_sets",
    "quiz_snapshots",
    "progress",
    "past_exams",
    "current_event_materials",
)
DATA_FILES = ("current_course.json", "settings.json", "mastery_overrides.json")
SECRET_FILENAMES = {".api_key.dpapi"}
SECRET_SETTING_KEYS = {"ai_api_key"}
LOCAL_ONLY_SETTING_KEYS = frozenset({
    "ai_api_key",
    "ai_provider",
    "ai_base_url",
    "ai_model",
})
DERIVED_FILENAMES = {
    INDEX_FILENAME,
    f"{INDEX_FILENAME}-wal",
    f"{INDEX_FILENAME}-shm",
}


@dataclass(frozen=True)
class AppDataImportResult:
    """Summary returned after importing an app data bundle."""

    imported_files: int
    skipped_files: list[str] = field(default_factory=list)
    ignored_settings: list[str] = field(default_factory=list)


def export_app_data_bundle(
    data_dir: str | Path,
    output_path: str | Path,
    *,
    task: TaskControl | None = None,
) -> Path:
    """Write a UTF-8 zip bundle containing portable runtime data."""
    source_dir = Path(data_dir)
    bundle_path = Path(output_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    _report(task, "scanning", detail=str(source_dir))
    files: list[tuple[Path, str]] = []
    for directory_name in DATA_DIRECTORIES:
        directory = source_dir / directory_name
        if not directory.exists():
            continue
        files.extend(
            (path, path.relative_to(source_dir).as_posix())
            for path in sorted(p for p in directory.rglob("*") if p.is_file())
            if path.name not in SECRET_FILENAMES | DERIVED_FILENAMES
        )
    for filename in DATA_FILES:
        path = source_dir / filename
        if path.exists() and path.is_file():
            files.append((path, filename))

    manifest = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "includes": [*DATA_DIRECTORIES, *DATA_FILES],
        "excludes": sorted([*SECRET_FILENAMES, *LOCAL_ONLY_SETTING_KEYS]),
    }

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{bundle_path.name}.",
            suffix=".tmp",
            dir=bundle_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            total = len(files)
            for index, (path, archive_name) in enumerate(files, start=1):
                _report(task, "exporting", index, total, archive_name)
                if archive_name == "settings.json":
                    archive.writestr(
                        archive_name,
                        json.dumps(_portable_settings(path), ensure_ascii=False, indent=2),
                    )
                else:
                    archive.write(path, archive_name)

        _report(task, "committing", total, total, bundle_path.name)
        os.replace(temporary_path, bundle_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    _complete(task, "saved", str(bundle_path))
    return bundle_path


def import_app_data_bundle(
    bundle_path: str | Path,
    data_dir: str | Path,
    *,
    task: TaskControl | None = None,
) -> AppDataImportResult:
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

        _report(task, "validating", detail=str(bundle_path))
        with zipfile.ZipFile(bundle_path) as archive:
            _validate_manifest(archive)
            staged_files, skipped, ignored_settings = _prepare_bundle(
                archive,
                staging_dir,
                task=task,
                target_dir=target_dir,
            )

        imported = _commit_staged_files(
            staged_files,
            target_dir,
            backup_dir,
            task=task,
        )

    _complete(task, "saved", str(target_dir))
    return AppDataImportResult(
        imported_files=imported,
        skipped_files=skipped,
        ignored_settings=ignored_settings,
    )


def _prepare_bundle(
    archive: zipfile.ZipFile,
    staging_dir: Path,
    *,
    task: TaskControl | None = None,
    target_dir: Path | None = None,
) -> tuple[list[tuple[Path, Path]], list[str], list[str]]:
    """Validate every import candidate and write it only to staging.

    Returns ``(staged_files, skipped_names, ignored_settings)``.
    When *target_dir* is supplied, existing ``settings.json`` is read
    so local AI trust fields survive the import.
    """
    staged_files: list[tuple[Path, Path]] = []
    skipped: list[str] = []
    ignored_settings: list[str] = []
    seen: set[str] = set()

    members = archive.infolist()
    total = sum(not info.is_dir() and info.filename != "manifest.json" for info in members)
    current = 0
    for info in members:
        name = info.filename
        if info.is_dir() or name == "manifest.json":
            continue
        current += 1
        _report(task, "staging", current, total, name)
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
            if name == "settings.json" and target_dir is not None:
                data = json.loads(payload.decode("utf-8"))
                existing = _read_existing_settings(target_dir)
                merged, ignored_settings = _merge_portable_settings(data, existing)
                payload = json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8")
            else:
                payload = _validated_json_payload(name, payload)

        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(payload)
        staged_files.append((relative_path, staged_path))

    return staged_files, skipped, ignored_settings


def _read_existing_settings(target_dir: Path) -> dict:
    """Read the target settings.json, returning an empty dict on any failure."""
    path = target_dir / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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
    for key in LOCAL_ONLY_SETTING_KEYS:
        data.pop(key, None)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _merge_portable_settings(
    imported: dict,
    existing: dict,
) -> tuple[dict, list[str]]:
    """Merge imported settings, preserving the receiving machine's AI trust.

    Returns ``(merged_settings, list_of_ignored_keys)``.  ``ai_api_key`` is
    never restored from either dictionary.
    """
    ignored = sorted(key for key in imported if key in LOCAL_ONLY_SETTING_KEYS)
    merged = {
        key: value
        for key, value in imported.items()
        if key not in LOCAL_ONLY_SETTING_KEYS
    }
    for key in LOCAL_ONLY_SETTING_KEYS:
        if key != "ai_api_key" and key in existing:
            merged[key] = existing[key]
    return merged, ignored


def _commit_staged_files(
    staged_files: list[tuple[Path, Path]],
    target_dir: Path,
    backup_dir: Path,
    *,
    task: TaskControl | None = None,
) -> int:
    """Commit staged files, restoring the original target state on failure."""
    backups: list[tuple[Path, Path]] = []
    created_paths: list[Path] = []

    try:
        total = len(staged_files)
        for index, (relative_path, staged_path) in enumerate(staged_files, start=1):
            _report(task, "committing", index, total, relative_path.as_posix())
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


def _report(
    task: TaskControl | None,
    stage: str,
    current: int = 0,
    total: int = 0,
    detail: str = "",
) -> None:
    if task is not None:
        task.report(stage, current, total, detail)


def _complete(task: TaskControl | None, stage: str, detail: str = "") -> None:
    if task is not None:
        task.complete(stage, detail)


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
    for key in LOCAL_ONLY_SETTING_KEYS:
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
    if Path(name).name in SECRET_FILENAMES | DERIVED_FILENAMES:
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
