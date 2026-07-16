"""Explicit current-events search, review, and material-pack creation."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.app_errors import format_app_error
from core.current_events import (
    CurrentEventMaterialManager,
    CurrentEventMaterialPack,
    CurrentEventsError,
    GDELTContextProvider,
    build_course_event_query,
    review_course_events,
)
from core.language_manager import LanguageManager
from ui.widgets.wheel_safe_controls import WheelSafeSpinBox


class CurrentEventSearchWorker(QThread):
    succeeded = pyqtSignal(list)
    failed = pyqtSignal(object)

    def __init__(self, provider, query: str, hours: int, limit: int, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.query = query
        self.hours = hours
        self.limit = limit

    def run(self) -> None:
        try:
            candidates = self.provider.search(
                self.query,
                hours=self.hours,
                limit=self.limit,
            )
        except CurrentEventsError as exc:
            self.failed.emit(exc.error)
        except Exception as exc:
            self.failed.emit(exc)
        else:
            self.succeeded.emit(candidates)


class CurrentEventReviewDialog(QDialog):
    """Keep network search opt-in and require selection before persistence."""

    CANDIDATE_ID_ROLE = int(Qt.ItemDataRole.UserRole)
    MATCH_ROLE = CANDIDATE_ID_ROLE + 1

    def __init__(
        self,
        project,
        *,
        provider=None,
        material_manager=None,
        parent=None,
    ):
        super().__init__(parent)
        self.project = project
        self.provider = provider or GDELTContextProvider()
        self.material_manager = material_manager or CurrentEventMaterialManager()
        self.lang_manager = LanguageManager.instance()
        self.search_worker = None
        self._candidates = []
        self.saved_pack = None
        self.generate_after_save = False
        self._setup_ui()
        self._on_language_changed(self.lang_manager.current)
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self) -> None:
        self.resize(980, 680)
        self.setMinimumSize(760, 540)
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

        query_row = QHBoxLayout()
        self.query_input = QLineEdit(build_course_event_query(self.project))
        self.query_input.setClearButtonEnabled(True)
        query_row.addWidget(self.query_input, 1)
        self.hours_input = WheelSafeSpinBox()
        self.hours_input.setRange(1, 24)
        self.hours_input.setValue(24)
        query_row.addWidget(self.hours_input)
        self.limit_input = WheelSafeSpinBox()
        self.limit_input.setRange(1, 25)
        self.limit_input.setValue(15)
        query_row.addWidget(self.limit_input)
        self.search_btn = QPushButton()
        self.search_btn.setObjectName("secondaryButton")
        self.search_btn.clicked.connect(self._start_search)
        query_row.addWidget(self.search_btn)
        layout.addLayout(query_row)

        self.status_label = QLabel()
        self.status_label.setObjectName("secondaryText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.candidate_list = QTreeWidget()
        self.candidate_list.setRootIsDecorated(False)
        self.candidate_list.setAlternatingRowColors(True)
        self.candidate_list.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.candidate_list.itemChanged.connect(lambda _item, _column: self._update_actions())
        self.candidate_list.itemSelectionChanged.connect(self._update_detail)
        layout.addWidget(self.candidate_list, 1)

        self.detail_view = QPlainTextEdit()
        self.detail_view.setObjectName("currentEventDetail")
        self.detail_view.setReadOnly(True)
        self.detail_view.setMaximumHeight(170)
        layout.addWidget(self.detail_view)

        footer = QHBoxLayout()
        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)
        footer.addStretch(1)
        self.save_btn = QPushButton()
        self.save_btn.setObjectName("secondaryButton")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(lambda: self._save_selection(False))
        footer.addWidget(self.save_btn)
        self.save_generate_btn = QPushButton()
        self.save_generate_btn.setObjectName("primaryButton")
        self.save_generate_btn.setEnabled(False)
        self.save_generate_btn.clicked.connect(lambda: self._save_selection(True))
        footer.addWidget(self.save_generate_btn)
        layout.addLayout(footer)

    def _on_language_changed(self, _language) -> None:
        gm = self.lang_manager.get_text
        self.setWindowTitle(gm("热点材料", "Current-Events Materials"))
        self.heading_label.setText(gm(
            f"{self.project.title} · 热点材料",
            f"{self.project.title} · Current-Events Materials",
        ))
        self.help_label.setText(gm(
            "仅在点击检索后联网。可编辑英文检索词；候选不会自动接受或写入题库，请核对来源与时间后再勾选。",
            "The app goes online only after Search. Edit the English query as needed; candidates are never auto-accepted or written to the question bank.",
        ))
        self.query_input.setPlaceholderText(gm("英文检索词", "English search query"))
        self.hours_input.setSuffix(gm(" 小时", " h"))
        self.limit_input.setSuffix(gm(" 条", " results"))
        self.search_btn.setText(gm("检索", "Search"))
        self.candidate_list.setHeaderLabels(
            ["标题", "相关性", "命中主题", "来源", "报道时间", "检索时间"]
            if self.lang_manager.current == "zh"
            else ["Title", "Relevance", "Topics", "Source", "Reported", "Retrieved"]
        )
        self.cancel_btn.setText(gm("取消", "Cancel"))
        self.save_btn.setText(gm("保存材料", "Save Materials"))
        self.save_generate_btn.setText(gm("保存并出题", "Save and Generate"))
        self._update_status_text()
        self._update_detail()

    def _start_search(self) -> None:
        query = self.query_input.text().strip()
        if len(query) < 2:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("检索词无效", "Invalid Query"),
                self.lang_manager.get_text(
                    "请输入至少两个字符的英文检索词。",
                    "Enter an English search query with at least two characters.",
                ),
            )
            return
        if self.search_worker is not None and self.search_worker.isRunning():
            return
        worker = CurrentEventSearchWorker(
            self.provider,
            query,
            self.hours_input.value(),
            self.limit_input.value(),
            self,
        )
        self.search_worker = worker
        worker.succeeded.connect(
            lambda result, source=worker: self._deliver_worker_result(
                source, self._show_candidates, result
            )
        )
        worker.failed.connect(
            lambda error, source=worker: self._deliver_worker_result(
                source, self._show_search_error, error
            )
        )
        worker.finished.connect(
            lambda source=worker: self._finish_search(source)
        )
        self._set_busy(True)
        worker.start()

    def _deliver_worker_result(self, source, handler, *args) -> None:
        if source is self.search_worker:
            handler(*args)

    def _finish_search(self, source) -> None:
        if source is self.search_worker:
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.search_btn.setEnabled(not busy)
        self.query_input.setEnabled(not busy)
        self.hours_input.setEnabled(not busy)
        self.limit_input.setEnabled(not busy)
        if busy:
            self.status_label.setText(self.lang_manager.get_text(
                "正在检索公共新闻索引…",
                "Searching the public news index...",
            ))

    def _show_candidates(self, candidates: list) -> None:
        self._candidates = list(candidates)
        review = review_course_events(self.project, self._candidates)
        self.candidate_list.clear()
        for match in review:
            candidate = match.candidate
            item = QTreeWidgetItem([
                candidate.title,
                self._relevance_text(match.score),
                ", ".join(match.topic_ids),
                candidate.domain,
                candidate.seen_at,
                candidate.retrieved_at,
            ])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, self.CANDIDATE_ID_ROLE, candidate.candidate_id)
            item.setData(0, self.MATCH_ROLE, match)
            self.candidate_list.addTopLevelItem(item)
        for column in range(self.candidate_list.columnCount()):
            self.candidate_list.resizeColumnToContents(column)
        if self.candidate_list.topLevelItemCount():
            self.candidate_list.setCurrentItem(self.candidate_list.topLevelItem(0))
        self._update_status_text()
        self._update_actions()

    def _relevance_text(self, score: int) -> str:
        if score <= 0:
            return self.lang_manager.get_text("低相关", "Low")
        if score >= 10:
            return self.lang_manager.get_text(f"高 · {score}", f"High · {score}")
        return self.lang_manager.get_text(f"相关 · {score}", f"Related · {score}")

    def _update_status_text(self) -> None:
        if self.search_worker is not None and self.search_worker.isRunning():
            return
        count = self.candidate_list.topLevelItemCount()
        selected = len(self._selected_candidate_ids())
        self.status_label.setText(self.lang_manager.get_text(
            f"候选 {count} 条，已选择 {selected} 条。低相关候选保留供人工判断。",
            f"{count} candidate(s), {selected} selected. Low-relevance results remain visible for manual review.",
        ))

    def _update_detail(self) -> None:
        item = self.candidate_list.currentItem()
        match = item.data(0, self.MATCH_ROLE) if item else None
        if match is None:
            self.detail_view.clear()
            return
        candidate = match.candidate
        gm = self.lang_manager.get_text
        self.detail_view.setPlainText("\n".join([
            f"{gm('来源', 'Source')}: {candidate.domain}",
            f"{gm('报道时间', 'Reported')}: {candidate.seen_at}",
            f"{gm('检索时间', 'Retrieved')}: {candidate.retrieved_at}",
            f"{gm('命中词', 'Matched terms')}: {', '.join(match.matched_terms) or gm('无', 'None')}",
            f"URL: {candidate.url}",
            "",
            candidate.context,
        ]))

    def _selected_candidate_ids(self) -> list[str]:
        return [
            str(self.candidate_list.topLevelItem(row).data(0, self.CANDIDATE_ID_ROLE) or "")
            for row in range(self.candidate_list.topLevelItemCount())
            if self.candidate_list.topLevelItem(row).checkState(0) == Qt.CheckState.Checked
        ]

    def _update_actions(self) -> None:
        enabled = bool(self._selected_candidate_ids())
        self.save_btn.setEnabled(enabled)
        self.save_generate_btn.setEnabled(enabled)
        self._update_status_text()

    def _save_selection(self, generate_after_save: bool) -> None:
        selected = self._selected_candidate_ids()
        if not selected:
            return
        pack = CurrentEventMaterialPack.create(
            course_id=self.project.course_id,
            course_updated_at=self.project.updated_at,
            query=self.query_input.text().strip(),
            candidates=self._candidates,
            selected_candidate_ids=selected,
        )
        if not self.material_manager.save(pack):
            QMessageBox.critical(
                self,
                self.lang_manager.get_text("保存失败", "Save Failed"),
                self.lang_manager.get_text(
                    "热点材料包未保存，请检查数据目录后重试。",
                    "The current-events material pack was not saved. Check the data directory and retry.",
                ),
            )
            return
        self.saved_pack = pack
        self.generate_after_save = bool(generate_after_save)
        self.accept()

    def _show_search_error(self, error) -> None:
        if hasattr(error, "status_text"):
            self.status_label.setText(error.status_text(self.lang_manager.current))
            QMessageBox.warning(
                self,
                error.title(self.lang_manager.current),
                format_app_error(error, self.lang_manager.current),
            )
            return
        self.status_label.setText(str(error))
        QMessageBox.warning(
            self,
            self.lang_manager.get_text("检索失败", "Search Failed"),
            str(error),
        )
