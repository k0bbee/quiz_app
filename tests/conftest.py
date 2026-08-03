from __future__ import annotations

import importlib.util
import re
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest


_QT_IMPORT_PATTERNS = ("from PyQt6", "import PyQt6")
_QT_FILE_MARKER_PATTERN = re.compile(
    r"(?m)^\s*pytestmark\s*=\s*pytest\.mark\.qt\s*$"
)


def pytest_addoption(parser):
    group = parser.getgroup("quiz-app")
    group.addoption(
        "--run-full",
        action="store_true",
        default=False,
        help="run opt-in full workflow and large fixture tests",
    )
    group.addoption(
        "--run-copyright",
        action="store_true",
        default=False,
        help="collect local software-copyright material tests",
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
    return any(pattern in text for pattern in _QT_IMPORT_PATTERNS) or bool(
        _QT_FILE_MARKER_PATTERN.search(text)
    )


def _is_copyright_test_file(path_text: str) -> bool:
    return Path(path_text).name.startswith("test_copyright_")


def pytest_ignore_collect(collection_path, config):
    """Keep optional local workflows and unavailable Qt tests out of collection."""
    if _is_copyright_test_file(str(collection_path)) and not config.getoption(
        "--run-copyright"
    ):
        return True
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
        is_copyright = _is_copyright_test_file(str(item_path))
        if item.get_closest_marker("full") and not (
            config.getoption("--run-full")
            or (is_copyright and config.getoption("--run-copyright"))
        ):
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
def _ensure_qt_application(request):
    """Give every Qt test an application without relying on module order."""
    if request.node.get_closest_marker("qt") is None or not _pyqt6_available():
        yield None
        return

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _isolate_qt_settings_and_secrets(
    request,
    monkeypatch,
    _ensure_qt_application,
):
    """Prevent UI tests from touching real settings files or OS credentials."""
    if request.node.get_closest_marker("qt") is None or not _pyqt6_available():
        yield
        return

    from core.secrets_manager import SecretsManager
    from core.application_services import ApplicationServices
    from core.background_task_center import BackgroundTaskCenter
    from core.generation_draft_store import GenerationDraftStore
    from core.mastery_overrides import MasteryOverrideStore
    from core.progress_tracker import ProgressManager
    from core.quiz_snapshot_manager import QuizSnapshotManager
    from models.course_project import CourseProjectManager
    from models.past_exam import PastExamManager
    from models.question import QuestionBank
    from models.question_set import SetManager
    from ui.screens import settings_screen

    secrets = _InMemorySecrets()
    with tempfile.TemporaryDirectory(prefix="quiz-app-qt-test-") as temp_dir:
        root = Path(temp_dir)
        services = ApplicationServices(
            question_bank=QuestionBank(str(root / "questions")),
            set_manager=SetManager(str(root / "sets")),
            progress_manager=ProgressManager(str(root / "progress")),
            snapshot_manager=QuizSnapshotManager(str(root / "snapshots")),
            mastery_overrides=MasteryOverrideStore(root / "mastery.json"),
            course_manager=CourseProjectManager(str(root / "courses")),
            past_exam_manager=PastExamManager(root / "past-exams"),
            task_center=BackgroundTaskCenter(root / "tasks.json"),
            generation_draft_store=GenerationDraftStore(
                root / "generation-drafts.json"
            ),
        )
        monkeypatch.setattr(
            settings_screen,
            "SETTINGS_FILE",
            str(root / "settings.json"),
        )
        monkeypatch.setattr(
            ApplicationServices,
            "default",
            classmethod(lambda cls: services),
        )
        monkeypatch.setattr(
            SecretsManager,
            "instance",
            classmethod(lambda cls: secrets),
        )
        yield


@pytest.fixture(autouse=True)
def _cleanup_qt_top_level_widgets(request, _ensure_qt_application):
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
