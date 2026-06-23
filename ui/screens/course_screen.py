"""Course project screen — import materials and manage active course context."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox, QTextEdit,
    QSplitter, QGroupBox, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from core.course_initializer import CourseInitializer
from models.course_project import CourseProjectManager
from core.language_manager import LanguageManager
from config import SETTINGS_FILE
from utils.json_io import read_json


class CourseScreen(QWidget):
    """Import folders of course files and choose the active course project."""

    current_course_changed = pyqtSignal()

    def __init__(self, manager: CourseProjectManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.initializer = CourseInitializer(manager)
        self.lang_manager = LanguageManager.instance()
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
        self.list_label.setText(self.lang_manager.get_text("已导入的课程:", "Imported courses:"))
        self.set_current_btn.setText(self.lang_manager.get_text("设为当前", "Set Current"))
        self.regenerate_btn.setText(self.lang_manager.get_text("Regenerate Summary", "Regenerate Summary"))
        self.delete_btn.setText(self.lang_manager.get_text("删除课程", "Delete Course"))
        self.refresh_btn.setText(self.lang_manager.get_text("刷新", "Refresh"))
        self.summary_label.setText(self.lang_manager.get_text("摘要预览", "Summary preview"))
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.title = QLabel(self.lang_manager.get_text("课程资料", "Course Materials"))
        self.title.setStyleSheet("font-size: 20px; font-weight: bold; padding-bottom: 8px;")
        layout.addWidget(self.title)

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
        self.init_btn.clicked.connect(self._initialize_course)
        title_row.addWidget(self.init_btn)
        import_layout.addLayout(title_row)

        layout.addWidget(self.import_group)

        # Progress bar for import
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.list_label = QLabel(self.lang_manager.get_text("已导入的课程:", "Imported courses:"))
        left_layout.addWidget(self.list_label)
        self.project_list = QListWidget()
        self.project_list.currentItemChanged.connect(self._on_project_selected)
        left_layout.addWidget(self.project_list, 1)

        btn_row = QHBoxLayout()
        self.set_current_btn = QPushButton(self.lang_manager.get_text("设为当前", "Set Current"))
        self.set_current_btn.clicked.connect(self._set_current)
        btn_row.addWidget(self.set_current_btn)
        self.regenerate_btn = QPushButton(self.lang_manager.get_text("Regenerate Summary", "Regenerate Summary"))
        self.regenerate_btn.clicked.connect(self._regenerate_selected_project)
        btn_row.addWidget(self.regenerate_btn)
        self.delete_btn = QPushButton(self.lang_manager.get_text("删除课程", "Delete Course"))
        self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self._delete_selected_project)
        btn_row.addWidget(self.delete_btn)
        self.refresh_btn = QPushButton(self.lang_manager.get_text("刷新", "Refresh"))
        self.refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.refresh_btn)
        left_layout.addLayout(btn_row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_label = QLabel(self.lang_manager.get_text("摘要预览", "Summary preview"))
        self.summary_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.summary_label)
        self.summary_preview = QTextEdit()
        self.summary_preview.setReadOnly(True)
        self.summary_preview.setStyleSheet("font-family: Consolas, 'Microsoft YaHei'; font-size: 12px;")
        right_layout.addWidget(self.summary_preview, 1)
        splitter.addWidget(right)
        splitter.setSizes([280, 620])

        layout.addWidget(splitter, 1)

    def refresh(self):
        """Reload projects from disk."""
        self.project_list.clear()
        current = self.manager.current()
        current_id = current.course_id if current else ""
        topics_label = self.lang_manager.get_text("个主题", "topics")
        for project in self.manager.load_all():
            prefix = "★ " if project.course_id == current_id else ""
            item = QListWidgetItem(f"{prefix}{project.title}  [{len(project.topics)} {topics_label}]")
            item.setData(Qt.ItemDataRole.UserRole, project.course_id)
            self.project_list.addItem(item)
        self.set_current_btn.setEnabled(False)
        self.regenerate_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        if current:
            current_label = self.lang_manager.get_text("当前:", "Current:")
            self.summary_label.setText(f"{current_label} {current.title}")
            self.summary_preview.setPlainText(current.summary_markdown[:20000])
        else:
            self.summary_label.setText(self.lang_manager.get_text("摘要预览", "Summary preview"))
            self.summary_preview.clear()

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

        self.init_btn.setEnabled(False)
        self.init_btn.setText(self.lang_manager.get_text("解析中...", "Parsing..."))
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate

        self._init_worker = CourseScreen._InitWorker(folder, self.title_input.text(), self._build_initializer())
        self._init_worker.finished.connect(self._on_init_done)
        self._init_worker.error.connect(self._on_init_error)
        self._init_worker.start()

    def _build_initializer(self):
        """Build an initializer using current AI settings when available."""
        from ai.course_summary_factory import create_course_summary_generator
        from core.secrets_manager import SecretsManager

        settings = read_json(SETTINGS_FILE) or {}
        api_key = SecretsManager.instance().get_key()
        summary_generator = create_course_summary_generator(settings, api_key=api_key)
        return CourseInitializer(self.manager, summary_generator=summary_generator)

    def _on_init_done(self, project):
        self.progress_bar.setVisible(False)
        self.init_btn.setEnabled(True)
        self.init_btn.setText(self.lang_manager.get_text("解析并生成总结", "Parse and generate summary"))

        lang = self.lang_manager.current
        if lang == "zh":
            msg = f"已初始化 '{project.title}'，包含 {len(project.documents)} 个文件和 {len(project.topics)} 个主题。"
        else:
            msg = f"Initialized '{project.title}' with {len(project.documents)} files and {len(project.topics)} topics."
        msg = self._with_summary_warning(msg, project)
        QMessageBox.information(
            self,
            self.lang_manager.get_text("课程就绪", "Course Ready"),
            msg,
        )
        self.refresh()
        self.current_course_changed.emit()

    def _on_init_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.init_btn.setEnabled(True)
        self.init_btn.setText(self.lang_manager.get_text("解析并生成总结", "Parse and generate summary"))
        QMessageBox.critical(
            self,
            self.lang_manager.get_text("初始化失败", "Initialization Failed"),
            error_msg,
        )


    class _InitWorker(QThread):
        """Background worker for course initialization."""
        finished = pyqtSignal(object)  # CourseProject
        error = pyqtSignal(str)

        def __init__(self, folder, title, initializer):
            super().__init__()
            self._folder = folder
            self._title = title
            self._initializer = initializer

        def run(self):
            try:
                project = self._initializer.initialize(self._folder, self._title)
                self.finished.emit(project)
            except Exception as exc:
                self.error.emit(str(exc))


    class _RegenWorker(QThread):
        """Background worker for course summary regeneration."""
        finished = pyqtSignal(object)
        error = pyqtSignal(str)

        def __init__(self, project, initializer):
            super().__init__()
            self._project = project
            self._initializer = initializer

        def run(self):
            try:
                project = self._initializer.regenerate_summary(self._project)
                self.finished.emit(project)
            except Exception as exc:
                self.error.emit(str(exc))

    def _on_project_selected(self, current, previous):
        if current is None:
            self.set_current_btn.setEnabled(False)
            self.regenerate_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return
        self.set_current_btn.setEnabled(True)
        self.regenerate_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.summary_label.setText(project.title)
        self.summary_preview.setPlainText(project.summary_markdown[:20000])


    def _regenerate_selected_project(self):
        current = self.project_list.currentItem()
        if not current:
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return

        self.regenerate_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.init_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        self._regen_worker = CourseScreen._RegenWorker(project, self._build_initializer())
        self._regen_worker.finished.connect(self._on_regen_done)
        self._regen_worker.error.connect(self._on_regen_error)
        self._regen_worker.start()

    def _delete_selected_project(self):
        current = self.project_list.currentItem()
        if not current:
            return
        course_id = current.data(Qt.ItemDataRole.UserRole)
        project = self.manager.get(course_id)
        if not project:
            return
        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("删除课程", "Delete Course"),
            self.lang_manager.get_text(
                f"确定删除课程“{project.title}”吗？这会删除生成的课程摘要，但不会删除原始课件文件夹。",
                f"Delete course '{project.title}'? This removes the generated summary but not the original material folder.",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self.manager.delete(course_id):
            QMessageBox.critical(
                self,
                self.lang_manager.get_text("删除失败", "Delete Failed"),
                self.lang_manager.get_text("课程项目删除失败。", "Failed to delete the course project."),
            )
            return
        self.summary_preview.clear()
        self.current_course_changed.emit()
        self.refresh()

    def _on_regen_done(self, project):
        self.progress_bar.setVisible(False)
        self.init_btn.setEnabled(True)
        self.regenerate_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.refresh()
        self.summary_label.setText(project.title)
        self.summary_preview.setPlainText(project.summary_markdown[:20000])
        self.current_course_changed.emit()
        msg = self.lang_manager.get_text("课程总结已重新生成。", "Course summary regenerated.")
        msg = self._with_summary_warning(msg, project)
        QMessageBox.information(
            self,
            self.lang_manager.get_text("Summary Updated", "Summary Updated"),
            msg,
        )

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

    def _on_regen_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.init_btn.setEnabled(True)
        self.regenerate_btn.setEnabled(self.project_list.currentItem() is not None)
        self.delete_btn.setEnabled(self.project_list.currentItem() is not None)
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
