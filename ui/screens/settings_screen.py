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
    QFileDialog, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt

from core.language_manager import LanguageManager
from config import SETTINGS_FILE, DEFAULT_SETTINGS
from utils.json_io import read_json, write_json
from ai.provider_presets import (
    PROVIDER_PRESETS,
    default_provider_settings,
    provider_from_base_url,
    detect_local_agents,
)


class SettingsScreen(QWidget):
    """Application settings with explicit save, crash-safe initialization."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_manager = LanguageManager.instance()
        self.lang_manager.language_changed.connect(self._on_language_changed)
        self._settings = self._load_settings()
        self._initializing = True
        self._setup_ui()
        self._populate_from_settings()
        self._initializing = False

    # ── Init helpers ──────────────────────────────────────────

    def _load_settings(self) -> dict:
        data = read_json(SETTINGS_FILE)
        if data:
            return {**DEFAULT_SETTINGS, **data}
        return dict(DEFAULT_SETTINGS)

    def _setup_ui(self):
        # Outer layout: just the scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.title = QLabel(self.lang_manager.get_text("设置", "Settings"))
        self.title.setStyleSheet("font-size: 20px; font-weight: bold; padding-bottom: 12px;")
        layout.addWidget(self.title)

        # ── Language ──
        self.lang_group = QGroupBox(self.lang_manager.get_text("显示语言", "Language"))
        lang_layout = QFormLayout(self.lang_group)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.currentIndexChanged.connect(self._on_language_combo_changed)
        self.lang_label = QLabel(self.lang_manager.get_text("显示语言:", "Display language:"))
        lang_layout.addRow(self.lang_label, self.lang_combo)
        layout.addWidget(self.lang_group)

        # ── AI Generation ──
        self.ai_group = QGroupBox(self.lang_manager.get_text("AI 出题", "AI Question Generation"))
        ai_layout = QFormLayout(self.ai_group)

        # Provider
        self.provider_combo = QComboBox()
        for key, preset in PROVIDER_PRESETS.items():
            self.provider_combo.addItem(preset["label"], key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_label = QLabel(self.lang_manager.get_text("提供商:", "Provider:"))
        ai_layout.addRow(self.provider_label, self.provider_combo)

        # API key
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText(
            self.lang_manager.get_text("输入 API 密钥...", "Enter API key..."))
        self.api_key_label = QLabel(self.lang_manager.get_text("API 密钥:", "API Key:"))
        ai_layout.addRow(self.api_key_label, self.api_key_input)

        # Base URL
        self.api_base_url = QLineEdit()
        self.api_base_url.setPlaceholderText(
            self.lang_manager.get_text(
                "例如: https://api.anthropic.com/v1",
                "e.g. https://api.anthropic.com/v1"))
        self.api_base_url.textChanged.connect(self._on_base_url_edited)
        self.api_base_url_label = QLabel(self.lang_manager.get_text("API 地址:", "API Base URL:"))
        ai_layout.addRow(self.api_base_url_label, self.api_base_url)

        # Model
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_label = QLabel(self.lang_manager.get_text("模型:", "Model:"))
        ai_layout.addRow(self.model_label, self.model_combo)

        # Help / local agent status
        self.provider_help = QLabel()
        self.provider_help.setWordWrap(True)
        self.provider_help.setStyleSheet("font-size: 12px; color: #a6adc8;")
        ai_layout.addRow("", self.provider_help)

        self.local_agent_status = QLabel()
        self.local_agent_status.setWordWrap(True)
        self.local_agent_status.setStyleSheet("font-size: 12px; color: #a6adc8;")
        self.local_agent_label = QLabel(self.lang_manager.get_text("本地代理:", "Local agent:"))
        ai_layout.addRow(self.local_agent_label, self.local_agent_status)

        # Save button
        save_row = QHBoxLayout()
        save_row.addStretch()
        self.save_btn = QPushButton(self.lang_manager.get_text("💾 保存设置", "💾 Save Settings"))
        self.save_btn.setMinimumHeight(40)
        self.save_btn.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.save_btn.clicked.connect(self.save_settings)
        save_row.addWidget(self.save_btn)
        ai_layout.addRow("", save_row)

        layout.addWidget(self.ai_group)

        # ── Data Management ──
        self.data_group = QGroupBox(self.lang_manager.get_text("数据管理", "Data Management"))
        data_layout = QVBoxLayout(self.data_group)

        self.export_btn = QPushButton(self.lang_manager.get_text("📤 导出进度", "📤 Export Progress"))
        self.export_btn.clicked.connect(self._export_progress)
        data_layout.addWidget(self.export_btn)

        self.import_btn = QPushButton(self.lang_manager.get_text("📥 导入进度", "📥 Import Progress"))
        self.import_btn.clicked.connect(self._import_progress)
        data_layout.addWidget(self.import_btn)

        reset_row = QHBoxLayout()
        self.reset_progress_btn = QPushButton(
            self.lang_manager.get_text("🗑 重置全部进度", "🗑 Reset All Progress"))
        self.reset_progress_btn.clicked.connect(self._reset_progress)
        reset_row.addWidget(self.reset_progress_btn)
        reset_row.addStretch()
        data_layout.addLayout(reset_row)

        layout.addWidget(self.data_group)
        layout.addStretch()

        version_label = QLabel("Course Quiz Studio v1.0.0")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #6c7086; font-size: 11px; padding-top: 12px;")
        layout.addWidget(version_label)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ── Language ──────────────────────────────────────────────

    def _on_language_changed(self, lang):
        self.title.setText(self.lang_manager.get_text("设置", "Settings"))
        self.lang_group.setTitle(self.lang_manager.get_text("显示语言", "Language"))
        self.lang_label.setText(self.lang_manager.get_text("显示语言:", "Display language:"))
        self.ai_group.setTitle(self.lang_manager.get_text("AI 出题", "AI Question Generation"))
        self.provider_label.setText(self.lang_manager.get_text("提供商:", "Provider:"))
        self.api_key_label.setText(self.lang_manager.get_text("API 密钥:", "API Key:"))
        self.api_base_url_label.setText(self.lang_manager.get_text("API 地址:", "API Base URL:"))
        self.model_label.setText(self.lang_manager.get_text("模型:", "Model:"))
        self.local_agent_label.setText(self.lang_manager.get_text("本地代理:", "Local agent:"))
        self.data_group.setTitle(self.lang_manager.get_text("数据管理", "Data Management"))
        self.export_btn.setText(self.lang_manager.get_text("📤 导出进度", "📤 Export Progress"))
        self.import_btn.setText(self.lang_manager.get_text("📥 导入进度", "📥 Import Progress"))
        self.reset_progress_btn.setText(self.lang_manager.get_text("🗑 重置全部进度", "🗑 Reset All Progress"))
        self.save_btn.setText(self.lang_manager.get_text("💾 保存设置", "💾 Save Settings"))
        self.api_key_input.setPlaceholderText(
            self.lang_manager.get_text("输入 API 密钥...", "Enter API key..."))
        self.api_base_url.setPlaceholderText(
            self.lang_manager.get_text("例如: https://api.anthropic.com/v1", "e.g. https://api.anthropic.com/v1"))
        self._refresh_local_agent_status()

    def _on_language_combo_changed(self, index):
        if self._initializing:
            return
        lang = self.lang_combo.currentData()
        if lang:
            self._settings["language"] = lang
            self.lang_manager.set_language(lang)

    # ── Population ────────────────────────────────────────────

    def _populate_from_settings(self):
        """Populate UI from loaded settings. Signal-safe via _initializing guard."""
        idx = self.lang_combo.findData(self._settings.get("language", "zh"))
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

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
        self.api_key_input.setText(SecretsManager.instance().get_key())
        self.api_base_url.setText(self._settings.get("ai_base_url", ""))

        model = self._settings.get("ai_model", "claude-sonnet-4-6")
        idx = self.model_combo.findText(model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        elif model:
            self.model_combo.setEditText(model)

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

            # Delegate API key storage to SecretsManager (env → keychain → file)
            from core.secrets_manager import SecretsManager
            SecretsManager.instance().set_key(self.api_key_input.text())

            # Do NOT store ai_api_key in settings dict — SecretsManager owns it.
            self._settings.pop("ai_api_key", None)

            write_json(SETTINGS_FILE, self._settings)

            if not silent:
                storage = SecretsManager.instance().get_storage_location()
                QMessageBox.information(
                    self,
                    self.lang_manager.get_text("已保存", "Saved"),
                    self.lang_manager.get_text(
                        f"设置已保存。\n提供商: {self._settings['ai_provider']}\n"
                        f"模型: {self._settings['ai_model']}\n密钥存储: {storage}",
                        f"Settings saved.\nProvider: {self._settings['ai_provider']}\n"
                        f"Model: {self._settings['ai_model']}\nKey storage: {storage}"),
                )
        except Exception as e:
            if not silent:
                QMessageBox.critical(
                    self, self.lang_manager.get_text("保存失败", "Save Failed"), str(e))

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
                        pid = record["progress_id"]
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
