"""Question-set asset management panel used inside the library workspace."""

from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.language_manager import LanguageManager
from core.library_scope import LibraryAssetScope, LibraryScopeKind
from models.question_set import SetManager
from utils.constants import topic_label


class QuestionSetLibraryPanel(QWidget):
    """Browse and maintain saved question-set assets."""

    SET_ID_ROLE = Qt.ItemDataRole.UserRole

    export_mock_exam = pyqtSignal(str)
    export_mock_exams = pyqtSignal(list)
    regenerate_questions = pyqtSignal(str)
    sets_changed = pyqtSignal()

    def __init__(
        self,
        set_manager: SetManager,
        *,
        progress_manager=None,
        parent=None,
    ):
        super().__init__(parent)
        self.set_manager = set_manager
        self.progress_manager = progress_manager
        self.lang_manager = LanguageManager.instance()
        self._current_course_id = ""
        self._asset_scope: LibraryAssetScope | None = None
        self._all_sets = []
        self.search_debounce_timer = QTimer(self)
        self.search_debounce_timer.setSingleShot(True)
        self.search_debounce_timer.setInterval(250)
        self.search_debounce_timer.timeout.connect(self._render_sets)
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.helper_label = QLabel()
        self.helper_label.setObjectName("secondaryText")
        self.helper_label.setWordWrap(True)
        layout.addWidget(self.helper_label)

        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self.search_debounce_timer.start)
        layout.addWidget(self.search_input)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(8)

        self.set_list = QListWidget()
        self.set_list.setObjectName("questionSetLibraryList")
        self.set_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.set_list.currentItemChanged.connect(self._update_selection)
        self.set_list.itemSelectionChanged.connect(self._update_selection)
        self.content_splitter.addWidget(self.set_list)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        self.info_label = QLabel()
        self.info_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.info_label.setWordWrap(True)
        detail_layout.addWidget(self.info_label)
        detail_layout.addStretch(1)

        action_layout = QHBoxLayout()
        self.rename_btn = self._action_button("secondaryButton")
        self.export_btn = self._action_button("secondaryButton")
        self.regenerate_btn = self._action_button("secondaryButton")
        self.delete_btn = self._action_button("dangerButton")
        self.rename_btn.clicked.connect(self._rename_selected)
        self.export_btn.clicked.connect(self._export_selected)
        self.regenerate_btn.clicked.connect(self._regenerate_selected)
        self.delete_btn.clicked.connect(self._delete_selected)
        for button in (
            self.rename_btn,
            self.export_btn,
            self.regenerate_btn,
            self.delete_btn,
        ):
            action_layout.addWidget(button)
        detail_layout.addLayout(action_layout)
        self.content_splitter.addWidget(detail)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([680, 440])
        layout.addWidget(self.content_splitter, 1)
        self._on_language_changed()

    def _action_button(self, object_name: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName(object_name)
        button.setMinimumHeight(38)
        button.setEnabled(False)
        return button

    def _on_language_changed(self, _lang=None) -> None:
        gm = self.lang_manager.get_text
        self.helper_label.setText(gm(
            "题目集是可复用的练习方案。这里负责命名、导出、重新生成和删除；开始学习请前往“学习”。",
            "Question sets are reusable practice presets. Manage, export, regenerate, or delete them here; start sessions from Study.",
        ))
        self.search_input.setPlaceholderText(gm(
            "搜索题目集、知识点",
            "Search question sets or topics",
        ))
        self.rename_btn.setText(gm("重命名", "Rename"))
        self.export_btn.setText(gm("导出模拟卷", "Export Mock Exam"))
        self.regenerate_btn.setText(gm("重新生成", "Regenerate"))
        self.delete_btn.setText(gm("删除", "Delete"))
        self.refresh()

    def set_current_course(self, course_id: str | None) -> None:
        course_id = str(course_id or "").strip()
        scope = LibraryAssetScope.course(course_id) if course_id else None
        self.set_asset_scope(scope)

    def set_asset_scope(self, scope: LibraryAssetScope | None) -> None:
        if scope == self._asset_scope:
            return
        self._asset_scope = scope
        self._current_course_id = (
            scope.course_id
            if scope is not None
            and scope.kind is LibraryScopeKind.COURSE
            else ""
        )
        self.refresh()

    def refresh(self) -> None:
        selected_ids = set(self._selected_set_ids())
        self._all_sets = [
            question_set
            for question_set in self.set_manager.load_all()
            if self._matches_current_course(question_set)
        ]
        self._render_sets(selected_ids)

    def _render_sets(self, selected_ids=None) -> None:
        if isinstance(selected_ids, bool) or selected_ids is None:
            selected_ids = set(self._selected_set_ids())
        else:
            selected_ids = set(selected_ids)
        query = self.search_input.text().strip().lower()
        self.set_list.clear()
        lang = self.lang_manager.current
        gm = self.lang_manager.get_text
        for question_set in self._all_sets:
            haystack = " ".join([
                question_set.get_title("zh"),
                question_set.get_title("en"),
                question_set.get_description("zh"),
                question_set.get_description("en"),
                *[str(topic) for topic in question_set.topics],
                *[topic_label(topic, lang) for topic in question_set.topics],
            ]).lower()
            if query and query not in haystack:
                continue
            empty_marker = gm("空题集 · ", "Empty · ") if not question_set.questions else ""
            item = QListWidgetItem(
                f"{question_set.get_title(lang)}  "
                f"[{empty_marker}{question_set.question_count} {gm('题', 'questions')}]"
            )
            item.setData(self.SET_ID_ROLE, question_set.set_id)
            self.set_list.addItem(item)
            if question_set.set_id in selected_ids:
                item.setSelected(True)
        if self.set_list.count() == 1:
            self.set_list.setCurrentRow(0)
        self._update_selection()

    def _update_selection(self, *_args) -> None:
        selected_ids = self._selected_set_ids()
        selected_sets = [
            self.set_manager.get(set_id) for set_id in selected_ids
        ]
        selected_sets = [
            question_set
            for question_set in selected_sets
            if question_set is not None
        ]
        single = len(selected_sets) == 1
        all_populated = bool(selected_sets) and all(
            question_set.question_count > 0
            for question_set in selected_sets
        )
        regeneratable = (
            single and self._is_regeneratable(selected_sets[0])
        )
        self.rename_btn.setEnabled(single)
        self.export_btn.setEnabled(all_populated)
        self.regenerate_btn.setEnabled(regeneratable)
        self.regenerate_btn.setVisible(regeneratable)
        self.delete_btn.setEnabled(bool(selected_sets))
        if not selected_sets:
            self.info_label.setText(self.lang_manager.get_text(
                "请选择一个题目集查看详情。",
                "Select a question set to view its details.",
            ))
            return
        if len(selected_sets) > 1:
            total = sum(item.question_count for item in selected_sets)
            self.info_label.setText(self.lang_manager.get_text(
                f"已选择 {len(selected_sets)} 个题目集，共 {total} 题。",
                f"{len(selected_sets)} question sets selected, {total} questions total.",
            ))
            return
        question_set = selected_sets[0]
        topics = "、".join(
            topic_label(topic, self.lang_manager.current)
            for topic in question_set.topics
        )
        self.info_label.setText(
            f"<b>{question_set.get_title(self.lang_manager.current)}</b><br>"
            f"{question_set.get_description(self.lang_manager.current)}<br><br>"
            f"{self.lang_manager.get_text('题目数', 'Questions')}: "
            f"{question_set.question_count}<br>"
            f"{self.lang_manager.get_text('知识点', 'Topics')}: "
            f"{topics or self.lang_manager.get_text('未标注', 'Unspecified')}"
        )

    def _rename_selected(self) -> None:
        selected_ids = self._selected_set_ids()
        if len(selected_ids) != 1:
            return
        question_set = self.set_manager.get(selected_ids[0])
        if question_set is None:
            return
        new_title, accepted = QInputDialog.getText(
            self,
            self.lang_manager.get_text(
                "重命名题目集",
                "Rename Question Set",
            ),
            self.lang_manager.get_text(
                "题目集名称：",
                "Question set name:",
            ),
            text=question_set.get_title(self.lang_manager.current),
        )
        new_title = new_title.strip()
        if not accepted or not new_title:
            return
        question_set.title = {"zh": new_title, "en": new_title}
        question_set.metadata["updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()
        question_set.metadata["renamed_by_user"] = True
        if self.set_manager.save(question_set):
            self.refresh()
            self._select_ids([question_set.set_id])
            self.sets_changed.emit()

    def _export_selected(self) -> None:
        selected_ids = self._selected_set_ids()
        selected_sets = [
            self.set_manager.get(set_id) for set_id in selected_ids
        ]
        if not selected_sets or any(
            question_set is None or not question_set.questions
            for question_set in selected_sets
        ):
            return
        if len(selected_ids) == 1:
            self.export_mock_exam.emit(selected_ids[0])
        else:
            self.export_mock_exams.emit(selected_ids)

    def _regenerate_selected(self) -> None:
        selected_ids = self._selected_set_ids()
        if len(selected_ids) != 1:
            return
        question_set = self.set_manager.get(selected_ids[0])
        if self._is_regeneratable(question_set):
            self.regenerate_questions.emit(selected_ids[0])

    def _delete_selected(self) -> None:
        selected_ids = self._selected_set_ids()
        if not selected_ids:
            return
        reply = QMessageBox.warning(
            self,
            self.lang_manager.get_text("删除题目集", "Delete Question Sets"),
            self.lang_manager.get_text(
                f"删除选中的 {len(selected_ids)} 个题目集？题目本身不会被删除。",
                f"Delete {len(selected_ids)} selected question set(s)? Questions are kept.",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted = sum(
            1 for set_id in selected_ids if self.set_manager.delete(set_id)
        )
        if deleted:
            self.refresh()
            self.sets_changed.emit()

    def _selected_set_ids(self) -> list[str]:
        return list(dict.fromkeys(
            str(item.data(self.SET_ID_ROLE) or "")
            for item in self.set_list.selectedItems()
            if item.data(self.SET_ID_ROLE)
        ))

    def _select_ids(self, set_ids) -> None:
        wanted = set(set_ids)
        for row in range(self.set_list.count()):
            item = self.set_list.item(row)
            item.setSelected(item.data(self.SET_ID_ROLE) in wanted)

    def _matches_current_course(self, question_set) -> bool:
        if self._asset_scope is not None:
            return self._asset_scope.matches(question_set)
        source_course_id = str(
            (question_set.metadata or {}).get("course_id", "") or ""
        )
        return (
            not source_course_id
            or not self._current_course_id
            or source_course_id == self._current_course_id
        )

    @staticmethod
    def _is_regeneratable(question_set) -> bool:
        source = str(
            (question_set.metadata or {}).get("source", "") or ""
        ).strip().lower() if question_set is not None else ""
        return source in {"ai_generated", "ai_regenerated"}
