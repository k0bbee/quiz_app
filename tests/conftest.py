from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest


_QT_IMPORT_PATTERNS = ("from PyQt6", "import PyQt6")


@lru_cache(maxsize=1)
def _pyqt6_available() -> bool:
    return importlib.util.find_spec("PyQt6") is not None


@lru_cache(maxsize=None)
def _is_qt_test_file(path_text: str) -> bool:
    path = Path(path_text)
    if path.suffix != ".py" or not path.name.startswith("test_"):
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(pattern in text for pattern in _QT_IMPORT_PATTERNS)


def pytest_ignore_collect(collection_path, config):
    """Skip Qt test collection entirely when PyQt6 is not installed."""
    if _is_qt_test_file(str(collection_path)) and not _pyqt6_available():
        return True
    return None


def pytest_collection_modifyitems(config, items):
    """Mark Qt tests automatically so core and UI suites can run separately."""
    for item in items:
        item_path = Path(str(getattr(item, "path", getattr(item, "fspath", ""))))
        if _is_qt_test_file(str(item_path)):
            item.add_marker(pytest.mark.qt)
