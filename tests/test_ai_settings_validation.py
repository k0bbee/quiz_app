import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox

from ai.settings_validation import validate_ai_settings
from ui.screens.settings_screen import SettingsScreen


_APP = QApplication.instance() or QApplication([])


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

    def test_settings_screen_test_button_reports_current_configuration(self):
        screen = SettingsScreen()
        screen.provider_combo.setCurrentIndex(screen.provider_combo.findData("local_agent"))
        screen.api_base_url.setText("local-agent://auto")
        screen.model_combo.setCurrentText("codex")
        screen.api_key_input.clear()

        with patch("ui.screens.settings_screen.detect_local_agents", return_value=["codex"]), \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen.test_ai_btn.click()

        self.assertTrue(info.called)
        self.assertIn("codex", info.call_args.args[2])

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
