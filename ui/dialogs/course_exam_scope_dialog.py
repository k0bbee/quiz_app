"""Text-only editor for one course's exam scope."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from core.language_manager import LanguageManager


class CourseExamScopeDialog(QDialog):
    """Choose all course topics or an explicit stable-topic subset."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.topics = list(getattr(project, "topics", []) or [])
        self.lang_manager = LanguageManager.instance()
        self._setup_ui()
        self._restore_scope()
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self._on_language_changed(self.lang_manager.current)

    def _setup_ui(self) -> None:
        self.resize(560, 520)
        self.setMinimumSize(460, 400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.heading_label = QLabel()
        self.heading_label.setObjectName("dialogTitle")
        layout.addWidget(self.heading_label)

        self.help_label = QLabel()
        self.help_label.setObjectName("secondaryText")
        self.help_label.setWordWrap(True)
        layout.addWidget(self.help_label)

        self.all_radio = QRadioButton()
        self.selected_radio = QRadioButton()
        self.all_radio.toggled.connect(self._on_mode_changed)
        self.selected_radio.toggled.connect(self._on_mode_changed)
        layout.addWidget(self.all_radio)
        layout.addWidget(self.selected_radio)

        selection_row = QHBoxLayout()
        self.select_all_btn = QPushButton()
        self.select_all_btn.setObjectName("secondaryButton")
        self.select_all_btn.clicked.connect(lambda: self._set_all_topics(True))
        selection_row.addWidget(self.select_all_btn)
        self.clear_btn = QPushButton()
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.clicked.connect(lambda: self._set_all_topics(False))
        selection_row.addWidget(self.clear_btn)
        selection_row.addStretch(1)
        self.count_label = QLabel()
        self.count_label.setObjectName("secondaryText")
        selection_row.addWidget(self.count_label)
        layout.addLayout(selection_row)

        self.topic_list = QListWidget()
        for topic in self.topics:
            item = QListWidgetItem(str(getattr(topic, "title", "") or topic.topic_id))
            item.setData(Qt.ItemDataRole.UserRole, topic.topic_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.topic_list.addItem(item)
        self.topic_list.itemChanged.connect(lambda _item: self._update_count())
        layout.addWidget(self.topic_list, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)
        self.save_btn = QPushButton()
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._accept_scope)
        footer.addWidget(self.save_btn)
        layout.addLayout(footer)

    def _restore_scope(self) -> None:
        selected_ids = set(getattr(self.project, "exam_scope_topic_ids", []) or [])
        selected_mode = getattr(self.project, "exam_scope_mode", "all") == "selected"
        for row in range(self.topic_list.count()):
            item = self.topic_list.item(row)
            checked = item.data(Qt.ItemDataRole.UserRole) in selected_ids if selected_mode else True
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.selected_radio.setChecked(selected_mode)
        self.all_radio.setChecked(not selected_mode)
        self._on_mode_changed()

    def _on_language_changed(self, _lang) -> None:
        gm = self.lang_manager.get_text
        self.setWindowTitle(gm("考试范围", "Exam Scope"))
        self.heading_label.setText(gm(
            f"{self.project.title} · 考试范围",
            f"{self.project.title} · Exam Scope",
        ))
        self.help_label.setText(gm(
            "范围会影响新题生成、真题预测和今日学习建议，不会删除已有题目或学习记录。",
            "Scope affects new generation, historical-exam prediction, and today's plan. Existing questions and progress are not deleted.",
        ))
        self.all_radio.setText(gm("全部知识点", "All topics"))
        self.selected_radio.setText(gm("指定知识点", "Selected topics"))
        self.select_all_btn.setText(gm("全选", "Select All"))
        self.clear_btn.setText(gm("清空", "Clear"))
        self.cancel_btn.setText(gm("取消", "Cancel"))
        self.save_btn.setText(gm("保存范围", "Save Scope"))
        self._update_count()

    def _on_mode_changed(self) -> None:
        editable = self.selected_radio.isChecked()
        self.topic_list.setEnabled(editable)
        self.select_all_btn.setEnabled(editable)
        self.clear_btn.setEnabled(editable)
        self._update_count()

    def _set_all_topics(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.topic_list.count()):
            self.topic_list.item(row).setCheckState(state)
        self._update_count()

    def _selected_topic_ids(self) -> list[str]:
        return [
            str(self.topic_list.item(row).data(Qt.ItemDataRole.UserRole) or "")
            for row in range(self.topic_list.count())
            if self.topic_list.item(row).checkState() == Qt.CheckState.Checked
        ]

    def _update_count(self) -> None:
        if not hasattr(self, "count_label"):
            return
        selected = len(self.topics) if self.all_radio.isChecked() else len(self._selected_topic_ids())
        self.count_label.setText(f"{selected} / {len(self.topics)}")

    def scope(self) -> tuple[str, list[str]]:
        if self.all_radio.isChecked():
            return "all", []
        return "selected", self._selected_topic_ids()

    def _accept_scope(self) -> None:
        mode, topic_ids = self.scope()
        if mode == "selected" and self.topics and not topic_ids:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("范围为空", "Empty Scope"),
                self.lang_manager.get_text(
                    "指定范围至少需要选择一个知识点。",
                    "Select at least one topic for a selected scope.",
                ),
            )
            return
        self.accept()
