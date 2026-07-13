"""Historical-exam import and source management workbench."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.background_task import BackgroundTaskCancelled, TaskControl
from core.language_manager import LanguageManager
from core.past_exam_analyzer import PastExamAnalysisService
from core.past_exam_importer import PastExamImporter


_MAX_PREVIEW_CHARS = 40000


class PastExamImportWorker(QThread):
    imported = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    progress = pyqtSignal(object)

    def __init__(self, importer, source_path, title, manual_course_id, parent=None):
        super().__init__(parent)
        self.importer = importer
        self.source_path = Path(source_path)
        self.title = title
        self.manual_course_id = manual_course_id
        self.control = TaskControl(self.progress.emit)

    def run(self):
        try:
            result = self.importer.import_file(
                self.source_path,
                title=self.title,
                manual_course_id=self.manual_course_id,
                task=self.control,
            )
            self.imported.emit(result)
        except BackgroundTaskCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self):
        self.control.cancel()


class PastExamAnalysisWorker(QThread):
    analyzed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    progress = pyqtSignal(object)

    def __init__(self, service, exam_id, parent=None):
        super().__init__(parent)
        self.service = service
        self.exam_id = exam_id
        self.control = TaskControl(self.progress.emit)

    def run(self):
        try:
            self.analyzed.emit(self.service.analyze(self.exam_id, task=self.control))
        except BackgroundTaskCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self):
        self.control.cancel()


class PastExamScreen(QWidget):
    """Import, preview and assign historical exam source documents."""

    def __init__(self, manager, course_manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.course_manager = course_manager
        self.lang_manager = LanguageManager.instance()
        self._import_worker = None
        self._analysis_worker = None
        self._courses = []
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("screenTitle")
        layout.addWidget(self.title_label)

        import_grid = QGridLayout()
        import_grid.setHorizontalSpacing(10)
        import_grid.setVerticalSpacing(8)
        self.file_input = QLineEdit()
        self.file_input.setReadOnly(True)
        self.browse_btn = QPushButton()
        self.browse_btn.setObjectName("secondaryButton")
        self.browse_btn.clicked.connect(self._browse_file)
        import_grid.addWidget(self.file_input, 0, 0, 1, 3)
        import_grid.addWidget(self.browse_btn, 0, 3)

        self.title_input = QLineEdit()
        self.import_course_combo = QComboBox()
        self.import_btn = QPushButton()
        self.import_btn.setObjectName("primaryButton")
        self.import_btn.clicked.connect(self._start_import)
        import_grid.addWidget(self.title_input, 1, 0, 1, 2)
        import_grid.addWidget(self.import_course_combo, 1, 2)
        import_grid.addWidget(self.import_btn, 1, 3)
        import_grid.setColumnStretch(0, 1)
        import_grid.setColumnStretch(1, 1)
        import_grid.setColumnStretch(2, 1)
        layout.addLayout(import_grid)

        progress_row = QHBoxLayout()
        self.progress_label = QLabel()
        self.progress_label.setObjectName("pastExamProgressLabel")
        self.progress_label.hide()
        progress_row.addWidget(self.progress_label, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        progress_row.addWidget(self.progress_bar, 2)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self._cancel_import)
        self.cancel_btn.hide()
        progress_row.addWidget(self.cancel_btn)
        layout.addLayout(progress_row)

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.list_label = QLabel()
        left_layout.addWidget(self.list_label)
        self.exam_list = QListWidget()
        self.exam_list.currentItemChanged.connect(self._show_selected_exam)
        left_layout.addWidget(self.exam_list, 1)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("pastExamEmptyLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        left_layout.addWidget(self.empty_label, 1)
        self.workspace_splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.assignment_status = QLabel()
        self.assignment_status.setObjectName("pastExamAssignmentStatus")
        self.assignment_status.setWordWrap(True)
        right_layout.addWidget(self.assignment_status)
        assignment_row = QHBoxLayout()
        self.assignment_combo = QComboBox()
        assignment_row.addWidget(self.assignment_combo, 1)
        self.save_assignment_btn = QPushButton()
        self.save_assignment_btn.setObjectName("secondaryButton")
        self.save_assignment_btn.clicked.connect(self._save_assignment)
        assignment_row.addWidget(self.save_assignment_btn)
        right_layout.addLayout(assignment_row)
        self.metadata_label = QLabel()
        self.metadata_label.setObjectName("pastExamMetadata")
        self.metadata_label.setWordWrap(True)
        right_layout.addWidget(self.metadata_label)
        analysis_row = QHBoxLayout()
        self.analysis_summary = QLabel()
        self.analysis_summary.setObjectName("pastExamAnalysisSummary")
        self.analysis_summary.setWordWrap(True)
        analysis_row.addWidget(self.analysis_summary, 1)
        self.analyze_btn = QPushButton()
        self.analyze_btn.setObjectName("secondaryButton")
        self.analyze_btn.clicked.connect(self._start_analysis)
        analysis_row.addWidget(self.analyze_btn, 0, Qt.AlignmentFlag.AlignTop)
        right_layout.addLayout(analysis_row)
        self.content_preview = QTextBrowser()
        self.content_preview.setObjectName("pastExamContentPreview")
        self.content_preview.setReadOnly(True)
        right_layout.addWidget(self.content_preview, 1)
        self.workspace_splitter.addWidget(right)
        self.workspace_splitter.setSizes([300, 650])
        layout.addWidget(self.workspace_splitter, 1)
        self._on_language_changed()

    def _on_language_changed(self, _lang=None):
        gm = self.lang_manager.get_text
        self.title_label.setText(gm("历史真题", "Historical Exams"))
        self.file_input.setPlaceholderText(gm(
            "选择 txt/md/pdf/docx/pptx 真题文件",
            "Choose a txt/md/pdf/docx/pptx exam file",
        ))
        self.browse_btn.setText(gm("浏览", "Browse"))
        self.title_input.setPlaceholderText(gm("真题名称（可选）", "Exam title (optional)"))
        self.import_btn.setText(gm("导入真题", "Import Exam"))
        self.cancel_btn.setText(gm("停止", "Stop"))
        self.list_label.setText(gm("已导入真题", "Imported Exams"))
        self.empty_label.setText(gm(
            "还没有历史真题。请在上方选择文件导入。",
            "No historical exams yet. Choose a file above to import one.",
        ))
        self.save_assignment_btn.setText(gm("保存课程归属", "Save Course Assignment"))
        self.analyze_btn.setText(gm("分析真题", "Analyze Exam"))
        self._reload_course_choices()
        self.refresh()

    def _reload_course_choices(self):
        import_selection = self.import_course_combo.currentData()
        assignment_selection = self.assignment_combo.currentData()
        self._courses = self.course_manager.load_all() if self.course_manager else []

        self.import_course_combo.clear()
        self.import_course_combo.addItem(
            self.lang_manager.get_text("自动匹配课程", "Auto-match Course"),
            None,
        )
        self.import_course_combo.addItem(
            self.lang_manager.get_text("暂不归属", "Leave Unassigned"),
            "",
        )
        self.assignment_combo.clear()
        self.assignment_combo.addItem(
            self.lang_manager.get_text("未归属", "Unassigned"),
            "",
        )
        for course in self._courses:
            self.import_course_combo.addItem(course.title, course.course_id)
            self.assignment_combo.addItem(course.title, course.course_id)
        self._restore_combo_data(self.import_course_combo, import_selection)
        self._restore_combo_data(self.assignment_combo, assignment_selection)

    @staticmethod
    def _restore_combo_data(combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def refresh(self):
        selected_id = self._selected_exam_id()
        self.exam_list.clear()
        records = self.manager.load_all()
        course_titles = {course.course_id: course.title for course in self._courses}
        for record in records:
            course_label = course_titles.get(record.course_id) or self.lang_manager.get_text(
                "未归属", "Unassigned"
            )
            item = QListWidgetItem(f"{record.title}  [{course_label}]")
            item.setData(Qt.ItemDataRole.UserRole, record.exam_id)
            self.exam_list.addItem(item)
            if record.exam_id == selected_id:
                self.exam_list.setCurrentItem(item)
        is_empty = not records
        self.exam_list.setVisible(not is_empty)
        self.empty_label.setVisible(is_empty)
        if is_empty:
            self._clear_preview()
        elif self.exam_list.currentRow() < 0:
            self.exam_list.setCurrentRow(0)

    def _browse_file(self):
        path, _filter = QFileDialog.getOpenFileName(
            self,
            self.lang_manager.get_text("选择历史真题", "Choose Historical Exam"),
            "",
            "Exam Files (*.txt *.md *.pdf *.docx *.pptx);;All Files (*)",
        )
        if path:
            self.file_input.setText(path)
            if not self.title_input.text().strip():
                self.title_input.setText(Path(path).stem)

    def _create_import_worker(self):
        selected_course = self.import_course_combo.currentData()
        # Empty string is an explicit unassigned choice; None enables automatic matching.
        manual_course_id = selected_course
        importer = PastExamImporter(self.manager, self.course_manager)
        return PastExamImportWorker(
            importer,
            Path(self.file_input.text()),
            self.title_input.text().strip(),
            manual_course_id,
            self,
        )

    def _start_import(self):
        source = Path(self.file_input.text())
        if not source.exists() or not source.is_file():
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("未选择文件", "No File Selected"),
                self.lang_manager.get_text("请选择有效的历史真题文件。", "Choose a valid historical exam file."),
            )
            return
        worker = self._create_import_worker()
        self._import_worker = worker
        worker.imported.connect(self._on_imported)
        worker.failed.connect(self._on_import_failed)
        worker.cancelled.connect(self._on_import_cancelled)
        worker.progress.connect(self._on_import_progress)
        worker.finished.connect(self._on_import_worker_finished)
        self._set_import_busy(True)
        worker.start()

    def _cancel_import(self):
        if self._import_worker is not None or self._analysis_worker is not None:
            self.cancel_active_task()
            self.progress_label.setText(self.lang_manager.get_text("正在停止…", "Stopping…"))
            self.cancel_btn.setEnabled(False)

    def _on_import_progress(self, progress):
        labels = {
            "hashing_source": self.lang_manager.get_text("校验文件", "Checking file"),
            "parsing_page": self.lang_manager.get_text("解析页面/OCR", "Parsing pages/OCR"),
            "copying_source": self.lang_manager.get_text("复制原文件", "Copying source"),
            "publishing": self.lang_manager.get_text("保存真题", "Saving exam"),
            "loading_exam": self.lang_manager.get_text("读取真题", "Loading exam"),
            "analyzing_structure": self.lang_manager.get_text("识别题型结构", "Analyzing structure"),
            "analyzing_topics": self.lang_manager.get_text("匹配课程知识点", "Matching course topics"),
            "saving_analysis": self.lang_manager.get_text("保存真题画像", "Saving exam profile"),
            "analysis_complete": self.lang_manager.get_text("分析完成", "Analysis complete"),
        }
        label = labels.get(progress.stage, progress.stage)
        self.progress_label.setText(f"{label}  {progress.detail}".strip())
        if progress.total > 0:
            self.progress_bar.setRange(0, progress.total)
            self.progress_bar.setValue(min(progress.current, progress.total))
        else:
            self.progress_bar.setRange(0, 0)

    def _on_imported(self, result):
        self._finish_import()
        self.refresh()
        self._select_exam(result.record.exam_id)
        message = (
            self.lang_manager.get_text("该文件已导入，已定位到现有记录。", "This file was already imported; the existing record is selected.")
            if result.duplicate
            else self.lang_manager.get_text("历史真题已导入。", "Historical exam imported.")
        )
        QMessageBox.information(
            self,
            self.lang_manager.get_text("导入完成", "Import Complete"),
            message,
        )

    def _on_import_failed(self, message):
        self._finish_import()
        QMessageBox.critical(
            self,
            self.lang_manager.get_text("导入失败", "Import Failed"),
            str(message),
        )

    def _on_import_cancelled(self):
        self._finish_import()
        self.progress_label.setText(self.lang_manager.get_text("导入已停止", "Import stopped"))

    def _finish_import(self):
        self._set_import_busy(False)

    def _on_import_worker_finished(self):
        sender = self.sender()
        if sender is self._import_worker:
            self._import_worker = None

    def _set_import_busy(self, busy):
        for widget in (
            self.file_input,
            self.browse_btn,
            self.title_input,
            self.import_course_combo,
            self.import_btn,
        ):
            widget.setEnabled(not busy)
        self.progress_label.setVisible(busy)
        self.progress_bar.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)

    def _show_selected_exam(self, current, _previous=None):
        if current is None:
            self._clear_preview()
            return
        record = self.manager.get(current.data(Qt.ItemDataRole.UserRole))
        if record is None:
            self._clear_preview()
            return
        course = self.course_manager.get(record.course_id) if record.course_id else None
        course_title = getattr(course, "title", "") or self.lang_manager.get_text("未归属", "Unassigned")
        mode_labels = {
            "manual": self.lang_manager.get_text("手动", "manual"),
            "auto": self.lang_manager.get_text("自动匹配", "auto-matched"),
            "unassigned": self.lang_manager.get_text("待确认", "needs review"),
        }
        assignment_text = self.lang_manager.get_text(
            f"课程归属：{course_title}（{mode_labels.get(record.assignment_mode, record.assignment_mode)}）",
            f"Course: {course_title} ({mode_labels.get(record.assignment_mode, record.assignment_mode)})",
        )
        if not record.course_id and record.match_candidates:
            candidate = record.match_candidates[0]
            candidate_title = str(candidate.get("course_title", "") or candidate.get("course_id", ""))
            score = round(float(candidate.get("score", 0.0) or 0.0) * 100)
            terms = ", ".join(str(term) for term in candidate.get("matched_terms", [])[:3])
            assignment_text += self.lang_manager.get_text(
                f"\n建议候选：{candidate_title}（{score}%）" + (f" · 命中：{terms}" if terms else ""),
                f"\nSuggested: {candidate_title} ({score}%)" + (f" · matched: {terms}" if terms else ""),
            )
        self.assignment_status.setText(assignment_text)
        self._restore_combo_data(self.assignment_combo, record.course_id)
        content = self.manager.get_content(record.exam_id)
        warning_text = "；".join(record.warnings[:3]) if record.warnings else self.lang_manager.get_text("无解析警告", "No extraction warnings")
        self.metadata_label.setText(self.lang_manager.get_text(
            f"来源：{record.source_filename}  ·  页数：{len((content or _EMPTY_CONTENT).pages)}\n{warning_text}",
            f"Source: {record.source_filename}  ·  Pages: {len((content or _EMPTY_CONTENT).pages)}\n{warning_text}",
        ))
        text = content.text if content else ""
        if len(text) > _MAX_PREVIEW_CHARS:
            text = text[:_MAX_PREVIEW_CHARS] + self.lang_manager.get_text(
                "\n\n……\n预览已截断；完整文本仍保存在真题记录中。",
                "\n\n…\nPreview truncated; the full text remains stored in the exam record.",
            )
        self.content_preview.setPlainText(text)
        self.assignment_combo.setEnabled(True)
        self.save_assignment_btn.setEnabled(True)
        self._show_analysis(record)

    def _show_analysis(self, record):
        analysis = self.manager.get_analysis(record.exam_id)
        gm = self.lang_manager.get_text
        self.analyze_btn.setEnabled(bool(record.course_id) and self._analysis_worker is None)
        self.analyze_btn.setText(gm(
            "重新分析" if analysis else "分析真题",
            "Reanalyze" if analysis else "Analyze Exam",
        ))
        if not record.course_id:
            self.analysis_summary.setText(gm(
                "请先归属课程，再分析题型与知识点。",
                "Assign a course before analyzing question types and topics.",
            ))
            return
        if analysis is None:
            self.analysis_summary.setText(gm(
                "尚未分析。画像仅采用明确题型分节和课程知识点命中证据。",
                "Not analyzed yet. The profile uses explicit sections and course-topic evidence only.",
            ))
            return
        type_labels = {
            "multiple_choice": gm("选择题", "Multiple choice"),
            "scenario_choice": gm("情境选择题", "Scenario choice"),
            "true_false": gm("判断题", "True/false"),
            "fill_in_blank": gm("填空题", "Fill in the blank"),
            "matching": gm("匹配题", "Matching"),
            "ordering": gm("排序题", "Ordering"),
            "short_answer": gm("简答/主观题", "Short answer / essay"),
        }
        type_text = " · ".join(
            f"{type_labels.get(item.question_type, item.question_type)} {item.count}"
            for item in analysis.question_types
        ) or gm("未识别明确题型", "No explicit types detected")
        topic_parts = []
        for item in analysis.topic_profile[:5]:
            if item.weight <= 0:
                continue
            terms = ", ".join(item.matched_terms[:3])
            part = f"{item.topic_title} {item.weight}%"
            if terms:
                part += gm(f"（命中：{terms}）", f" (matched: {terms})")
            topic_parts.append(part)
        topic_text = " · ".join(topic_parts) or gm("未找到可靠知识点证据", "No reliable topic evidence")
        self.analysis_summary.setText(gm(
            f"画像：{analysis.detected_question_count} 题 · {type_text}\n知识点：{topic_text}",
            f"Profile: {analysis.detected_question_count} questions · {type_text}\nTopics: {topic_text}",
        ))

    def _start_analysis(self):
        exam_id = self._selected_exam_id()
        if not exam_id or self._analysis_worker is not None:
            return
        service = PastExamAnalysisService(self.manager, self.course_manager)
        worker = PastExamAnalysisWorker(service, exam_id, self)
        self._analysis_worker = worker
        worker.analyzed.connect(lambda _analysis: self._on_analyzed(exam_id))
        worker.failed.connect(self._on_analysis_failed)
        worker.cancelled.connect(self._on_analysis_cancelled)
        worker.progress.connect(self._on_import_progress)
        worker.finished.connect(self._on_analysis_worker_finished)
        self._set_import_busy(True)
        self.analyze_btn.setEnabled(False)
        worker.start()

    def _on_analyzed(self, exam_id):
        self._finish_import()
        self.refresh()
        self._select_exam(exam_id)

    def _on_analysis_failed(self, message):
        self._finish_import()
        QMessageBox.critical(
            self,
            self.lang_manager.get_text("分析失败", "Analysis Failed"),
            str(message),
        )

    def _on_analysis_cancelled(self):
        self._finish_import()

    def _on_analysis_worker_finished(self):
        sender = self.sender()
        if sender is self._analysis_worker:
            self._analysis_worker = None
            current = self.manager.get(self._selected_exam_id())
            if current is not None:
                self._show_analysis(current)

    def _save_assignment(self):
        exam_id = self._selected_exam_id()
        if not exam_id:
            return
        course_id = str(self.assignment_combo.currentData() or "")
        try:
            updated = self.manager.reassign_course(exam_id, course_id)
        except OSError as exc:
            QMessageBox.critical(
                self,
                self.lang_manager.get_text("保存失败", "Save Failed"),
                str(exc),
            )
            return
        if updated is not None:
            self.refresh()
            self._select_exam(exam_id)

    def _selected_exam_id(self):
        item = self.exam_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _select_exam(self, exam_id):
        for row in range(self.exam_list.count()):
            item = self.exam_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == exam_id:
                self.exam_list.setCurrentRow(row)
                return

    def _clear_preview(self):
        self.assignment_status.clear()
        self.metadata_label.clear()
        self.content_preview.clear()
        self.analysis_summary.clear()
        self.assignment_combo.setEnabled(False)
        self.save_assignment_btn.setEnabled(False)
        self.analyze_btn.setEnabled(False)

    def cancel_active_task(self):
        if self._import_worker is not None:
            self._import_worker.cancel()
        if self._analysis_worker is not None:
            self._analysis_worker.cancel()

    def request_shutdown(self) -> bool:
        """Cooperatively stop OCR/import without blocking the GUI thread."""
        import_running = self._import_worker is not None and self._import_worker.isRunning()
        analysis_running = self._analysis_worker is not None and self._analysis_worker.isRunning()
        if not import_running and not analysis_running:
            return True
        self.cancel_active_task()
        return False


class _EmptyContent:
    pages = []


_EMPTY_CONTENT = _EmptyContent()
