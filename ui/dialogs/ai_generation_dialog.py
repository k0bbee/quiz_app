"""AI question generation dialog — wizard for selecting topics and generating."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QSpinBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox, QCheckBox,
    QAbstractItemView, QScrollArea, QFrame, QWidget, QSlider, QFormLayout,
    QSplitter, QLineEdit
)
import time
from collections import Counter

from PyQt6.QtCore import Qt, QTimer

from utils.constants import topic_label, topic_value
from core.app_errors import coerce_app_error, format_app_error
from core.language_manager import LanguageManager
from ai.llm_client import LLMClient
from ai.batch_generator import GenerationWorker
from ai.generation_config import (
    DIFFICULTY_DEFAULTS,
    QUESTION_TYPE_DEFAULTS,
    GenerationConfig,
    planned_generation_counts,
)
from ai.generation_report import GenerationReport
from ai.question_plan import build_question_plan, summarize_plan_items
from ai.exam_plan import (
    ExamGenerationPlan,
    ExamPlanPatch,
    ExamPlanValidationError,
    apply_exam_plan_patch,
)
from ai.course_summary_factory import provider_requires_api_key
from models.question import Question
from ui.dialogs.question_review_dialog import QuestionReviewDialog
from ai.course_context import extract_relevant_course_context
from core.course_index import retrieve_course_context
from ui.widgets.wheel_safe_controls import WheelSafeComboBox, WheelSafeSlider, WheelSafeSpinBox


def _compact_label_text(text: str, limit: int = 34) -> str:
    """Return a single-line label while preserving full text in tooltip elsewhere."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(1, limit - 1)].rstrip() + "…"


