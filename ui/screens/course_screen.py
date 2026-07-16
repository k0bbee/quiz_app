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
    QDialog, QRadioButton, QMenu, QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from core.course_initializer import CourseInitializer
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
from config import SETTINGS_FILE
from ui.dialogs.course_exam_scope_dialog import CourseExamScopeDialog
from ui.widgets.course_qa_panel import CourseQAPanel
from utils.json_io import read_json


def _contains_ocr_warning(warnings) -> bool:
    return any(
        "ocr" in str(warning).lower() or "tesseract" in str(warning).lower()
        for warning in warnings
    )


class CourseScreen(QWidget):
    """Import folders of course files and choose the active course project."""

    current_course_changed = pyqtSignal()
    generate_questions_requested = pyqtSignal(str)

    def __init__(
        self,
        manager: CourseProjectManager,
        question_bank=None,
        set_manager=None,
        progress_manager=None,
        snapshot_manager=None,
        parent=None,
        task_center=None,
        qa_service_factory=None,
    ):
        super().__init__(parent)
        self.manager = manager
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.progress_manager = progress_manager
        self.snapshot_manager = snapshot_manager
        self.task_center = task_center
        self.qa_service_factory = qa_service_factory or self._create_qa_service
        self.initializer = CourseInitializer(manager)
        self.lang_manager = LanguageManager.instance()
        self._init_worker = None
        self._regen_worker = None
        self._summary_markdown = ""
        self._summary_raw_mode = False
        self._last_task_progress = None
        self._task_bridge = None
        self._import_expanded = False
        self._setup_ui()
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
        self.generate_questions_btn.setText(self.lang_manager.get_text("生成题目", "Generate Questions"))
        self._update_import_toggle_text()
        self.list_label.setText(self.lang_manager.get_text("已导入的课程:", "Imported courses:"))
        self.set_current_btn.setText(self.lang_manager.get_text("设为当前", "Set Current"))
        self.scope_btn.setText(self.lang_manager.get_text("考试范围", "Exam Scope"))
        self.more_actions_btn.setText(self.lang_manager.get_text("更多操作", "More Actions"))
        self.rename_action.setText(self.lang_manager.get_text("重命名", "Rename"))
        self.regenerate_action.setText(self.lang_manager.get_text("重新生成总结", "Regenerate Summary"))
        self.refresh_action.setText(self.lang_manager.get_text("刷新", "Refresh"))
        self.delete_action.setText(self.lang_manager.get_text("删除课程", "Delete Course"))
        self.summary_label.setText(self.lang_manager.get_text("摘要预览", "Summary preview"))
        self.qa_mode_btn.setText(self.lang_manager.get_text(
            "返回课程总结" if self._qa_mode_active() else "问答巩固",
            "Back to Summary" if self._qa_mode_active() else "Q&A Review",
        ))
        self.qa_panel.retranslate()
        self._update_summary_mode_button_text()
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
        self.list_label = QLabel(self.lang_manager.get_text("已导入的课程:", "Imported courses:"))
        self.left_layout.addWidget(self.list_label)
        self.empty_state_label = QLabel()
        self.empty_state_label.setObjectName("courseEmptyStateLabel")
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setVisible(False)
        self.left_layout.addWidget(self.empty_state_label, 1)
        self.project_list = QListWidget()
        self.project_list.currentItemChanged.connect(self._on_project_selected)
        self.left_layout.addWidget(self.project_list, 1)

        self.generate_questions_btn = QPushButton(
            self.lang_manager.get_text("生成题目", "Generate Questions")
        )
        self.generate_questions_btn.setObjectName("primaryButton")
        self.generate_questions_btn.setEnabled(False)
        self.generate_questions_btn.clicked.connect(self._generate_for_selected_course)
        self.left_layout.addWidget(self.generate_questions_btn)

        self.course_action_layout = QHBoxLayout()
        self.set_current_btn = QPushButton(self.lang_manager.get_text("设为当前", "Set Current"))
        self.set_current_btn.setObjectName("secondaryButton")
        self.set_current_btn.clicked.connect(self._set_current)
        self.course_action_layout.addWidget(self.set_current_btn)
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
        self.refresh_action = QAction(self.lang_manager.get_text("刷新", "Refresh"), self)
        self.refresh_action.triggered.connect(self.refresh)
        self.more_actions_menu.addAction(self.refresh_action)
        self.more_actions_menu.addSeparator()
        self.delete_action = QAction(self.lang_manager.get_text("删除课程", "Delete Course"), self)
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
        summary_header = QHBoxLayout()
        self.summary_label = QLabel(self.lang_manager.get_text("摘要预览", "Summary preview"))
        self.summary_label.setObjectName("courseSummaryLabel")
        summary_header.addWidget(self.summary_label, 1)
        self.qa_mode_btn = QPushButton(self.lang_manager.get_text("问答巩固", "Q&A Review"))
        self.qa_mode_btn.setObjectName("secondaryButton")
        self.qa_mode_btn.setEnabled(False)
        self.qa_mode_btn.clicked.connect(self._toggle_qa_mode)
        summary_header.addWidget(self.qa_mode_btn)
        self.summary_mode_btn = QPushButton()
        self.summary_mode_btn.setObjectName("secondaryButton")
        self.summary_mode_btn.clicked.connect(self._toggle_summary_mode)
        self._update_summary_mode_button_text()
        summary_header.addWidget(self.summary_mode_btn)
        right_layout.addLayout(summary_header)
        self.content_stack = QStackedWidget()
        self.summary_preview = QTextBrowser()
        self.summary_preview.setObjectName("courseSummaryPreview")
        self.summary_preview.setReadOnly(True)
        self.summary_preview.setOpenExternalLinks(False)
        self.content_stack.addWidget(self.summary_preview)
        self.qa_panel = CourseQAPanel(self.qa_service_factory)
        self.content_stack.addWidget(self.qa_panel)
        right_layout.addWidget(self.content_stack, 1)
        splitter.addWidget(right)
        splitter.setSizes([280, 620])

        layout.addWidget(splitter, 1)

    def refresh(self):
        """Reload projects from disk."""
        self.project_list.clear()
        current = self.manager.current()
        current_id = current.course_id if current else ""
        projects = self.manager.load_all()
        for project in projects:
            prefix = "★ " if project.course_id == current_id else ""
            scope_count = len(project.exam_topics())
            scope_label = self.lang_manager.get_text("范围", "scope")
            item = QListWidgetItem(
                f"{prefix}{project.title}  [{scope_count}/{len(project.topics)} {scope_label}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, project.course_id)
            self.project_list.addItem(item)
        is_empty = not projects
        if is_empty:
            self._import_expanded = True
        self.import_group.setVisible(self._import_expanded)
        self.generate_questions_btn.setVisible(not is_empty)
        import_role = "primaryButton" if is_empty else "secondaryButton"
        if self.init_btn.objectName() != import_role:
            self.init_btn.setObjectName(import_role)
            self.init_btn.style().unpolish(self.init_btn)
            self.init_btn.style().polish(self.init_btn)
        self._update_import_toggle_text()
        self.empty_state_label.setText(self.lang_manager.get_text(
            "还没有课程。请在上方选择课程资料文件夹并导入第一个课程。",
            "No courses yet. Choose a course-material folder above and import your first course.",
        ))
        self.empty_state_label.setVisible(is_empty)
        self.project_list.setVisible(not is_empty)
        self.set_current_btn.setEnabled(False)
        self.scope_btn.setEnabled(False)
        self.generate_questions_btn.setEnabled(False)
        self.qa_mode_btn.setEnabled(False)
        self.rename_action.setEnabled(False)
        self.regenerate_action.setEnabled(False)
        self.delete_action.setEnabled(False)
        if projects:
            selected_row = 0
            if current:
                for row in range(self.project_list.count()):
                    if self.project_list.item(row).data(Qt.ItemDataRole.UserRole) == current.course_id:
                        selected_row = row
                        break
            self.project_list.setCurrentRow(selected_row)
        else:
            self.summary_label.setText(self.lang_manager.get_text("摘要预览", "Summary preview"))
            self._clear_summary()
            self.qa_panel.set_course(None)

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

    def _initialize_course(self):
        folder = self.folder_input.text().strip()
        if not folder:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("缺少文件夹", "Missing Folder"),
                self.lang_manager.get_text("请先选择一个课程资料文件夹。", "Please select a course-material folder first.")
            )
            return

        self._init_worker = CourseScreen._InitWorker(folder, self.title_input.text(), self._build_initializer())
        self._init_worker.finished.connect(self._on_init_done)
        self._init_worker.error.connect(self._on_init_error)
        self._init_worker.cancelled.connect(self._on_course_task_cancelled)
        self._init_worker.progress.connect(self._on_course_task_progress)
        self._begin_persistent_task(
            kind="course_import",
            title=self.lang_manager.get_text(
                f"导入课程：{self.title_input.text().strip() or Path(folder).name}",
                f"Import course: {self.title_input.text().strip() or Path(folder).name}",
            ),
            metadata={
                "source_folder": folder,
                "course_title": self.title_input.text().strip(),
            },
            worker=self._init_worker,
        )
        self._set_course_task_active(True)
        self._init_worker.start()

    def _begin_persistent_task(self, *, kind, title, metadata, worker) -> None:
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

    def _finish_persistent_task(self, outcome, **kwargs) -> None:
        bridge = self._task_bridge
        if bridge is None:
            return
        getattr(bridge, outcome)(**kwargs)
        self._task_bridge = None

    def _set_course_task_active(self, active: bool) -> None:
        """Keep all course actions consistent while one background task owns state."""
        if active:
            self.qa_panel.stop_request(show_status=False)
        self.qa_panel.setEnabled(not active)
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
            for button in (
                self.generate_questions_btn,
                self.set_current_btn,
                self.scope_btn,
                self.more_actions_btn,
                self.qa_mode_btn,
            ):
                button.setEnabled(False)
            for action in self.more_actions_menu.actions():
                action.setEnabled(False)
        else:
            self._last_task_progress = None
            self.task_status_label.clear()
            self.init_btn.setText(self.lang_manager.get_text(
                "解析并生成总结", "Parse and generate summary"
            ))
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

    def request_shutdown(self) -> bool:
        """Request cooperative cancellation; never block the GUI thread."""
        workers = [worker for worker in (self._init_worker, self._regen_worker) if worker]
        if not any(worker.isRunning() for worker in workers):
            return True
        self._cancel_course_task()
        return False

    def _on_course_task_progress(self, progress: TaskProgress) -> None:
        sender = self.sender()
        if sender is not None and sender not in (self._init_worker, self._regen_worker):
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

    def _course_task_progress_text(self, progress: TaskProgress) -> str:
        stages = {
            "parsing": ("扫描课程资料", "Scanning course materials"),
            "files_found": ("已发现资料文件", "Course files found"),
            "parsing_file": ("正在解析文件", "Parsing file"),
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
        if sender is self._init_worker:
            self._init_worker = None
        elif sender is self._regen_worker:
            self._regen_worker = None
        elif sender is not None:
            return
        self._finish_persistent_task("cancelled")
        self._set_course_task_active(False)
        QMessageBox.information(
            self,
            self.lang_manager.get_text("已停止", "Stopped"),
            self.lang_manager.get_text(
                "操作已安全停止，未保存未完成的更改。",
                "The operation stopped safely; incomplete changes were not saved.",
            ),
        )

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
        )

    def _on_init_done(self, project):
        if not self._is_current_worker("_init_worker"):
            return
        self._init_worker = None
        self._finish_persistent_task(
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
        QMessageBox.information(
            self,
            self.lang_manager.get_text("课程就绪", "Course Ready"),
            msg,
        )
        self._import_expanded = False
        self.refresh()
        self.current_course_changed.emit()

    def _on_init_error(self, error_msg):
        if not self._is_current_worker("_init_worker"):
            return
        self._init_worker = None
        self._finish_persistent_task("fail", error=error_msg)
        self._set_course_task_active(False)
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
            self.generate_questions_btn.setEnabled(False)
            self.set_current_btn.setEnabled(False)
            self.scope_btn.setEnabled(False)
            self.qa_mode_btn.setEnabled(False)
            self.rename_action.setEnabled(False)
            self.regenerate_action.setEnabled(False)
            self.delete_action.setEnabled(False)
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return
        active = self.manager.current()
        self.set_current_btn.setEnabled(not active or active.course_id != course_id)
        self.generate_questions_btn.setEnabled(True)
        self.scope_btn.setEnabled(True)
        self.qa_mode_btn.setEnabled(True)
        self.rename_action.setEnabled(True)
        self.regenerate_action.setEnabled(True)
        self.delete_action.setEnabled(True)
        self.qa_panel.set_course(project)
        self._update_content_header(project)
        self._show_summary(project.summary_markdown)

    def _generate_for_selected_course(self):
        current_item = self.project_list.currentItem()
        if current_item is None:
            return
        course_id = str(current_item.data(Qt.ItemDataRole.UserRole) or "")
        project = self.manager.get(course_id)
        if project is None:
            return
        active = self.manager.current()
        if active is None or active.course_id != course_id:
            if not self.manager.set_current(course_id):
                QMessageBox.warning(
                    self,
                    self.lang_manager.get_text("切换失败", "Course Switch Failed"),
                    self.lang_manager.get_text(
                        "无法将所选课程设为当前课程，请检查数据目录后重试。",
                        "Could not activate the selected course. Check the data directory and try again.",
                    ),
                )
                return
            self.current_course_changed.emit()
            self.refresh()
        self.generate_questions_requested.emit(course_id)

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
        self._begin_persistent_task(
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
        dialog.setWindowTitle(self.lang_manager.get_text("删除课程", "Delete Course"))
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
                CourseRemovalMode.KEEP_ASSETS,
                self.lang_manager.get_text("仅删除课程资料", "Delete Course Only"),
                self.lang_manager.get_text(
                    "保留题目、题集、学习记录和草稿；以后仍可独立练习。",
                    "Keep questions, sets, learning records, and drafts for independent practice.",
                ),
            ),
            (
                CourseRemovalMode.UNLINK_ASSETS,
                self.lang_manager.get_text("解除关联并删除课程", "Unlink and Delete Course"),
                self.lang_manager.get_text(
                    "保留全部练习数据，但移除课程与来源定位信息。",
                    "Keep all practice data but remove course and source-location links.",
                ),
            ),
            (
                CourseRemovalMode.DELETE_LINKED_BANK,
                self.lang_manager.get_text("删除课程及关联题库", "Delete Course and Linked Bank"),
                self.lang_manager.get_text(
                    "删除关联题目并清理题集和草稿；学习记录仍会保留。",
                    "Delete linked questions and clean sets and drafts; learning records remain.",
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
        radios[CourseRemovalMode.KEEP_ASSETS].setChecked(True)

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
                f"学习记录：{impact.progress_count}（始终保留）\n"
                f"未完成草稿：{impact.snapshot_count}"
            ),
            (
                f"Delete course '{project.title}'\n\n"
                f"Linked questions: {impact.question_count}\n"
                f"Linked question sets: {impact.question_set_count}\n"
                f"Learning records: {impact.progress_count} (always kept)\n"
                f"Unfinished drafts: {impact.snapshot_count}"
            ),
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
        self._finish_persistent_task(
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
        self._finish_persistent_task("fail", error=error_msg)
        self._set_course_task_active(False)
        QMessageBox.critical(
            self,
            self.lang_manager.get_text("Regeneration Failed", "Regeneration Failed"),
            error_msg,
        )

    def _set_current(self):
        current = self.project_list.currentItem()
        if not current:
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        if self.manager.set_current(course_id):
            self.refresh()
            self.current_course_changed.emit()

    def _toggle_summary_mode(self):
        """Switch between rendered summary and raw Markdown for the current course."""
        self._summary_raw_mode = not self._summary_raw_mode
        self._render_summary_preview()

    def _toggle_qa_mode(self):
        """Switch the selected course workspace between summary and grounded Q&A."""
        if self.qa_panel.course is None:
            return
        target = self.summary_preview if self._qa_mode_active() else self.qa_panel
        self.content_stack.setCurrentWidget(target)
        self.summary_mode_btn.setVisible(target is self.summary_preview)
        self.qa_mode_btn.setText(self.lang_manager.get_text(
            "返回课程总结" if target is self.qa_panel else "问答巩固",
            "Back to Summary" if target is self.qa_panel else "Q&A Review",
        ))
        self._update_content_header(self.qa_panel.course)

    def _qa_mode_active(self) -> bool:
        return (
            hasattr(self, "content_stack")
            and hasattr(self, "qa_panel")
            and self.content_stack.currentWidget() is self.qa_panel
        )

    def _update_content_header(self, project) -> None:
        if project is None:
            self.summary_label.setText(self.lang_manager.get_text("摘要预览", "Summary preview"))
            return
        if self._qa_mode_active():
            self.summary_label.setText(self.lang_manager.get_text(
                f"问答巩固 · {project.title}",
                f"Q&A Review · {project.title}",
            ))
        else:
            self.summary_label.setText(project.title)

    def _create_qa_service(self, project):
        """Build a validated course Q&A service from persisted AI settings."""
        from ai.course_qa import CourseQAError, CourseQAService
        from ai.course_summary_factory import provider_requires_api_key
        from ai.llm_client import LLMClient
        from ai.provider_presets import detect_local_agents
        from ai.settings_validation import validate_ai_settings
        from core.app_errors import AppError
        from core.secrets_manager import SecretsManager

        settings = read_json(SETTINGS_FILE) or {}
        api_key = SecretsManager.instance().get_key() if provider_requires_api_key(settings) else ""
        validation = validate_ai_settings(
            settings,
            api_key=api_key,
            detected_agents=detect_local_agents(),
        )
        if not validation.ok:
            raise CourseQAError(AppError(
                code="QA-SETTINGS-001",
                severity="warning",
                title_zh="AI 设置需要处理",
                title_en="AI Settings Need Attention",
                message_zh=validation.message,
                message_en=validation.message,
                action_zh="请到设置页检查服务商、地址、模型和 API Key。",
                action_en="Check the provider, endpoint, model, and API key in Settings.",
                technical_detail=validation.message,
            ))
        client = LLMClient(
            api_key=api_key,
            base_url=settings.get("ai_base_url", "https://api.anthropic.com/v1"),
            model=settings.get("ai_model", "claude-sonnet-4-6"),
            provider=settings.get("ai_provider", ""),
        )
        return CourseQAService(client, project)

    def _show_summary(self, markdown: str):
        """Display course summary as rendered Markdown by default."""
        self._summary_markdown = str(markdown or "")[:20000]
        self._render_summary_preview()

    def _clear_summary(self):
        self._summary_markdown = ""
        self.summary_preview.setPlainText(self.lang_manager.get_text(
            "选择左侧课程查看摘要；如果还没有课程，请先导入课程资料。",
            "Select a course on the left to view its summary. If none exist, import course materials first.",
        ))
        self.summary_mode_btn.setEnabled(False)
        if hasattr(self, "content_stack"):
            self.content_stack.setCurrentWidget(self.summary_preview)
            self.summary_mode_btn.setVisible(True)
        if hasattr(self, "qa_mode_btn"):
            self.qa_mode_btn.setText(self.lang_manager.get_text("问答巩固", "Q&A Review"))
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
