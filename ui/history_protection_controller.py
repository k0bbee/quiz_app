"""Coordinate startup migration failures and history-sensitive navigation."""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from core.application_data_migration import ApplicationDataMigrator


class HistoryProtectionController:
    """Keep legacy-history protection state out of the application shell."""

    def __init__(self, host) -> None:
        self._host = host

    def show_startup_warning(self) -> None:
        host = self._host
        if not host._history_protection_blocked:
            return
        reply = QMessageBox.warning(
            host,
            host.lang_manager.get_text(
                "旧历史保护未完成",
                "Legacy History Protection Incomplete",
            ),
            self.message(),
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Retry,
        )
        if reply == QMessageBox.StandardButton.Retry:
            self.retry()

    def message(self) -> str:
        host = self._host
        report = host.startup_migration_report
        failed_count = len(tuple(getattr(report, "failed_progress_ids", ()) or ()))
        detail = "\n".join(
            str(error)
            for error in tuple(getattr(report, "errors", ()) or ())[:3]
        )
        suffix = f"\n\n{detail}" if detail else ""
        return host.lang_manager.get_text(
            f"{failed_count} 条旧练习记录暂未完成保护。请先检查数据目录权限，"
            f"为避免历史答案失真，课程、题库维护以及数据导入/重置"
            f"已暂时停用。修复后可重试。{suffix}",
            f"{failed_count} legacy practice record(s) could not be protected. "
            f"To preserve historical answers, course, question-bank and "
            f"maintenance plus data import/reset are temporarily "
            f"disabled. Fix the data-directory issue, then retry.{suffix}",
        )

    def set_blocked(self, blocked: bool, report=None) -> None:
        host = self._host
        if report is not None:
            host.startup_migration_report = report
        host._history_protection_blocked = bool(blocked)
        host.settings_screen.set_history_protection_blocked(
            host._history_protection_blocked,
            self.message() if host._history_protection_blocked else "",
        )

    def retry(self) -> bool:
        host = self._host
        report = ApplicationDataMigrator(host.services).migrate()
        blocked = bool(getattr(report, "has_failures", False))
        self.set_blocked(blocked, report)
        if blocked:
            QMessageBox.warning(
                host,
                host.lang_manager.get_text(
                    "仍未完成保护",
                    "Protection Still Incomplete",
                ),
                self.message(),
            )
            return False
        QMessageBox.information(
            host,
            host.lang_manager.get_text(
                "历史保护已完成",
                "History Protection Complete",
            ),
            host.lang_manager.get_text(
                "旧历史已完成保护，课程与资料维护功能已恢复。",
                "Legacy history is now protected. Course and library "
                "maintenance are available again.",
            ),
        )
        return True

    def confirm_navigation(self, screen_index: int) -> bool:
        host = self._host
        if not host._history_protection_blocked or screen_index not in {
            host.SCREEN_COURSES,
            host.SCREEN_QUESTION_BANK,
        }:
            return True
        reply = QMessageBox.warning(
            host,
            host.lang_manager.get_text(
                "数据保护模式",
                "Data Protection Mode",
            ),
            self.message(),
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Retry,
        )
        return reply == QMessageBox.StandardButton.Retry and self.retry()
