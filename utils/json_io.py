"""Safe JSON read/write with error handling."""
from utils.logger import debug, warning, error

import json
import os
import re
from typing import Any, Optional


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
    """Write data to a JSON file. Creates parent directories if needed.
    Returns True on success."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        return True
    except (OSError, TypeError) as e:
        error(f"Failed to write {filepath}: {e}")
        return False


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
