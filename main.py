"""Entry point for the AI课程刷题软件 application."""

import sys

from PyQt6.QtWidgets import QApplication

from config import APP_NAME, DEFAULT_SETTINGS, SETTINGS_FILE
from core.application_data_migration import ApplicationDataMigrator
from core.application_services import ApplicationServices
from ui.application_style import load_stylesheet
from ui.font_scale import normalize_font_scale
from ui.main_window import MainWindow
from utils.json_io import read_json


def main() -> None:
    app = QApplication(sys.argv)
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)

    settings = read_json(SETTINGS_FILE) or {}
    font_scale = normalize_font_scale(
        settings.get("font_scale", DEFAULT_SETTINGS["font_scale"])
    )
    load_stylesheet(app, font_scale=font_scale)

    services = ApplicationServices.default()
    migration_report = ApplicationDataMigrator(services).migrate()
    window = MainWindow(
        services=services,
        startup_migration_report=migration_report,
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
