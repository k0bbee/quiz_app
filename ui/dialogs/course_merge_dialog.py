"""Review source courses before merging them into one retained course."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from core.course_asset_lifecycle import CourseAssetImpact
from core.language_manager import LanguageManager


class CourseMergeDialog(QDialog):
    """Choose source courses while keeping the selected target identity."""

    def __init__(self, target_course, courses, parent=None, *, impacts=None):
        super().__init__(parent)
        self.target_course = target_course
        self.source_courses = [
            course
            for course in courses
            if course.course_id != target_course.course_id
        ]
        self.impacts: dict[str, CourseAssetImpact] = {
            str(course_id): impact
            for course_id, impact in dict(impacts or {}).items()
            if isinstance(impact, CourseAssetImpact)
        }
        self.lang_manager = LanguageManager.instance()
        self._setup_ui()
        self._on_language_changed(self.lang_manager.current)
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self) -> None:
        self.resize(600, 520)
        self.setMinimumSize(480, 400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.heading_label = QLabel()
        self.heading_label.setObjectName("dialogTitle")
        layout.addWidget(self.heading_label)

        self.target_label = QLabel()
        self.target_label.setObjectName("courseMergeTargetLabel")
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)

        self.help_label = QLabel()
        self.help_label.setObjectName("secondaryText")
        self.help_label.setWordWrap(True)
        layout.addWidget(self.help_label)

        self.source_list = QListWidget()
        for course in self.source_courses:
            item = QListWidgetItem(course.title)
            item.setData(Qt.ItemDataRole.UserRole, course.course_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.source_list.addItem(item)
        self.source_list.itemChanged.connect(lambda _item: self._update_selection())
        layout.addWidget(self.source_list, 1)

        self.count_label = QLabel()
        self.count_label.setObjectName("secondaryText")
        layout.addWidget(self.count_label)

        self.impact_label = QLabel()
        self.impact_label.setObjectName("courseMergeImpact")
        self.impact_label.setWordWrap(True)
        layout.addWidget(self.impact_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)
        self.merge_btn = QPushButton()
        self.merge_btn.setObjectName("primaryButton")
        self.merge_btn.clicked.connect(self.accept)
        footer.addWidget(self.merge_btn)
        layout.addLayout(footer)
        self._update_selection()

    def selected_source_ids(self) -> list[str]:
        return [
            str(self.source_list.item(row).data(Qt.ItemDataRole.UserRole) or "")
            for row in range(self.source_list.count())
            if self.source_list.item(row).checkState() == Qt.CheckState.Checked
        ]

    def _update_selection(self) -> None:
        count = len(self.selected_source_ids())
        self.merge_btn.setEnabled(count > 0)
        self.count_label.setText(self.lang_manager.get_text(
            f"已选择 {count} 门来源课程",
            f"{count} source course(s) selected",
        ))
        self._update_impact_text()

    def _update_impact_text(self) -> None:
        selected_ids = set(self.selected_source_ids())
        if not selected_ids:
            self.impact_label.setText(self.lang_manager.get_text(
                "勾选来源课程后显示迁移范围。",
                "Select source courses to preview the migration scope.",
            ))
            return

        impacts = [
            self.impacts[course_id]
            for course_id in selected_ids
            if course_id in self.impacts
        ]

        def unique_count(attribute: str) -> int:
            return len({
                item_id
                for impact in impacts
                for item_id in getattr(impact, attribute, ())
            })

        question_count = unique_count("question_ids")
        set_count = unique_count("affected_set_ids")
        history_count = unique_count("progress_ids")
        draft_count = (
            unique_count("draft_progress_ids")
            + unique_count("snapshot_ids")
        )
        past_exam_count = unique_count("past_exam_ids")
        event_count = unique_count("current_event_pack_ids")
        target_title = self.target_course.title
        self.impact_label.setText(self.lang_manager.get_text(
            (
                f"并入“{target_title}”\n"
                f"题目：{question_count}　题集：{set_count}　完成历史：{history_count}\n"
                f"未完成草稿：{draft_count}　历史真题：{past_exam_count}　热点材料：{event_count}\n"
                "题目和题集迁移到保留课程；未完成草稿随完整迁移的题目继续保留。"
                "历史发生时的课程身份保持不变，重练仍取决于迁移后的实时题库。"
            ),
            (
                f"Merge into '{target_title}'\n"
                f"Questions: {question_count}  Sets: {set_count}  "
                f"Completed history: {history_count}\n"
                f"Unfinished drafts: {draft_count}  Historical exams: {past_exam_count}  "
                f"Current-event packs: {event_count}\n"
                "Questions and sets move to the retained course; unfinished drafts remain "
                "when their questions migrate completely. Historical course identity remains "
                "unchanged, while retry availability follows the migrated live question bank."
            ),
        ))

    def _on_language_changed(self, _lang) -> None:
        gm = self.lang_manager.get_text
        self.setWindowTitle(gm("合并课程", "Merge Courses"))
        self.heading_label.setText(gm("合并课程", "Merge Courses"))
        self.target_label.setText(gm(
            f"保留课程：{self.target_course.title}",
            f"Retained course: {self.target_course.title}",
        ))
        self.help_label.setText(gm(
            "勾选要并入的课程。题目、题集、掌握状态、热点材料和历史真题会迁移到保留课程；来源课程只在全部保存成功后删除。历史真题需重新分析。",
            "Select courses to absorb. Questions, sets, mastery, current-event materials, and historical exams move to the retained course. Sources are deleted only after every save succeeds. Historical exams require re-analysis.",
        ))
        self.cancel_btn.setText(gm("取消", "Cancel"))
        self.merge_btn.setText(gm("合并所选课程", "Merge Selected Courses"))
        self._update_selection()
