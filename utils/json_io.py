"""Safe JSON read/write with error handling."""
from utils.logger import warning, error

import json
import os
import re
import tempfile
import time
from typing import Any, Optional


_REPLACE_RETRY_DELAYS = (0.02, 0.05, 0.1)


def sanitize_filename_part(name: str) -> str:
    """Return a safe version of `name` for use in file paths.

    Only allows [a-zA-Z0-9_.-]. Rejects `..`, `/`, `\\`.
    Raises ValueError if the sanitized name differs from the original
    or if the result is empty.
    """
    if not name or not isinstance(name, str):
        raise ValueError("filename part must be a non-empty string")

    # Block path traversal patterns
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"path traversal rejected: {name!r}")

    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", name).strip("_")
    if not safe:
        raise ValueError(f"sanitized filename is empty for: {name!r}")
    if safe != name:
        raise ValueError(f"unsafe characters in filename: {name!r} → {safe!r}")

    return safe


def read_json(filepath: str) -> Optional[dict]:
    """Read a JSON file. Returns None if file doesn't exist or is invalid."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        warning(f"Failed to read {filepath}: {e}")
        return None


def write_json(filepath: str, data: Any, indent: int = 2) -> bool:
    """Atomically write data to a JSON file. Creates parent directories if needed.
    Returns True on success.

    Writes to a temporary file in the same directory, flushes it, then replaces
    the target with ``os.replace`` so crashes or serialization errors do not
    leave a half-written target JSON file.
    """
    tmp_path = ""
    try:
        target_path = os.path.abspath(filepath)
        directory = os.path.dirname(target_path) or "."
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{os.path.basename(target_path)}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=indent, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp_path, target_path)
        _fsync_parent_directory(directory)
        return True
    except (OSError, TypeError, ValueError) as e:
        error(f"Failed to write {filepath}: {e}")
        if tmp_path:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError as cleanup_error:
                warning(f"Failed to remove temporary JSON file {tmp_path}: {cleanup_error}")
        return False


def _replace_with_retry(source: str, target: str) -> None:
    """Retry only transient file-lock failures while preserving atomic replace."""
    for delay in (*_REPLACE_RETRY_DELAYS, None):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            if delay is None or not _is_transient_replace_error(exc):
                raise
            time.sleep(delay)


def _is_transient_replace_error(error: OSError) -> bool:
    """Return whether another process may briefly hold the destination file."""
    return isinstance(error, PermissionError) or getattr(error, "winerror", None) in {
        5,   # access denied
        32,  # sharing violation
        33,  # lock violation
    }


def _fsync_parent_directory(directory: str):
    """Best-effort directory fsync for platforms that support it."""
    flags = getattr(os, "O_RDONLY", 0)
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    else:
        return
    try:
        fd = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def list_json_files(directory: str) -> list[str]:
    """List all .json files in a directory. Returns empty list if directory missing."""
    if not os.path.exists(directory):
        return []
    return sorted([
        f for f in os.listdir(directory)
        if f.endswith(".json")
    ])


def load_all_json(directory: str) -> list[dict]:
    """Load all JSON files from a directory. Skips invalid files."""
    results = []
    for filename in list_json_files(directory):
        filepath = os.path.join(directory, filename)
        data = read_json(filepath)
        if data is not None:
            results.append(data)
    return results


def delete_json(filepath: str) -> bool:
    """Delete a JSON file. Returns True if deleted or didn't exist."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
        return True
    except OSError as e:
        error(f"Failed to delete {filepath}: {e}")
        return False
