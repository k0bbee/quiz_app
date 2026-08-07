"""Render-only panels for course source health and topic coverage."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QSplitter,
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

        self.table = _read_only_table(4)
        self.table.setObjectName("courseKnowledgeTable")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 58), (2, 64), (3, 96)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table.itemSelectionChanged.connect(self._render_detail)
        self.table.setMinimumWidth(240)

        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        detail_layout.setSpacing(8)
        self.detail_title = QLabel()
        self.detail_title.setObjectName("courseKnowledgeDetailTitle")
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        self.detail_summary = QLabel()
        self.detail_summary.setObjectName("courseKnowledgeDetailSummary")
        self.detail_summary.setWordWrap(True)
        detail_layout.addWidget(self.detail_summary)
        self.detail_action_btn = QPushButton()
        self.detail_action_btn.setObjectName("secondaryButton")
        self.detail_action_btn.clicked.connect(self._emit_detail_action)
        self.detail_action_btn.setEnabled(False)
        detail_layout.addWidget(self.detail_action_btn)
        detail_layout.addStretch(1)
        self.knowledge_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.knowledge_splitter.setChildrenCollapsible(False)
        self.knowledge_splitter.addWidget(self.table)
        self.knowledge_splitter.addWidget(detail_widget)
        self.knowledge_splitter.setStretchFactor(0, 3)
        self.knowledge_splitter.setStretchFactor(1, 2)
        self.knowledge_splitter.setSizes([360, 240])
        layout.addWidget(self.knowledge_splitter, 1)
        self._view = None
        self._selected_topic = None
        self._get_text = None

    def render(self, view, get_text) -> None:
        self._view = view
        self._get_text = get_text
        self.table.setHorizontalHeaderLabels([
            get_text("知识点", "Knowledge Point"),
            get_text("资料覆盖", "Sources"),
            get_text("题目数量", "Questions"),
            get_text("学习状态", "Learning Status"),
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
                str(topic.source_count),
                str(topic.question_count),
                _topic_table_status(topic, get_text),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, topic.topic_id)
                self.table.setItem(row, column, item)
        if view.topics:
            self.table.selectRow(0)
        else:
            self._clear_detail()

    def _render_detail(self) -> None:
        if self._view is None:
            return
        row = self.table.currentRow()
        if not 0 <= row < len(self._view.topics):
            self._clear_detail()
            return
        topic = self._view.topics[row]
        self._selected_topic = topic
        get_text = self._get_text
        self.detail_title.setText(topic.title)
        self.detail_summary.setText(get_text(
            f"考试范围：{'是' if topic.in_exam_scope else '否'} · "
            f"资料覆盖：{topic.source_count} · 题目：{topic.question_count}\n"
            f"历史表现：{_topic_mastery_text(topic, get_text)} · "
            f"最近练习：{topic.recent_practice} · "
            f"出题权重：{topic.generation_weight or '—'}%",
            f"Exam scope: {'Yes' if topic.in_exam_scope else 'No'} · "
            f"Sources: {topic.source_count} · Questions: {topic.question_count}\n"
            f"Historical performance: {_topic_mastery_text(topic, get_text)} · "
            f"Last practice: {topic.recent_practice} · "
            f"Generation weight: {topic.generation_weight or '—'}%",
        ))
        self.detail_action_btn.setText(_topic_action_text(
            topic.status,
            get_text,
            in_exam_scope=topic.in_exam_scope,
        ))
        self.detail_action_btn.setEnabled(True)

    def _clear_detail(self) -> None:
        self._selected_topic = None
        self.detail_title.clear()
        self.detail_summary.clear()
        self.detail_action_btn.setText(
            self._get_text("请选择知识点", "Select a knowledge point")
            if self._get_text is not None
            else ""
        )
        self.detail_action_btn.setEnabled(False)

    def _emit_detail_action(self) -> None:
        if self._selected_topic is None:
            return
        topic = self._selected_topic
        action = _topic_action(topic.status, in_exam_scope=topic.in_exam_scope)
        self.topic_action_requested.emit(self._selected_topic.topic_id, action)


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


def _topic_table_status(topic, get_text) -> str:
    status = _topic_status_text(topic.status, get_text)
    scope = get_text("范围内", "In scope") if topic.in_exam_scope else get_text("范围外", "Out of scope")
    return f"{status} · {scope}"


def _topic_mastery_text(topic, get_text) -> str:
    if topic.mastery == "mastered":
        return get_text("已掌握", "Mastered")
    return topic.mastery or get_text("未开始", "Not started")


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
