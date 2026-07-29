"""Render-only panels for course source health and topic coverage."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class CourseSourcesPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.status_label = QLabel()
        self.status_label.setObjectName("secondaryText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.table = _read_only_table(4)
        self.table.setObjectName("courseSourcesTable")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        layout.addWidget(self.table, 1)

    def render(self, view, get_text) -> None:
        self.table.setHorizontalHeaderLabels([
            get_text("资料", "Source"),
            get_text("类型", "Type"),
            get_text("页数", "Pages"),
            get_text("解析状态", "Parse Status"),
        ])
        self.status_label.setText(
            get_text(
                f"{view.document_count} 份资料 · "
                f"{view.document_count - view.warning_count} 份完整 · "
                f"{view.warning_count} 份需关注",
                f"{view.document_count} sources · "
                f"{view.document_count - view.warning_count} ready · "
                f"{view.warning_count} need attention",
            )
        )
        self.table.setRowCount(len(view.sources))
        for row, source in enumerate(view.sources):
            status = get_text("完整", "Ready")
            if source.warning:
                status = get_text("需关注", "Needs attention")
            values = (
                source.name,
                source.extension.lstrip(".").upper() or "—",
                str(source.page_count) if source.page_count else "—",
                status,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if source.warning:
                    item.setToolTip(source.warning)
                self.table.setItem(row, column, item)


class CourseKnowledgePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.status_label = QLabel()
        self.status_label.setObjectName("secondaryText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.table = _read_only_table(4)
        self.table.setObjectName("courseKnowledgeTable")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        layout.addWidget(self.table, 1)

    def render(self, view, get_text) -> None:
        self.table.setHorizontalHeaderLabels([
            get_text("知识点", "Knowledge Point"),
            get_text("考试范围", "Exam Scope"),
            get_text("资料覆盖", "Sources"),
            get_text("题目数量", "Questions"),
        ])
        self.status_label.setText(
            get_text(
                f"考试范围 {view.exam_topic_count} 个 · "
                f"已有题目 {view.covered_exam_topic_count} 个 · "
                f"尚未覆盖 {view.uncovered_exam_topic_count} 个",
                f"{view.exam_topic_count} in exam scope · "
                f"{view.covered_exam_topic_count} with questions · "
                f"{view.uncovered_exam_topic_count} uncovered",
            )
        )
        self.table.setRowCount(len(view.topics))
        for row, topic in enumerate(view.topics):
            values = (
                topic.title,
                get_text("范围内", "Included")
                if topic.in_exam_scope
                else get_text("范围外", "Excluded"),
                str(topic.source_count),
                str(topic.question_count),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, topic.topic_id)
                self.table.setItem(row, column, item)


def _read_only_table(columns: int) -> QTableWidget:
    table = QTableWidget(0, columns)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table
