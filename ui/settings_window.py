"""Independent application settings window."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

from config import APP_NAME_EN, APP_NAME_ZH
from core.language_manager import LanguageManager
from ui.screens.settings_screen import SettingsScreen


class SettingsWindow(QDialog):
    """Host the settings screen without replacing the active workspace."""

    def __init__(
        self,
        *,
        task_center=None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("settingsWindow")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumSize(820, 600)
        self.resize(1040, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.screen = SettingsScreen(
            task_center=task_center,
            parent=self,
        )
        layout.addWidget(self.screen)

        self.lang_manager = LanguageManager.instance()
        self.lang_manager.language_changed.connect(self._update_window_title)
        self._update_window_title()

    def show_settings(self, section: str = "") -> None:
        """Show one reusable settings window and optionally focus a section."""
        if section == "data":
            self.screen.show_data_management()
        elif section == "ai":
            self.screen.show_ai_settings()
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _update_window_title(self, _lang: str | None = None) -> None:
        self.setWindowTitle(
            self.lang_manager.get_text(
                f"{APP_NAME_ZH} - 设置",
                f"{APP_NAME_EN} - Settings",
            )
        )
