import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core.secrets_manager import SecretsManager


class FakeDPAPIStore:
    def __init__(self, value="", write_ok=True, available=True):
        self.value = value
        self.write_ok = write_ok
        self.available = available
        self.deleted = 0

    def is_available(self):
        return self.available

    def get_key(self):
        return self.value

    def set_key(self, key):
        if self.write_ok:
            self.value = key
        return self.write_ok

    def delete_key(self):
        self.deleted += 1
        self.value = ""
        return True


class SecretsManagerTests(unittest.TestCase):
    def setUp(self):
        self.previous_instance = SecretsManager._instance
        SecretsManager._instance = None

    def tearDown(self):
        SecretsManager._instance = self.previous_instance
        os.environ.pop("QUIZ_APP_API_KEY", None)

    def test_subclass_initialization_does_not_replace_base_singleton(self):
        class SpecializedSecretsManager(SecretsManager):
            _instance = None

        specialized = SpecializedSecretsManager()

        self.assertIs(specialized, SpecializedSecretsManager._instance)
        self.assertIsNone(SecretsManager._instance)

    def test_without_keyring_new_key_is_session_only_and_not_plaintext(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(
                json.dumps({"language": "zh", "ai_api_key": "legacy", "ai_api_key_stored_in_plaintext": True}),
                encoding="utf-8",
            )
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", False), \
                 patch("core.secrets_manager.DPAPI_STORE", FakeDPAPIStore(available=False)):
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
                 patch("core.secrets_manager.keyring") as keyring, \
                 patch("core.secrets_manager.DPAPI_STORE", FakeDPAPIStore()) as dpapi:
                manager = SecretsManager()

                location = manager.set_key("sk-keyring")

                keyring.set_password.assert_called_once()
                saved = json.loads(Path(settings_file).read_text(encoding="utf-8"))
                self.assertNotIn("ai_api_key", saved)
                self.assertEqual("system keychain", location)
                self.assertEqual("system keychain", manager.get_storage_location())
                self.assertEqual(1, dpapi.deleted)

    def test_keyring_storage_reports_failed_legacy_plaintext_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(
                json.dumps({"ai_api_key": "legacy"}),
                encoding="utf-8",
            )
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", True), \
                 patch("core.secrets_manager.keyring"), \
                 patch("core.secrets_manager.DPAPI_STORE", FakeDPAPIStore()), \
                 patch("core.secrets_manager.write_json", return_value=False):
                manager = SecretsManager()

                location = manager.set_key("sk-new")

                self.assertIn("plaintext cleanup failed", location)
                self.assertIn("plaintext cleanup failed", manager.get_storage_warning())
                self.assertNotIn("sk-new", manager.get_storage_warning())

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
                 patch("core.secrets_manager.keyring") as keyring, \
                 patch("core.secrets_manager.DPAPI_STORE", FakeDPAPIStore("dpapi-old")) as dpapi:
                manager = SecretsManager()

                location = manager.set_key("")

                self.assertEqual("not set", location)
                self.assertNotIn("QUIZ_APP_API_KEY", os.environ)
                keyring.delete_password.assert_called_once()
                saved = json.loads(Path(settings_file).read_text(encoding="utf-8"))
                self.assertNotIn("ai_api_key", saved)
                self.assertNotIn("ai_api_key_stored_in_plaintext", saved)
                self.assertEqual(1, dpapi.deleted)

    def test_legacy_plaintext_is_readable_and_auto_migrated_to_dpapi(self):
        """First read of a legacy plaintext key migrates it to DPAPI and removes plaintext."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(json.dumps({
                "ai_api_key": "legacy",
                "ai_api_key_stored_in_plaintext": True,
            }), encoding="utf-8")
            store = FakeDPAPIStore()
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", False), \
                 patch("core.secrets_manager.DPAPI_STORE", store):
                manager = SecretsManager()

                self.assertEqual("legacy", manager.get_key())

            # After migration, settings no longer contain the key.
            remaining = json.loads(Path(settings_file).read_text(encoding="utf-8"))
            self.assertNotIn("ai_api_key", remaining)
            self.assertNotIn("ai_api_key_stored_in_plaintext", remaining)

    def test_legacy_migration_reports_failed_plaintext_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(
                json.dumps({
                    "ai_api_key": "sk-legacy-secret",
                    "ai_api_key_stored_in_plaintext": True,
                }),
                encoding="utf-8",
            )
            store = FakeDPAPIStore()
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", False), \
                 patch("core.secrets_manager.DPAPI_STORE", store), \
                patch("core.secrets_manager.write_json", return_value=False):
                manager = SecretsManager()

                self.assertEqual("sk-legacy-secret", manager.get_key())

                self.assertIn(
                    "plaintext cleanup failed",
                    manager.get_storage_warning(),
                )
                self.assertIn(
                    "plaintext cleanup failed",
                    manager.get_storage_location(),
                )
                self.assertNotIn(
                    "sk-legacy-secret",
                    manager.get_storage_warning(),
                )

    def test_windows_dpapi_persists_key_when_keyring_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            store = FakeDPAPIStore()
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", False), \
                 patch("core.secrets_manager.DPAPI_STORE", store):
                manager = SecretsManager()

                location = manager.set_key("sk-persistent")
                os.environ.pop("QUIZ_APP_API_KEY", None)
                manager._last_storage_location = ""

                self.assertEqual("Windows DPAPI encrypted store", location)
                self.assertEqual("sk-persistent", manager.get_key())
                self.assertEqual("Windows DPAPI encrypted store", manager.get_storage_location())
                saved = json.loads(Path(settings_file).read_text(encoding="utf-8"))
                self.assertNotIn("ai_api_key", saved)

    def test_keyring_write_failure_records_warning_without_exposing_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            store = FakeDPAPIStore()
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", True), \
                 patch("core.secrets_manager.keyring") as keyring, \
                 patch("core.secrets_manager.DPAPI_STORE", store):
                keyring.set_password.side_effect = RuntimeError("credential store locked")
                manager = SecretsManager()

                location = manager.set_key("sk-secret-write-failure")

                warning = manager.get_storage_warning()
                self.assertEqual("Windows DPAPI encrypted store", location)
                self.assertEqual("sk-secret-write-failure", store.value)
                self.assertIn("system keychain", warning)
                self.assertIn("RuntimeError", warning)
                self.assertNotIn("credential store locked", warning)
                self.assertNotIn("sk-secret-write-failure", warning)

    def test_keyring_warning_never_displays_backend_exception_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            token = "AIzaSyDUMMY_SECRET_1234567890"
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", True), \
                 patch("core.secrets_manager.keyring") as keyring, \
                 patch(
                     "core.secrets_manager.DPAPI_STORE",
                     FakeDPAPIStore(available=False),
                 ):
                keyring.set_password.side_effect = RuntimeError(
                    f"backend rejected credential={token}"
                )
                manager = SecretsManager()

                manager.set_key(token)

                warning = manager.get_storage_warning()
                self.assertIn("RuntimeError", warning)
                self.assertNotIn(token, warning)
                self.assertNotIn("backend rejected", warning)

    def test_keyring_read_failure_records_warning_and_uses_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            store = FakeDPAPIStore("sk-dpapi-fallback")
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", True), \
                 patch("core.secrets_manager.keyring") as keyring, \
                 patch("core.secrets_manager.DPAPI_STORE", store):
                keyring.get_password.side_effect = OSError("backend unavailable")
                manager = SecretsManager()

                self.assertEqual("sk-dpapi-fallback", manager.get_key())

                warning = manager.get_storage_warning()
                self.assertIn("system keychain", warning)
                self.assertIn("OSError", warning)
                self.assertNotIn("backend unavailable", warning)
                self.assertNotIn("sk-dpapi-fallback", warning)

    def test_keyring_delete_failure_does_not_report_clean_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(
                json.dumps({"ai_api_key": "legacy", "ai_api_key_stored_in_plaintext": True}),
                encoding="utf-8",
            )
            os.environ["QUIZ_APP_API_KEY"] = "sk-session"
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", True), \
                 patch("core.secrets_manager.keyring") as keyring, \
                 patch("core.secrets_manager.DPAPI_STORE", FakeDPAPIStore("dpapi-old")) as dpapi:
                keyring.delete_password.side_effect = RuntimeError("delete denied")
                manager = SecretsManager()

                location = manager.set_key("")

                warning = manager.get_storage_warning()
                self.assertIn("system keychain clear failed", location)
                self.assertIn("RuntimeError", warning)
                self.assertNotIn("delete denied", warning)
                self.assertNotIn("sk-session", warning)
                self.assertNotIn("QUIZ_APP_API_KEY", os.environ)
                self.assertEqual(1, dpapi.deleted)

    def test_dpapi_availability_is_read_from_current_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            store = FakeDPAPIStore()
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", False), \
                 patch("core.secrets_manager.DPAPI_STORE_AVAILABLE", False), \
                 patch("core.secrets_manager.DPAPI_STORE", store):
                manager = SecretsManager()

                location = manager.set_key("sk-dynamic-dpapi")
                os.environ.pop("QUIZ_APP_API_KEY", None)

                self.assertEqual("Windows DPAPI encrypted store", location)
                self.assertEqual("sk-dynamic-dpapi", manager.get_key())

    def test_plaintext_flag_requires_an_actual_legacy_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(
                json.dumps({"ai_api_key_stored_in_plaintext": True}),
                encoding="utf-8",
            )
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file):
                manager = SecretsManager()

                self.assertFalse(manager.is_plaintext_fallback())

    def test_set_key_serializes_multi_step_storage_writes(self):
        manager = SecretsManager()
        start_barrier = threading.Barrier(2)
        first_write_entered = threading.Event()
        second_write_entered = threading.Event()
        counter_lock = threading.Lock()
        active_writes = 0
        max_active_writes = 0
        errors = []

        def slow_write_json(_path, _settings):
            nonlocal active_writes, max_active_writes
            with counter_lock:
                active_writes += 1
                max_active_writes = max(max_active_writes, active_writes)
                if active_writes == 1:
                    first_write_entered.set()
                elif active_writes == 2:
                    second_write_entered.set()
            first_write_entered.wait(1)
            second_write_entered.wait(0.2)
            with counter_lock:
                active_writes -= 1
            return True

        def set_key_thread(key):
            try:
                start_barrier.wait(1)
                manager.set_key(key)
            except Exception as exc:
                errors.append(exc)

        with patch("core.secrets_manager.KEYRING_AVAILABLE", False), \
             patch("core.secrets_manager.DPAPI_STORE", FakeDPAPIStore(available=False)), \
             patch("core.secrets_manager.read_json", return_value={}), \
             patch("core.secrets_manager.write_json", side_effect=slow_write_json):
            threads = [
                threading.Thread(target=set_key_thread, args=("sk-one",)),
                threading.Thread(target=set_key_thread, args=("sk-two",)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual([], errors)
        self.assertEqual(1, max_active_writes)


    def test_migration_failure_preserves_plaintext_when_both_backends_unavailable(self):
        """When keyring and DPAPI both fail, plaintext key must survive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            original = {
                "ai_api_key": "legacy-key",
                "ai_api_key_stored_in_plaintext": True,
            }
            Path(settings_file).write_text(
                json.dumps(original), encoding="utf-8"
            )
            store = FakeDPAPIStore(write_ok=False, available=True)
            with patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.KEYRING_AVAILABLE", False), \
                 patch("core.secrets_manager.DPAPI_STORE", store):
                manager = SecretsManager()

                first = manager.get_key()
                second = manager.get_key()

            self.assertEqual("legacy-key", first)
            self.assertEqual("legacy-key", second)
            remaining = json.loads(Path(settings_file).read_text(encoding="utf-8"))
            self.assertIn("ai_api_key", remaining)
            self.assertEqual("legacy-key", remaining["ai_api_key"])

    def test_migration_readback_failure_preserves_plaintext(self):
        """Plaintext must survive when migration write cannot be verified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = str(Path(tmpdir) / "settings.json")
            Path(settings_file).write_text(
                json.dumps({"ai_api_key": "legacy-key-2"}), encoding="utf-8"
            )
            # keyring write succeeds but readback returns different value.
            readback_values = ["legacy-key-2", "mismatch"]

            def fake_get_password(service, account):
                return readback_values.pop(0)

            with patch("core.secrets_manager.KEYRING_AVAILABLE", True), \
                 patch("core.secrets_manager.keyring.set_password"), \
                 patch("core.secrets_manager.keyring.get_password",
                       side_effect=fake_get_password), \
                 patch("core.secrets_manager.SETTINGS_FILE", settings_file), \
                 patch("core.secrets_manager.DPAPI_STORE",
                       FakeDPAPIStore(available=False)):
                manager = SecretsManager()
                key = manager.get_key()

            self.assertEqual("legacy-key-2", key)
            remaining = json.loads(Path(settings_file).read_text(encoding="utf-8"))
            self.assertIn("ai_api_key", remaining,
                          "plaintext must survive when readback fails")


if __name__ == "__main__":
    unittest.main()
