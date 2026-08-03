"""Language manager singleton with Qt signal support."""

import threading

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6 import sip


class LanguageManager(QObject):
    """Singleton managing the current display language across the app."""

    language_changed = pyqtSignal(str)  # "zh" or "en"

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        if LanguageManager._instance is not None:
            raise RuntimeError("Use LanguageManager.instance() instead of direct construction")
        super().__init__()
        self._current = "zh"  # default language
        LanguageManager._instance = self

    @classmethod
    def instance(cls) -> "LanguageManager":
        if cls._instance is not None:
            try:
                if sip.isdeleted(cls._instance):
                    cls._instance = None
            except (AttributeError, RuntimeError):
                cls._instance = None
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def current(self) -> str:
        return self._current

    @property
    def current_label(self) -> str:
        """Human-readable current language label."""
        return "中文" if self._current == "zh" else "English"

    def set_language(self, lang: str):
        """Set the language. Only emits signal on actual change."""
        if lang != self._current and lang in ("zh", "en"):
            self._current = lang
            self.language_changed.emit(lang)

    def toggle(self):
        """Switch between Chinese and English."""
        self.set_language("en" if self._current == "zh" else "zh")

    def get_text(self, zh_text: str, en_text: str) -> str:
        """Convenience: get the appropriate text based on current language."""
        return zh_text if self._current == "zh" else en_text
