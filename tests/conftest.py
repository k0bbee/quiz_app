from __future__ import annotations

import importlib.util
import tempfile
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
        if item_path.name.startswith("test_copyright_"):
            item.add_marker(pytest.mark.full)
        if item.get_closest_marker("full") and not config.getoption("--run-full"):
            item.add_marker(skip_full)


class _InMemorySecrets:
    def __init__(self):
        self.value = ""

    def get_key(self) -> str:
        return self.value

    def set_key(self, value: str) -> str:
        self.value = value.strip()
        return "test memory"

    def get_storage_location(self) -> str:
        return "test memory"

    def get_storage_warning(self) -> str:
        return ""


@pytest.fixture(autouse=True)
def _isolate_qt_settings_and_secrets(request, monkeypatch):
    """Prevent UI tests from touching real settings files or OS credentials."""
    if request.node.get_closest_marker("qt") is None or not _pyqt6_available():
        yield
        return

    from core.secrets_manager import SecretsManager
    from ui.screens import settings_screen

    secrets = _InMemorySecrets()
    with tempfile.TemporaryDirectory(prefix="quiz-app-qt-test-") as temp_dir:
        monkeypatch.setattr(
            settings_screen,
            "SETTINGS_FILE",
            str(Path(temp_dir) / "settings.json"),
        )
        monkeypatch.setattr(
            SecretsManager,
            "instance",
            classmethod(lambda cls: secrets),
        )
        yield


@pytest.fixture(autouse=True)
def _cleanup_qt_top_level_widgets(request):
    """Keep Qt tests isolated instead of accumulating windows across modules."""
    yield
    if request.node.get_closest_marker("qt") is None or not _pyqt6_available():
        return

    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in tuple(app.topLevelWidgets()):
        widget.hide()
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
