"""Visible history and recovery controls for persisted background tasks."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.background_task_presenter import build_task_center_view


class BackgroundTaskDialog(QDialog):
    """Show attention tasks first while keeping completed history reachable."""

    TASK_ID_ROLE = int(Qt.ItemDataRole.UserRole)

    def __init__(self, task_center, *, language: str, parent=None):
        super().__init__(parent)
        self.task_center = task_center
        self.language = "zh" if language == "zh" else "en"
        self.requested_task_id = ""
        self._setup_ui()
        self._translate_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        self.resize(820, 520)
        self.setMinimumSize(640, 400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        heading_row = QHBoxLayout()
        self.heading_label = QLabel()
        self.heading_label.setObjectName("dialogTitle")
        heading_row.addWidget(self.heading_label)
        heading_row.addStretch(1)
        self.attention_only_btn = QPushButton()
        self.attention_only_btn.setObjectName("secondaryButton")
        self.attention_only_btn.setCheckable(True)
        self.attention_only_btn.setChecked(True)
        self.attention_only_btn.toggled.connect(lambda _checked: self.refresh())
        heading_row.addWidget(self.attention_only_btn)
        layout.addLayout(heading_row)

        self.help_label = QLabel()
        self.help_label.setObjectName("secondaryText")
        self.help_label.setWordWrap(True)
        layout.addWidget(self.help_label)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("mutedLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        self.task_list = QTreeWidget()
        self.task_list.setRootIsDecorated(False)
        self.task_list.setAlternatingRowColors(True)
        self.task_list.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.task_list.itemSelectionChanged.connect(self._update_selection)
        self.task_list.itemDoubleClicked.connect(lambda _item, _column: self._open_selected())
        layout.addWidget(self.task_list, 1)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("secondaryText")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.detail_label)

        footer = QHBoxLayout()
        self.cancel_task_btn = QPushButton()
        self.cancel_task_btn.setObjectName("secondaryButton")
        self.cancel_task_btn.clicked.connect(self._cancel_selected)
        footer.addWidget(self.cancel_task_btn)
        self.dismiss_btn = QPushButton()
        self.dismiss_btn.setObjectName("secondaryButton")
        self.dismiss_btn.clicked.connect(self._dismiss_selected)
        footer.addWidget(self.dismiss_btn)
        self.open_task_btn = QPushButton()
        self.open_task_btn.setObjectName("secondaryButton")
        self.open_task_btn.clicked.connect(self._open_selected)
        footer.addWidget(self.open_task_btn)
        footer.addStretch(1)
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("primaryButton")
        self.close_btn.clicked.connect(self.accept)
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)

    def _translate_ui(self) -> None:
        zh = self.language == "zh"
        self.setWindowTitle("后台任务" if zh else "Background Tasks")
        self.heading_label.setText("后台任务" if zh else "Background Tasks")
        self.help_label.setText(
            "这里汇总耗时操作。失败或中断的任务会优先显示；切换到全部记录可查看已完成任务。"
            if zh
            else "Long-running operations appear here. Failed and interrupted tasks are prioritized; show all to review completed history."
        )
        self.attention_only_btn.setText("只看需处理" if zh else "Attention Only")
        self.task_list.setHeaderLabels(
            ["任务", "类型", "状态", "进度", "更新时间"]
            if zh
            else ["Task", "Type", "Status", "Progress", "Updated"]
        )
        self.cancel_task_btn.setText("取消任务" if zh else "Cancel Task")
        self.dismiss_btn.setText("移除记录" if zh else "Dismiss")
        self.open_task_btn.setText("打开任务页面" if zh else "Open Task Page")
        self.close_btn.setText("关闭" if zh else "Close")

    def refresh(self) -> None:
        selected_id = self._selected_task_id()
        view = build_task_center_view(
            self.task_center.snapshots(),
            language=self.language,
            attention_only=self.attention_only_btn.isChecked(),
        )
        self.task_list.clear()
        selected_item = None
        for task in view.items:
            item = QTreeWidgetItem(
                [
                    task.title,
                    task.kind_text,
                    task.status_text,
                    task.progress_text,
                    task.updated_at,
                ]
            )
            item.setData(0, self.TASK_ID_ROLE, task.task_id)
            item.setData(0, self.TASK_ID_ROLE + 1, task.detail_text)
            item.setData(0, self.TASK_ID_ROLE + 2, task.can_cancel)
            item.setData(0, self.TASK_ID_ROLE + 3, task.can_dismiss)
            item.setData(0, self.TASK_ID_ROLE + 4, task.can_open)
            self.task_list.addTopLevelItem(item)
            if task.task_id == selected_id:
                selected_item = item
        self.task_list.resizeColumnToContents(0)
        self.task_list.resizeColumnToContents(1)
        self.task_list.resizeColumnToContents(2)
        self.task_list.resizeColumnToContents(3)
        self.empty_label.setText(view.empty_text)
        self.empty_label.setVisible(not view.items)
        self.task_list.setVisible(bool(view.items))
        if selected_item is not None:
            self.task_list.setCurrentItem(selected_item)
        elif self.task_list.topLevelItemCount():
            self.task_list.setCurrentItem(self.task_list.topLevelItem(0))
        self._update_selection()

    def _selected_task_id(self) -> str:
        item = self.task_list.currentItem()
        return str(item.data(0, self.TASK_ID_ROLE) or "") if item else ""

    def _update_selection(self) -> None:
        item = self.task_list.currentItem()
        if item is None:
            self.detail_label.clear()
            self.cancel_task_btn.setEnabled(False)
            self.dismiss_btn.setEnabled(False)
            self.open_task_btn.setEnabled(False)
            return
        self.detail_label.setText(str(item.data(0, self.TASK_ID_ROLE + 1) or ""))
        self.cancel_task_btn.setEnabled(bool(item.data(0, self.TASK_ID_ROLE + 2)))
        self.dismiss_btn.setEnabled(bool(item.data(0, self.TASK_ID_ROLE + 3)))
        self.open_task_btn.setEnabled(bool(item.data(0, self.TASK_ID_ROLE + 4)))

    def _open_selected(self) -> None:
        item = self.task_list.currentItem()
        if item is None or not bool(item.data(0, self.TASK_ID_ROLE + 4)):
            return
        self.requested_task_id = self._selected_task_id()
        if self.requested_task_id:
            self.accept()

    def _cancel_selected(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        try:
            self.task_center.request_cancel(task_id)
        except (KeyError, OSError, ValueError) as exc:
            self._show_error(exc)
        self.refresh()

    def _dismiss_selected(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        try:
            self.task_center.dismiss(task_id)
        except (KeyError, OSError, ValueError) as exc:
            self._show_error(exc)
        self.refresh()

    def _show_error(self, error: Exception) -> None:
        QMessageBox.warning(
            self,
            "操作失败" if self.language == "zh" else "Action Failed",
            str(error),
        )
