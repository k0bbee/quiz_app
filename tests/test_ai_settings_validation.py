import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox

from ai.connection_probe import ConnectionProbeResult
from ai.settings_validation import validate_ai_settings
from core.environment_check import CheckResult, EnvironmentReport
from core.language_manager import LanguageManager
from core.ocr_runtime import OCR_REMEDIATION
from ui.screens.settings_screen import SettingsScreen


_APP = QApplication.instance() or QApplication([])


class ManualSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


class ManualConnectionWorker:
    def __init__(self):
        self.result_ready = ManualSignal()
        self.start_called = False

    def start(self):
        self.start_called = True


class AISettingsValidationTests(unittest.TestCase):
    def test_local_agent_settings_are_valid_when_agent_is_detected(self):
        result = validate_ai_settings(
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            api_key="",
            detected_agents=["codex"],
        )

        self.assertTrue(result.ok)
        self.assertIn("codex", result.message)

    def test_remote_provider_requires_key_base_url_and_model(self):
        result = validate_ai_settings(
            {"ai_provider": "openai", "ai_base_url": "https://api.openai.com/v1", "ai_model": "gpt-4.1-mini"},
            api_key="",
            detected_agents=[],
        )

        self.assertFalse(result.ok)
        self.assertIn("API key", result.message)

    def test_remote_endpoints_require_https_except_for_loopback(self):
        secure = validate_ai_settings(
            {"ai_provider": "custom", "ai_base_url": "https://llm.example.com/v1", "ai_model": "model"},
            api_key="sk-test",
        )
        loopback = validate_ai_settings(
            {"ai_provider": "custom", "ai_base_url": "http://127.0.0.1:11434/v1", "ai_model": "model"},
            api_key="sk-test",
        )
        insecure = validate_ai_settings(
            {"ai_provider": "custom", "ai_base_url": "http://llm.example.com/v1", "ai_model": "model"},
            api_key="sk-test",
        )

        self.assertTrue(secure.ok)
        self.assertTrue(loopback.ok)
        self.assertFalse(insecure.ok)
        self.assertIn("HTTPS", insecure.message)

    def test_remote_endpoint_rejects_embedded_credentials_and_invalid_scheme(self):
        for base_url in (
            "https://user:password@llm.example.com/v1",
            "ftp://llm.example.com/v1",
            "https://",
        ):
            with self.subTest(base_url=base_url):
                result = validate_ai_settings(
                    {"ai_provider": "custom", "ai_base_url": base_url, "ai_model": "model"},
                    api_key="sk-test",
                )
                self.assertFalse(result.ok)

    def test_settings_screen_test_button_validates_then_starts_local_agent_probe(self):
        screen = SettingsScreen()
        screen.provider_combo.setCurrentIndex(screen.provider_combo.findData("local_agent"))
        screen.api_base_url.setText("local-agent://auto")
        screen.model_combo.setCurrentText("codex")
        screen.api_key_input.clear()
        worker = ManualConnectionWorker()

        with patch.object(screen, "_create_connection_test_worker", return_value=worker) as create_worker, \
             patch("ui.screens.settings_screen.detect_local_agents", return_value=["codex"]), \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen.test_ai_btn.click()
            self.assertTrue(worker.start_called)
            self.assertFalse(info.called)

            worker.result_ready.emit(ConnectionProbeResult(
                ok=True,
                message="Connected to provider 'local_agent' with model 'codex'.",
                elapsed_ms=15,
                provider="local_agent",
                model="codex",
            ))

        settings_arg, api_key_arg = create_worker.call_args.args
        self.assertEqual("local_agent", settings_arg["ai_provider"])
        self.assertEqual("", api_key_arg)
        self.assertTrue(info.called)
        self.assertIn("codex", info.call_args.args[2])

    def test_settings_screen_runs_connection_probe_in_background(self):
        screen = SettingsScreen()
        screen.provider_combo.setCurrentIndex(screen.provider_combo.findData("custom"))
        screen.api_base_url.setText("https://api.example.com/v1")
        screen.model_combo.setCurrentText("test-model")
        screen.api_key_input.setText("sk-test")
        worker = ManualConnectionWorker()

        with patch.object(screen, "_create_connection_test_worker", return_value=worker) as create_worker, \
             patch("ui.screens.settings_screen.detect_local_agents", return_value=[]), \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen.test_ai_btn.click()

            self.assertTrue(worker.start_called)
            self.assertFalse(screen.test_ai_btn.isEnabled())
            self.assertFalse(screen.save_btn.isEnabled())
            self.assertNotEqual("", screen.ai_connection_status.text())

            worker.result_ready.emit(ConnectionProbeResult(
                ok=True,
                message="Connected to provider 'custom' with model 'test-model'.",
                elapsed_ms=123,
                provider="custom",
                model="test-model",
            ))

        create_worker.assert_called_once()
        self.assertTrue(screen.test_ai_btn.isEnabled())
        self.assertTrue(screen.save_btn.isEnabled())
        self.assertIn("Connected", screen.ai_connection_status.text())
        self.assertTrue(info.called)
        self.assertIn("123 ms", info.call_args.args[2])

    def test_settings_screen_connection_status_label_updates_with_language(self):
        manager = LanguageManager.instance()
        original = manager.current
        try:
            screen = SettingsScreen()
            manager.set_language("en")
            self.assertEqual("Connection:", screen.ai_connection_status_label.text())

            manager.set_language("zh")
            self.assertEqual("连接状态:", screen.ai_connection_status_label.text())
        finally:
            manager.set_language(original)

    def test_settings_screen_exposes_environment_check_with_ocr_fix_options(self):
        screen = SettingsScreen()
        report = EnvironmentReport(
            (
                CheckResult("Python", True, True, "3.13.5"),
                CheckResult(
                    "Tesseract OCR",
                    False,
                    False,
                    "optional system executable not found; scanned PDF OCR is unavailable",
                    "Windows: winget install -e --id UB-Mannheim.TesseractOCR",
                ),
            )
        )

        with patch("ui.screens.settings_screen.collect_environment_report", return_value=report) as collect, \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen.environment_check_btn.click()

        collect.assert_called_once()
        self.assertTrue(info.called)
        message = info.call_args.args[2]
        self.assertIn("[WARN] Tesseract OCR", message)
        self.assertIn("winget install -e --id UB-Mannheim.TesseractOCR", message)

    def test_settings_screen_copies_ocr_fix_commands(self):
        screen = SettingsScreen()
        _APP.clipboard().clear()

        with patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen.ocr_fix_btn.click()

        self.assertEqual(OCR_REMEDIATION, _APP.clipboard().text())
        self.assertTrue(info.called)
        self.assertIn("winget install -e --id UB-Mannheim.TesseractOCR", info.call_args.args[2])

    def test_settings_screen_saves_practice_defaults(self):
        screen = SettingsScreen()
        screen.default_question_count_input.setValue(24)
        screen.default_difficulty_combo.setCurrentIndex(
            screen.default_difficulty_combo.findData("hard")
        )
        screen.default_template_combo.setCurrentIndex(
            screen.default_template_combo.findData("final_exam")
        )
        screen.show_timer_checkbox.setChecked(True)

        with patch("ui.screens.settings_screen.write_json", return_value=True) as write_json:
            screen.save_settings(silent=True)

        saved = write_json.call_args.args[1]
        self.assertEqual(24, saved["default_question_count"])
        self.assertEqual("hard", saved["default_difficulty"])
        self.assertEqual("final_exam", saved["default_generation_template"])
        self.assertTrue(saved["show_timer"])

    def test_settings_screen_does_not_reveal_existing_api_key(self):
        manager = SimpleNamespace(
            get_key=lambda: "sk-super-secret",
            get_storage_location=lambda: "system keychain",
        )
        with patch("core.secrets_manager.SecretsManager.instance", return_value=manager):
            screen = SettingsScreen()

        self.assertEqual("", screen.api_key_input.text())
        self.assertNotIn("sk-super-secret", screen.api_key_input.placeholderText())
        self.assertIn("system keychain", screen.api_key_input.placeholderText())
        self.assertTrue(screen.clear_api_key_btn.isEnabled())

    def test_blank_save_keeps_existing_key_and_typed_save_updates_it(self):
        manager = SimpleNamespace(
            get_key=lambda: "sk-existing",
            get_storage_location=lambda: "system keychain",
            set_key=unittest.mock.Mock(return_value="system keychain"),
        )
        with patch("core.secrets_manager.SecretsManager.instance", return_value=manager), \
             patch("ui.screens.settings_screen.write_json", return_value=True):
            screen = SettingsScreen()
            screen.save_settings(silent=True)
            manager.set_key.assert_not_called()

            screen.api_key_input.setText("sk-new")
            screen.save_settings(silent=True)

        manager.set_key.assert_called_once_with("sk-new")
        self.assertEqual("", screen.api_key_input.text())

    def test_clear_key_requires_confirmation_and_clears_secret(self):
        manager = SimpleNamespace(
            get_key=lambda: "sk-existing",
            get_storage_location=lambda: "system keychain",
            set_key=unittest.mock.Mock(return_value="not set"),
        )
        with patch("core.secrets_manager.SecretsManager.instance", return_value=manager), \
             patch("ui.screens.settings_screen.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
             patch("ui.screens.settings_screen.QMessageBox.information"):
            screen = SettingsScreen()
            screen.clear_api_key_btn.click()

        manager.set_key.assert_called_once_with("")
        self.assertFalse(screen.clear_api_key_btn.isEnabled())
        self.assertNotIn("system keychain", screen.api_key_input.placeholderText())


if __name__ == "__main__":
    unittest.main()
