"""Compact source evidence list with safe file navigation actions."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.source_navigation import (
    SourceLocation,
    format_source_location,
    resolve_source_location,
)
from ui.widgets.source_refs import format_source_refs


class SourceRefsPanel(QWidget):
    """Show source refs without turning every row into a button cluster."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._refs: list[dict] = []
        self._locations: list[SourceLocation | None] = []
        self._language = "zh"
        self._label = "来源"
        self._formatted_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.header_label = QLabel()
        self.header_label.setObjectName("sourcePanelHeader")
        layout.addWidget(self.header_label)
        self.source_list = QListWidget()
        self.source_list.setObjectName("sourcePanelList")
        self.source_list.setMaximumHeight(130)
        self.source_list.currentRowChanged.connect(self._update_action_state)
        layout.addWidget(self.source_list)

        actions = QHBoxLayout()
        actions.addStretch()
        self.open_btn = QPushButton()
        self.open_btn.setObjectName("secondaryButton")
        self.open_btn.clicked.connect(self.open_selected_source)
        actions.addWidget(self.open_btn)
        self.copy_btn = QPushButton()
        self.copy_btn.setObjectName("secondaryButton")
        self.copy_btn.clicked.connect(self.copy_selected_location)
        actions.addWidget(self.copy_btn)
        self.details_btn = QPushButton()
        self.details_btn.setObjectName("secondaryButton")
        self.details_btn.clicked.connect(self.show_selected_details)
        actions.addWidget(self.details_btn)
        layout.addLayout(actions)
        self._update_strings()
        self._update_action_state()

    def set_source_refs(
        self,
        source_refs,
        course_project=None,
        language: str = "zh",
        label: str | None = None,
        status: str | None = None,
    ) -> None:
        self._language = "zh" if language == "zh" else "en"
        self._label = label or ("来源" if self._language == "zh" else "Source Evidence")
        self._refs = [dict(ref) for ref in source_refs or [] if isinstance(ref, dict)]
        self._locations = [
            resolve_source_location(course_project, ref) for ref in self._refs
        ]
        self._formatted_text = format_source_refs(
            self._refs,
            label=self._label,
            status=status,
            language=self._language,
        )
        self.header_label.setText(format_source_refs(
            [], label=self._label, status=status, language=self._language
        ) or self._label)
        self.source_list.clear()
        for ref in self._refs:
            self.source_list.addItem(QListWidgetItem(self._item_text(ref)))
        self._update_strings()
        if self._refs:
            self.source_list.setCurrentRow(0)
        else:
            self._update_action_state()
        self.setVisible(bool(self._refs or status))

    def text(self) -> str:
        """Return the formatted text for lightweight callers and tests."""
        return self._formatted_text

    def _item_text(self, ref: dict) -> str:
        parts = [str(ref.get("source_file", "") or "").strip() or self._label]
        page = ref.get("page_or_slide")
        if page not in (None, ""):
            page_label = "页码/幻灯片" if self._language == "zh" else "page/slide"
            parts.append(f"{page_label} {page}")
        heading = str(ref.get("heading", "") or "").strip()
        if heading:
            parts.append(heading)
        return " · ".join(parts)

    def _selected(self) -> tuple[dict | None, SourceLocation | None]:
        row = self.source_list.currentRow()
        if row < 0 or row >= len(self._refs):
            return None, None
        return self._refs[row], self._locations[row]

    def _update_strings(self) -> None:
        zh = self._language == "zh"
        self.open_btn.setText("打开文件" if zh else "Open File")
        self.copy_btn.setText("复制位置" if zh else "Copy Location")
        self.details_btn.setText("查看定位" if zh else "View Location")

    def _update_action_state(self, *_args) -> None:
        ref, location = self._selected()
        self.open_btn.setEnabled(bool(location and location.exists))
        self.copy_btn.setEnabled(location is not None)
        self.details_btn.setEnabled(ref is not None)

    def copy_selected_location(self) -> None:
        _ref, location = self._selected()
        if location is None:
            return
        QApplication.clipboard().setText(format_source_location(location, self._language))

    def open_selected_source(self) -> None:
        _ref, location = self._selected()
        if location is None or not location.exists:
            return
        url = QUrl.fromLocalFile(str(location.path))
        if location.source_type == "pdf" and location.page_or_slide is not None:
            url.setFragment(f"page={location.page_or_slide}")
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "打开失败" if self._language == "zh" else "Open Failed",
                "系统无法打开该课程文件。" if self._language == "zh"
                else "The system could not open this course file.",
            )

    def show_selected_details(self) -> None:
        ref, location = self._selected()
        if ref is None:
            return
        details = format_source_refs(
            [ref], label=self._label, language=self._language
        )
        if location is not None:
            details += "\n\n" + format_source_location(location, self._language)
            if not location.exists:
                details += "\n" + (
                    "原文件已移动或删除。" if self._language == "zh"
                    else "The original file was moved or deleted."
                )
        QMessageBox.information(
            self,
            "来源定位" if self._language == "zh" else "Source Location",
            details,
        )
