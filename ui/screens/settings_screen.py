"""Settings screen — language, API key, data management.

Changes from previous version:
- Explicit "Save Settings" button instead of auto-save on every keystroke
- _initializing guard prevents signal-cascade crash during _populate_from_settings
- Custom endpoint supports manual model entry
- Save shows confirmation; errors are caught and displayed
"""

import json
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QComboBox, QLineEdit, QFormLayout, QMessageBox,
    QFileDialog, QScrollArea, QFrame, QSpinBox, QCheckBox, QApplication,
    QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from core.environment_check import collect_environment_report, format_environment_report
from core.ocr_runtime import OCR_REMEDIATION
from core.language_manager import LanguageManager
from config import (
    APP_NAME,
    BASE_DIR,
    DATA_DIR,
    SETTINGS_FILE,
    DEFAULT_SETTINGS,
    DEFAULT_DIFFICULTY_WEIGHTS,
    DEFAULT_QUESTION_TYPE_WEIGHTS,
)
from utils.json_io import read_json, write_json, sanitize_filename_part
from ai.connection_probe import AIConnectionProbe
from ai.provider_presets import (
    PROVIDER_PRESETS,
    default_provider_settings,
    provider_from_base_url,
    detect_local_agents,
)
from ai.course_summary_factory import provider_requires_api_key
from ui.font_scale import apply_font_scale
from ai.settings_validation import validate_ai_settings
from ui.widgets.wheel_safe_controls import WheelSafeComboBox, WheelSafeSpinBox
from core.background_task import BackgroundTaskCancelled, TaskControl, TaskProgress
from core.background_task_bridge import BackgroundTaskBridge


def _normalize_weight_shares(weights: dict[str, int]) -> dict[str, int]:
    """Normalize relative weights into integer percentages that sum to 100."""
    keys = list(weights)
    if not keys:
        return {}
    source = {key: max(0, int(weights[key])) for key in keys}
    total = sum(source.values())
    if total <= 0:
        return {key: 0 for key in keys}
    raw = {key: source[key] * 100 / total for key in keys}
    normalized = {key: int(raw[key]) for key in keys}
    remainder = 100 - sum(normalized.values())
    ranked = sorted(
        keys,
        key=lambda key: (-(raw[key] - normalized[key]), keys.index(key)),
    )
    for key in ranked[:remainder]:
        normalized[key] += 1
    return normalized


def _secret_storage_warning(secrets) -> str:
    getter = getattr(secrets, "get_storage_warning", None)
    if not callable(getter):
        return ""
    return str(getter() or "")


class AIConnectionTestWorker(QThread):
    """Run the provider connection probe away from the UI thread."""

    result_ready = pyqtSignal(object)

    def __init__(self, probe: AIConnectionProbe, settings: dict, api_key: str, parent=None):
        super().__init__(parent)
        self.probe = probe
        self.settings = dict(settings)
        self.api_key = api_key

    def run(self):
        self.result_ready.emit(self.probe.run(self.settings, self.api_key))


class AppDataBundleWorker(QThread):
    """Run app data bundle import/export away from the UI thread."""

    exported = pyqtSignal(object)
    imported = pyqtSignal(object)
    failed = pyqtSignal(str)
    progressed = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(
        self,
        operation: str,
        filepath: str,
        data_dir: str,
        parent=None,
        *,
        task_center=None,
        task_id: str = "",
    ):
        super().__init__(parent)
        self.operation = operation
        self.filepath = filepath
        self.data_dir = data_dir
        self.task_id = str(task_id or "")
        self._bridge = (
            BackgroundTaskBridge(task_center, self.task_id)
            if task_center is not None and self.task_id
            else None
        )
        self._control = TaskControl(self._report_progress)

    def cancel(self):
        self._control.cancel()

    def _report_progress(self, progress: TaskProgress):
        self.progressed.emit(progress)
        if self._bridge is not None:
            self._bridge.report(progress)

    def run(self):
        if self._bridge is not None and not self._bridge.start(self.cancel):
            self.cancelled.emit()
            return
        try:
            if self.operation == "export":
                from core.app_data_bundle import export_app_data_bundle

                written = export_app_data_bundle(
                    self.data_dir,
                    self.filepath,
                    task=self._control,
                )
                if self._bridge is not None:
                    self._bridge.complete(result_summary=str(written), result_count=1)
                self.exported.emit(written)
            elif self.operation == "import":
                from core.app_data_bundle import import_app_data_bundle

                result = import_app_data_bundle(
                    self.filepath,
                    self.data_dir,
                    task=self._control,
                )
                if self._bridge is not None:
                    self._bridge.complete(
                        result_summary=str(self.filepath),
                        result_count=result.imported_files,
                    )
                self.imported.emit(result)
            else:
                raise ValueError(f"Unsupported app data operation: {self.operation}")
        except BackgroundTaskCancelled:
            if self._bridge is not None:
                self._bridge.cancelled()
            self.cancelled.emit()
        except Exception as exc:
            if self._bridge is not None:
                self._bridge.fail(exc)
            self.failed.emit(str(exc))


