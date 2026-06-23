import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.secrets_manager import SecretsManager


class SecretsManagerTests(unittest.TestCase):
    def setUp(self):
        self.previous_instance = SecretsManager._instance
        SecretsManager._instance = None

    def tearDown(self):
        SecretsManager._instance = self.previous_instance
        os.environ.pop("QUIZ_APP_API_KEY", None)

    def test_without_keyring_new_key_is_session_only_and_not_plaintext(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(
                json.dumps({"language": "zh", "ai_api_key": "legacy", "ai_api_key_stored_in_plaintext": True}),
                encoding="utf-8",
            )
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", False):
                manager = SecretsManager()

                location = manager.set_key("sk-session")

                saved = json.loads(Path(settings_file).read_text(encoding="utf-8"))
                self.assertEqual("sk-session", os.environ["QUIZ_APP_API_KEY"])
                self.assertNotIn("ai_api_key", saved)
                self.assertNotIn("ai_api_key_stored_in_plaintext", saved)
                self.assertIn("current session", location)
                self.assertIn("current session", manager.get_storage_location())

    def test_keyring_storage_clears_legacy_plaintext(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(json.dumps({"ai_api_key": "legacy"}), encoding="utf-8")
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", True), \
                 patch("core.secrets_manager.keyring") as keyring:
                manager = SecretsManager()

                location = manager.set_key("sk-keyring")

                keyring.set_password.assert_called_once()
                saved = json.loads(Path(settings_file).read_text(encoding="utf-8"))
                self.assertNotIn("ai_api_key", saved)
                self.assertEqual("system keychain", location)
                self.assertEqual("system keychain", manager.get_storage_location())

    def test_clear_key_removes_session_key_keyring_and_legacy_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(
                json.dumps({"ai_api_key": "legacy", "ai_api_key_stored_in_plaintext": True}),
                encoding="utf-8",
            )
            os.environ["QUIZ_APP_API_KEY"] = "sk-session"
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", True), \
                 patch("core.secrets_manager.keyring") as keyring:
                manager = SecretsManager()

                location = manager.set_key("")

                self.assertEqual("not set", location)
                self.assertNotIn("QUIZ_APP_API_KEY", os.environ)
                keyring.delete_password.assert_called_once()
                saved = json.loads(Path(settings_file).read_text(encoding="utf-8"))
                self.assertNotIn("ai_api_key", saved)
                self.assertNotIn("ai_api_key_stored_in_plaintext", saved)

    def test_legacy_plaintext_remains_readable_until_user_migrates_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(json.dumps({"ai_api_key": "legacy"}), encoding="utf-8")
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", False):
                manager = SecretsManager()

                self.assertEqual("legacy", manager.get_key())
                self.assertIn("plaintext", manager.get_storage_location())


if __name__ == "__main__":
    unittest.main()
