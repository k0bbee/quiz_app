"""Render-only panels for course source health and topic coverage."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
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
        self.table.itemSelectionChanged.connect(self._render_selection)
        layout.addWidget(self.table, 1)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("courseSourceDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.excerpt = QTextBrowser()
        self.excerpt.setObjectName("courseSourceExcerpt")
        self.excerpt.setMaximumHeight(140)
        self.excerpt.setOpenExternalLinks(False)
        layout.addWidget(self.excerpt)
        self._view = None
        self._get_text = None

    def render(self, view, get_text) -> None:
        self._view = view
        self._get_text = get_text
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
        if view.sources:
            self.table.selectRow(0)
        else:
            self.detail_label.clear()
            self.excerpt.clear()

    def _render_selection(self) -> None:
        if self._view is None or self._get_text is None:
            return
        row = self.table.currentRow()
        if not 0 <= row < len(self._view.sources):
            self.detail_label.clear()
            self.excerpt.clear()
            return
        source = self._view.sources[row]
        get_text = self._get_text
        topics = "、".join(source.topic_titles) or get_text("未关联", "None")
        warning = source.warning or get_text("无", "None")
        self.detail_label.setText(get_text(
            f"{source.page_count or '—'} 页 · {source.word_count or '—'} 字 · "
            f"关联知识点：{topics}\n解析警告：{warning}",
            f"{source.page_count or '—'} pages · {source.word_count or '—'} words · "
            f"Topics: {', '.join(source.topic_titles) or 'None'}\n"
            f"Parse warning: {warning}",
        ))
        self.detail_label.setToolTip(source.path)
        self.excerpt.setPlainText(
            source.excerpt
            or get_text(
                "没有可预览的提取文本。",
                "No extracted text is available for preview.",
            )
        )


class CourseKnowledgePanel(QWidget):
    topic_action_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.status_label = QLabel()
        self.status_label.setObjectName("secondaryText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.table = _read_only_table(8)
        self.table.setObjectName("courseKnowledgeTable")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 8):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        self.table.cellClicked.connect(self._handle_cell_clicked)
        layout.addWidget(self.table, 1)
        self._view = None

    def render(self, view, get_text) -> None:
        self._view = view
        self.table.setHorizontalHeaderLabels([
            get_text("知识点", "Knowledge Point"),
            get_text("考试权重", "Exam Weight"),
            get_text("资料覆盖", "Sources"),
            get_text("题目数量", "Questions"),
            get_text("掌握度", "Mastery"),
            get_text("最近练习", "Last Practice"),
            get_text("状态", "Status"),
            get_text("下一步", "Next Action"),
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
                (
                    f"{topic.exam_weight}%"
                    if topic.exam_weight
                    else (
                        get_text("范围内", "Included")
                        if topic.in_exam_scope
                        else get_text("范围外", "Excluded")
                    )
                ),
                str(topic.source_count),
                str(topic.question_count),
                get_text("已掌握", "Mastered")
                if topic.mastery == "mastered"
                else topic.mastery,
                topic.recent_practice,
                _topic_status_text(topic.status, get_text),
                _topic_action_text(
                    topic.status,
                    get_text,
                    in_exam_scope=topic.in_exam_scope,
                ),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, topic.topic_id)
                self.table.setItem(row, column, item)

    def _handle_cell_clicked(self, row: int, column: int) -> None:
        if column != 7 or self._view is None:
            return
        if not 0 <= row < len(self._view.topics):
            return
        topic = self._view.topics[row]
        action = _topic_action(topic.status, in_exam_scope=topic.in_exam_scope)
        self.topic_action_requested.emit(topic.topic_id, action)


def _read_only_table(columns: int) -> QTableWidget:
    table = QTableWidget(0, columns)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


def _topic_status_text(status: str, get_text) -> str:
    return {
        "mastered": get_text("已掌握", "Mastered"),
        "weak": get_text("薄弱", "Weak"),
        "learning": get_text("学习中", "Learning"),
        "uncovered": get_text("尚未覆盖", "Uncovered"),
        "not_started": get_text("未开始", "Not started"),
    }.get(status, get_text("未开始", "Not started"))


def _topic_action(status: str, *, in_exam_scope: bool = True) -> str:
    if not in_exam_scope:
        return "view"
    return {
        "weak": "practice",
        "uncovered": "generate",
        "not_started": "practice",
        "learning": "practice",
        "mastered": "view",
    }.get(status, "view")


def _topic_action_text(status: str, get_text, *, in_exam_scope: bool = True) -> str:
    action = _topic_action(status, in_exam_scope=in_exam_scope)
    return {
        "practice": (
            get_text("强化", "Practice")
            if status == "weak"
            else get_text("开始学习", "Start")
            if status == "not_started"
            else get_text("继续学习", "Continue")
        ),
        "generate": get_text("补齐题目", "Add questions"),
        "view": get_text("查看", "View"),
    }[action]