class SettingsScreen(QWidget):
    """Application settings with explicit save, crash-safe initialization."""

    def __init__(self, parent=None, connection_probe_factory=None, task_center=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self._settings = self._load_settings()
        self._connection_probe_factory = connection_probe_factory or AIConnectionProbe
        self.task_center = task_center
        self._connection_test_worker = None
        self._app_data_worker = None
        self._app_data_task_id = ""
        self._app_data_operation = ""
        self._initializing = True
        self.settings_dirty = False
        self._setup_ui()
        self._connect_settings_dirty_tracking()
        self._populate_from_settings()
        self._initializing = False
        self._set_settings_dirty(False)

    # ── Init helpers ──────────────────────────────────────────

    def _load_settings(self) -> dict:
        data = read_json(SETTINGS_FILE)
        if data:
            return {**DEFAULT_SETTINGS, **data}
        return dict(DEFAULT_SETTINGS)

    def _setup_ui(self):
        # Outer layout: VSCode/Clash-style category navigation + detail pane.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.settings_nav_list = QListWidget()
        self.settings_nav_list.setObjectName("settingsNavList")
        self.settings_nav_list.setMinimumWidth(150)
        self.settings_nav_list.setMaximumWidth(200)
        self.settings_nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings_nav_list.currentRowChanged.connect(self._on_settings_nav_changed)
        outer.addWidget(self.settings_nav_list)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )

        self.settings_content = QWidget()
        self.settings_content.setMaximumWidth(960)
        layout = QVBoxLayout(self.settings_content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.title = QLabel(self.lang_manager.get_text("设置", "Settings"))
        self.title.setObjectName("screenTitle")
        layout.addWidget(self.title)

        # ── Language ──
        self.lang_group = QGroupBox(self.lang_manager.get_text("显示语言", "Language"))
        lang_layout = QFormLayout(self.lang_group)
        lang_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        lang_layout.setHorizontalSpacing(16)
        lang_layout.setVerticalSpacing(10)
        self.lang_combo = WheelSafeComboBox()
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.currentIndexChanged.connect(self._on_language_combo_changed)
        self.lang_label = QLabel(self.lang_manager.get_text("显示语言:", "Display language:"))
        lang_layout.addRow(self.lang_label, self.lang_combo)
        self.font_scale_combo = WheelSafeComboBox()
        self.font_scale_combo.addItem(self.lang_manager.get_text("小", "Small"), "small")
        self.font_scale_combo.addItem(self.lang_manager.get_text("中", "Medium"), "medium")
        self.font_scale_combo.addItem(self.lang_manager.get_text("大", "Large"), "large")
        self.font_scale_label = QLabel(self.lang_manager.get_text("字体大小:", "Font size:"))
        lang_layout.addRow(self.font_scale_label, self.font_scale_combo)
        layout.addWidget(self.lang_group)

        # ── AI Generation ──
        self.ai_group = QGroupBox(self.lang_manager.get_text("AI 出题", "AI Question Generation"))
        self.ai_form_layout = QFormLayout(self.ai_group)
        self.ai_form_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.ai_form_layout.setHorizontalSpacing(16)
        self.ai_form_layout.setVerticalSpacing(10)

        # Provider
        self.provider_combo = WheelSafeComboBox()
        for key, preset in PROVIDER_PRESETS.items():
            self.provider_combo.addItem(preset["label"], key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_label = QLabel(self.lang_manager.get_text("提供商:", "Provider:"))
        self.ai_form_layout.addRow(self.provider_label, self.provider_combo)

        # API key
        self.api_key_row = QWidget()
        api_key_row_layout = QHBoxLayout(self.api_key_row)
        api_key_row_layout.setContentsMargins(0, 0, 0, 0)
        api_key_row_layout.setSpacing(8)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_row_layout.addWidget(self.api_key_input, 1)
        self.clear_api_key_btn = QPushButton(
            self.lang_manager.get_text("清除", "Clear")
        )
        self.clear_api_key_btn.setObjectName("secondaryButton")
        self.clear_api_key_btn.clicked.connect(self._clear_api_key)
        api_key_row_layout.addWidget(self.clear_api_key_btn)
        self.api_key_label = QLabel(self.lang_manager.get_text("API 密钥:", "API Key:"))
        self.ai_form_layout.addRow(self.api_key_label, self.api_key_row)

        # Base URL
        self.api_base_url = QLineEdit()
        self.api_base_url.setPlaceholderText(
            self.lang_manager.get_text(
                "例如: https://api.anthropic.com/v1",
                "e.g. https://api.anthropic.com/v1"))
        self.api_base_url.textChanged.connect(self._on_base_url_edited)
        self.api_base_url_label = QLabel(self.lang_manager.get_text("API 地址:", "API Base URL:"))
        self.ai_form_layout.addRow(self.api_base_url_label, self.api_base_url)

        # Model
        self.model_combo = WheelSafeComboBox()
        self.model_combo.setEditable(True)
        self.model_label = QLabel(self.lang_manager.get_text("模型:", "Model:"))
        self.ai_form_layout.addRow(self.model_label, self.model_combo)

        # Help / local agent status
        self.provider_help = QLabel()
        self.provider_help.setWordWrap(True)
        self.provider_help.setObjectName("settingsProviderHelp")
        self.ai_form_layout.addRow("", self.provider_help)

        self.local_agent_status = QLabel()
        self.local_agent_status.setWordWrap(True)
        self.local_agent_status.setObjectName("settingsLocalAgentStatus")
        self.local_agent_label = QLabel(self.lang_manager.get_text("本地代理:", "Local agent:"))
        self.ai_form_layout.addRow(self.local_agent_label, self.local_agent_status)

        self.ai_connection_status = QLabel(
            self.lang_manager.get_text(
                "尚未测试连接。",
                "Connection has not been tested yet.",
            )
        )
        self.ai_connection_status.setWordWrap(True)
        self.ai_connection_status.setObjectName("settingsConnectionStatus")
        self.ai_connection_status_label = QLabel(self.lang_manager.get_text("连接状态:", "Connection:"))
        self.ai_form_layout.addRow(
            self.ai_connection_status_label,
            self.ai_connection_status,
        )

        # Save button
        self.ai_action_layout = QHBoxLayout()
        self.ai_action_layout.setContentsMargins(0, 8, 0, 0)
        self.ai_action_layout.addStretch()
        self.test_ai_btn = QPushButton(self.lang_manager.get_text("测试 AI 设置", "Test AI Settings"))
        self.test_ai_btn.setObjectName("secondaryButton")
        self.test_ai_btn.setMinimumHeight(34)
        self.test_ai_btn.clicked.connect(self._test_ai_settings)
        self.ai_action_layout.addWidget(self.test_ai_btn)
        self.save_btn = QPushButton(self.lang_manager.get_text("保存设置", "Save Settings"))
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setMinimumHeight(34)
        self.save_btn.clicked.connect(self.save_settings)
        self.ai_action_layout.addWidget(self.save_btn)
        self.settings_save_status = QLabel()
        self.settings_save_status.setObjectName("settingsSaveStatus")
        self.ai_action_layout.addWidget(self.settings_save_status)
        self.ai_form_layout.addRow("", self.ai_action_layout)

        layout.addWidget(self.ai_group)

        # ── Practice Defaults ──
        self.practice_group = QGroupBox(
            self.lang_manager.get_text("练习默认值", "Practice Defaults")
        )
        self.practice_form_layout = QFormLayout(self.practice_group)
        self.practice_form_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.practice_form_layout.setHorizontalSpacing(16)
        self.practice_form_layout.setVerticalSpacing(10)

        self.default_question_count_input = WheelSafeSpinBox()
        self.default_question_count_input.setRange(3, 60)
        self.default_question_count_input.setSingleStep(1)
        self.default_question_count_label = QLabel(
            self.lang_manager.get_text("默认题量:", "Default question count:")
        )
        self.practice_form_layout.addRow(
            self.default_question_count_label,
            self.default_question_count_input,
        )

        self.default_difficulty_combo = WheelSafeComboBox()
        self.default_difficulty_combo.addItem(self.lang_manager.get_text("简单", "Easy"), "easy")
        self.default_difficulty_combo.addItem(self.lang_manager.get_text("中等", "Medium"), "medium")
        self.default_difficulty_combo.addItem(self.lang_manager.get_text("困难", "Hard"), "hard")
        self.default_difficulty_label = QLabel(
            self.lang_manager.get_text("默认难度:", "Default difficulty:")
        )
        self.practice_form_layout.addRow(
            self.default_difficulty_label,
            self.default_difficulty_combo,
        )

        self.default_template_combo = WheelSafeComboBox()
        self._refresh_template_labels()
        self.default_template_label = QLabel(
            self.lang_manager.get_text("默认模板:", "Default template:")
        )
        self.practice_form_layout.addRow(
            self.default_template_label,
            self.default_template_combo,
        )

        self.weight_help_label = QLabel(self.lang_manager.get_text(
            "以下数值是相对权重，无需合计 100。调整后点击确认，下面才会更新最终占比。",
            "The values below are relative weights and do not need to total 100. Confirm after editing to update the effective shares.",
        ))
        self.weight_help_label.setObjectName("settingsProviderHelp")
        self.weight_help_label.setWordWrap(True)
        self.practice_form_layout.addRow(self.weight_help_label)

        self.question_type_weight_label = QLabel(
            self.lang_manager.get_text("默认题型相对权重", "Default question type relative weights")
        )
        self.question_type_weight_label.setObjectName("sectionLabel")
        self.practice_form_layout.addRow(self.question_type_weight_label)

        self.default_mc_weight_input = self._make_weight_spinbox(
            DEFAULT_QUESTION_TYPE_WEIGHTS["multiple_choice"]
        )
        self.default_scenario_weight_input = self._make_weight_spinbox(
            DEFAULT_QUESTION_TYPE_WEIGHTS["scenario_choice"]
        )
        self.default_true_false_weight_input = self._make_weight_spinbox(
            DEFAULT_QUESTION_TYPE_WEIGHTS["true_false"]
        )
        self.default_fill_blank_weight_input = self._make_weight_spinbox(
            DEFAULT_QUESTION_TYPE_WEIGHTS["fill_in_blank"]
        )
        self.default_matching_weight_input = self._make_weight_spinbox(
            DEFAULT_QUESTION_TYPE_WEIGHTS["matching"]
        )
        self.default_ordering_weight_input = self._make_weight_spinbox(
            DEFAULT_QUESTION_TYPE_WEIGHTS["ordering"]
        )
        self.default_short_answer_weight_input = self._make_weight_spinbox(
            DEFAULT_QUESTION_TYPE_WEIGHTS["short_answer"]
        )
        self.default_mc_weight_label = QLabel(self.lang_manager.get_text("选择题:", "Multiple choice:"))
        self.default_scenario_weight_label = QLabel(
            self.lang_manager.get_text("情境选择题:", "Scenario choice:")
        )
        self.default_true_false_weight_label = QLabel(
            self.lang_manager.get_text("判断题:", "True / false:")
        )
        self.default_fill_blank_weight_label = QLabel(
            self.lang_manager.get_text("填空题:", "Fill in the blank:")
        )
        self.advanced_question_type_weight_label = QLabel(
            self.lang_manager.get_text("高级题型（默认关闭）", "Advanced types (off by default)")
        )
        self.advanced_question_type_weight_label.setObjectName("sectionLabel")
        self.default_matching_weight_label = QLabel(
            self.lang_manager.get_text("配对题:", "Matching:")
        )
        self.default_ordering_weight_label = QLabel(
            self.lang_manager.get_text("排序题:", "Ordering:")
        )
        self.default_short_answer_weight_label = QLabel(
            self.lang_manager.get_text("简答题（需自评）:", "Short answer (self-assessed):")
        )
        self.practice_form_layout.addRow(self.default_mc_weight_label, self.default_mc_weight_input)
        self.practice_form_layout.addRow(
            self.default_scenario_weight_label,
            self.default_scenario_weight_input,
        )
        self.practice_form_layout.addRow(
            self.default_true_false_weight_label,
            self.default_true_false_weight_input,
        )
        self.practice_form_layout.addRow(
            self.default_fill_blank_weight_label,
            self.default_fill_blank_weight_input,
        )
        self.practice_form_layout.addRow(self.advanced_question_type_weight_label)
        self.practice_form_layout.addRow(
            self.default_matching_weight_label,
            self.default_matching_weight_input,
        )
        self.practice_form_layout.addRow(
            self.default_ordering_weight_label,
            self.default_ordering_weight_input,
        )
        self.practice_form_layout.addRow(
            self.default_short_answer_weight_label,
            self.default_short_answer_weight_input,
        )
        self.question_type_weight_preview = QLabel()
        self.question_type_weight_preview.setObjectName("settingsWeightPreview")
        self.question_type_weight_preview.setWordWrap(True)
        self.question_type_weight_preview_title = QLabel(
            self.lang_manager.get_text("有效占比:", "Effective share:")
        )
        self.practice_form_layout.addRow(
            self.question_type_weight_preview_title,
            self.question_type_weight_preview,
        )

        self.difficulty_weight_label = QLabel(
            self.lang_manager.get_text("默认难度相对权重", "Default difficulty relative weights")
        )
        self.difficulty_weight_label.setObjectName("sectionLabel")
        self.practice_form_layout.addRow(self.difficulty_weight_label)

        self.default_easy_weight_input = self._make_weight_spinbox(
            DEFAULT_DIFFICULTY_WEIGHTS["easy"]
        )
        self.default_medium_weight_input = self._make_weight_spinbox(
            DEFAULT_DIFFICULTY_WEIGHTS["medium"]
        )
        self.default_hard_weight_input = self._make_weight_spinbox(
            DEFAULT_DIFFICULTY_WEIGHTS["hard"]
        )
        self.default_easy_weight_label = QLabel(self.lang_manager.get_text("简单:", "Easy:"))
        self.default_medium_weight_label = QLabel(self.lang_manager.get_text("中等:", "Medium:"))
        self.default_hard_weight_label = QLabel(self.lang_manager.get_text("困难:", "Hard:"))
        self.practice_form_layout.addRow(self.default_easy_weight_label, self.default_easy_weight_input)
        self.practice_form_layout.addRow(
            self.default_medium_weight_label,
            self.default_medium_weight_input,
        )
        self.practice_form_layout.addRow(self.default_hard_weight_label, self.default_hard_weight_input)
        self.difficulty_weight_preview = QLabel()
        self.difficulty_weight_preview.setObjectName("settingsWeightPreview")
        self.difficulty_weight_preview.setWordWrap(True)
        self.difficulty_weight_preview_title = QLabel(
            self.lang_manager.get_text("有效占比:", "Effective share:")
        )
        self.practice_form_layout.addRow(
            self.difficulty_weight_preview_title,
            self.difficulty_weight_preview,
        )

        self.refresh_default_weight_preview_btn = QPushButton(
            self.lang_manager.get_text("确认并更新占比", "Confirm Effective Shares")
        )
        self.refresh_default_weight_preview_btn.setObjectName("secondaryButton")
        self.refresh_default_weight_preview_btn.clicked.connect(self._refresh_default_weight_previews)
        self.practice_form_layout.addRow("", self.refresh_default_weight_preview_btn)

        self.show_timer_checkbox = QCheckBox(
            self.lang_manager.get_text("练习时显示计时器", "Show timer during practice")
        )
        self.practice_form_layout.addRow("", self.show_timer_checkbox)

        layout.addWidget(self.practice_group)

        # ── Runtime Environment ──
        self.environment_group = QGroupBox(
            self.lang_manager.get_text("运行环境", "Runtime Environment")
        )
        environment_layout = QVBoxLayout(self.environment_group)
        environment_layout.setSpacing(10)
        self.environment_help = QLabel(
            self.lang_manager.get_text(
                "检查 Python 依赖、API Key 持久化、OCR/Tesseract 和 data/ 写入权限。",
                "Check Python packages, API key persistence, OCR/Tesseract, and data/ write access.",
            )
        )
        self.environment_help.setWordWrap(True)
        self.environment_help.setObjectName("settingsProviderHelp")
        environment_layout.addWidget(self.environment_help)
        self.environment_status = QLabel(
            self.lang_manager.get_text(
                "尚未检查运行环境。",
                "Runtime environment has not been checked yet.",
            )
        )
        self.environment_status.setWordWrap(True)
        self.environment_status.setObjectName("settingsEnvironmentStatus")
        self.environment_status.setProperty("envState", "unknown")
        environment_layout.addWidget(self.environment_status)

        self.environment_action_layout = QHBoxLayout()
        self.environment_action_layout.setContentsMargins(0, 0, 0, 0)
        self.environment_action_layout.addStretch()
        self.environment_check_btn = QPushButton(
            self.lang_manager.get_text("检查环境", "Check Environment")
        )
        self.environment_check_btn.setObjectName("secondaryButton")
        self.environment_check_btn.setMinimumHeight(34)
        self.environment_check_btn.clicked.connect(self._show_environment_check)
        self.environment_action_layout.addWidget(self.environment_check_btn)
        self.ocr_fix_btn = QPushButton(
            self.lang_manager.get_text("复制 OCR 修复命令", "Copy OCR Fix Commands")
        )
        self.ocr_fix_btn.setObjectName("secondaryButton")
        self.ocr_fix_btn.setMinimumHeight(34)
        self.ocr_fix_btn.clicked.connect(self._copy_ocr_fix_commands)
        self.environment_action_layout.addWidget(self.ocr_fix_btn)
        environment_layout.addLayout(self.environment_action_layout)

        layout.addWidget(self.environment_group)

        # ── Data Management ──
        self.data_group = QGroupBox(self.lang_manager.get_text("数据管理", "Data Management"))
        data_layout = QVBoxLayout(self.data_group)
        self.data_action_layout = QHBoxLayout()
        self.data_action_layout.setSpacing(8)

        self.export_btn = QPushButton(self.lang_manager.get_text("导出进度", "Export Progress"))
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.clicked.connect(self._export_progress)
        self.data_action_layout.addWidget(self.export_btn)

        self.import_btn = QPushButton(self.lang_manager.get_text("导入进度", "Import Progress"))
        self.import_btn.setObjectName("secondaryButton")
        self.import_btn.clicked.connect(self._import_progress)
        self.data_action_layout.addWidget(self.import_btn)

        self.export_app_data_btn = QPushButton(
            self.lang_manager.get_text("导出应用数据", "Export App Data")
        )
        self.export_app_data_btn.setObjectName("secondaryButton")
        self.export_app_data_btn.clicked.connect(self._export_app_data)
        self.data_action_layout.addWidget(self.export_app_data_btn)

        self.import_app_data_btn = QPushButton(
            self.lang_manager.get_text("导入应用数据", "Import App Data")
        )
        self.import_app_data_btn.setObjectName("secondaryButton")
        self.import_app_data_btn.clicked.connect(self._import_app_data)
        self.data_action_layout.addWidget(self.import_app_data_btn)

        self.reset_progress_btn = QPushButton(
            self.lang_manager.get_text("重置全部进度", "Reset All Progress"))
        self.reset_progress_btn.setObjectName("dangerButton")
        self.reset_progress_btn.clicked.connect(self._reset_progress)
        self.data_action_layout.addStretch()
        self.data_action_layout.addWidget(self.reset_progress_btn)
        data_layout.addLayout(self.data_action_layout)

        self.app_data_status_layout = QHBoxLayout()
        self.app_data_status_layout.setSpacing(8)
        self.app_data_status_label = QLabel("")
        self.app_data_status_label.setObjectName("secondaryText")
        self.app_data_status_label.setWordWrap(True)
        self.app_data_status_label.hide()
        self.app_data_status_layout.addWidget(self.app_data_status_label, 1)
        self.cancel_app_data_btn = QPushButton(
            self.lang_manager.get_text("停止", "Stop")
        )
        self.cancel_app_data_btn.setObjectName("secondaryButton")
        self.cancel_app_data_btn.clicked.connect(self._cancel_app_data)
        self.cancel_app_data_btn.hide()
        self.app_data_status_layout.addWidget(self.cancel_app_data_btn)
        data_layout.addLayout(self.app_data_status_layout)

        layout.addWidget(self.data_group)

        # ── About ──
        self.about_group = QGroupBox(self.lang_manager.get_text("关于", "About"))
        self.about_group.setObjectName("aboutSettingsGroup")
        about_layout = QVBoxLayout(self.about_group)
        self.about_description_label = QLabel()
        self.about_description_label.setWordWrap(True)
        self.about_description_label.setObjectName("secondaryText")
        about_layout.addWidget(self.about_description_label)
        self.about_license_label = QLabel("License: GPL-3.0-only")
        self.about_license_label.setObjectName("secondaryText")
        about_layout.addWidget(self.about_license_label)
        self.version_label = QLabel(f"{APP_NAME} v1.0.0")
        self.version_label.setObjectName("settingsVersionLabel")
        about_layout.addWidget(self.version_label)
        layout.addWidget(self.about_group)
        layout.addStretch()
        self._refresh_about_text()

        self.settings_scroll.setWidget(self.settings_content)
        outer.addWidget(self.settings_scroll, 1)
        self._refresh_settings_nav()
        self.settings_nav_list.setCurrentRow(0)

    # ── Language ──────────────────────────────────────────────

    def _on_language_changed(self, lang):
        self.title.setText(self.lang_manager.get_text("设置", "Settings"))
        self.lang_group.setTitle(self.lang_manager.get_text("显示语言", "Language"))
        self.lang_label.setText(self.lang_manager.get_text("显示语言:", "Display language:"))
        self.font_scale_label.setText(self.lang_manager.get_text("字体大小:", "Font size:"))
        font_scale_labels = (
            self.lang_manager.get_text("小", "Small"),
            self.lang_manager.get_text("中", "Medium"),
            self.lang_manager.get_text("大", "Large"),
        )
        for index, label in enumerate(font_scale_labels):
            self.font_scale_combo.setItemText(index, label)
        self.ai_group.setTitle(self.lang_manager.get_text("AI 出题", "AI Question Generation"))
        self.provider_label.setText(self.lang_manager.get_text("提供商:", "Provider:"))
        self.api_key_label.setText(self.lang_manager.get_text("API 密钥:", "API Key:"))
        self.api_base_url_label.setText(self.lang_manager.get_text("API 地址:", "API Base URL:"))
        self.model_label.setText(self.lang_manager.get_text("模型:", "Model:"))
        self.local_agent_label.setText(self.lang_manager.get_text("本地代理:", "Local agent:"))
        self.ai_connection_status_label.setText(self.lang_manager.get_text("连接状态:", "Connection:"))
        if hasattr(self, "ai_connection_status") and not getattr(self, "_connection_test_worker", None):
            self.ai_connection_status.setText(self.lang_manager.get_text(
                "尚未测试连接。",
                "Connection has not been tested yet.",
            ))
        self.environment_group.setTitle(self.lang_manager.get_text("运行环境", "Runtime Environment"))
        self.environment_help.setText(self.lang_manager.get_text(
            "检查 Python 依赖、API Key 持久化、OCR/Tesseract 和 data/ 写入权限。",
            "Check Python packages, API key persistence, OCR/Tesseract, and data/ write access.",
        ))
        if getattr(self.environment_status, "property", None) and self.environment_status.property("envState") == "unknown":
            self.environment_status.setText(self.lang_manager.get_text(
                "尚未检查运行环境。",
                "Runtime environment has not been checked yet.",
            ))
        self.environment_check_btn.setText(self.lang_manager.get_text("检查环境", "Check Environment"))
        self.ocr_fix_btn.setText(self.lang_manager.get_text("复制 OCR 修复命令", "Copy OCR Fix Commands"))
        self.practice_group.setTitle(self.lang_manager.get_text("练习默认值", "Practice Defaults"))
        self.default_question_count_label.setText(
            self.lang_manager.get_text("默认题量:", "Default question count:")
        )
        self.default_difficulty_label.setText(
            self.lang_manager.get_text("默认难度:", "Default difficulty:")
        )
        self._refresh_difficulty_labels()
        self.default_template_label.setText(
            self.lang_manager.get_text("默认模板:", "Default template:")
        )
        self._refresh_template_labels()
        self.question_type_weight_label.setText(
            self.lang_manager.get_text("默认题型相对权重", "Default question type relative weights")
        )
        self.weight_help_label.setText(self.lang_manager.get_text(
            "以下数值是相对权重，无需合计 100。调整后点击确认，下面才会更新最终占比。",
            "The values below are relative weights and do not need to total 100. Confirm after editing to update the effective shares.",
        ))
        self.default_mc_weight_label.setText(self.lang_manager.get_text("选择题:", "Multiple choice:"))
        self.default_scenario_weight_label.setText(
            self.lang_manager.get_text("情境选择题:", "Scenario choice:")
        )
        self.default_true_false_weight_label.setText(
            self.lang_manager.get_text("判断题:", "True / false:")
        )
        self.default_fill_blank_weight_label.setText(
            self.lang_manager.get_text("填空题:", "Fill in the blank:")
        )
        self.advanced_question_type_weight_label.setText(self.lang_manager.get_text(
            "高级题型（默认关闭）", "Advanced types (off by default)"
        ))
        self.default_matching_weight_label.setText(
            self.lang_manager.get_text("配对题:", "Matching:")
        )
        self.default_ordering_weight_label.setText(
            self.lang_manager.get_text("排序题:", "Ordering:")
        )
        self.default_short_answer_weight_label.setText(self.lang_manager.get_text(
            "简答题（需自评）:", "Short answer (self-assessed):"
        ))
        self.question_type_weight_preview_title.setText(
            self.lang_manager.get_text("有效占比:", "Effective share:")
        )
        self.difficulty_weight_label.setText(
            self.lang_manager.get_text("默认难度相对权重", "Default difficulty relative weights")
        )
        self.default_easy_weight_label.setText(self.lang_manager.get_text("简单:", "Easy:"))
        self.default_medium_weight_label.setText(self.lang_manager.get_text("中等:", "Medium:"))
        self.default_hard_weight_label.setText(self.lang_manager.get_text("困难:", "Hard:"))
        self.difficulty_weight_preview_title.setText(
            self.lang_manager.get_text("有效占比:", "Effective share:")
        )
        self.refresh_default_weight_preview_btn.setText(
            self.lang_manager.get_text("确认并更新占比", "Confirm Effective Shares")
        )
        self.show_timer_checkbox.setText(
            self.lang_manager.get_text("练习时显示计时器", "Show timer during practice")
        )
        self.data_group.setTitle(self.lang_manager.get_text("数据管理", "Data Management"))
        self.about_group.setTitle(self.lang_manager.get_text("关于", "About"))
        self._refresh_about_text()
        self._refresh_settings_nav(preserve_selection=True)
        self.export_btn.setText(self.lang_manager.get_text("导出进度", "Export Progress"))
        self.import_btn.setText(self.lang_manager.get_text("导入进度", "Import Progress"))
        self.export_app_data_btn.setText(self.lang_manager.get_text("导出应用数据", "Export App Data"))
        self.import_app_data_btn.setText(self.lang_manager.get_text("导入应用数据", "Import App Data"))
        self.reset_progress_btn.setText(self.lang_manager.get_text("重置全部进度", "Reset All Progress"))
        self.cancel_app_data_btn.setText(self.lang_manager.get_text("停止", "Stop"))
        self.test_ai_btn.setText(self.lang_manager.get_text("测试 AI 设置", "Test AI Settings"))
        self.save_btn.setText(self.lang_manager.get_text("保存设置", "Save Settings"))
        self.clear_api_key_btn.setText(self.lang_manager.get_text("清除", "Clear"))
        self._refresh_settings_save_status()
        self._update_api_key_placeholder()
        self.api_base_url.setPlaceholderText(
            self.lang_manager.get_text("例如: https://api.anthropic.com/v1", "e.g. https://api.anthropic.com/v1"))
        self._refresh_local_agent_status()

    def _refresh_settings_nav(self, preserve_selection: bool = False):
        """Refresh the settings category list while preserving group mappings."""
        previous_group = getattr(self, "_active_settings_group", None) if preserve_selection else None
        sections = [
            (self.lang_manager.get_text("显示语言", "Language"), self.lang_group),
            (self.lang_manager.get_text("AI 出题", "AI Question Generation"), self.ai_group),
            (self.lang_manager.get_text("练习默认值", "Practice Defaults"), self.practice_group),
            (self.lang_manager.get_text("运行环境", "Runtime Environment"), self.environment_group),
            (self.lang_manager.get_text("数据管理", "Data Management"), self.data_group),
            (self.lang_manager.get_text("关于", "About"), self.about_group),
        ]
        self.settings_nav_list.blockSignals(True)
        self.settings_nav_list.clear()
        row_to_select = 0
        for index, (label, group) in enumerate(sections):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.settings_nav_list.addItem(item)
            if group is previous_group:
                row_to_select = index
        self.settings_nav_list.blockSignals(False)
        if self.settings_nav_list.count():
            self.settings_nav_list.setCurrentRow(row_to_select)
            self._active_settings_group = self.settings_nav_list.item(row_to_select).data(
                Qt.ItemDataRole.UserRole
            )

    def _refresh_about_text(self):
        self.about_description_label.setText(self.lang_manager.get_text(
            "从课程资料生成总结、题库并完成练习复盘。",
            "Generate summaries and question banks from course materials, then review practice results.",
        ))
        self.about_license_label.setText(self.lang_manager.get_text(
            "许可证：GPL-3.0-only",
            "License: GPL-3.0-only",
        ))

    def _on_settings_nav_changed(self, row: int):
        """Scroll the settings detail pane to the selected category."""
        item = self.settings_nav_list.item(row)
        if item is None:
            return
        group = item.data(Qt.ItemDataRole.UserRole)
        self._active_settings_group = group
        self.settings_scroll.ensureWidgetVisible(group, 0, 12)

    def _on_language_combo_changed(self, index):
        if self._initializing:
            return
        lang = self.lang_combo.currentData()
        if lang:
            self._settings["language"] = lang
            self.lang_manager.set_language(lang)
            self._set_settings_dirty(True)

    # ── Population ────────────────────────────────────────────

    def _populate_from_settings(self):
        """Populate UI from loaded settings. Signal-safe via _initializing guard."""
        idx = self.lang_combo.findData(self._settings.get("language", "zh"))
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        font_scale_index = self.font_scale_combo.findData(
            self._settings.get("font_scale", DEFAULT_SETTINGS["font_scale"])
        )
        if font_scale_index >= 0:
            self.font_scale_combo.setCurrentIndex(font_scale_index)

        # Prefer URL-based detection over stored label, so edited URLs
        # don't show a mismatched provider (e.g. "anthropic" with siliconflow URL).
        stored_url = self._settings.get("ai_base_url", "")
        stored_provider = self._settings.get("ai_provider", "")
        detected = provider_from_base_url(stored_url) if stored_url else ""
        # If URL is set and doesn't match stored provider, trust the URL
        if stored_url and detected and detected != stored_provider:
            provider = detected
            self._settings["ai_provider"] = detected
        else:
            provider = stored_provider or detected or "anthropic"
        idx = self.provider_combo.findData(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self._populate_provider_models(provider, keep_existing=True)

        from core.secrets_manager import SecretsManager
        secrets = SecretsManager.instance()
        self._has_existing_api_key = bool(secrets.get_key())
        self._key_storage_location = secrets.get_storage_location()
        self.api_key_input.clear()
        self._update_api_key_placeholder()
        self.api_base_url.setText(self._settings.get("ai_base_url", ""))

        model = self._settings.get("ai_model", "claude-sonnet-4-6")
        idx = self.model_combo.findText(model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        elif model:
            self.model_combo.setEditText(model)

        self.default_question_count_input.setValue(
            int(self._settings.get("default_question_count", DEFAULT_SETTINGS["default_question_count"]))
        )
        difficulty = self._settings.get("default_difficulty", DEFAULT_SETTINGS["default_difficulty"])
        difficulty_index = self.default_difficulty_combo.findData(difficulty)
        if difficulty_index >= 0:
            self.default_difficulty_combo.setCurrentIndex(difficulty_index)
        template = self._settings.get(
            "default_generation_template",
            DEFAULT_SETTINGS["default_generation_template"],
        )
        template_index = self.default_template_combo.findData(template)
        if template_index >= 0:
            self.default_template_combo.setCurrentIndex(template_index)
        question_type_weights = self._settings_weights(
            "default_question_type_weights",
            DEFAULT_QUESTION_TYPE_WEIGHTS,
        )
        self.default_mc_weight_input.setValue(question_type_weights["multiple_choice"])
        self.default_scenario_weight_input.setValue(question_type_weights["scenario_choice"])
        self.default_true_false_weight_input.setValue(question_type_weights["true_false"])
        self.default_fill_blank_weight_input.setValue(question_type_weights["fill_in_blank"])
        self.default_matching_weight_input.setValue(question_type_weights["matching"])
        self.default_ordering_weight_input.setValue(question_type_weights["ordering"])
        self.default_short_answer_weight_input.setValue(question_type_weights["short_answer"])
        difficulty_weights = self._settings_weights(
            "default_difficulty_weights",
            DEFAULT_DIFFICULTY_WEIGHTS,
        )
        self.default_easy_weight_input.setValue(difficulty_weights["easy"])
        self.default_medium_weight_input.setValue(difficulty_weights["medium"])
        self.default_hard_weight_input.setValue(difficulty_weights["hard"])
        self.show_timer_checkbox.setChecked(
            bool(self._settings.get("show_timer", DEFAULT_SETTINGS["show_timer"]))
        )
        self._refresh_default_weight_previews()

        self._refresh_local_agent_status()

    # ── Save ─────────────────────────────────────────────────

    def save_settings(self, silent: bool = False):
        """Save current settings to file.
        When silent=True (e.g. auto-save on close), skips the confirmation popup.
        """
        if not hasattr(self, "api_key_input"):
            return
        try:
            self._settings["ai_provider"] = self.provider_combo.currentData() or ""
            self._settings["ai_base_url"] = self.api_base_url.text().strip()
            self._settings["ai_model"] = self.model_combo.currentText().strip()
            self._settings["default_question_count"] = self.default_question_count_input.value()
            self._settings["default_difficulty"] = self.default_difficulty_combo.currentData() or "medium"
            self._settings["default_generation_template"] = (
                self.default_template_combo.currentData() or "quick_review"
            )
            self._settings["default_question_type_weights"] = {
                "multiple_choice": self.default_mc_weight_input.value(),
                "scenario_choice": self.default_scenario_weight_input.value(),
                "true_false": self.default_true_false_weight_input.value(),
                "fill_in_blank": self.default_fill_blank_weight_input.value(),
                "matching": self.default_matching_weight_input.value(),
                "ordering": self.default_ordering_weight_input.value(),
                "short_answer": self.default_short_answer_weight_input.value(),
            }
            self._settings["default_difficulty_weights"] = {
                "easy": self.default_easy_weight_input.value(),
                "medium": self.default_medium_weight_input.value(),
                "hard": self.default_hard_weight_input.value(),
            }
            self._settings["show_timer"] = self.show_timer_checkbox.isChecked()
            self._settings["font_scale"] = self.font_scale_combo.currentData() or "medium"

            # A blank field means "keep the existing key". Only explicit new
            # input changes secret storage; the actual key is never re-rendered.
            from core.secrets_manager import SecretsManager
            secrets = SecretsManager.instance()
            new_key = self.api_key_input.text().strip()
            if new_key:
                self._key_storage_location = secrets.set_key(new_key)
                self._has_existing_api_key = True
                self.api_key_input.clear()
                self._update_api_key_placeholder()

            # Do NOT store ai_api_key in settings dict — SecretsManager owns it.
            self._settings.pop("ai_api_key", None)

            write_json(SETTINGS_FILE, self._settings)
            apply_font_scale(QApplication.instance(), self._settings["font_scale"])
            self._set_settings_dirty(False, saved=True)

            if not silent:
                storage = secrets.get_storage_location()
                storage_warning = _secret_storage_warning(secrets)
                zh_message = (
                    f"设置已保存。\n提供商: {self._settings['ai_provider']}\n"
                    f"模型: {self._settings['ai_model']}\n密钥存储: {storage}"
                )
                en_message = (
                    f"Settings saved.\nProvider: {self._settings['ai_provider']}\n"
                    f"Model: {self._settings['ai_model']}\nKey storage: {storage}"
                )
                if storage_warning:
                    zh_message += f"\n存储提示: {storage_warning}"
                    en_message += f"\nStorage note: {storage_warning}"
                QMessageBox.information(
                    self,
                    self.lang_manager.get_text("已保存", "Saved"),
                    self.lang_manager.get_text(zh_message, en_message),
                )
        except Exception as e:
            if not silent:
                QMessageBox.critical(
                    self, self.lang_manager.get_text("保存失败", "Save Failed"), str(e))

    def _connect_settings_dirty_tracking(self):
        controls = (
            self.provider_combo,
            self.model_combo,
            self.default_difficulty_combo,
            self.default_template_combo,
            self.font_scale_combo,
        )
        for combo in controls:
            combo.currentIndexChanged.connect(self._mark_settings_dirty)
            combo.currentTextChanged.connect(self._mark_settings_dirty)
        self.api_key_input.textChanged.connect(self._mark_settings_dirty)
        self.api_base_url.textChanged.connect(self._mark_settings_dirty)
        for spinbox in (
            self.default_question_count_input,
            self.default_mc_weight_input,
            self.default_scenario_weight_input,
            self.default_true_false_weight_input,
            self.default_fill_blank_weight_input,
            self.default_matching_weight_input,
            self.default_ordering_weight_input,
            self.default_short_answer_weight_input,
            self.default_easy_weight_input,
            self.default_medium_weight_input,
            self.default_hard_weight_input,
        ):
            spinbox.valueChanged.connect(self._mark_settings_dirty)
        self.show_timer_checkbox.toggled.connect(self._mark_settings_dirty)

    def _mark_settings_dirty(self, *_args):
        self._set_settings_dirty(True)

    def _set_settings_dirty(self, dirty: bool, saved: bool = False):
        if getattr(self, "_initializing", False):
            return
        self.settings_dirty = dirty
        self._settings_saved_state = saved and not dirty
        self._refresh_settings_save_status()

    def _refresh_settings_save_status(self):
        if not hasattr(self, "settings_save_status"):
            return
        if self.settings_dirty:
            text = self.lang_manager.get_text("有未保存更改", "Unsaved changes")
            state = "dirty"
        elif getattr(self, "_settings_saved_state", False):
            text = self.lang_manager.get_text("已保存", "Saved")
            state = "saved"
        else:
            text = self.lang_manager.get_text("无未保存更改", "No unsaved changes")
            state = "clean"
        self.settings_save_status.setText(text)
        self.settings_save_status.setProperty("saveState", state)
        self.settings_save_status.style().unpolish(self.settings_save_status)
        self.settings_save_status.style().polish(self.settings_save_status)

    def _make_weight_spinbox(self, value: int) -> QSpinBox:
        spinbox = WheelSafeSpinBox()
        spinbox.setRange(0, 100)
        spinbox.setSingleStep(5)
        spinbox.setValue(value)
        return spinbox

    def _settings_weights(self, settings_key: str, defaults: dict[str, int]) -> dict[str, int]:
        configured = self._settings.get(settings_key, {})
        weights = dict(defaults)
        if isinstance(configured, dict):
            for key in defaults:
                try:
                    weights[key] = max(0, min(100, int(configured.get(key, defaults[key]))))
                except (TypeError, ValueError):
                    weights[key] = defaults[key]
        return weights

    def _refresh_default_weight_previews(self):
        """Refresh normalized effective shares for default generation weights."""
        type_weights = _normalize_weight_shares({
            "multiple_choice": self.default_mc_weight_input.value(),
            "scenario_choice": self.default_scenario_weight_input.value(),
            "true_false": self.default_true_false_weight_input.value(),
            "fill_in_blank": self.default_fill_blank_weight_input.value(),
            "matching": self.default_matching_weight_input.value(),
            "ordering": self.default_ordering_weight_input.value(),
            "short_answer": self.default_short_answer_weight_input.value(),
        })
        difficulty_weights = _normalize_weight_shares({
            "easy": self.default_easy_weight_input.value(),
            "medium": self.default_medium_weight_input.value(),
            "hard": self.default_hard_weight_input.value(),
        })
        self.question_type_weight_preview.setText(
            self.lang_manager.get_text(
                "；".join([
                    f"选择题 {type_weights['multiple_choice']}%",
                    f"情境选择题 {type_weights['scenario_choice']}%",
                    f"判断题 {type_weights['true_false']}%",
                    f"填空题 {type_weights['fill_in_blank']}%",
                    f"配对题 {type_weights['matching']}%",
                    f"排序题 {type_weights['ordering']}%",
                    f"简答题 {type_weights['short_answer']}%",
                ]),
                "; ".join([
                    f"Multiple choice {type_weights['multiple_choice']}%",
                    f"Scenario choice {type_weights['scenario_choice']}%",
                    f"True / false {type_weights['true_false']}%",
                    f"Fill in the blank {type_weights['fill_in_blank']}%",
                    f"Matching {type_weights['matching']}%",
                    f"Ordering {type_weights['ordering']}%",
                    f"Short answer {type_weights['short_answer']}%",
                ]),
            )
        )
        self.difficulty_weight_preview.setText(
            self.lang_manager.get_text(
                "；".join([
                    f"简单 {difficulty_weights['easy']}%",
                    f"中等 {difficulty_weights['medium']}%",
                    f"困难 {difficulty_weights['hard']}%",
                ]),
                "; ".join([
                    f"Easy {difficulty_weights['easy']}%",
                    f"Medium {difficulty_weights['medium']}%",
                    f"Hard {difficulty_weights['hard']}%",
                ]),
            )
        )

    def _update_api_key_placeholder(self):
        if not hasattr(self, "api_key_input"):
            return
        has_key = bool(getattr(self, "_has_existing_api_key", False))
        storage = str(getattr(self, "_key_storage_location", "") or "")
        if has_key:
            placeholder = self.lang_manager.get_text(
                f"已配置（{storage}）；留空保持不变",
                f"Configured ({storage}); leave blank to keep it",
            )
        else:
            placeholder = self.lang_manager.get_text(
                "输入新密钥（不会回显）",
                "Enter a new key (it will not be displayed again)",
            )
        self.api_key_input.setPlaceholderText(placeholder)
        self.clear_api_key_btn.setEnabled(has_key)

    def _clear_api_key(self):
        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("清除 API 密钥", "Clear API Key"),
            self.lang_manager.get_text(
                "确定清除当前 API 密钥吗？之后远程 LLM 将不可用，直到输入新密钥。",
                "Clear the current API key? Remote LLMs will be unavailable until a new key is entered.",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from core.secrets_manager import SecretsManager

        secrets = SecretsManager.instance()
        self._key_storage_location = secrets.set_key("")
        storage_warning = _secret_storage_warning(secrets)
        self._has_existing_api_key = False
        self.api_key_input.clear()
        self._update_api_key_placeholder()
        zh_message = "API 密钥已清除。"
        en_message = "The API key was cleared."
        if storage_warning:
            zh_message += f"\n存储提示: {storage_warning}"
            en_message += f"\nStorage note: {storage_warning}"
        QMessageBox.information(
            self,
            self.lang_manager.get_text("已清除", "Cleared"),
            self.lang_manager.get_text(zh_message, en_message),
        )

    # ── Provider change ──────────────────────────────────────

    def _on_base_url_edited(self, text):
        """Auto-detect provider when user edits the base URL."""
        if self._initializing:
            return
        detected = provider_from_base_url(text.strip())
        if detected:
            idx = self.provider_combo.findData(detected)
            if idx >= 0:
                self.provider_combo.blockSignals(True)
                self.provider_combo.setCurrentIndex(idx)
                self.provider_combo.blockSignals(False)
                defaults = default_provider_settings(detected)
                self._populate_provider_models(detected, keep_existing=True)
                self.provider_help.setText(defaults["help"])

    def _on_provider_changed(self, index):
        if self._initializing:
            return
        provider = self.provider_combo.currentData()
        if not provider:
            return
        self._settings["ai_provider"] = provider
        defaults = default_provider_settings(provider)
        self._populate_provider_models(provider, keep_existing=False)
        if provider != "custom":
            self.api_base_url.setText(defaults["base_url"])
            if defaults["model"]:
                self.model_combo.setCurrentText(defaults["model"])
        self.provider_help.setText(defaults["help"])
        self._refresh_local_agent_status()

    def _refresh_difficulty_labels(self):
        if not hasattr(self, "default_difficulty_combo"):
            return
        current = self.default_difficulty_combo.currentData()
        labels = (
            ("easy", self.lang_manager.get_text("简单", "Easy")),
            ("medium", self.lang_manager.get_text("中等", "Medium")),
            ("hard", self.lang_manager.get_text("困难", "Hard")),
        )
        self.default_difficulty_combo.blockSignals(True)
        self.default_difficulty_combo.clear()
        for value, label in labels:
            self.default_difficulty_combo.addItem(label, value)
        index = self.default_difficulty_combo.findData(current or "medium")
        if index >= 0:
            self.default_difficulty_combo.setCurrentIndex(index)
        self.default_difficulty_combo.blockSignals(False)

    def _refresh_template_labels(self):
        if not hasattr(self, "default_template_combo"):
            return
        current = self.default_template_combo.currentData()
        labels = (
            ("quick_review", self.lang_manager.get_text("快速复习", "Quick Review")),
            ("final_exam", self.lang_manager.get_text("期末模拟", "Final Exam Style")),
            ("calculation_practice", self.lang_manager.get_text("计算训练", "Calculation Practice")),
        )
        self.default_template_combo.blockSignals(True)
        self.default_template_combo.clear()
        for value, label in labels:
            self.default_template_combo.addItem(label, value)
        index = self.default_template_combo.findData(current or "quick_review")
        if index >= 0:
            self.default_template_combo.setCurrentIndex(index)
        self.default_template_combo.blockSignals(False)

    def _populate_provider_models(self, provider: str, keep_existing: bool):
        current = self.model_combo.currentText() if keep_existing else ""
        defaults = default_provider_settings(provider)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(defaults["models"])
        if current:
            self.model_combo.setEditText(current)
        elif defaults["model"]:
            self.model_combo.setCurrentText(defaults["model"])
        self.model_combo.blockSignals(False)
        self.provider_help.setText(defaults["help"])
        self._refresh_local_agent_status()

    def _refresh_local_agent_status(self):
        if not hasattr(self, "local_agent_status"):
            return
        found = detect_local_agents()
        if found:
            agents_str = ", ".join(found)
            self.local_agent_status.setText(self.lang_manager.get_text(
                f"检测到: {agents_str}。选择 Local CLI Agent 无需 API Key。",
                f"Detected: {agents_str}. Select Local CLI Agent for keyless mode."))
        else:
            self.local_agent_status.setText(self.lang_manager.get_text(
                "未检测到本地 CLI。需要 API Key 或安装 claude/codex CLI。",
                "No local CLI detected. API key required, or install claude/codex CLI."))

    def _test_ai_settings(self):
        from core.secrets_manager import SecretsManager

        if self._connection_test_worker is not None:
            return
        settings = {
            "ai_provider": self.provider_combo.currentData() or "",
            "ai_base_url": self.api_base_url.text().strip(),
            "ai_model": self.model_combo.currentText().strip(),
        }
        if provider_requires_api_key(settings):
            api_key = self.api_key_input.text() or SecretsManager.instance().get_key()
        else:
            api_key = ""
        result = validate_ai_settings(settings, api_key=api_key, detected_agents=detect_local_agents())
        if not result.ok:
            self.ai_connection_status.setObjectName("settingsConnectionStatusError")
            self.ai_connection_status.setText(result.message)
            self.ai_connection_status.style().unpolish(self.ai_connection_status)
            self.ai_connection_status.style().polish(self.ai_connection_status)
            QMessageBox.warning(
                self,
                self.lang_manager.get_text("AI 设置需要处理", "AI Settings Need Attention"),
                result.message,
            )
            return

        self._set_connection_test_busy(True)
        worker = self._create_connection_test_worker(settings, api_key)
        self._connection_test_worker = worker
        worker.result_ready.connect(self._handle_connection_test_result)
        finished_signal = getattr(worker, "finished", None)
        if finished_signal is not None:
            finished_signal.connect(worker.deleteLater)
        worker.start()

    def _create_connection_test_worker(self, settings: dict, api_key: str):
        return AIConnectionTestWorker(
            self._connection_probe_factory(),
            settings,
            api_key,
            self,
        )

    def _set_connection_test_busy(self, busy: bool):
        self.test_ai_btn.setEnabled(not busy)
        self.save_btn.setEnabled(not busy)
        self.provider_combo.setEnabled(not busy)
        self.api_key_input.setEnabled(not busy)
        self.clear_api_key_btn.setEnabled((not busy) and bool(getattr(self, "_has_existing_api_key", False)))
        self.api_base_url.setEnabled(not busy)
        self.model_combo.setEnabled(not busy)
        if busy:
            self.ai_connection_status.setObjectName("settingsConnectionStatus")
            self.ai_connection_status.setText(self.lang_manager.get_text(
                "正在测试连接，请稍候……",
                "Testing connection, please wait...",
            ))
            self.ai_connection_status.style().unpolish(self.ai_connection_status)
            self.ai_connection_status.style().polish(self.ai_connection_status)

    def _handle_connection_test_result(self, result):
        self._connection_test_worker = None
        self._set_connection_test_busy(False)
        detail = f"{result.message}\n{result.elapsed_ms} ms"
        if result.ok:
            self.ai_connection_status.setObjectName("settingsConnectionStatusOk")
            self.ai_connection_status.setText(detail)
            self.ai_connection_status.style().unpolish(self.ai_connection_status)
            self.ai_connection_status.style().polish(self.ai_connection_status)
            QMessageBox.information(
                self,
                self.lang_manager.get_text("AI 连接可用", "AI Connection Ready"),
                detail,
            )
            return

        self.ai_connection_status.setObjectName("settingsConnectionStatusError")
        self.ai_connection_status.setText(detail)
        self.ai_connection_status.style().unpolish(self.ai_connection_status)
        self.ai_connection_status.style().polish(self.ai_connection_status)
        QMessageBox.warning(
            self,
            self.lang_manager.get_text("AI 连接失败", "AI Connection Failed"),
            detail,
        )

    def _show_environment_check(self):
        report = collect_environment_report(BASE_DIR)
        self._set_environment_status_from_report(report)
        message_box = QMessageBox.information if report.ok else QMessageBox.warning
        message_box(
            self,
            self.lang_manager.get_text("环境检查", "Environment Check"),
            format_environment_report(report),
        )

    def _set_environment_status_from_report(self, report):
        """Show a compact environment status in the settings page itself."""
        required_failures = [check for check in report.checks if check.required and not check.ok]
        optional_warnings = [check for check in report.checks if not check.required and not check.ok]
        if required_failures:
            state = "fail"
            title = "Environment check: FAIL"
            focus = required_failures[:2]
        elif optional_warnings:
            state = "warn"
            title = "Environment check: WARN"
            focus = optional_warnings[:2]
        else:
            state = "pass"
            title = "Environment check: PASS"
            focus = [
                check for check in report.checks
                if check.name in {"Tesseract OCR", "secure API key persistence", "keyring backend"}
            ][:3]
        details = "\n".join(f"{check.name}: {check.detail}" for check in focus)
        text = title if not details else f"{title}\n{details}"
        self.environment_status.setText(text)
        self.environment_status.setProperty("envState", state)
        self.environment_status.style().unpolish(self.environment_status)
        self.environment_status.style().polish(self.environment_status)

    def _copy_ocr_fix_commands(self):
        QApplication.clipboard().setText(OCR_REMEDIATION)
        QMessageBox.information(
            self,
            self.lang_manager.get_text("已复制", "Copied"),
            self.lang_manager.get_text(
                f"OCR/Tesseract 补齐命令已复制到剪贴板：\n\n{OCR_REMEDIATION}",
                f"OCR/Tesseract remediation commands copied to clipboard:\n\n{OCR_REMEDIATION}",
            ),
        )

    # ── Public ────────────────────────────────────────────────

    def get_setting(self, key: str, default=None):
        return self._settings.get(key, default)

    # ── Data management ──────────────────────────────────────

    def _export_progress(self):
        from config import PROGRESS_DIR
        from utils.json_io import load_all_json
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            self.lang_manager.get_text("导出进度", "Export Progress"),
            "progress_export.json", "JSON Files (*.json)")
        if filepath:
            data = load_all_json(PROGRESS_DIR)
            if write_json(filepath, data):
                QMessageBox.information(
                    self,
                    self.lang_manager.get_text("已导出", "Exported"),
                    self.lang_manager.get_text(f"进度已导出到:\n{filepath}", f"Progress exported to:\n{filepath}"))

    def _import_progress(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            self.lang_manager.get_text("导入进度", "Import Progress"),
            "", "JSON Files (*.json)")
        if filepath:
            data = read_json(filepath)
            if data and isinstance(data, list):
                from config import PROGRESS_DIR
                count = 0
                for record in data:
                    if isinstance(record, dict) and "progress_id" in record:
                        try:
                            pid = sanitize_filename_part(record["progress_id"])
                        except ValueError:
                            continue
                        path = os.path.join(PROGRESS_DIR, f"{pid}.json")
                        if write_json(path, record):
                            count += 1
                QMessageBox.information(
                    self,
                    self.lang_manager.get_text("已导入", "Imported"),
                    self.lang_manager.get_text(f"已导入 {count} 条记录。", f"Imported {count} records."))
            else:
                QMessageBox.warning(
                    self,
                    self.lang_manager.get_text("无效文件", "Invalid File"),
                    self.lang_manager.get_text("文件格式无效。", "Invalid file format."))

    def _export_app_data(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            self.lang_manager.get_text("导出应用数据", "Export App Data"),
            "quiz_app_data.quizdata",
            "Quiz App Data (*.quizdata);;Zip Files (*.zip);;All Files (*)",
        )
        if not filepath:
            return

        self._start_app_data_worker(self._create_app_data_worker("export", filepath), "export")

    def _create_app_data_worker(self, operation: str, filepath: str):
        task_id = ""
        if self.task_center is not None:
            title = self.lang_manager.get_text(
                "导出应用数据" if operation == "export" else "导入应用数据",
                "Export App Data" if operation == "export" else "Import App Data",
            )
            snapshot = self.task_center.create(
                kind=f"app_data_{operation}",
                title=title,
                metadata={"operation": operation, "path": filepath},
            )
            task_id = snapshot.task_id
        self._app_data_task_id = task_id
        return AppDataBundleWorker(
            operation,
            filepath,
            DATA_DIR,
            self,
            task_center=self.task_center,
            task_id=task_id,
        )

    def _start_app_data_worker(self, worker, operation: str):
        self._app_data_worker = worker
        self._app_data_operation = operation
        self._app_data_task_id = self._app_data_task_id or str(
            getattr(worker, "task_id", "") or ""
        )
        self._set_app_data_busy(True, operation)
        worker.exported.connect(self._on_app_data_exported)
        worker.imported.connect(self._on_app_data_imported)
        worker.failed.connect(lambda message: self._on_app_data_failed(message, operation))
        if hasattr(worker, "progressed"):
            worker.progressed.connect(self._on_app_data_progress)
        if hasattr(worker, "cancelled"):
            worker.cancelled.connect(self._on_app_data_cancelled)
        worker.start()

    def _set_app_data_busy(self, busy: bool, operation: str = ""):
        for button in (
            self.export_btn,
            self.import_btn,
            self.export_app_data_btn,
            self.import_app_data_btn,
            self.reset_progress_btn,
        ):
            button.setEnabled(not busy)
        self.app_data_status_label.setVisible(busy)
        self.cancel_app_data_btn.setVisible(busy)
        self.cancel_app_data_btn.setEnabled(busy)
        if busy and operation == "export":
            self.export_app_data_btn.setText(self.lang_manager.get_text("导出中…", "Exporting…"))
            self.app_data_status_label.setText(
                self.lang_manager.get_text("正在准备导出…", "Preparing export…")
            )
        elif busy and operation == "import":
            self.import_app_data_btn.setText(self.lang_manager.get_text("导入中…", "Importing…"))
            self.app_data_status_label.setText(
                self.lang_manager.get_text("正在验证导入包…", "Validating import bundle…")
            )
        else:
            self.export_app_data_btn.setText(self.lang_manager.get_text("导出应用数据", "Export App Data"))
            self.import_app_data_btn.setText(self.lang_manager.get_text("导入应用数据", "Import App Data"))
            self.app_data_status_label.clear()

    def _on_app_data_progress(self, progress: TaskProgress):
        stage_labels = {
            "scanning": self.lang_manager.get_text("扫描数据", "Scanning data"),
            "exporting": self.lang_manager.get_text("写入导出包", "Writing bundle"),
            "validating": self.lang_manager.get_text("验证导入包", "Validating bundle"),
            "staging": self.lang_manager.get_text("暂存数据", "Staging data"),
            "committing": self.lang_manager.get_text("提交数据", "Committing data"),
            "saved": self.lang_manager.get_text("正在完成", "Finishing"),
        }
        label = stage_labels.get(progress.stage, progress.stage)
        count = (
            f" {progress.current}/{progress.total}"
            if progress.total > 0
            else ""
        )
        detail = f" · {progress.detail}" if progress.detail else ""
        self.app_data_status_label.setText(f"{label}{count}{detail}")

    def _cancel_app_data(self):
        worker = self._app_data_worker
        if worker is None:
            return
        self.cancel_app_data_btn.setEnabled(False)
        self.app_data_status_label.setText(
            self.lang_manager.get_text("正在安全停止…", "Stopping safely…")
        )
        if self.task_center is not None and self._app_data_task_id:
            try:
                self.task_center.request_cancel(self._app_data_task_id)
            except (KeyError, ValueError):
                pass
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()

    def _finish_app_data_worker(self):
        self._set_app_data_busy(False)
        self._app_data_worker = None
        self._app_data_task_id = ""
        self._app_data_operation = ""

    def _on_app_data_exported(self, written):
        self._finish_app_data_worker()
        QMessageBox.information(
            self,
            self.lang_manager.get_text("已导出", "Exported"),
            self.lang_manager.get_text(
                f"应用数据已导出到:\n{written}\n\nAPI Key 不会包含在导出包中。",
                f"App data exported to:\n{written}\n\nAPI keys are not included in the bundle.",
            ),
        )

    def _on_app_data_failed(self, message: str, operation: str):
        self._finish_app_data_worker()
        QMessageBox.critical(
            self,
            self.lang_manager.get_text(
                "导出失败" if operation == "export" else "导入失败",
                "Export Failed" if operation == "export" else "Import Failed",
            ),
            message,
        )

    def _on_app_data_cancelled(self):
        self._finish_app_data_worker()
        QMessageBox.information(
            self,
            self.lang_manager.get_text("已停止", "Stopped"),
            self.lang_manager.get_text(
                "数据操作已安全停止，未提交的更改已撤销。",
                "The data operation stopped safely; uncommitted changes were rolled back.",
            ),
        )

    def _import_app_data(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            self.lang_manager.get_text("导入应用数据", "Import App Data"),
            "",
            "Quiz App Data (*.quizdata);;Zip Files (*.zip);;All Files (*)",
        )
        if not filepath:
            return

        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("导入应用数据?", "Import App Data?"),
            self.lang_manager.get_text(
                "将导入课程、历史真题、题库、题目集、草稿、进度和非敏感设置；同名文件会被覆盖。API Key 不会从导入包读取。继续吗？",
                "This imports courses, historical exams, questions, question sets, drafts, progress, and non-sensitive settings; files with the same name will be overwritten. API keys are never read from the bundle. Continue?",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._start_app_data_worker(self._create_app_data_worker("import", filepath), "import")

    def _on_app_data_imported(self, result):
        self._finish_app_data_worker()
        skipped_hint = ""
        if result.skipped_files:
            skipped_hint = self.lang_manager.get_text(
                f"\n已跳过 {len(result.skipped_files)} 个不安全或不支持的文件。",
                f"\nSkipped {len(result.skipped_files)} unsafe or unsupported files.",
            )
        QMessageBox.information(
            self,
            self.lang_manager.get_text("已导入", "Imported"),
            self.lang_manager.get_text(
                f"已导入 {result.imported_files} 个数据文件。{skipped_hint}\n建议重启应用以刷新全部数据。",
                f"Imported {result.imported_files} data files.{skipped_hint}\nRestart the app to refresh all data.",
            ),
        )

    def _reset_progress(self):
        reply = QMessageBox.question(
            self,
            self.lang_manager.get_text("重置进度?", "Reset Progress?"),
            self.lang_manager.get_text(
                "确定要删除所有进度记录吗？此操作无法撤销。",
                "Delete ALL progress records? This cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            from config import PROGRESS_DIR
            import os
            if not os.path.isdir(PROGRESS_DIR):
                QMessageBox.information(
                    self,
                    self.lang_manager.get_text("完成", "Done"),
                    self.lang_manager.get_text("没有进度记录可删除。", "No progress records to delete."))
                return
            for filename in os.listdir(PROGRESS_DIR):
                if filename.endswith(".json"):
                    os.remove(os.path.join(PROGRESS_DIR, filename))
            QMessageBox.information(
                self,
                self.lang_manager.get_text("完成", "Done"),
                self.lang_manager.get_text("所有进度记录已删除。", "All progress records deleted."))
