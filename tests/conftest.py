from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest


_QT_IMPORT_PATTERNS = ("from PyQt6", "import PyQt6")


def pytest_addoption(parser):
    group = parser.getgroup("quiz-app")
    group.addoption(
        "--run-full",
        action="store_true",
        default=False,
        help="run opt-in full workflow and large fixture tests",
    )


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
    """Mark Qt tests and keep expensive full workflows opt-in."""
    skip_full = pytest.mark.skip(reason="full workflow test; pass --run-full to execute")
    for item in items:
        item_path = Path(str(getattr(item, "path", getattr(item, "fspath", ""))))
        if _is_qt_test_file(str(item_path)):
            item.add_marker(pytest.mark.qt)
        if item.get_closest_marker("full") and not config.getoption("--run-full"):
            item.add_marker(skip_full)
