"""Learning setup workspace for daily, free-practice, and mock-exam flows."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.language_manager import LanguageManager
from core.practice_plan_preview import build_practice_plan_preview
from core.practice_selection import select_practice_question_ids
from core.study_intent import StudyAction, StudyIntent
from models.question import QuestionBank
from models.question_set import SetManager
from ui.widgets.wheel_safe_controls import WheelSafeComboBox, WheelSafeSpinBox
from utils.constants import topic_label, topic_value


class TopicSelectionScreen(QWidget):
    """Configure a study session without exposing question-set maintenance."""

    study_start = pyqtSignal(object, list)  # StudyIntent, question_ids
    generate_missing = pyqtSignal(object, int)  # StudyIntent, missing count
    today_mode_requested = pyqtSignal()

    def __init__(
        self,
        set_manager: SetManager,
        progress_manager=None,
        *,
        question_bank: QuestionBank | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.set_manager = set_manager
        self.progress_manager = progress_manager
        self.question_bank = question_bank
        self.lang_manager = LanguageManager.instance()
        self.study_mode = "practice"
        self._current_course_id = ""
        self._current_course_title = ""
        self._study_intent: StudyIntent | None = None
        self._all_sets = []
        self._scheduling_index: dict[str, tuple[str, str, str]] = {}
        self._updating_topics = False
        self._updating_preset = False
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self.refresh()

    def _setup_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setObjectName("studySetupScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        content = QWidget()
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        self.title_label = QLabel()
        self.title_label.setObjectName("screenTitle")
        layout.addWidget(self.title_label)

        self.mode_frame = QFrame()
        self.mode_frame.setObjectName("studyModeBar")
        mode_layout = QHBoxLayout(self.mode_frame)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(8)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.today_mode_btn = self._mode_button("todayStudyMode")
        self.free_practice_mode_btn = self._mode_button("freePracticeMode")
        self.mock_exam_mode_btn = self._mode_button("mockExamMode")
        for button in (
            self.today_mode_btn,
            self.free_practice_mode_btn,
            self.mock_exam_mode_btn,
        ):
            mode_layout.addWidget(button)
        mode_layout.addStretch(1)
        self.today_mode_btn.clicked.connect(self._request_today_mode)
        self.free_practice_mode_btn.clicked.connect(
            lambda: self._set_study_mode("practice")
        )
        self.mock_exam_mode_btn.clicked.connect(
            lambda: self._set_study_mode("exam")
        )
        self.today_mode_btn.hide()
        layout.addWidget(self.mode_frame)

        self.course_context_label = QLabel()
        self.course_context_label.setObjectName("topicCourseContextLabel")
        self.course_context_label.setWordWrap(True)
        layout.addWidget(self.course_context_label)

        self.study_intent_banner = QLabel()
        self.study_intent_banner.setObjectName("studyIntentBanner")
        self.study_intent_banner.setWordWrap(True)
        self.study_intent_banner.hide()
        layout.addWidget(self.study_intent_banner)

        self.setup_card = QFrame()
        self.setup_card.setObjectName("studySetupCard")
        setup_layout = QVBoxLayout(self.setup_card)
        setup_layout.setContentsMargins(18, 18, 18, 18)
        setup_layout.setSpacing(14)

        self.setup_title = QLabel()
        self.setup_title.setObjectName("sectionTitle")
        setup_layout.addWidget(self.setup_title)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.preset_combo = WheelSafeComboBox()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.preset_label = QLabel()
        form.addRow(self.preset_label, self.preset_combo)

        self.topic_filter = WheelSafeComboBox()
        self.topic_filter.setEditable(True)
        self.topic_filter.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.topic_filter.lineEdit().setReadOnly(True)
        self.topic_filter.model().itemChanged.connect(
            self._on_topic_filter_item_changed
        )
        self.topic_label = QLabel()
        form.addRow(self.topic_label, self.topic_filter)

        self.difficulty_filter = WheelSafeComboBox()
        self.difficulty_filter.currentIndexChanged.connect(
            self._on_scope_control_changed
        )
        self.difficulty_label = QLabel()
        form.addRow(self.difficulty_label, self.difficulty_filter)

        self.question_count_input = WheelSafeSpinBox()
        self.question_count_input.setRange(1, 100)
        self.question_count_input.setValue(10)
        self.question_count_input.valueChanged.connect(
            self._on_scope_control_changed
        )
        self.question_count_label = QLabel()
        form.addRow(self.question_count_label, self.question_count_input)
        setup_layout.addLayout(form)

        self.practice_preview_card = QFrame()
        self.practice_preview_card.setObjectName("practicePreviewCard")
        preview_layout = QVBoxLayout(self.practice_preview_card)
        preview_layout.setContentsMargins(18, 18, 18, 18)
        preview_layout.setSpacing(10)
        self.practice_preview_title = QLabel()
        self.practice_preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(self.practice_preview_title)
        self.practice_preview_primary = QLabel()
        self.practice_preview_primary.setObjectName("practicePreviewPrimary")
        self.practice_preview_primary.setWordWrap(True)
        preview_layout.addWidget(self.practice_preview_primary)
        self.practice_preview_coverage = QLabel()
        self.practice_preview_coverage.setObjectName("secondaryText")
        self.practice_preview_coverage.setWordWrap(True)
        preview_layout.addWidget(self.practice_preview_coverage)
        self.coverage_label = self.practice_preview_coverage
        self.practice_preview_difficulty = QLabel()
        self.practice_preview_difficulty.setObjectName("secondaryText")
        self.practice_preview_difficulty.setWordWrap(True)
        preview_layout.addWidget(self.practice_preview_difficulty)
        self.practice_preview_gap = QLabel()
        self.practice_preview_gap.setObjectName("practicePreviewGap")
        self.practice_preview_gap.setWordWrap(True)
        preview_layout.addWidget(self.practice_preview_gap)
        preview_layout.addStretch(1)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.generate_missing_btn = QPushButton()
        self.generate_missing_btn.setObjectName("secondaryButton")
        self.generate_missing_btn.setMinimumHeight(40)
        self.generate_missing_btn.clicked.connect(
            self._request_missing_generation
        )
        self.generate_missing_btn.hide()
        action_layout.addWidget(self.generate_missing_btn)
        self.start_btn = QPushButton()
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self._start_quiz)
        action_layout.addWidget(self.start_btn)
        preview_layout.addLayout(action_layout)

        self.practice_workspace_layout = QBoxLayout(
            QBoxLayout.Direction.LeftToRight
        )
        self.practice_workspace_layout.setSpacing(16)
        self.practice_workspace_layout.addWidget(self.setup_card, 1)
        self.practice_workspace_layout.addWidget(self.practice_preview_card, 1)
        layout.addLayout(self.practice_workspace_layout, 1)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )

        self._on_language_changed()
        self._update_workspace_direction()
        self._sync_mode_buttons()

    def _mode_button(self, object_name: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("quizModeOption")
        button.setProperty("modeKey", object_name)
        button.setProperty("studyModeOption", True)
        button.setCheckable(True)
        button.setMinimumHeight(36)
        self.mode_group.addButton(button)
        return button

    def _on_language_changed(self, _lang=None) -> None:
        gm = self.lang_manager.get_text
        self.title_label.setText(gm("自由练习", "Free Practice"))
        self.today_mode_btn.setText(gm("今日学习", "Today"))
        self.free_practice_mode_btn.setText(gm("练习模式", "Practice Mode"))
        self.mock_exam_mode_btn.setText(gm("模拟考试", "Mock Exam"))
        self.setup_title.setText(gm("练习目标", "Practice Goal"))
        self.practice_preview_title.setText(gm("本次练习", "This Session"))
        self.preset_label.setText(gm("保存的方案", "Saved Preset"))
        self.topic_label.setText(gm("知识点", "Topics"))
        self.difficulty_label.setText(gm("难度", "Difficulty"))
        self.question_count_label.setText(gm("题量", "Questions"))
        self._update_course_context_label()
        self.refresh()

    def set_current_course(
        self,
        course_id: str | None,
        course_title: str | None = None,
    ) -> None:
        course_id = str(course_id or "").strip()
        course_title = str(course_title or "").strip()
        if (
            course_id == self._current_course_id
            and course_title == self._current_course_title
        ):
            return
        self._current_course_id = course_id
        self._current_course_title = course_title
        self._update_course_context_label()
        self.refresh()

    def refresh(self) -> None:
        selected_preset = self.preset_combo.currentData()
        selected_topics = set(self._selected_topic_ids())
        selected_difficulty = self.difficulty_filter.currentData()

        self._all_sets = (
            [
                question_set
                for question_set in self.set_manager.load_all()
                if self._matches_current_course(question_set)
            ]
            if self._current_course_id
            else []
        )
        self._scheduling_index = (
            self.question_bank.scheduling_index(
                course_id=self._current_course_id
            )
            if self.question_bank is not None and self._current_course_id
            else {}
        )
        self._populate_presets(selected_preset)
        self._populate_topics(selected_topics)
        self._populate_difficulties(selected_difficulty)
        self._update_scope_state()

    def apply_study_intent(self, intent: StudyIntent) -> None:
        if not isinstance(intent, StudyIntent) or intent.action not in {
            StudyAction.PRACTICE_TOPIC,
            StudyAction.CUSTOM_PRACTICE,
        }:
            return
        self._study_intent = intent
        if intent.course_id:
            self._current_course_id = intent.course_id
            self._current_course_title = ""
        self.study_mode = intent.submission_mode
        self.question_count_input.setValue(max(1, intent.question_count))
        self.refresh()
        if intent.set_id:
            index = self.preset_combo.findData(intent.set_id)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        self._set_checked_topics(intent.topic_ids)
        self._sync_mode_buttons()
        self._update_scope_state()

    def clear_study_intent(self) -> None:
        self._study_intent = None
        self.study_intent_banner.clear()
        self.study_intent_banner.hide()
        self.generate_missing_btn.hide()
        self._set_study_mode("practice")

    def _request_today_mode(self) -> None:
        self._sync_mode_buttons()
        self.today_mode_requested.emit()

    def _set_study_mode(self, mode: str) -> None:
        if mode not in {"practice", "exam"}:
            return
        self.study_mode = mode
        self._sync_mode_buttons()
        self._update_scope_state()

    def _sync_mode_buttons(self) -> None:
        for button, checked in (
            (self.today_mode_btn, False),
            (self.free_practice_mode_btn, self.study_mode == "practice"),
            (self.mock_exam_mode_btn, self.study_mode == "exam"),
        ):
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)

    def _populate_presets(self, selected_set_id: str | None) -> None:
        gm = self.lang_manager.get_text
        self._updating_preset = True
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem(gm("不使用预设", "No preset"), "")
        for question_set in self._all_sets:
            if not question_set.questions:
                continue
            self.preset_combo.addItem(
                f"{question_set.get_title(self.lang_manager.current)}"
                f" · {question_set.question_count} {gm('题', 'questions')}",
                question_set.set_id,
            )
        index = self.preset_combo.findData(selected_set_id or "")
        self.preset_combo.setCurrentIndex(max(0, index))
        self.preset_combo.blockSignals(False)
        self._updating_preset = False

    def _populate_topics(self, selected_topics: set[str]) -> None:
        topic_titles: dict[str, str] = {}
        for topic_id, topic_title, _difficulty in self._scheduling_index.values():
            topic_id = str(topic_id or "").strip()
            if topic_id:
                topic_titles.setdefault(
                    topic_id,
                    str(topic_title or topic_id).strip() or topic_id,
                )
        for question_set in self._all_sets:
            for topic in question_set.topics:
                topic_id = topic_value(topic)
                topic_titles.setdefault(
                    topic_id,
                    topic_label(topic, self.lang_manager.current),
                )

        self._updating_topics = True
        model = self.topic_filter.model()
        model.blockSignals(True)
        self.topic_filter.clear()
        self.topic_filter.addItem(
            self.lang_manager.get_text("全部知识点", "All Topics"),
            None,
        )
        self._make_topic_item_checkable(0, checked=not selected_topics)
        for topic_id in sorted(topic_titles):
            self.topic_filter.addItem(topic_titles[topic_id], topic_id)
            self._make_topic_item_checkable(
                self.topic_filter.count() - 1,
                checked=topic_id in selected_topics,
            )
        model.blockSignals(False)
        self._updating_topics = False
        self._update_topic_filter_label()

    def _populate_difficulties(self, selected: str | None) -> None:
        gm = self.lang_manager.get_text
        self.difficulty_filter.blockSignals(True)
        self.difficulty_filter.clear()
        self.difficulty_filter.addItem(gm("自适应", "Adaptive"), "")
        self.difficulty_filter.addItem(gm("简单", "Easy"), "easy")
        self.difficulty_filter.addItem(gm("中等", "Medium"), "medium")
        self.difficulty_filter.addItem(gm("困难", "Hard"), "hard")
        index = self.difficulty_filter.findData(selected or "")
        self.difficulty_filter.setCurrentIndex(max(0, index))
        self.difficulty_filter.blockSignals(False)

    def _make_topic_item_checkable(self, row: int, *, checked: bool) -> None:
        item = self.topic_filter.model().item(row)
        if item is None:
            return
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        )
        item.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )

    def _on_topic_filter_item_changed(self, item) -> None:
        if self._updating_topics:
            return
        self._updating_topics = True
        try:
            model = self.topic_filter.model()
            row = item.row()
            if row == 0 and item.checkState() == Qt.CheckState.Checked:
                for other_row in range(1, self.topic_filter.count()):
                    model.item(other_row).setCheckState(
                        Qt.CheckState.Unchecked
                    )
            elif row > 0 and item.checkState() == Qt.CheckState.Checked:
                model.item(0).setCheckState(Qt.CheckState.Unchecked)
            if not self._selected_topic_ids():
                model.item(0).setCheckState(Qt.CheckState.Checked)
        finally:
            self._updating_topics = False
        self._update_topic_filter_label()
        self._on_scope_control_changed()

    def _set_checked_topics(self, topic_ids) -> None:
        wanted = {str(topic_id or "").strip() for topic_id in topic_ids}
        self._updating_topics = True
        try:
            model = self.topic_filter.model()
            for row in range(self.topic_filter.count()):
                topic_id = self.topic_filter.itemData(row)
                checked = (
                    (topic_id is None and not wanted)
                    or (topic_id is not None and topic_id in wanted)
                )
                model.item(row).setCheckState(
                    Qt.CheckState.Checked
                    if checked
                    else Qt.CheckState.Unchecked
                )
        finally:
            self._updating_topics = False
        self._update_topic_filter_label()

    def _selected_topic_ids(self) -> list[str]:
        selected = []
        model = self.topic_filter.model()
        for row in range(1, self.topic_filter.count()):
            item = model.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                topic_id = str(self.topic_filter.itemData(row) or "").strip()
                if topic_id:
                    selected.append(topic_id)
        return selected

    def _update_topic_filter_label(self) -> None:
        count = len(self._selected_topic_ids())
        text = self.lang_manager.get_text(
            "全部知识点" if not count else f"已选 {count} 个知识点",
            "All Topics" if not count else f"{count} topics selected",
        )
        self.topic_filter.lineEdit().setText(text)

    def _on_preset_changed(self) -> None:
        if self._updating_preset:
            return
        set_id = str(self.preset_combo.currentData() or "")
        question_set = self.set_manager.get(set_id) if set_id else None
        using_preset = question_set is not None
        if question_set is not None:
            self.question_count_input.setValue(
                max(1, question_set.question_count)
            )
            self._set_checked_topics(
                [topic_value(topic) for topic in question_set.topics]
            )
            index = self.difficulty_filter.findData(
                question_set.difficulty.value
            )
            if index >= 0:
                self.difficulty_filter.setCurrentIndex(index)
        for control in (
            self.topic_filter,
            self.difficulty_filter,
            self.question_count_input,
        ):
            control.setEnabled(not using_preset)
        self._update_scope_state()

    def _on_scope_control_changed(self, *_args) -> None:
        self._update_scope_state()

    def _selected_question_ids(self) -> list[str]:
        set_id = str(self.preset_combo.currentData() or "")
        if set_id:
            question_set = self.set_manager.get(set_id)
            if question_set is None:
                return []
            if not self._scheduling_index:
                return list(question_set.questions)
            return [
                question_id
                for question_id in question_set.questions
                if question_id in self._scheduling_index
            ]
        return select_practice_question_ids(
            self._scheduling_index,
            topic_ids=self._selected_topic_ids(),
            difficulty=str(self.difficulty_filter.currentData() or ""),
            limit=self.question_count_input.value(),
        )

    def _build_intent(self, question_ids: list[str]) -> StudyIntent:
        set_id = str(self.preset_combo.currentData() or "")
        topic_ids = tuple(self._selected_topic_ids())
        requested_count = self.question_count_input.value()
        current = self._study_intent
        if (
            current is not None
            and not set_id
            and current.course_id == self._current_course_id
            and current.topic_ids == topic_ids
            and current.question_count == requested_count
            and current.submission_mode == self.study_mode
        ):
            return current
        return StudyIntent(
            course_id=self._current_course_id,
            action=StudyAction.CUSTOM_PRACTICE,
            set_id=set_id,
            topic_ids=topic_ids,
            question_ids=tuple(question_ids),
            question_count=requested_count,
            submission_mode=self.study_mode,
            source="study_workspace",
        )

    def _start_quiz(self) -> None:
        question_ids = self._selected_question_ids()
        if not question_ids:
            return
        self.study_start.emit(self._build_intent(question_ids), question_ids)

    def _request_missing_generation(self) -> None:
        question_ids = self._selected_question_ids()
        missing = max(0, self.question_count_input.value() - len(question_ids))
        if missing:
            self.generate_missing.emit(
                self._build_intent(question_ids),
                missing,
            )

    def _update_scope_state(self) -> None:
        if not hasattr(self, "start_btn"):
            return
        gm = self.lang_manager.get_text
        question_ids = self._selected_question_ids()
        requested = self.question_count_input.value()
        mode_text = gm(
            "逐题反馈" if self.study_mode == "practice" else "最后统一交卷",
            "Immediate feedback"
            if self.study_mode == "practice"
            else "Submit at the end",
        )
        preview = build_practice_plan_preview(
            self._scheduling_index,
            question_ids=question_ids,
            requested_count=requested,
        )
        coverage = " · ".join(
            f"{title} {count}" for title, count in preview.topic_counts
        )
        difficulties = " · ".join(
            f"{_difficulty_label(difficulty, gm)} {count}"
            for difficulty, count in preview.difficulty_counts
        )
        self.practice_preview_primary.setText(gm(
            f"{preview.ready_count} 题 · 约 {preview.ready_minutes} 分钟 · {mode_text}",
            f"{preview.ready_count} questions · about {preview.ready_minutes} min · {mode_text}",
        ))
        self.practice_preview_coverage.setText(gm(
            f"知识点覆盖：{coverage or '当前范围没有可用题目'}",
            f"Topic coverage: {coverage or 'No available questions in this scope'}",
        ))
        self.practice_preview_difficulty.setText(gm(
            f"难度分布：{difficulties or '暂无'}",
            f"Difficulty mix: {difficulties or 'None'}",
        ))
        if preview.missing_count:
            self.practice_preview_gap.setText(gm(
                f"还差 {preview.missing_count} 题。补齐后约 {preview.target_minutes} 分钟。",
                f"{preview.missing_count} more needed. About {preview.target_minutes} min when complete.",
            ))
        else:
            self.practice_preview_gap.setText(gm(
                "题量已满足，可直接开始。",
                "Your target is ready to start.",
            ))
        self.start_btn.setText(gm(
            f"开始练习 {preview.ready_count} 题"
            if self.study_mode == "practice"
            else f"开始模拟考试 {preview.ready_count} 题",
            f"Start Practice {preview.ready_count} Questions"
            if self.study_mode == "practice"
            else f"Start Mock Exam {preview.ready_count} Questions",
        ))
        self.start_btn.setEnabled(preview.ready_count > 0)
        missing = preview.missing_count
        self.generate_missing_btn.setText(gm(
            f"补生成 {missing} 题",
            f"Generate {missing} More",
        ))
        self.generate_missing_btn.setVisible(
            self._study_intent is not None and missing > 0
        )
        if self._study_intent is not None:
            self.study_intent_banner.setText(gm(
                f"已按学习建议预填：{preview.ready_count}/{requested} 题",
                f"Study suggestion applied: {preview.ready_count}/{requested} ready",
            ))
            self.study_intent_banner.show()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._update_workspace_direction()

    def _update_workspace_direction(self) -> None:
        if not hasattr(self, "practice_workspace_layout"):
            return
        direction = (
            QBoxLayout.Direction.TopToBottom
            if self.width() < 940
            else QBoxLayout.Direction.LeftToRight
        )
        self.practice_workspace_layout.setDirection(direction)

    def _update_course_context_label(self) -> None:
        title = self._current_course_title or self._current_course_id
        self.course_context_label.setText(self.lang_manager.get_text(
            f"当前课程：{title or '尚未选择'}",
            f"Current course: {title or 'None selected'}",
        ))

    def _matches_current_course(self, question_set) -> bool:
        source_course_id = str(
            (question_set.metadata or {}).get("course_id", "") or ""
        )
        return (
            not source_course_id
            or source_course_id == self._current_course_id
        ) if self._current_course_id else False


def _difficulty_label(difficulty: str, get_text) -> str:
    return {
        "easy": get_text("简单", "Easy"),
        "medium": get_text("中等", "Medium"),
        "hard": get_text("困难", "Hard"),
    }.get(difficulty, get_text("其他", "Other"))
