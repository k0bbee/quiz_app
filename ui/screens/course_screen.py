"""Course project screen — import materials and manage active course context."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QSplitter, QGroupBox, QProgressBar, QInputDialog, QTextBrowser,
    QButtonGroup, QDialog, QRadioButton, QMenu, QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from core.course_initializer import CourseInitializer
from core.course_hub_presenter import build_course_hub_view
from core.course_parse_checkpoint import CourseParseCheckpointStore
from core.course_asset_lifecycle import (
    CourseRemovalMode,
    analyze_course_asset_impact,
    remove_course_assets,
)
from core.background_task import BackgroundTaskCancelled, TaskControl, TaskProgress
from core.background_task_bridge import BackgroundTaskBridge
from core.ocr_runtime import OCR_REMEDIATION
from core.topic_identity_migration import TopicIdentityRepairReport, repair_question_topic_identities
from models.course_project import CourseProjectManager
from core.language_manager import LanguageManager
from config import COURSE_CHECKPOINTS_DIR, SETTINGS_FILE
from ui.dialogs.course_exam_scope_dialog import CourseExamScopeDialog
from ui.widgets.course_hub_panels import (
    CourseKnowledgePanel,
    CourseSourcesPanel,
)
from utils.json_io import read_json


def _contains_ocr_warning(warnings) -> bool:
    return any(
        "ocr" in str(warning).lower() or "tesseract" in str(warning).lower()
        for warning in warnings
    )


class CourseScreen(QWidget):
    """Import folders of course files and choose the active course project."""

    current_course_changed = pyqtSignal()
    course_topic_action_requested = pyqtSignal(str, str, str)
    view_course_library_requested = pyqtSignal(str)
    course_import_started = pyqtSignal()
    course_import_progressed = pyqtSignal(object)
    course_import_completed = pyqtSignal(object)
    course_import_failed = pyqtSignal(str)
    course_import_cancelled = pyqtSignal()

    def __init__(
        self,
        manager: CourseProjectManager,
        question_bank=None,
        set_manager=None,
        progress_manager=None,
        snapshot_manager=None,
        mastery_overrides=None,
        generation_draft_store=None,
        parent=None,
        task_center=None,
        checkpoint_store=None,
    ):
        super().__init__(parent)
        self.manager = manager
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.progress_manager = progress_manager
        self.snapshot_manager = snapshot_manager
        self.mastery_overrides = mastery_overrides
        self.generation_draft_store = generation_draft_store
        self.task_center = task_center
        self.checkpoint_store = checkpoint_store or CourseParseCheckpointStore(
            COURSE_CHECKPOINTS_DIR
        )
        self.initializer = CourseInitializer(
            manager,
            checkpoint_store=self.checkpoint_store,
        )
        self.lang_manager = LanguageManager.instance()
        self._init_worker = None
        self._regen_worker = None
        self._summary_markdown = ""
        self._summary_raw_mode = False
        self._active_section = "overview"
        self._course_hub_view = None
        self._last_task_progress = None
        self._task_bridge = None
        self._init_present_result = True
        self._import_expanded = False
        self._course_scope = "active"
        self._setup_ui()
        self.folder_input.editingFinished.connect(self._refresh_checkpoint_action)
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self.refresh()

    def _on_language_changed(self, lang):
        """Update all UI labels based on current language."""
        self.title.setText(self.lang_manager.get_text("课程资料", "Course Materials"))
        self.import_group.setTitle(self.lang_manager.get_text("从文件夹导入", "Initialize from folder"))
        self.folder_input.setPlaceholderText(
            self.lang_manager.get_text(
                "选择包含 pptx/pdf/docx/md/txt 文件的文件夹",
                "Select a folder with pptx/pdf/docx/md/txt files"
            )
        )
        self.browse_btn.setText(self.lang_manager.get_text("浏览", "Browse"))
        self.title_input.setPlaceholderText(
            self.lang_manager.get_text("课程名称（可选）", "Course title (optional)")
        )
        self.init_btn.setText(self.lang_manager.get_text("解析并生成总结", "Parse and generate summary"))
        self._update_import_toggle_text()
        self.list_label.setText(self.lang_manager.get_text("课程", "Courses"))
        self.active_scope_btn.setText(
            self.lang_manager.get_text("进行中的课程", "Active")
        )
        self.archived_scope_btn.setText(
            self.lang_manager.get_text("已归档", "Archived")
        )
        self.restore_course_btn.setText(
            self.lang_manager.get_text("恢复课程", "Restore Course")
        )
        self.view_course_library_btn.setText(
            self.lang_manager.get_text("查看题库", "View Library")
        )
        self.delete_archived_course_btn.setText(
            self.lang_manager.get_text("永久删除", "Delete Permanently")
        )
        self.scope_btn.setText(self.lang_manager.get_text("考试范围", "Exam Scope"))
        self.more_actions_btn.setText(self.lang_manager.get_text("更多操作", "More Actions"))
        self.rename_action.setText(self.lang_manager.get_text("重命名", "Rename"))
        self.regenerate_action.setText(self.lang_manager.get_text("重新生成总结", "Regenerate Summary"))
        self.refresh_action.setText(self.lang_manager.get_text("刷新", "Refresh"))
        self.archive_action.setText(
            self.lang_manager.get_text("归档课程", "Archive Course")
        )
        self.delete_action.setText(
            self.lang_manager.get_text("永久删除…", "Delete Permanently…")
        )
        self.summary_label.setText(self.lang_manager.get_text("摘要预览", "Summary preview"))
        self._update_summary_mode_button_text()
        self._refresh_checkpoint_action()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title_layout = QHBoxLayout()
        self.title = QLabel(self.lang_manager.get_text("课程资料", "Course Materials"))
        self.title.setObjectName("screenTitle")
        title_layout.addWidget(self.title)
        title_layout.addStretch(1)
        self.import_toggle_btn = QPushButton()
        self.import_toggle_btn.setObjectName("secondaryButton")
        self.import_toggle_btn.clicked.connect(self._toggle_import_panel)
        title_layout.addWidget(self.import_toggle_btn)
        layout.addLayout(title_layout)

        self.import_group = QGroupBox(self.lang_manager.get_text("从文件夹导入", "Initialize from folder"))
        import_layout = QVBoxLayout(self.import_group)

        folder_row = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText(
            self.lang_manager.get_text(
                "选择包含 pptx/pdf/docx/md/txt 文件的文件夹",
                "Select a folder with pptx/pdf/docx/md/txt files"
            )
        )
        folder_row.addWidget(self.folder_input, 1)
        self.browse_btn = QPushButton(self.lang_manager.get_text("浏览", "Browse"))
        self.browse_btn.setObjectName("secondaryButton")
        self.browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.browse_btn)
        import_layout.addLayout(folder_row)

        title_row = QHBoxLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText(
            self.lang_manager.get_text("课程名称（可选）", "Course title (optional)")
        )
        title_row.addWidget(self.title_input, 1)
        self.init_btn = QPushButton(self.lang_manager.get_text("解析并生成总结", "Parse and generate summary"))
        self.init_btn.setObjectName("primaryButton")
        self.init_btn.clicked.connect(self._initialize_course)
        title_row.addWidget(self.init_btn)
        import_layout.addLayout(title_row)

        layout.addWidget(self.import_group)
        self.import_group.setVisible(self._import_expanded)
        self._update_import_toggle_text()

        # Progress bar for import
        progress_row = QHBoxLayout()
        self.task_status_label = QLabel()
        self.task_status_label.setObjectName("courseTaskStatusLabel")
        self.task_status_label.setVisible(False)
        progress_row.addWidget(self.task_status_label, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_row.addWidget(self.progress_bar, 2)
        self.cancel_task_btn = QPushButton(self.lang_manager.get_text("停止", "Stop"))
        self.cancel_task_btn.setObjectName("secondaryButton")
        self.cancel_task_btn.setVisible(False)
        self.cancel_task_btn.clicked.connect(self._cancel_course_task)
        progress_row.addWidget(self.cancel_task_btn)
        layout.addLayout(progress_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        self.left_layout = QVBoxLayout(left)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.list_label = QLabel(self.lang_manager.get_text("课程", "Courses"))
        self.left_layout.addWidget(self.list_label)
        self.course_scope_layout = QHBoxLayout()
        self.course_scope_layout.setSpacing(6)
        self.course_scope_group = QButtonGroup(self)
        self.course_scope_group.setExclusive(True)
        self.active_scope_btn = QPushButton(
            self.lang_manager.get_text("进行中的课程", "Active")
        )
        self.archived_scope_btn = QPushButton(
            self.lang_manager.get_text("已归档", "Archived")
        )
        for button in (self.active_scope_btn, self.archived_scope_btn):
            button.setObjectName("quizModeOption")
            button.setCheckable(True)
            button.setMinimumHeight(34)
            self.course_scope_group.addButton(button)
            self.course_scope_layout.addWidget(button)
        self.course_scope_layout.addStretch(1)
        self.active_scope_btn.clicked.connect(
            lambda: self._set_course_scope("active")
        )
        self.archived_scope_btn.clicked.connect(
            lambda: self._set_course_scope("archived")
        )
        self.active_scope_btn.setChecked(True)
        self.left_layout.addLayout(self.course_scope_layout)
        self.empty_state_label = QLabel()
        self.empty_state_label.setObjectName("courseEmptyStateLabel")
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setVisible(False)
        self.left_layout.addWidget(self.empty_state_label, 1)
        self.project_list = QListWidget()
        self.project_list.currentItemChanged.connect(self._on_project_selected)
        self.left_layout.addWidget(self.project_list, 1)

        self.restore_course_btn = QPushButton(
            self.lang_manager.get_text("恢复课程", "Restore Course")
        )
        self.restore_course_btn.setObjectName("primaryButton")
        self.restore_course_btn.setVisible(False)
        self.restore_course_btn.setEnabled(False)
        self.restore_course_btn.clicked.connect(self._restore_selected_project)
        self.view_course_library_btn = QPushButton(
            self.lang_manager.get_text("查看题库", "View Library")
        )
        self.view_course_library_btn.setObjectName("secondaryButton")
        self.view_course_library_btn.setVisible(False)
        self.view_course_library_btn.setEnabled(False)
        self.view_course_library_btn.clicked.connect(
            self._view_selected_course_library
        )
        self.delete_archived_course_btn = QPushButton(
            self.lang_manager.get_text("永久删除", "Delete Permanently")
        )
        self.delete_archived_course_btn.setObjectName("dangerButton")
        self.delete_archived_course_btn.setVisible(False)
        self.delete_archived_course_btn.setEnabled(False)
        self.delete_archived_course_btn.clicked.connect(
            self._delete_selected_project
        )
        self.archived_action_layout = QHBoxLayout()
        self.archived_action_layout.setSpacing(6)
        self.archived_action_layout.addWidget(self.restore_course_btn)
        self.archived_action_layout.addWidget(self.delete_archived_course_btn)
        self.left_layout.addLayout(self.archived_action_layout)

        self.course_action_layout = QHBoxLayout()
        self.scope_btn = QPushButton(self.lang_manager.get_text("考试范围", "Exam Scope"))
        self.scope_btn.setObjectName("secondaryButton")
        self.scope_btn.clicked.connect(self._edit_exam_scope)
        self.course_action_layout.addWidget(self.scope_btn)
        self.more_actions_menu = QMenu(self)
        self.rename_action = QAction(self.lang_manager.get_text("重命名", "Rename"), self)
        self.rename_action.triggered.connect(self._rename_selected_project)
        self.more_actions_menu.addAction(self.rename_action)
        self.regenerate_action = QAction(
            self.lang_manager.get_text("重新生成总结", "Regenerate Summary"), self
        )
        self.regenerate_action.triggered.connect(self._regenerate_selected_project)
        self.more_actions_menu.addAction(self.regenerate_action)
        self.archive_action = QAction(
            self.lang_manager.get_text("归档课程", "Archive Course"),
            self,
        )
        self.archive_action.triggered.connect(self._archive_selected_project)
        self.more_actions_menu.addAction(self.archive_action)
        self.refresh_action = QAction(self.lang_manager.get_text("刷新", "Refresh"), self)
        self.refresh_action.triggered.connect(self.refresh)
        self.more_actions_menu.addAction(self.refresh_action)
        self.more_actions_menu.addSeparator()
        self.delete_action = QAction(
            self.lang_manager.get_text("永久删除…", "Delete Permanently…"),
            self,
        )
        self.delete_action.setObjectName("dangerAction")
        self.delete_action.triggered.connect(self._delete_selected_project)
        self.more_actions_menu.addAction(self.delete_action)

        self.more_actions_btn = QPushButton(self.lang_manager.get_text("更多操作", "More Actions"))
        self.more_actions_btn.setObjectName("secondaryButton")
        self.more_actions_btn.clicked.connect(self._show_more_actions_menu)
        self.course_action_layout.addWidget(self.more_actions_btn)
        self.left_layout.addLayout(self.course_action_layout)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_header = QHBoxLayout()
        self.summary_label = QLabel(self.lang_manager.get_text("摘要预览", "Summary preview"))
        self.summary_label.setObjectName("courseSummaryLabel")
        self.summary_header.addWidget(self.summary_label, 1)
        self.summary_header.addWidget(self.view_course_library_btn)
        self.summary_mode_btn = QPushButton()
        self.summary_mode_btn.setObjectName("secondaryButton")
        self.summary_mode_btn.clicked.connect(self._toggle_summary_mode)
        self._update_summary_mode_button_text()
        self.summary_header.addWidget(self.summary_mode_btn)
        right_layout.addLayout(self.summary_header)
        self.overview_metrics_label = QLabel()
        self.overview_metrics_label.setObjectName("secondaryText")
        self.overview_metrics_label.setWordWrap(True)
        right_layout.addWidget(self.overview_metrics_label)
        self.content_stack = QStackedWidget()
        self.overview_panel = QWidget()
        overview_layout = QVBoxLayout(self.overview_panel)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(8)
        self.course_health_label = QLabel()
        self.course_health_label.setObjectName("courseHealthSummary")
        self.course_health_label.setWordWrap(True)
        overview_layout.addWidget(self.course_health_label)
        self.course_coverage_label = QLabel()
        self.course_coverage_label.setObjectName("courseCoverageSummary")
        self.course_coverage_label.setWordWrap(True)
        overview_layout.addWidget(self.course_coverage_label)
        self.course_learning_label = QLabel()
        self.course_learning_label.setObjectName("courseLearningSummary")
        self.course_learning_label.setWordWrap(True)
        overview_layout.addWidget(self.course_learning_label)
        self.course_production_label = QLabel()
        self.course_production_label.setObjectName("courseProductionSummary")
        self.course_production_label.setWordWrap(True)
        overview_layout.addWidget(self.course_production_label)
        self.course_summary_heading = QLabel()
        self.course_summary_heading.setObjectName("courseSummaryHeading")
        overview_layout.addWidget(self.course_summary_heading)
        self.summary_preview = QTextBrowser()
        self.summary_preview.setObjectName("courseSummaryPreview")
        self.summary_preview.setReadOnly(True)
        self.summary_preview.setOpenExternalLinks(False)
        self.summary_preview.document().setDefaultStyleSheet("""
            body {
                font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
                font-size: 13px;
                line-height: 1.45;
            }
            h1 { font-size: 20px; margin: 4px 0 10px 0; }
            h2 { font-size: 17px; margin: 14px 0 7px 0; }
            h3 { font-size: 14px; margin: 12px 0 6px 0; }
            p { margin: 4px 0 8px 0; }
            ul, ol { margin: 4px 0 8px 18px; }
            li { margin: 2px 0; }
            code, pre {
                font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
                font-size: 12px;
            }
        """)
        overview_layout.addWidget(self.summary_preview, 1)
        self.content_stack.addWidget(self.overview_panel)
        self.sources_panel = CourseSourcesPanel()
        self.sources_table = self.sources_panel.table
        self.content_stack.addWidget(self.sources_panel)
        self.knowledge_panel = CourseKnowledgePanel()
        self.knowledge_table = self.knowledge_panel.table
        self.knowledge_panel.topic_action_requested.connect(
            self._on_knowledge_topic_action
        )
        self.content_stack.addWidget(self.knowledge_panel)
        right_layout.addWidget(self.content_stack, 1)
        splitter.addWidget(right)
        splitter.setSizes([280, 620])

        layout.addWidget(splitter, 1)

    def _all_projects(self) -> list:
        try:
            return list(self.manager.load_all(include_archived=True))
        except TypeError:
            return list(self.manager.load_all())

    def _set_course_scope(self, scope: str) -> None:
        normalized = "archived" if scope == "archived" else "active"
        self._course_scope = normalized
        self.refresh()

    def show_archived_courses(self) -> None:
        """Open the recoverable-course scope without changing course state."""
        self._set_course_scope("archived")

    def selected_course_id(self) -> str:
        item = self.project_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "").strip()

    def show_course(self, course_id: str, section: str = "overview") -> None:
        """Render the exact course named by a semantic route."""
        normalized_id = str(course_id or "").strip()
        project = self.manager.get(normalized_id) if normalized_id else None
        if project is not None:
            self._course_scope = (
                "archived"
                if getattr(project, "is_archived", False)
                else "active"
            )
        self.refresh()
        if project is not None:
            for row in range(self.project_list.count()):
                item = self.project_list.item(row)
                if (
                    str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                    == normalized_id
                ):
                    self.project_list.setCurrentRow(row)
                    break
        self.show_section(section)

    def show_section(self, section: str) -> None:
        """Show one Course Hub section without creating nested navigation."""
        normalized = str(section or "").strip()
        widgets = {
            "overview": self.overview_panel,
            "sources": self.sources_panel,
            "knowledge": self.knowledge_panel,
        }
        if normalized not in widgets:
            raise ValueError(f"unknown course section: {normalized}")
        self._active_section = normalized
        self.content_stack.setCurrentWidget(widgets[normalized])
        is_overview = normalized == "overview"
        self.overview_metrics_label.setVisible(is_overview)
        self.summary_mode_btn.setVisible(is_overview)
        project = self.manager.get(self.selected_course_id())
        self._update_content_header(project)

    def focus_knowledge_topic(self, topic_id: str) -> bool:
        """Select a knowledge-point row after a contextual action navigates here."""
        wanted = str(topic_id or "").strip()
        if not wanted:
            return False
        for row in range(self.knowledge_table.rowCount()):
            item = self.knowledge_table.item(row, 0)
            if item is not None and str(
                item.data(Qt.ItemDataRole.UserRole) or ""
            ).strip() == wanted:
                self.knowledge_table.selectRow(row)
                return True
        return False

    def _render_course_hub(self, project) -> None:
        view = build_course_hub_view(
            project,
            self.question_bank,
            progress_manager=self.progress_manager,
            mastery_overrides=self.mastery_overrides,
            generation_draft_store=self.generation_draft_store,
        )
        self._course_hub_view = view
        gm = self.lang_manager.get_text
        warning_text = (
            gm(
                f" · {view.warning_count} 份资料需关注",
                f" · {view.warning_count} source(s) need attention",
            )
            if view.warning_count
            else ""
        )
        self.overview_metrics_label.setText(
            gm(
                f"{view.document_count} 份资料 · {view.topic_count} 个知识点 · "
                f"{view.question_count} 道题 · "
                f"考试范围 {view.exam_topic_count}/{view.topic_count}"
                f"{warning_text}",
                f"{view.document_count} sources · {view.topic_count} knowledge points · "
                f"{view.question_count} questions · "
                f"exam scope {view.exam_topic_count}/{view.topic_count}"
                f"{warning_text}",
            )
        )
        self.course_health_label.setText(gm(
            f"资料健康\n{view.document_count} 份资料 · "
            f"{view.document_count - view.warning_count} 份正常 · "
            f"{view.warning_count} 份需要处理",
            f"Source health\n{view.document_count} sources · "
            f"{view.document_count - view.warning_count} ready · "
            f"{view.warning_count} need attention",
        ))
        self.course_coverage_label.setText(gm(
            f"内容覆盖\n考试知识点 {view.exam_topic_count} 个 · "
            f"已有题目 {view.covered_exam_topic_count} 个 · "
            f"缺少题目 {view.uncovered_exam_topic_count} 个",
            f"Content coverage\n{view.exam_topic_count} exam topics · "
            f"{view.covered_exam_topic_count} covered · "
            f"{view.uncovered_exam_topic_count} missing questions",
        ))
        unstarted = sum(topic.status == "not_started" for topic in view.topics)
        self.course_learning_label.setText(gm(
            f"学习状态\n薄弱知识点 {view.weak_topic_count} 个 · "
            f"未开始 {unstarted} 个",
            f"Learning status\n{view.weak_topic_count} weak · "
            f"{unstarted} not started",
        ))
        self.course_production_label.setText(gm(
            f"内容生产\n待审核题目 {view.pending_review_question_count} 道 · "
            f"质量警告 {view.quality_warning_count} 道",
            f"Content production\n{view.pending_review_question_count} pending review · "
            f"{view.quality_warning_count} quality warnings",
        ))
        self.course_summary_heading.setText(
            gm("课程总结", "Course Summary")
        )
        self.sources_panel.render(view, gm)
        self.knowledge_panel.render(view, gm)

    def _clear_course_hub(self) -> None:
        self._course_hub_view = None
        self.overview_metrics_label.clear()
        for label in (
            self.course_health_label,
            self.course_coverage_label,
            self.course_learning_label,
            self.course_production_label,
            self.course_summary_heading,
        ):
            label.clear()
        self.sources_table.setRowCount(0)
        self.knowledge_table.setRowCount(0)

    def _on_knowledge_topic_action(self, topic_id: str, action: str) -> None:
        course_id = self.selected_course_id()
        if not course_id:
            return
        self.course_topic_action_requested.emit(course_id, topic_id, action)

    def refresh(self):
        """Reload active or archived projects from disk."""
        selected_item = self.project_list.currentItem()
        selected_id = (
            str(selected_item.data(Qt.ItemDataRole.UserRole) or "")
            if selected_item is not None
            else ""
        )
        self.project_list.clear()
        current = self.manager.current()
        current_id = current.course_id if current else ""
        all_projects = self._all_projects()
        active_projects = [
            project
            for project in all_projects
            if not getattr(project, "is_archived", False)
        ]
        archived_projects = [
            project
            for project in all_projects
            if getattr(project, "is_archived", False)
        ]
        has_archived_projects = bool(archived_projects)
        self.active_scope_btn.setVisible(has_archived_projects)
        self.archived_scope_btn.setVisible(has_archived_projects)
        if self._course_scope == "archived" and not has_archived_projects:
            self._course_scope = "active"
        if self._course_scope == "active" and not active_projects and archived_projects:
            self._course_scope = "archived"
        self.active_scope_btn.setChecked(self._course_scope == "active")
        self.archived_scope_btn.setChecked(self._course_scope == "archived")
        projects = (
            archived_projects
            if self._course_scope == "archived"
            else active_projects
        )
        for project in projects:
            prefix = (
                "★ "
                if self._course_scope == "active"
                and project.course_id == current_id
                else ""
            )
            scope_count = len(project.exam_topics())
            scope_label = self.lang_manager.get_text("范围", "scope")
            item = QListWidgetItem(
                f"{prefix}{project.title}  [{scope_count}/{len(project.topics)} {scope_label}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, project.course_id)
            self.project_list.addItem(item)
        is_empty = not projects
        has_any_course = bool(all_projects)
        if not has_any_course:
            self._import_expanded = True
        self.import_group.setVisible(self._import_expanded)
        active_scope = self._course_scope == "active"
        self.restore_course_btn.setVisible(not active_scope and not is_empty)
        # Active courses already scope the global Library route to the current
        # course. Keep this contextual shortcut only for archived courses,
        # whose assets must be opened without restoring them as current.
        self.view_course_library_btn.setVisible(
            not is_empty and self._course_scope == "archived"
        )
        self.delete_archived_course_btn.setVisible(
            not active_scope and not is_empty
        )
        import_role = "primaryButton" if not has_any_course else "secondaryButton"
        if self.init_btn.objectName() != import_role:
            self.init_btn.setObjectName(import_role)
            self.init_btn.style().unpolish(self.init_btn)
            self.init_btn.style().polish(self.init_btn)
        self._update_import_toggle_text()
        if not has_any_course:
            empty_text = self.lang_manager.get_text(
                "还没有课程。请在上方选择课程资料文件夹并导入第一个课程。",
                "No courses yet. Choose a course-material folder above and import your first course.",
            )
        elif self._course_scope == "archived":
            empty_text = self.lang_manager.get_text(
                "没有已归档课程。",
                "There are no archived courses.",
            )
        else:
            empty_text = self.lang_manager.get_text(
                f"暂无进行中的课程。你有 {len(archived_projects)} 门已归档课程，可以切换到“已归档”后恢复。",
                f"There are no active courses. You have {len(archived_projects)} archived "
                "course(s); switch to Archived to restore one.",
            )
        self.empty_state_label.setText(empty_text)
        self.empty_state_label.setVisible(is_empty)
        self.project_list.setVisible(not is_empty)
        self.restore_course_btn.setEnabled(False)
        self.view_course_library_btn.setEnabled(False)
        self.delete_archived_course_btn.setEnabled(False)
        self.scope_btn.setEnabled(False)
        self.rename_action.setEnabled(False)
        self.regenerate_action.setEnabled(False)
        self.archive_action.setEnabled(False)
        self.delete_action.setEnabled(False)
        if projects:
            selected_row = 0
            preferred_id = selected_id
            if not preferred_id and current and active_scope:
                preferred_id = current.course_id
            if preferred_id:
                for row in range(self.project_list.count()):
                    if (
                        self.project_list.item(row).data(Qt.ItemDataRole.UserRole)
                        == preferred_id
                    ):
                        selected_row = row
                        break
            self.project_list.setCurrentRow(selected_row)
        else:
            self.summary_label.setText(self.lang_manager.get_text("摘要预览", "Summary preview"))
            self._clear_course_hub()
            self._clear_summary()

    def restore_task_context(self, snapshot) -> None:
        """Restore safe local inputs for a persisted course task without starting it."""
        metadata = getattr(snapshot, "metadata", {}) or {}
        if getattr(snapshot, "kind", "") == "course_import":
            self._import_expanded = True
            self.import_group.setVisible(True)
            self.folder_input.setText(str(metadata.get("source_folder", "") or ""))
            self.title_input.setText(str(metadata.get("course_title", "") or ""))
            self._update_import_toggle_text()
            self._refresh_checkpoint_action()
            return
        course_id = str(metadata.get("course_id", "") or "")
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == course_id:
                self.project_list.setCurrentRow(row)
                break

    def _toggle_import_panel(self):
        self._import_expanded = not self._import_expanded
        self.import_group.setVisible(self._import_expanded)
        self._update_import_toggle_text()

    def _update_import_toggle_text(self):
        if not hasattr(self, "import_toggle_btn"):
            return
        self.import_toggle_btn.setText(self.lang_manager.get_text(
            "收起导入" if self._import_expanded else "导入课程",
            "Hide Import" if self._import_expanded else "Import Course",
        ))

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            self.lang_manager.get_text("选择课程文件夹", "Select Course Folder")
        )
        if folder:
            self.folder_input.setText(folder)
            if not self.title_input.text().strip():
                self.title_input.setText(folder.split("/")[-1].split("\\")[-1])
            self._refresh_checkpoint_action()

    def _refresh_checkpoint_action(self) -> None:
        """Reflect reusable parsed files without starting background work."""
        normal_text = self.lang_manager.get_text(
            "解析并生成总结",
            "Parse and generate summary",
        )
        self.init_btn.setText(normal_text)
        self.init_btn.setToolTip("")
        folder = self.folder_input.text().strip()
        if not folder:
            return
        try:
            source_paths = self.initializer.parser.source_paths(folder)
            count = self.checkpoint_store.reusable_count(
                folder,
                operation="initialize",
                course_id="",
                source_paths=source_paths,
            )
        except (FileNotFoundError, OSError, ValueError):
            return
        if count <= 0:
            return
        self.init_btn.setText(self.lang_manager.get_text(
            "继续解析并生成总结",
            "Resume Parsing and Summary",
        ))
        self.init_btn.setToolTip(self.lang_manager.get_text(
            f"将复用 {count} 个已解析且未变化的文件；仍需你点击后才会继续。",
            f"Reuses {count} parsed unchanged file(s); nothing resumes until you click.",
        ))

    def _initialize_course(self):
        self.start_import(
            self.folder_input.text(),
            self.title_input.text(),
        )

    def start_import(
        self,
        folder: str,
        title: str = "",
        *,
        present_result: bool = True,
    ) -> bool:
        """Start the existing background import from another workspace."""
        folder = str(folder or "").strip()
        if not folder:
            if present_result:
                QMessageBox.warning(
                    self,
                    self.lang_manager.get_text("缺少文件夹", "Missing Folder"),
                    self.lang_manager.get_text(
                        "请先选择一个课程资料文件夹。",
                        "Please select a course-material folder first.",
                    ),
                )
            return False
        if self._init_worker is not None and self._init_worker.isRunning():
            return False

        title = str(title or "").strip()
        self.folder_input.setText(folder)
        self.title_input.setText(title)
        self._init_present_result = bool(present_result)
        self._init_worker = CourseScreen._InitWorker(
            folder,
            title,
            self._build_initializer(),
        )
        self._init_worker.finished.connect(self._on_init_done)
        self._init_worker.error.connect(self._on_init_error)
        self._init_worker.cancelled.connect(self._on_course_task_cancelled)
        self._init_worker.progress.connect(self._on_course_task_progress)
        self._begin_task(
            kind="course_import",
            title=self.lang_manager.get_text(
                f"导入课程：{title or Path(folder).name}",
                f"Import course: {title or Path(folder).name}",
            ),
            metadata={
                "source_folder": folder,
                "course_title": title,
            },
            worker=self._init_worker,
        )
        self._set_course_task_active(True)
        self.course_import_started.emit()
        self._init_worker.start()
        return True

    def _begin_task(self, *, kind, title, metadata, worker) -> None:
        if self.task_center is None:
            self._task_bridge = None
            return
        snapshot = self.task_center.create(
            kind=kind,
            title=title,
            metadata=metadata,
        )
        bridge = BackgroundTaskBridge(self.task_center, snapshot.task_id)
        bridge.start(worker.cancel)
        self._task_bridge = bridge

    def _finish_task(self, outcome, **kwargs) -> None:
        bridge = self._task_bridge
        if bridge is None:
            return
        getattr(bridge, outcome)(**kwargs)
        self._task_bridge = None

    def _set_course_task_active(self, active: bool) -> None:
        """Keep all course actions consistent while one background task owns state."""
        self.progress_bar.setVisible(active)
        self.task_status_label.setVisible(active)
        self.cancel_task_btn.setVisible(active)
        self.cancel_task_btn.setEnabled(active)
        self.cancel_task_btn.setText(self.lang_manager.get_text("停止", "Stop"))
        self.folder_input.setEnabled(not active)
        self.title_input.setEnabled(not active)
        self.browse_btn.setEnabled(not active)
        self.init_btn.setEnabled(not active)
        self.import_toggle_btn.setEnabled(not active)
        self.project_list.setEnabled(not active)
        if active:
            self.progress_bar.setRange(0, 0)
            self.task_status_label.setText(self.lang_manager.get_text("正在准备…", "Preparing…"))
            for button in (self.scope_btn, self.more_actions_btn):
                button.setEnabled(False)
            for action in self.more_actions_menu.actions():
                action.setEnabled(False)
        else:
            self._last_task_progress = None
            self.task_status_label.clear()
            self.init_btn.setText(self.lang_manager.get_text(
                "解析并生成总结", "Parse and generate summary"
            ))
            self._refresh_checkpoint_action()
            self.more_actions_btn.setEnabled(True)
            self.refresh_action.setEnabled(True)
            self._on_project_selected(self.project_list.currentItem(), None)

    def _show_more_actions_menu(self) -> None:
        """Open secondary course actions without adding an icon or menu arrow."""
        self.more_actions_menu.popup(
            self.more_actions_btn.mapToGlobal(self.more_actions_btn.rect().bottomLeft())
        )

    def _cancel_course_task(self) -> None:
        worker = self._init_worker or self._regen_worker
        if worker is None:
            return
        if self._task_bridge is not None:
            self.task_center.request_cancel(self._task_bridge.task_id)
        else:
            worker.cancel()
        self.cancel_task_btn.setEnabled(False)
        self.cancel_task_btn.setText(self.lang_manager.get_text("正在停止…", "Stopping…"))
        self.task_status_label.setText(self.lang_manager.get_text(
            "正在等待当前步骤安全结束…",
            "Waiting for the current step to stop safely…",
        ))

    def cancel_active_task(self) -> None:
        """Expose cooperative cancellation to the hosting workspace."""
        self._cancel_course_task()

    def request_shutdown(self) -> bool:
        """Request cooperative cancellation; never block the GUI thread."""
        workers = [
            worker
            for worker in (
                self._init_worker,
                self._regen_worker,
            )
            if worker
        ]
        if not any(worker.isRunning() for worker in workers):
            return True
        self._cancel_course_task()
        return False

    def _on_course_task_progress(self, progress: TaskProgress) -> None:
        sender = self.sender()
        if sender is not None and sender not in (
            self._init_worker,
            self._regen_worker,
        ):
            return
        self._last_task_progress = progress
        if self._task_bridge is not None:
            self._task_bridge.report(progress)
        if progress.total > 0:
            self.progress_bar.setRange(0, progress.total)
            self.progress_bar.setValue(progress.current)
        else:
            self.progress_bar.setRange(0, 0)
        self.task_status_label.setText(self._course_task_progress_text(progress))
        if sender is self._init_worker:
            self.course_import_progressed.emit(progress)

    def _course_task_progress_text(self, progress: TaskProgress) -> str:
        stages = {
            "parsing": ("扫描课程资料", "Scanning course materials"),
            "files_found": ("已发现资料文件", "Course files found"),
            "parsing_file": ("正在解析文件", "Parsing file"),
            "reusing_file": ("复用已解析文件", "Reusing parsed file"),
            "parsing_page": ("正在解析页面", "Parsing page"),
            "topics": ("识别课程主题", "Identifying course topics"),
            "summary": ("生成本地总结", "Building local summary"),
            "summary_ai": ("AI 正在整理课程总结", "AI is refining the course summary"),
            "profile": ("生成出题配置", "Building quiz defaults"),
            "index": ("构建来源索引", "Building source index"),
            "saving": ("保存课程", "Saving course"),
            "saved": ("课程已保存", "Course saved"),
        }
        zh, en = stages.get(progress.stage, ("处理课程资料", "Processing course materials"))
        text = self.lang_manager.get_text(zh, en)
        if progress.total > 0:
            text += f"  {progress.current} / {progress.total}"
        if progress.detail:
            text += f"  {progress.detail}"
        return text

    def _on_course_task_cancelled(self) -> None:
        sender = self.sender()
        import_cancelled = sender is self._init_worker
        if sender is self._init_worker:
            self._init_worker = None
        elif sender is self._regen_worker:
            self._regen_worker = None
        elif sender is not None:
            return
        self._finish_task("cancelled")
        self._set_course_task_active(False)
        if import_cancelled:
            self.course_import_cancelled.emit()
        if not import_cancelled or self._init_present_result:
            QMessageBox.information(
                self,
                self.lang_manager.get_text("已停止", "Stopped"),
                self.lang_manager.get_text(
                    "操作已安全停止，未保存未完成的更改。",
                    "The operation stopped safely; incomplete changes were not saved.",
                ),
            )
        self._init_present_result = True

    def _build_initializer(self):
        """Build an initializer using current AI settings when available."""
        from ai.course_summary_factory import (
            create_course_generation_profile_generator,
            create_course_summary_generator,
            provider_requires_api_key,
        )
        from core.secrets_manager import SecretsManager

        settings = read_json(SETTINGS_FILE) or {}
        api_key = SecretsManager.instance().get_key() if provider_requires_api_key(settings) else ""
        summary_generator = create_course_summary_generator(settings, api_key=api_key)
        profile_generator = create_course_generation_profile_generator(settings, api_key=api_key)
        return CourseInitializer(
            self.manager,
            summary_generator=summary_generator,
            profile_generator=profile_generator,
            checkpoint_store=self.checkpoint_store,
        )

    def _on_init_done(self, project):
        if not self._is_current_worker("_init_worker"):
            return
        self._init_worker = None
        present_result = self._init_present_result
        self._init_present_result = True
        self._finish_task(
            "complete",
            result_summary=f"Imported course {project.title}",
            result_count=len(project.documents),
        )
        self._set_course_task_active(False)
        self.cancel_task_btn.setText(self.lang_manager.get_text("停止", "Stop"))

        lang = self.lang_manager.current
        if lang == "zh":
            msg = f"已初始化 '{project.title}'，包含 {len(project.documents)} 个文件和 {len(project.topics)} 个主题。"
        else:
            msg = f"Initialized '{project.title}' with {len(project.documents)} files and {len(project.topics)} topics."
        msg = self._with_summary_warning(msg, project)
        msg = self._with_profile_warning(msg, project)
        msg = self._with_document_warnings(msg, project)
        if present_result:
            QMessageBox.information(
                self,
                self.lang_manager.get_text("课程就绪", "Course Ready"),
                msg,
            )
        self._import_expanded = False
        self.refresh()
        self.course_import_completed.emit(project)
        self.current_course_changed.emit()

    def _on_init_error(self, error_msg):
        if not self._is_current_worker("_init_worker"):
            return
        self._init_worker = None
        present_result = self._init_present_result
        self._init_present_result = True
        self._finish_task("fail", error=error_msg)
        self._set_course_task_active(False)
        self.course_import_failed.emit(str(error_msg))
        if present_result:
            QMessageBox.critical(
                self,
                self.lang_manager.get_text("初始化失败", "Initialization Failed"),
                error_msg,
            )


    class _InitWorker(QThread):
        """Background worker for course initialization."""
        finished = pyqtSignal(object)  # CourseProject
        error = pyqtSignal(str)
        cancelled = pyqtSignal()
        progress = pyqtSignal(object)

        def __init__(self, folder, title, initializer):
            super().__init__()
            self._folder = folder
            self._title = title
            self._initializer = initializer
            self._task = TaskControl(self.progress.emit)

        def cancel(self):
            self._task.cancel()

        def run(self):
            try:
                project = self._initializer.initialize(
                    self._folder, self._title, task=self._task
                )
                self.finished.emit(project)
            except BackgroundTaskCancelled:
                self.cancelled.emit()
            except Exception as exc:
                self.error.emit(str(exc))


    class _RegenWorker(QThread):
        """Background worker for course summary regeneration."""
        finished = pyqtSignal(object)
        error = pyqtSignal(str)
        cancelled = pyqtSignal()
        progress = pyqtSignal(object)

        def __init__(self, project, initializer, question_bank=None):
            super().__init__()
            self._project = project
            self._initializer = initializer
            self._question_bank = question_bank
            self._task = TaskControl(self.progress.emit)

        def cancel(self):
            self._task.cancel()

        def run(self):
            try:
                project = self._initializer.regenerate_summary(
                    self._project, task=self._task
                )
                report = None
                if self._question_bank is not None:
                    report = repair_question_topic_identities(self._question_bank, project)
                self.finished.emit((project, report))
            except BackgroundTaskCancelled:
                self.cancelled.emit()
            except Exception as exc:
                self.error.emit(str(exc))

    def _on_project_selected(self, current, previous):
        if current is None:
            self._clear_course_hub()
            self.restore_course_btn.setEnabled(False)
            self.view_course_library_btn.setEnabled(False)
            self.delete_archived_course_btn.setEnabled(False)
            self.scope_btn.setEnabled(False)
            self.rename_action.setEnabled(False)
            self.regenerate_action.setEnabled(False)
            self.archive_action.setEnabled(False)
            self.delete_action.setEnabled(False)
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return
        archived = bool(getattr(project, "is_archived", False))
        if not archived:
            active = self.manager.current()
            set_current = getattr(self.manager, "set_current", None)
            if (
                callable(set_current)
                and (not active or active.course_id != course_id)
                and set_current(course_id)
            ):
                self.current_course_changed.emit()
        self.restore_course_btn.setEnabled(archived)
        self.view_course_library_btn.setEnabled(archived)
        self.delete_archived_course_btn.setEnabled(archived)
        self.scope_btn.setEnabled(not archived)
        self.rename_action.setEnabled(not archived)
        self.regenerate_action.setEnabled(not archived)
        self.archive_action.setEnabled(not archived)
        self.delete_action.setEnabled(True)
        self._render_course_hub(project)
        self._show_summary(project.summary_markdown)
        self.show_section(self._active_section)

    def _edit_exam_scope(self):
        current = self.project_list.currentItem()
        if not current:
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return
        dialog = CourseExamScopeDialog(project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        mode, topic_ids = dialog.scope()
        updated = deepcopy(project)
        try:
            updated.set_exam_scope(mode, topic_ids)
        except ValueError as exc:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("范围无效", "Invalid Scope"),
                str(exc),
            )
            return
        updated.updated_at = datetime.now(timezone.utc).isoformat()
        if not self.manager.save(updated, make_current=False):
            QMessageBox.critical(
                self,
                self.lang_manager.get_text("保存失败", "Save Failed"),
                self.lang_manager.get_text(
                    "考试范围未保存，原课程数据保持不变。请检查数据目录后重试。",
                    "The exam scope was not saved. Original course data remains unchanged. Check the data directory and retry.",
                ),
            )
            return
        self.refresh()
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == course_id:
                self.project_list.setCurrentRow(row)
                break
        self.current_course_changed.emit()

    def _rename_selected_project(self):
        current = self.project_list.currentItem()
        if not current:
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return
        new_title, accepted = QInputDialog.getText(
            self,
            self.lang_manager.get_text("重命名课程", "Rename Course"),
            self.lang_manager.get_text("课程名称:", "Course name:"),
            text=project.title,
        )
        new_title = new_title.strip()
        if not accepted or not new_title:
            return
        project.title = new_title
        project.updated_at = datetime.now(timezone.utc).isoformat()
        self.manager.save(project, make_current=False)
        self.refresh()
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == course_id:
                self.project_list.setCurrentRow(row)
                break

    def _regenerate_selected_project(self):
        current = self.project_list.currentItem()
        if not current:
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return

        self._regen_worker = CourseScreen._RegenWorker(
            project,
            self._build_initializer(),
            question_bank=self.question_bank,
        )
        self._regen_worker.finished.connect(self._on_regen_done)
        self._regen_worker.error.connect(self._on_regen_error)
        self._regen_worker.cancelled.connect(self._on_course_task_cancelled)
        self._regen_worker.progress.connect(self._on_course_task_progress)
        self._begin_task(
            kind="course_summary",
            title=self.lang_manager.get_text(
                f"重新生成课程总结：{project.title}",
                f"Regenerate course summary: {project.title}",
            ),
            metadata={"course_id": project.course_id},
            worker=self._regen_worker,
        )
        self._set_course_task_active(True)
        self._regen_worker.start()

    def _archive_selected_project(self) -> None:
        current = self.project_list.currentItem()
        if current is None:
            return
        course_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        project = self.manager.get(course_id)
        if project is None or getattr(project, "is_archived", False):
            return
        result = remove_course_assets(
            course_id,
            CourseRemovalMode.ARCHIVE,
            course_manager=self.manager,
            question_bank=self.question_bank,
            set_manager=self.set_manager,
            progress_manager=self.progress_manager,
            snapshot_manager=self.snapshot_manager,
            generation_draft_store=self.generation_draft_store,
        )
        if not result.success:
            QMessageBox.critical(
                self,
                self.lang_manager.get_text("归档失败", "Archive Failed"),
                self.lang_manager.get_text(
                    f"课程未能归档，原数据保持不变。\n{result.error}",
                    f"The course could not be archived; its data was left unchanged.\n{result.error}",
                ),
            )
            return
        if self.manager.current() is None:
            remaining_courses = list(self.manager.load_all())
            if remaining_courses:
                self.manager.set_current(remaining_courses[0].course_id)
        self.current_course_changed.emit()
        self.refresh()

    def _restore_selected_project(self) -> None:
        current = self.project_list.currentItem()
        if current is None:
            return
        course_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        project = self.manager.get(course_id)
        if project is None or not getattr(project, "is_archived", False):
            return
        if not self.manager.restore(course_id, make_current=True):
            QMessageBox.critical(
                self,
                self.lang_manager.get_text("恢复失败", "Restore Failed"),
                self.lang_manager.get_text(
                    "课程未能恢复，请检查应用数据目录后重试。",
                    "The course could not be restored. Check the app data directory and try again.",
                ),
            )
            return
        self._course_scope = "active"
        self.refresh()
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == course_id:
                self.project_list.setCurrentRow(row)
                break
        self.current_course_changed.emit()

    def _view_selected_course_library(self) -> None:
        current = self.project_list.currentItem()
        if current is None:
            return
        course_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        if self.manager.get(course_id) is not None:
            self.view_course_library_requested.emit(course_id)

    def _delete_selected_project(self):
        current = self.project_list.currentItem()
        if not current:
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return
        impact = analyze_course_asset_impact(
            course_id,
            self.question_bank,
            self.set_manager,
            self.progress_manager,
            self.snapshot_manager,
            generation_draft_store=self.generation_draft_store,
        )
        mode = self._choose_course_removal_mode(project, impact)
        if mode is None:
            return
        result = remove_course_assets(
            course_id,
            mode,
            course_manager=self.manager,
            question_bank=self.question_bank,
            set_manager=self.set_manager,
            progress_manager=self.progress_manager,
            snapshot_manager=self.snapshot_manager,
            generation_draft_store=self.generation_draft_store,
        )
        if not result.success:
            rollback_note = ""
            if result.rollback_errors:
                rollback_note = self.lang_manager.get_text(
                    "\n部分数据恢复失败，请立即从应用数据备份恢复。",
                    "\nSome data could not be restored. Restore an app-data backup immediately.",
                )
            QMessageBox.critical(
                self,
                self.lang_manager.get_text("删除失败", "Delete Failed"),
                self.lang_manager.get_text(
                    f"课程删除未完成，已尝试恢复原数据。\n{result.error}{rollback_note}",
                    f"Course removal did not complete; the original data was restored.\n{result.error}{rollback_note}",
                ),
            )
            return
        self.summary_preview.clear()
        self.current_course_changed.emit()
        self.refresh()

    def _choose_course_removal_mode(self, project, impact):
        dialog = QDialog(self)
        dialog.setWindowTitle(
            self.lang_manager.get_text("永久删除课程", "Delete Course Permanently")
        )
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        impact_label = QLabel(self._course_removal_impact_text(project, impact))
        impact_label.setWordWrap(True)
        impact_label.setObjectName("courseRemovalImpact")
        layout.addWidget(impact_label)

        choices = (
            (
                CourseRemovalMode.UNLINK_ASSETS,
                self.lang_manager.get_text("解除关联并删除课程", "Unlink and Delete Course"),
                self._course_removal_mode_text(
                    CourseRemovalMode.UNLINK_ASSETS,
                    impact,
                ),
            ),
            (
                CourseRemovalMode.DELETE_LINKED_BANK,
                self.lang_manager.get_text("删除课程及关联题库", "Delete Course and Linked Bank"),
                self._course_removal_mode_text(
                    CourseRemovalMode.DELETE_LINKED_BANK,
                    impact,
                ),
            ),
        )
        radios = {}
        for mode, title, description in choices:
            radio = QRadioButton(title)
            radios[mode] = radio
            layout.addWidget(radio)
            detail = QLabel(description)
            detail.setObjectName("secondaryText")
            detail.setWordWrap(True)
            detail.setContentsMargins(24, 0, 0, 4)
            layout.addWidget(detail)
        radios[CourseRemovalMode.UNLINK_ASSETS].setChecked(True)

        source_note = QLabel(self.lang_manager.get_text(
            "原始课件文件夹始终不会被删除。",
            "The original material folder is never deleted.",
        ))
        source_note.setObjectName("secondaryText")
        layout.addWidget(source_note)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel_button = QPushButton(self.lang_manager.get_text("取消", "Cancel"))
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(dialog.reject)
        footer.addWidget(cancel_button)
        continue_button = QPushButton(self.lang_manager.get_text("继续", "Continue"))
        continue_button.setObjectName("primaryButton")
        continue_button.clicked.connect(dialog.accept)
        footer.addWidget(continue_button)
        layout.addLayout(footer)

        def sync_continue_style():
            object_name = (
                "dangerButton"
                if radios[CourseRemovalMode.DELETE_LINKED_BANK].isChecked()
                else "primaryButton"
            )
            continue_button.setObjectName(object_name)
            continue_button.style().unpolish(continue_button)
            continue_button.style().polish(continue_button)

        for radio in radios.values():
            radio.toggled.connect(sync_continue_style)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return next(mode for mode, radio in radios.items() if radio.isChecked())

    def _course_removal_impact_text(self, project, impact) -> str:
        return self.lang_manager.get_text(
            (
                f"删除课程“{project.title}”\n\n"
                f"相关题目：{impact.question_count}\n"
                f"相关题集：{impact.question_set_count}\n"
                f"学习记录：{impact.progress_count}（完整归档 "
                f"{impact.complete_archive_count}，残缺归档 "
                f"{impact.incomplete_archive_count}，删除前待迁移 "
                f"{impact.legacy_archive_count}）\n"
                f"未完成草稿：{impact.unfinished_draft_count}（删除课程时取消）"
            ),
            (
                f"Delete course '{project.title}'\n\n"
                f"Linked questions: {impact.question_count}\n"
                f"Linked question sets: {impact.question_set_count}\n"
                f"Learning records: {impact.progress_count} "
                f"(complete archives {impact.complete_archive_count}, "
                f"incomplete archives {impact.incomplete_archive_count}, "
                f"migrate before deletion {impact.legacy_archive_count})\n"
                f"Unfinished drafts: {impact.unfinished_draft_count} "
                "(cancelled when the course is deleted)"
            ),
        )

    def _course_removal_mode_text(
        self,
        mode: CourseRemovalMode,
        impact,
    ) -> str:
        drafts = impact.unfinished_draft_count
        mode = CourseRemovalMode(mode)
        archive_note = self._course_archive_preparation_text(impact)
        if mode is CourseRemovalMode.KEEP_ASSETS:
            return self.lang_manager.get_text(
                f"题目和题集原样保留；{drafts} 个未完成草稿将取消。"
                f"完成历史仍可复盘。{archive_note[0]}",
                f"Questions and sets remain unchanged; {drafts} unfinished draft(s) "
                f"will be cancelled. Completed history remains reviewable. {archive_note[1]}",
            )
        if mode is CourseRemovalMode.UNLINK_ASSETS:
            return self.lang_manager.get_text(
                f"保留题目和题集，但移除课程归属和来源定位；{drafts} 个未完成草稿将取消。"
                f"完成历史仍可复盘。{archive_note[0]}",
                "Keep questions and sets, but remove course ownership and source locations; "
                f"{drafts} unfinished draft(s) will be cancelled. Completed history remains "
                f"reviewable. {archive_note[1]}",
            )
        return self.lang_manager.get_text(
            f"删除关联题目并清理题集；{drafts} 个未完成草稿将取消。"
            f"完成历史仍可复盘，但原题删除后不能重练。{archive_note[0]}",
            f"Delete linked questions and clean affected sets; {drafts} unfinished draft(s) "
            "will be cancelled. Completed history remains reviewable, but deleted questions "
            f"cannot be retried. {archive_note[1]}",
        )

    @staticmethod
    def _course_archive_preparation_text(impact) -> tuple[str, str]:
        zh_parts = []
        en_parts = []
        if impact.legacy_archive_count:
            zh_parts.append(f"删除前先迁移 {impact.legacy_archive_count} 条旧历史")
            en_parts.append(
                f"migrate {impact.legacy_archive_count} legacy record(s) before deletion"
            )
        if impact.incomplete_archive_count:
            zh_parts.append(
                f"{impact.incomplete_archive_count} 条残缺历史保留明确标记"
            )
            en_parts.append(
                f"keep {impact.incomplete_archive_count} incomplete archive(s) marked"
            )
        if not zh_parts:
            return (
                "历史归档状态已明确。",
                "Historical archive status is explicit.",
            )
        return (
            "；".join(zh_parts) + "。",
            "; ".join(en_parts) + ".",
        )

    def _on_regen_done(self, result):
        if not self._is_current_worker("_regen_worker"):
            return
        self._regen_worker = None
        if isinstance(result, tuple):
            project, repair_report = result
        else:
            project = result
            repair_report = None
        self._finish_task(
            "complete",
            result_summary=f"Regenerated summary for {project.title}",
            result_count=len(project.documents),
        )
        self._set_course_task_active(False)
        self.refresh()
        self.summary_label.setText(project.title)
        self._show_summary(project.summary_markdown)
        self.current_course_changed.emit()
        msg = self.lang_manager.get_text("课程总结已重新生成。", "Course summary regenerated.")
        msg = self._with_topic_repair_report(msg, repair_report)
        msg = self._with_summary_warning(msg, project)
        msg = self._with_profile_warning(msg, project)
        msg = self._with_document_warnings(msg, project)
        QMessageBox.information(
            self,
            self.lang_manager.get_text("Summary Updated", "Summary Updated"),
            msg,
        )

    def _is_current_worker(self, attribute: str) -> bool:
        sender = self.sender()
        if sender is None:
            return True
        return sender is getattr(self, attribute, None)

    def _with_topic_repair_report(self, message, report: TopicIdentityRepairReport | None):
        """Append a localized summary of automatic topic-ID repairs."""
        if report is None:
            return message
        parts = []
        if report.updated:
            parts.append(self.lang_manager.get_text(
                f"已修复 {report.updated} 道题目的知识点身份。",
                f"Repaired topic identity for {report.updated} question(s).",
            ))
        if report.unmatched:
            parts.append(self.lang_manager.get_text(
                f"{len(report.unmatched)} 道题无法自动映射，请在题库中人工检查。",
                f"{len(report.unmatched)} question(s) could not be mapped automatically; review them in the question bank.",
            ))
        if report.save_failed:
            parts.append(self.lang_manager.get_text(
                f"{len(report.save_failed)} 道题保存修复结果失败。",
                f"Failed to save topic repairs for {len(report.save_failed)} question(s).",
            ))
        if not parts:
            parts.append(self.lang_manager.get_text(
                "题库知识点身份已检查，无需修复。",
                "Question topic identities were checked; no repairs were needed.",
            ))
        return f"{message}\n\n" + "\n".join(parts)

    def _with_summary_warning(self, message, project):
        """Append a localized notice when LLM generation used the local fallback."""
        warning = str(getattr(project, "summary_warning", "") or "").strip()
        if not warning:
            return message
        fallback = self.lang_manager.get_text(
            "LLM 总结生成失败，已保存本地总结。原因：",
            "LLM summary generation failed; a local summary was saved. Reason:",
        )
        return f"{message}\n\n{fallback} {warning}"

    def _with_profile_warning(self, message, project):
        """Append a localized notice when course-specific defaults used fallback."""
        warning = str(getattr(project, "generation_profile_warning", "") or "").strip()
        if not warning:
            return message
        fallback = self.lang_manager.get_text(
            "课程默认出题配置已使用本地方案。原因：",
            "Course quiz defaults used the local fallback. Reason:",
        )
        return f"{message}\n\n{fallback} {warning}"

    def _with_document_warnings(self, message, project):
        """Append a bounded, localized summary of document extraction warnings."""
        warnings = []
        for document in getattr(project, "documents", []) or []:
            source = Path(str(document.get("path", ""))).name
            source = source or str(document.get("title", "")) or "unknown"
            for warning in document.get("warnings", []) or []:
                warning_text = str(warning).strip()
                if warning_text:
                    warnings.append((source, warning_text))
        if not warnings:
            return message

        lines = [
            self.lang_manager.get_text(
                "资料解析警告：",
                "Course material extraction warnings:",
            )
        ]
        lines.extend(f"- {source}: {warning}" for source, warning in warnings[:3])
        remaining = len(warnings) - 3
        if remaining > 0:
            lines.append(self.lang_manager.get_text(
                f"- 另有 {remaining} 条警告未显示。",
                f"- {remaining} more warning(s) not shown.",
            ))
        if _contains_ocr_warning(warning for _, warning in warnings):
            lines.append("")
            lines.append(self.lang_manager.get_text(
                "OCR 补齐选项：",
                "OCR setup options:",
            ))
            lines.append(OCR_REMEDIATION)
        return f"{message}\n\n" + "\n".join(lines)

    def _on_regen_error(self, error_msg):
        if not self._is_current_worker("_regen_worker"):
            return
        self._regen_worker = None
        self._finish_task("fail", error=error_msg)
        self._set_course_task_active(False)
        QMessageBox.critical(
            self,
            self.lang_manager.get_text("重新生成总结失败", "Regeneration Failed"),
            error_msg,
        )

    def _toggle_summary_mode(self):
        """Switch between rendered summary and raw Markdown for the current course."""
        self._summary_raw_mode = not self._summary_raw_mode
        self._render_summary_preview()

    def _update_content_header(self, project) -> None:
        if project is None:
            self.summary_label.setText(self.lang_manager.get_text("摘要预览", "Summary preview"))
            return
        section_labels = {
            "sources": ("资料", "Sources"),
            "knowledge": ("知识点", "Knowledge"),
        }
        labels = section_labels.get(self._active_section)
        if labels is None:
            self.summary_label.setText(project.title)
            return
        zh, en = labels
        self.summary_label.setText(self.lang_manager.get_text(
            f"{zh} · {project.title}",
            f"{en} · {project.title}",
        ))

    def _show_summary(self, markdown: str):
        """Display course summary as rendered Markdown by default."""
        self._summary_markdown = str(markdown or "")[:20000]
        self._render_summary_preview()

    def _clear_summary(self):
        self._summary_markdown = ""
        self._active_section = "overview"
        self.summary_preview.setPlainText(self.lang_manager.get_text(
            "选择左侧课程查看摘要；如果还没有课程，请先导入课程资料。",
            "Select a course on the left to view its summary. If none exist, import course materials first.",
        ))
        self.summary_mode_btn.setEnabled(False)
        if hasattr(self, "content_stack"):
            self.content_stack.setCurrentWidget(self.overview_panel)
            self.overview_metrics_label.setVisible(True)
            self.summary_mode_btn.setVisible(True)
        self._update_summary_mode_button_text()

    def _render_summary_preview(self):
        if not self._summary_markdown:
            self._clear_summary()
            return
        self.summary_mode_btn.setEnabled(True)
        if self._summary_raw_mode:
            self.summary_preview.setPlainText(self._summary_markdown)
        else:
            self.summary_preview.setMarkdown(self._summary_markdown)
        self._update_summary_mode_button_text()

    def _update_summary_mode_button_text(self):
        if not hasattr(self, "summary_mode_btn"):
            return
        self.summary_mode_btn.setText(
            self.lang_manager.get_text("渲染预览", "Rendered Preview")
            if self._summary_raw_mode
            else self.lang_manager.get_text("原文 Markdown", "Raw Markdown")
        )