class AIGenerationDialog(QDialog):
    """Dialog for generating questions via AI."""

    def __init__(self, course_content: str, settings: dict, parent=None, available_topics: list = None, course_project=None):
        super().__init__(parent)
        self.course_content = course_content
        self.settings = settings
        self.available_topics = available_topics or []
        self.course_project = course_project
        self.lang_manager = LanguageManager.instance()
        self.generated_questions: list[Question] = []
        self.worker: GenerationWorker = None
        self._generation_failed = False
        self._generation_cancelled = False
        self._partial_generation_error = None
        self._partial_generation_report: GenerationReport | None = None
        self.weight_value_labels: dict[QSlider, QLabel] = {}
        self.topic_weight_labels: dict[str, QLabel] = {}
        self.topic_weight_rows: dict[str, QWidget] = {}
        self._generation_started_at: float | None = None
        self._last_generation_progress = ""
        self._generation_events: list[str] = []
        self.generation_status_timer = QTimer(self)
        self.generation_status_timer.setInterval(1000)
        self.generation_status_timer.timeout.connect(self._refresh_generation_status)

        self.setWindowTitle(self.lang_manager.get_text("AI 出题", "AI Question Generation"))
        self.resize(1000, 700)
        self.setMinimumSize(820, 600)
        self._setup_ui()
        self.lang_manager.language_changed.connect(self._on_language_changed)

    def _setup_ui(self):
        # Desktop layout: two-pane work area + fixed status/action footer.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 12, 16, 8)
        body_layout.setSpacing(0)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(8)

        self.left_pane = QWidget()
        left_layout = QVBoxLayout(self.left_pane)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(12)

        # Topic selection
        self.topic_group = QGroupBox(self.lang_manager.get_text("选择主题", "Select Topics"))
        topic_layout = QVBoxLayout(self.topic_group)
        topic_layout.setSpacing(8)

        # Select all / deselect all
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton(self.lang_manager.get_text("全选", "Select All"))
        self.select_all_btn.setObjectName("secondaryButton")
        self.select_all_btn.clicked.connect(lambda: self._toggle_all(True))
        self.deselect_btn = QPushButton(self.lang_manager.get_text("取消全选", "Deselect All"))
        self.deselect_btn.setObjectName("secondaryButton")
        self.deselect_btn.clicked.connect(lambda: self._toggle_all(False))
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.deselect_btn)
        btn_row.addStretch()
        topic_layout.addLayout(btn_row)

        self.topic_list = QListWidget()
        lang = self.lang_manager.current
        for topic in self.available_topics:
            label = topic_label(topic, lang)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, topic)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.topic_list.addItem(item)
        # Use standard selection with checkboxes; don't disable selection
        self.topic_list.itemChanged.connect(lambda _item: self._on_topics_changed())
        topic_layout.addWidget(self.topic_list)

        left_layout.addWidget(self.topic_group, 3)

        # Prompt preview stays beside the controls instead of below all of them.
        self.prompt_group = QGroupBox(self.lang_manager.get_text("课程内容预览", "Course Content Preview"))
        prompt_layout = QVBoxLayout(self.prompt_group)
        self.prompt_preview = QTextEdit()
        self.prompt_preview.setReadOnly(True)
        prompt_layout.addWidget(self.prompt_preview)
        left_layout.addWidget(self.prompt_group, 2)

        self.content_splitter.addWidget(self.left_pane)

        # Configuration is independently scrollable when the window is short.
        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.right_content = QWidget()
        right_layout = QVBoxLayout(self.right_content)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(12)

        self.config_group = QGroupBox(
            self.lang_manager.get_text("生成参数", "Generation Settings")
        )
        config_layout = QFormLayout(self.config_group)
        config_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        config_layout.setHorizontalSpacing(16)
        config_layout.setVerticalSpacing(10)

        self.set_title_label = QLabel(self.lang_manager.get_text("题集名称:", "Set name:"))
        self.set_title_input = QLineEdit()
        self.set_title_input.setPlaceholderText(
            self.lang_manager.get_text("留空则自动命名", "Leave blank to name automatically")
        )
        config_layout.addRow(self.set_title_label, self.set_title_input)

        self.count_label = QLabel(self.lang_manager.get_text("数量:", "Count:"))
        self.count_spin = WheelSafeSpinBox()
        self.count_spin.setRange(3, 60)
        default_count = int(self.settings.get("default_question_count", 15) or 15)
        self.count_spin.setValue(max(self.count_spin.minimum(), min(self.count_spin.maximum(), default_count)))
        config_layout.addRow(self.count_label, self.count_spin)

        self.diff_label = QLabel(self.lang_manager.get_text("整体难度:", "Overall difficulty:"))
        self.diff_combo = WheelSafeComboBox()
        difficulties = [
            (self.lang_manager.get_text("简单", "easy"), "easy"),
            (self.lang_manager.get_text("中等", "medium"), "medium"),
            (self.lang_manager.get_text("困难", "hard"), "hard"),
            (self.lang_manager.get_text("混合", "mixed"), "mixed"),
        ]
        for display, value in difficulties:
            self.diff_combo.addItem(display, value)
        for i in range(self.diff_combo.count()):
            if self.diff_combo.itemData(i) == self.settings.get("default_difficulty", "medium"):
                self.diff_combo.setCurrentIndex(i)
                break
        config_layout.addRow(self.diff_label, self.diff_combo)

        self.template_label = QLabel(self.lang_manager.get_text("模板:", "Template:"))
        self.template_combo = WheelSafeComboBox()
        self.template_combo.addItem(self.lang_manager.get_text("快速复习", "Quick Review"), "quick_review")
        self.template_combo.addItem(self.lang_manager.get_text("期末模拟", "Final Exam Style"), "final_exam")
        self.template_combo.addItem(self.lang_manager.get_text("计算训练", "Calculation Practice"), "calculation_practice")
        default_template = self.settings.get("default_generation_template", "quick_review")
        template_index = self.template_combo.findData(default_template)
        if template_index >= 0:
            self.template_combo.setCurrentIndex(template_index)
        config_layout.addRow(self.template_label, self.template_combo)

        self.assistant_action_layout = QHBoxLayout()
        self.assistant_action_layout.addStretch()
        self.exam_assistant_btn = QPushButton(
            self.lang_manager.get_text("试卷助手…", "Exam Assistant…")
        )
        self.exam_assistant_btn.setObjectName("secondaryButton")
        self.exam_assistant_btn.clicked.connect(self._open_exam_assistant)
        self.assistant_action_layout.addWidget(self.exam_assistant_btn)
        config_layout.addRow("", self.assistant_action_layout)
        right_layout.addWidget(self.config_group)

        self.topic_weight_sliders: dict[str, QSlider] = {}
        if self.available_topics:
            self.topic_weight_group = QGroupBox(
                self.lang_manager.get_text("知识点权重", "Topic Weights")
            )
            topic_weight_layout = QFormLayout(self.topic_weight_group)
            topic_weight_layout.setLabelAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            topic_weight_layout.setHorizontalSpacing(12)
            topic_weight_layout.setVerticalSpacing(8)
            default_weight = max(1, 100 // len(self.available_topics))
            for topic in self.available_topics:
                key = topic_value(topic)
                slider = self._make_slider(default_weight)
                self.topic_weight_sliders[key] = slider
                label = self._weight_topic_label(topic_label(topic, lang))
                row = self._slider_row(slider)
                self.topic_weight_labels[key] = label
                self.topic_weight_rows[key] = row
                topic_weight_layout.addRow(label, row)
            self.topic_weight_empty_label = QLabel(
                self.lang_manager.get_text(
                    "选择左侧主题后显示对应权重。",
                    "Select topics on the left to show their weights.",
                )
            )
            self.topic_weight_empty_label.setObjectName("mutedLabel")
            topic_weight_layout.addRow("", self.topic_weight_empty_label)
            right_layout.addWidget(self.topic_weight_group)

        # Structure controls
        self.structure_group = QGroupBox(self.lang_manager.get_text("题目结构", "Question Structure"))
        structure_layout = QFormLayout(self.structure_group)
        structure_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        structure_layout.setHorizontalSpacing(12)
        structure_layout.setVerticalSpacing(8)

        self.question_type_heading = QLabel(
            self.lang_manager.get_text("题型权重", "Question type weights")
        )
        self.question_type_heading.setObjectName("sectionLabel")
        structure_layout.addRow(self.question_type_heading)

        question_type_defaults = self._settings_weights(
            "default_question_type_weights",
            QUESTION_TYPE_DEFAULTS,
        )
        self.mc_slider = self._make_slider(question_type_defaults["multiple_choice"])
        self.scenario_slider = self._make_slider(question_type_defaults["scenario_choice"])
        self.true_false_slider = self._make_slider(question_type_defaults["true_false"])
        self.fill_blank_slider = self._make_slider(question_type_defaults["fill_in_blank"])
        self.mc_label = QLabel(self.lang_manager.get_text("选择题", "Multiple choice"))
        self.scenario_label = QLabel(self.lang_manager.get_text("情境选择题", "Scenario choice"))
        self.true_false_label = QLabel(self.lang_manager.get_text("判断题", "True / false"))
        self.fill_blank_label = QLabel(self.lang_manager.get_text("填空题", "Fill in the blank"))
        structure_layout.addRow(self.mc_label, self._slider_row(self.mc_slider))
        structure_layout.addRow(self.scenario_label, self._slider_row(self.scenario_slider))
        structure_layout.addRow(self.true_false_label, self._slider_row(self.true_false_slider))
        structure_layout.addRow(self.fill_blank_label, self._slider_row(self.fill_blank_slider))

        self.difficulty_weight_heading = QLabel(
            self.lang_manager.get_text("难度权重", "Difficulty weights")
        )
        self.difficulty_weight_heading.setObjectName("sectionLabel")
        structure_layout.addRow(self.difficulty_weight_heading)

        difficulty_defaults = self._settings_weights(
            "default_difficulty_weights",
            DIFFICULTY_DEFAULTS,
        )
        self.easy_slider = self._make_slider(difficulty_defaults["easy"])
        self.medium_slider = self._make_slider(difficulty_defaults["medium"])
        self.hard_slider = self._make_slider(difficulty_defaults["hard"])
        self.easy_label = QLabel(self.lang_manager.get_text("简单", "Easy"))
        self.medium_label = QLabel(self.lang_manager.get_text("中等", "Medium"))
        self.hard_label = QLabel(self.lang_manager.get_text("困难", "Hard"))
        structure_layout.addRow(self.easy_label, self._slider_row(self.easy_slider))
        structure_layout.addRow(self.medium_label, self._slider_row(self.medium_slider))
        structure_layout.addRow(self.hard_label, self._slider_row(self.hard_slider))

        self.refresh_weight_preview_btn = QPushButton(
            self.lang_manager.get_text("更新权重显示", "Update Weight Preview")
        )
        self.refresh_weight_preview_btn.setObjectName("secondaryButton")
        self.refresh_weight_preview_btn.clicked.connect(self._refresh_weight_preview_and_plan)
        structure_layout.addRow("", self.refresh_weight_preview_btn)

        right_layout.addWidget(self.structure_group)

        self.plan_group = QGroupBox(
            self.lang_manager.get_text("生成计划预览", "Generation Plan Preview")
        )
        plan_layout = QVBoxLayout(self.plan_group)
        plan_layout.setContentsMargins(10, 10, 10, 10)
        self.plan_preview = QTextEdit()
        self.plan_preview.setObjectName("generationPlanPreview")
        self.plan_preview.setReadOnly(True)
        self.plan_preview.setMaximumHeight(170)
        plan_layout.addWidget(self.plan_preview)
        right_layout.addWidget(self.plan_group)

        self.generation_log_group = QGroupBox(
            self.lang_manager.get_text("生成过程", "Generation Activity")
        )
        generation_log_layout = QVBoxLayout(self.generation_log_group)
        generation_log_layout.setContentsMargins(10, 10, 10, 10)
        self.generation_log = QTextEdit()
        self.generation_log.setObjectName("generationProgressLog")
        self.generation_log.setReadOnly(True)
        self.generation_log.setMaximumHeight(130)
        self.generation_log.setPlaceholderText(
            self.lang_manager.get_text(
                "开始生成后显示批次、接受、拒绝和错误摘要。",
                "Generation batches, accepted counts, rejections, and errors will appear here.",
            )
        )
        generation_log_layout.addWidget(self.generation_log)
        right_layout.addWidget(self.generation_log_group)

        self.count_spin.valueChanged.connect(lambda _value: self._update_preview())
        self.diff_combo.currentIndexChanged.connect(lambda _index: self._update_preview())
        self.template_combo.currentIndexChanged.connect(lambda _index: self._update_preview())

        right_layout.addStretch()

        if hasattr(self, "topic_weight_group"):
            self.topic_weight_group.setTitle(self.lang_manager.get_text("知识点权重", "Topic Weights"))
        self._sync_topic_weight_rows()
        self._refresh_weight_labels()
        self._update_preview()

        self.right_scroll.setWidget(self.right_content)
        self.content_splitter.addWidget(self.right_scroll)
        self.content_splitter.setStretchFactor(0, 5)
        self.content_splitter.setStretchFactor(1, 4)
        self.content_splitter.setSizes([540, 440])
        body_layout.addWidget(self.content_splitter)
        outer.addWidget(body, 1)

        # Fixed bottom bar (always visible)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 4, 16, 12)
        bottom_layout.setSpacing(8)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        bottom_layout.addWidget(self.progress_bar)

        self.status_label = QLabel()
        bottom_layout.addWidget(self.status_label)

        self.partial_recovery_label = QLabel()
        self.partial_recovery_label.setObjectName("generationPartialRecoveryLabel")
        self.partial_recovery_label.setWordWrap(True)
        self.partial_recovery_label.setHidden(True)
        bottom_layout.addWidget(self.partial_recovery_label)

        # Action buttons
        self.footer_action_layout = QHBoxLayout()

        self.cancel_btn = QPushButton(self.lang_manager.get_text("取消", "Cancel"))
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        self.footer_action_layout.addWidget(self.cancel_btn)

        self.footer_action_layout.addStretch()

        self.generate_btn = QPushButton(self.lang_manager.get_text("生成题目", "Generate Questions"))
        self.generate_btn.setObjectName("primaryButton")
        self.generate_btn.setMinimumHeight(34)
        self.generate_btn.clicked.connect(self._start_generation)
        self.footer_action_layout.addWidget(self.generate_btn)

        bottom_layout.addLayout(self.footer_action_layout)
        outer.addWidget(bottom)

    def _make_slider(self, value: int) -> QSlider:
        slider = WheelSafeSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        slider.setValue(value)
        return slider

    def _settings_weights(self, settings_key: str, defaults: dict[str, int]) -> dict[str, int]:
        configured = self.settings.get(settings_key, {})
        weights = dict(defaults)
        if isinstance(configured, dict):
            for key in defaults:
                try:
                    weights[key] = max(0, min(100, int(configured.get(key, defaults[key]))))
                except (TypeError, ValueError):
                    weights[key] = defaults[key]
        return weights

    def _slider_row(self, slider: QSlider) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(f"{slider.value()}%")
        label.setMinimumWidth(40)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.weight_value_labels[slider] = label
        layout.addWidget(slider, 1)
        layout.addWidget(label)
        return row

    def _refresh_weight_labels(self) -> None:
        """Show raw slider weights and their normalized effective percentages."""
        groups: list[list[QSlider]] = []
        if hasattr(self, "topic_weight_sliders"):
            selected_topic_keys = set(self._selected_topic_keys())
            groups.append([
                slider
                for key, slider in self.topic_weight_sliders.items()
                if key in selected_topic_keys
            ])
        question_sliders = [
            getattr(self, name, None)
            for name in ("mc_slider", "scenario_slider", "true_false_slider", "fill_blank_slider")
        ]
        difficulty_sliders = [
            getattr(self, name, None)
            for name in ("easy_slider", "medium_slider", "hard_slider")
        ]
        groups.append([slider for slider in question_sliders if slider is not None])
        groups.append([slider for slider in difficulty_sliders if slider is not None])

        for sliders in groups:
            self._refresh_weight_label_group(sliders)

    def _weight_topic_label(self, text: str) -> QLabel:
        label = QLabel(_compact_label_text(text, limit=34))
        label.setObjectName("weightTopicLabel")
        label.setToolTip(text)
        label.setWordWrap(False)
        label.setMaximumWidth(220)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _refresh_weight_label_group(self, sliders: list[QSlider]) -> None:
        sliders = [slider for slider in sliders if slider in self.weight_value_labels]
        if not sliders:
            return
        raw_values = {slider: max(0, int(slider.value())) for slider in sliders}
        total = sum(raw_values.values())
        if total <= 0:
            normalized = {slider: 0 for slider in sliders}
        else:
            normalized = {
                slider: round(value * 100 / total)
                for slider, value in raw_values.items()
            }
            delta = 100 - sum(normalized.values())
            if normalized:
                first_slider = next(iter(normalized))
                normalized[first_slider] += delta

        for slider in sliders:
            raw = raw_values[slider]
            effective = normalized[slider]
            text = f"{effective}%" if raw == effective else f"{raw} ({effective}%)"
            label = self.weight_value_labels[slider]
            label.setText(text)
            label.setToolTip(
                self.lang_manager.get_text(
                    f"原始权重：{raw}；有效占比：{effective}%。",
                    f"Raw weight: {raw}; effective share: {effective}%.",
                )
            )

    def _refresh_weight_preview_and_plan(self) -> None:
        self._refresh_weight_labels()
        self._update_preview()

    def _on_language_changed(self, lang):
        """Update all UI strings when language changes."""
        self.setWindowTitle(self.lang_manager.get_text("AI 出题", "AI Question Generation"))
        self.topic_group.setTitle(self.lang_manager.get_text("选择主题", "Select Topics"))
        self.select_all_btn.setText(self.lang_manager.get_text("全选", "Select All"))
        self.deselect_btn.setText(self.lang_manager.get_text("取消全选", "Deselect All"))

        # Update topic list items
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            topic = item.data(Qt.ItemDataRole.UserRole)
            label_text = topic_label(topic, lang)
            item.setText(label_text)
            key = topic_value(topic)
            if key in self.topic_weight_labels:
                label = self.topic_weight_labels[key]
                label.setText(_compact_label_text(label_text, limit=34))
                label.setToolTip(label_text)

        self.count_label.setText(self.lang_manager.get_text("数量:", "Count:"))
        self.set_title_label.setText(self.lang_manager.get_text("题集名称:", "Set name:"))
        self.set_title_input.setPlaceholderText(
            self.lang_manager.get_text("留空则自动命名", "Leave blank to name automatically")
        )
        self.diff_label.setText(self.lang_manager.get_text("整体难度:", "Overall difficulty:"))
        self.config_group.setTitle(self.lang_manager.get_text("生成参数", "Generation Settings"))
        self.template_label.setText(self.lang_manager.get_text("模板:", "Template:"))

        current_template = self.template_combo.currentData()
        template_labels = (
            ("快速复习", "Quick Review"),
            ("期末模拟", "Final Exam Style"),
            ("计算训练", "Calculation Practice"),
        )
        for index, (zh, en) in enumerate(template_labels):
            self.template_combo.setItemText(index, self.lang_manager.get_text(zh, en))
        template_index = self.template_combo.findData(current_template)
        if template_index >= 0:
            self.template_combo.setCurrentIndex(template_index)

        # Rebuild difficulty combo items preserving the selected value
        current_diff = self.diff_combo.currentData()
        self.diff_combo.clear()
        difficulties = [
            (self.lang_manager.get_text("简单", "easy"), "easy"),
            (self.lang_manager.get_text("中等", "medium"), "medium"),
            (self.lang_manager.get_text("困难", "hard"), "hard"),
            (self.lang_manager.get_text("混合", "mixed"), "mixed"),
        ]
        for display, value in difficulties:
            self.diff_combo.addItem(display, value)
        for i in range(self.diff_combo.count()):
            if self.diff_combo.itemData(i) == current_diff:
                self.diff_combo.setCurrentIndex(i)
                break

        self.prompt_group.setTitle(self.lang_manager.get_text("课程内容预览", "Course Content Preview"))
        self.structure_group.setTitle(self.lang_manager.get_text("题目结构", "Question Structure"))
        self.question_type_heading.setText(
            self.lang_manager.get_text("题型权重", "Question type weights")
        )
        self.mc_label.setText(self.lang_manager.get_text("选择题", "Multiple choice"))
        self.scenario_label.setText(self.lang_manager.get_text("情境选择题", "Scenario choice"))
        self.true_false_label.setText(self.lang_manager.get_text("判断题", "True / false"))
        self.fill_blank_label.setText(self.lang_manager.get_text("填空题", "Fill in the blank"))
        self.difficulty_weight_heading.setText(
            self.lang_manager.get_text("难度权重", "Difficulty weights")
        )
        self.easy_label.setText(self.lang_manager.get_text("简单", "Easy"))
        self.medium_label.setText(self.lang_manager.get_text("中等", "Medium"))
        self.hard_label.setText(self.lang_manager.get_text("困难", "Hard"))
        self.refresh_weight_preview_btn.setText(
            self.lang_manager.get_text("更新权重显示", "Update Weight Preview")
        )
        if hasattr(self, "topic_weight_group"):
            self.topic_weight_group.setTitle(self.lang_manager.get_text("知识点权重", "Topic Weights"))
        self.plan_group.setTitle(
            self.lang_manager.get_text("生成计划预览", "Generation Plan Preview")
        )
        self.generation_log_group.setTitle(
            self.lang_manager.get_text("生成过程", "Generation Activity")
        )
        self.generation_log.setPlaceholderText(
            self.lang_manager.get_text(
                "开始生成后显示批次、接受、拒绝和错误摘要。",
                "Generation batches, accepted counts, rejections, and errors will appear here.",
            )
        )
        if hasattr(self, "topic_weight_empty_label"):
            self.topic_weight_empty_label.setText(
                self.lang_manager.get_text(
                    "选择左侧主题后显示对应权重。",
                    "Select topics on the left to show their weights.",
                )
            )
        self._update_preview()

        self.cancel_btn.setText(self.lang_manager.get_text("取消", "Cancel"))
        self.generate_btn.setText(self.lang_manager.get_text("生成题目", "Generate Questions"))
        self.partial_recovery_label.setText(self._partial_recovery_hint(self.lang_manager.current))
        self.exam_assistant_btn.setText(
            self.lang_manager.get_text("试卷助手…", "Exam Assistant…")
        )

    def _toggle_all(self, selected: bool):
        """Select/deselect all topics."""
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def _selected_topic_keys(self) -> list[str]:
        return [topic_value(topic) for topic in self._get_selected_topics()]

    def _on_topics_changed(self) -> None:
        self._sync_topic_weight_rows()
        self._update_preview()

    def _sync_topic_weight_rows(self) -> None:
        selected = set(self._selected_topic_keys())
        for key, row in self.topic_weight_rows.items():
            visible = key in selected
            row.setVisible(visible)
            label = self.topic_weight_labels.get(key)
            if label is not None:
                label.setVisible(visible)
        if hasattr(self, "topic_weight_empty_label"):
            self.topic_weight_empty_label.setVisible(not selected)

    def _get_selected_topics(self) -> list:
        """Get list of selected Topic enums."""
        topics = []
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                topics.append(item.data(Qt.ItemDataRole.UserRole))
        return topics

    def configure_from_question_set(self, question_set):
        """Pre-fill controls from a set, including its persisted generation history."""
        metadata = question_set.metadata or {}
        payload = {
            "question_count": max(
                self.count_spin.minimum(),
                min(self.count_spin.maximum(), question_set.question_count),
            ),
            "difficulty": metadata.get("difficulty_mode", question_set.difficulty.value),
            "template": metadata.get("generation_template", self.template_combo.currentData()),
            "selected_topics": [topic_value(topic) for topic in question_set.topics],
        }
        for field in (
            "question_type_weights",
            "difficulty_weights",
            "topic_weights",
        ):
            value = metadata.get(field)
            if isinstance(value, dict):
                payload[field] = value
        try:
            patch = ExamPlanPatch.from_mapping(payload)
            plan = apply_exam_plan_patch(
                self.build_exam_plan(),
                patch,
                self._available_topic_keys(),
            )
            self.apply_exam_plan(plan)
        except ExamPlanValidationError:
            # Legacy or partially corrupted sets still retain their basic fields.
            self.count_spin.setValue(payload["question_count"])
            difficulty_index = self.diff_combo.findData(question_set.difficulty.value)
            if difficulty_index >= 0:
                self.diff_combo.setCurrentIndex(difficulty_index)
            wanted_topics = set(payload["selected_topics"])
            for i in range(self.topic_list.count()):
                item = self.topic_list.item(i)
                key = topic_value(item.data(Qt.ItemDataRole.UserRole))
                item.setCheckState(
                    Qt.CheckState.Checked if key in wanted_topics else Qt.CheckState.Unchecked
                )
            self._update_preview()

    def configure_from_course_profile(self, course_project) -> bool:
        """Apply persisted course defaults, rejecting malformed legacy data safely."""
        profile = getattr(course_project, "generation_profile", None)
        if not profile:
            return False
        try:
            patch = ExamPlanPatch.from_mapping(profile)
            plan = apply_exam_plan_patch(
                self.build_exam_plan(),
                patch,
                self._available_topic_keys(),
            )
            self.apply_exam_plan(plan)
        except (ExamPlanValidationError, TypeError, ValueError) as exc:
            self.status_label.setObjectName("errorLabel")
            self.status_label.setText(
                self.lang_manager.get_text(
                    f"课程默认配置无效，已保留系统默认值：{exc}",
                    f"Invalid course defaults; system defaults were kept: {exc}",
                )
            )
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            return False

        source = getattr(course_project, "generation_profile_source", "local")
        warning = str(getattr(course_project, "generation_profile_warning", "") or "").strip()
        source_text = self.lang_manager.get_text(
            "LLM 建议" if source == "llm" else "本地回退",
            "LLM suggestion" if source == "llm" else "local fallback",
        )
        message = self.lang_manager.get_text(
            f"已应用本课程默认出题配置（{source_text}）。",
            f"Applied this course's quiz defaults ({source_text}).",
        )
        if warning:
            message = f"{message} {warning}"
        self.status_label.setObjectName("")
        self.status_label.setText(message)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        return True

    def _available_topic_keys(self) -> list[str]:
        return [
            topic_value(self.topic_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.topic_list.count())
        ]

    def build_exam_plan(self) -> ExamGenerationPlan:
        """Capture the current controls as an immutable assistant draft."""
        topics = tuple(topic_value(topic) for topic in self._get_selected_topics())
        topic_weights = {
            topic: self.topic_weight_sliders[topic].value()
            for topic in topics
            if topic in self.topic_weight_sliders
        }
        return ExamGenerationPlan(
            question_count=self.count_spin.value(),
            difficulty=self.diff_combo.currentData() or "medium",
            template=self.template_combo.currentData() or "quick_review",
            selected_topics=topics,
            question_type_weights={
                "multiple_choice": self.mc_slider.value(),
                "scenario_choice": self.scenario_slider.value(),
                "true_false": self.true_false_slider.value(),
                "fill_in_blank": self.fill_blank_slider.value(),
            },
            difficulty_weights={
                "easy": self.easy_slider.value(),
                "medium": self.medium_slider.value(),
                "hard": self.hard_slider.value(),
            },
            topic_weights=topic_weights,
        )

    def apply_exam_plan(self, plan: ExamGenerationPlan):
        """Apply one confirmed assistant plan to every generation control."""
        available = {
            topic_value(self.topic_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.topic_list.count())
        }
        unknown = sorted(set(plan.selected_topics) - available)
        if unknown:
            raise ValueError(f"Exam plan contains unavailable topics: {', '.join(unknown)}")

        self.count_spin.setValue(plan.question_count)
        difficulty_index = self.diff_combo.findData(plan.difficulty)
        if difficulty_index >= 0:
            self.diff_combo.setCurrentIndex(difficulty_index)
        template_index = self.template_combo.findData(plan.template)
        if template_index >= 0:
            self.template_combo.setCurrentIndex(template_index)

        wanted = set(plan.selected_topics)
        self.topic_list.blockSignals(True)
        try:
            for index in range(self.topic_list.count()):
                item = self.topic_list.item(index)
                key = topic_value(item.data(Qt.ItemDataRole.UserRole))
                item.setCheckState(
                    Qt.CheckState.Checked if key in wanted else Qt.CheckState.Unchecked
                )
        finally:
            self.topic_list.blockSignals(False)

        slider_values = {
            self.mc_slider: plan.question_type_weights["multiple_choice"],
            self.scenario_slider: plan.question_type_weights["scenario_choice"],
            self.true_false_slider: plan.question_type_weights["true_false"],
            self.fill_blank_slider: plan.question_type_weights["fill_in_blank"],
            self.easy_slider: plan.difficulty_weights["easy"],
            self.medium_slider: plan.difficulty_weights["medium"],
            self.hard_slider: plan.difficulty_weights["hard"],
        }
        for slider, value in slider_values.items():
            slider.setValue(value)
        for topic, slider in self.topic_weight_sliders.items():
            if topic in plan.topic_weights:
                slider.setValue(plan.topic_weights[topic])
        self._sync_topic_weight_rows()
        self._refresh_weight_labels()
        self._update_preview()

    def _open_exam_assistant(self):
        """Open a reviewable dialogue and apply only its confirmed plan."""
        from ui.dialogs.exam_assistant_dialog import ExamAssistantDialog

        available = [topic_value(topic) for topic in self.available_topics]
        assistant = ExamAssistantDialog(
            self.build_exam_plan(),
            available,
            settings=self.settings,
            parent=self,
        )
        if assistant.exec() != QDialog.DialogCode.Accepted:
            return
        plan = assistant.get_confirmed_plan()
        if plan is not None:
            self.apply_exam_plan(plan)

    def _update_preview(self):
        """Show a brief preview of relevant course content."""
        topics = self._get_selected_topics()
        self._update_plan_preview(topics)
        if not topics:
            self.prompt_preview.setPlainText(
                self.lang_manager.get_text(
                    "选择主题以查看相关课程内容...",
                    "Select topics to see relevant course content..."
                )
            )
            return

        topic_names = [
            topic_label(t, self.lang_manager.current) for t in topics
        ]
        if self.course_project is not None:
            context = retrieve_course_context(
                self.course_project,
                [topic_value(t) for t in topics],
                max_chars=1800,
            )
        else:
            context = extract_relevant_course_context(self.course_content, topics, max_chars=1800)

        if self.lang_manager.current == "zh":
            preview = (
                f"已选择 {len(topics)} 个主题: {', '.join(topic_names)}\n"
                f"提示上下文预览:\n\n{context[:1800]}"
            )
        else:
            preview = (
                f"Selected {len(topics)} topic(s): {', '.join(topic_names)}\n"
                f"Prompt context preview:\n\n{context[:1800]}"
            )
        self.prompt_preview.setPlainText(preview)

    def _update_plan_preview(self, topics: list) -> None:
        """Show exact marginal quotas before launching generation."""
        if not hasattr(self, "plan_preview"):
            return
        if not topics:
            self.plan_preview.setPlainText(
                self.lang_manager.get_text(
                    "选择主题后显示本次题量、主题、题型和难度分布。",
                    "Select topics to preview count, topic, type, and difficulty distribution.",
                )
            )
            return

        config = self._build_generation_config()
        count = self.count_spin.value()
        topic_keys = [topic_value(topic) for topic in topics]
        topic_titles = {
            topic_value(topic): topic_label(topic, self.lang_manager.current)
            for topic in topics
        }
        plan = planned_generation_counts(config, topic_keys, count)
        plan_items = build_question_plan(config, topic_keys, count, topic_titles)
        if self.lang_manager.current == "zh":
            lines = [f"本次计划生成 {count} 题"]
            sections = (
                ("主题分布", plan["topics"]),
                ("题型分布", plan["question_types"]),
                ("难度分布", plan["difficulties"]),
                ("能力分布", Counter(item.target_skill for item in plan_items)),
            )
        else:
            lines = [f"Planned total: {count} question(s)"]
            sections = (
                ("Topic distribution", plan["topics"]),
                ("Question type distribution", plan["question_types"]),
                ("Difficulty distribution", plan["difficulties"]),
                ("Skill distribution", Counter(item.target_skill for item in plan_items)),
            )
        for title, values in sections:
            lines.append("")
            lines.append(title)
            for key, value in values.items():
                if value > 0:
                    lines.append(f"- {key}: {value}")
        self._append_plan_item_summary(lines, plan_items)
        self.plan_preview.setPlainText("\n".join(lines))

    def _append_plan_item_summary(self, lines: list[str], plan_items: list) -> None:
        if self.lang_manager.current == "zh":
            lines.append("")
            lines.append("组合计划")
            for topic_id, groups in summarize_plan_items(plan_items).items():
                topic_title = next(
                    (item.topic_title for item in plan_items if item.topic_id == topic_id),
                    topic_id,
                )
                lines.append(topic_title)
                for (question_type, difficulty, skill), amount in groups.items():
                    lines.append(f"- {amount} 道 {difficulty} / {question_type} / {skill}")
            return

        lines.append("")
        lines.append("Combination plan")
        for topic_id, groups in summarize_plan_items(plan_items).items():
            topic_title = next(
                (item.topic_title for item in plan_items if item.topic_id == topic_id),
                topic_id,
            )
            lines.append(topic_title)
            for (question_type, difficulty, skill), amount in groups.items():
                lines.append(f"- {amount} x {difficulty} / {question_type} / {skill}")

    def _start_generation(self):
        """Start the background generation process."""
        topics = self._get_selected_topics()
        if not topics:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("未选择主题", "No Topics"),
                self.lang_manager.get_text("请至少选择一个主题。", "Please select at least one topic.")
            )
            return

        from core.secrets_manager import SecretsManager
        requires_api_key = provider_requires_api_key(self.settings)
        api_key = SecretsManager.instance().get_key() if requires_api_key else ""
        if requires_api_key and not api_key:
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("未配置 API Key", "No API Key"),
                self.lang_manager.get_text("请在设置中配置 API Key。", "Please configure your API key in Settings.")
            )
            return

        base_url = self.settings.get("ai_base_url", "https://api.anthropic.com/v1")
        model = self.settings.get("ai_model", "claude-sonnet-4-6")
        count = self.count_spin.value()
        difficulty = self.diff_combo.currentData()
        generation_config = self._build_generation_config()

        # Disable UI during generation
        self._generation_failed = False
        self._generation_cancelled = False
        self._partial_generation_error = None
        self._partial_generation_report = None
        self.generated_questions = []
        self._generation_started_at = time.monotonic()
        self._last_generation_progress = self.lang_manager.get_text(
            "正在启动 AI 出题任务…",
            "Starting AI generation...",
        )
        self.partial_recovery_label.setHidden(True)
        self.partial_recovery_label.clear()
        self._reset_generation_log()
        self._append_generation_event(self._last_generation_progress)
        self._refresh_generation_status()
        self.generation_status_timer.start()
        self.generate_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate

        # Create client and worker
        client = LLMClient(api_key=api_key, base_url=base_url, model=model)
        self.worker = GenerationWorker(
            client, self.course_content, topics, count, difficulty,
            course_project=self.course_project,
            generation_config=generation_config,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.batch_done.connect(self._on_batch_done)
        self.worker.partial_done.connect(self._on_partial_done)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _build_generation_config(self) -> GenerationConfig:
        topics = self._get_selected_topics()
        topic_weights = {}
        for topic in topics:
            key = topic_value(topic)
            slider = self.topic_weight_sliders.get(key)
            if slider is not None:
                topic_weights[key] = slider.value()
        if not topic_weights:
            topic_weight = 100 // len(topics) if topics else 0
            topic_weights = {topic_value(topic): topic_weight for topic in topics}
            if topics:
                topic_weights[topic_value(topics[-1])] += 100 - sum(topic_weights.values())
        return GenerationConfig(
            question_type_weights={
                "multiple_choice": self.mc_slider.value(),
                "scenario_choice": self.scenario_slider.value(),
                "true_false": self.true_false_slider.value(),
                "fill_in_blank": self.fill_blank_slider.value(),
            },
            difficulty_weights={
                "easy": self.easy_slider.value(),
                "medium": self.medium_slider.value(),
                "hard": self.hard_slider.value(),
            },
            topic_weights=topic_weights,
            template=self.template_combo.currentData() or "quick_review",
        )

    def question_set_title(self) -> str:
        """Return the optional user-supplied title for the new question set."""
        return self.set_title_input.text().strip()

    def _on_progress(self, message: str):
        if self._generation_cancelled:
            return
        self._last_generation_progress = message
        self._append_generation_event(message)
        self._refresh_generation_status()

    def _reset_generation_log(self) -> None:
        self._generation_events = []
        if hasattr(self, "generation_log"):
            self.generation_log.clear()

    def _append_generation_event(self, message: str) -> None:
        clean = " ".join(str(message or "").split())
        if not clean:
            return
        self._generation_events.append(clean)
        self._generation_events = self._generation_events[-40:]
        if hasattr(self, "generation_log"):
            self.generation_log.setPlainText("\n".join(self._generation_events))

    def _refresh_generation_status(self):
        if self._generation_cancelled:
            return
        base = self._last_generation_progress or self.lang_manager.get_text(
            "正在生成题目…",
            "Generating questions...",
        )
        if self._generation_started_at is None:
            self.status_label.setText(base)
            return
        elapsed = int(max(0, time.monotonic() - self._generation_started_at))
        if self.lang_manager.current == "zh":
            self.status_label.setText(f"{base}（已用 {elapsed}s，可取消）")
        else:
            self.status_label.setText(f"{base} ({elapsed}s elapsed, cancellable)")

    def _on_batch_done(self, questions: list[Question]):
        if self._generation_cancelled:
            return
        self._partial_generation_error = None
        self._partial_generation_report = None
        self.generated_questions = questions
        self.partial_recovery_label.setHidden(True)
        self.partial_recovery_label.clear()
        self._append_generation_event(
            self.lang_manager.get_text(
                f"已收到 {len(questions)} 道候选题，准备进入审核。",
                f"Received {len(questions)} question(s); preparing review.",
            )
        )

    def _on_partial_done(self, questions: list[Question], report_or_reason):
        if self._generation_cancelled:
            return
        self.generated_questions = questions
        self._append_generation_event(
            self.lang_manager.get_text(
                f"生成未完成，但保留了 {len(questions)} 道可审核题目。",
                f"Generation incomplete; kept {len(questions)} reviewable question(s).",
            )
        )
        if isinstance(report_or_reason, GenerationReport):
            self._partial_generation_report = report_or_reason
            self._partial_generation_error = report_or_reason.error
        else:
            self._partial_generation_report = None
            self._partial_generation_error = coerce_app_error(
                report_or_reason,
                default_code="GEN-PARTIAL-001",
                title_zh="生成未完成",
                title_en="Generation incomplete",
                action_zh="可先审核并保存已生成题目，稍后再继续补齐。",
                action_en="Review and save the generated questions now, then continue later.",
            )
        self.partial_recovery_label.setText(self._partial_recovery_hint(self.lang_manager.current))
        self.partial_recovery_label.setHidden(False)
        self.status_label.setText(self._partial_status_text(self.lang_manager.current))

    def _on_error(self, message):
        if self._generation_cancelled:
            return
        self._generation_failed = True
        app_error = coerce_app_error(
            message,
            default_code="GEN-AI-001",
            title_zh="生成错误",
            title_en="Generation error",
            action_zh="请检查 AI 设置、网络连接或稍后重试。",
            action_en="Check AI settings, network connectivity, or try again later.",
        )
        lang = self.lang_manager.current
        self._append_generation_event(app_error.status_text(lang))
        self.generation_status_timer.stop()
        self._generation_started_at = None
        self.partial_recovery_label.setHidden(True)
        self.partial_recovery_label.clear()
        self.status_label.setText(app_error.status_text(lang))
        QMessageBox.critical(
            self,
            app_error.title(lang),
            format_app_error(app_error, lang),
        )
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    def _on_finished(self):
        if self._generation_cancelled:
            return
        self.generation_status_timer.stop()
        self._generation_started_at = None
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        if self._generation_failed:
            return

        if self.generated_questions:
            partial_error = self._partial_generation_error
            if self.lang_manager.current == "zh":
                if partial_error:
                    self.status_label.setText(
                        f"{self._partial_status_text('zh')} 正在打开预览..."
                    )
                else:
                    self.status_label.setText(f"已生成 {len(self.generated_questions)} 道题目。正在打开预览...")
            else:
                if partial_error:
                    self.status_label.setText(
                        f"{self._partial_status_text('en')} Opening review..."
                    )
                else:
                    self.status_label.setText(f"Generated {len(self.generated_questions)} questions. Opening review...")
            # Open review dialog
            review_dialog = QuestionReviewDialog(self.generated_questions, self)
            if review_dialog.exec() == QDialog.DialogCode.Accepted:
                accepted = review_dialog.get_accepted_questions()
                if not accepted:
                    QMessageBox.warning(
                        self,
                        self.lang_manager.get_text("没有接受的题目", "No Questions Accepted"),
                        self.lang_manager.get_text(
                            "没有题目被接受，请至少接受一道题目或取消操作。",
                            "No questions were accepted. Please accept at least one or cancel."
                        )
                    )
                    self.generate_btn.setEnabled(True)
                    self.progress_bar.setVisible(False)
                    return
                self.generated_questions = accepted
                self.accept()
        else:
            self.status_label.setText(self.lang_manager.get_text("未生成任何题目。", "No questions were generated."))

        if not self.worker:
            self.status_label.setText(self.lang_manager.get_text("未生成任何题目。", "No questions were generated."))

    def _partial_status_text(self, lang: str) -> str:
        if self._partial_generation_report is not None:
            title = "生成未完成" if lang == "zh" else "Generation incomplete"
            code = self._partial_generation_report.error.code if self._partial_generation_report.error else "GEN-PARTIAL-001"
            return f"{title}: {self._partial_generation_report.summary_text(lang)} [{code}]"
        if self._partial_generation_error is not None:
            return self._partial_generation_error.status_text(lang)
        return ""

    def _partial_recovery_hint(self, lang: str) -> str:
        if lang == "zh":
            return "下一步: 可保存已生成题目；也可放宽约束后重新生成。"
        return "Next: save generated questions, or relax constraints and generate again."

    def reject(self):
        """Cancel generation if the dialog is closed while a worker is running."""
        if self.worker and self.worker.isRunning():
            self._generation_cancelled = True
            self.generation_status_timer.stop()
            self.worker.cancel()
        super().reject()
