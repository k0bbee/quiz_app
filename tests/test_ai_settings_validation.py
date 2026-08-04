import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox

from ai.connection_probe import ConnectionProbeResult
from ai.settings_validation import validate_ai_settings
from core.environment_check import CheckResult, EnvironmentReport
from core.language_manager import LanguageManager
from core.ocr_runtime import OCR_REMEDIATION
from core.background_task import TaskProgress
from core.background_task_center import BackgroundTaskCenter, TaskStatus
from ui.screens.settings_screen import AppDataBundleWorker, SettingsScreen


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


class ManualAppDataWorker:
    def __init__(self):
        self.exported = ManualSignal()
        self.imported = ManualSignal()
        self.failed = ManualSignal()
        self.progressed = ManualSignal()
        self.cancelled = ManualSignal()
        self.start_called = False
        self.cancel_called = False

    def start(self):
        self.start_called = True

    def cancel(self):
        self.cancel_called = True


class AISettingsValidationTests(unittest.TestCase):
    def test_settings_hides_local_agent_status_for_remote_provider(self):
        screen = SettingsScreen()

        screen.provider_combo.setCurrentIndex(screen.provider_combo.findData("openai"))

        self.assertTrue(screen.local_agent_label.isHidden())
        self.assertTrue(screen.local_agent_status.isHidden())

        screen.provider_combo.setCurrentIndex(screen.provider_combo.findData("local_agent"))

        self.assertFalse(screen.local_agent_label.isHidden())
        self.assertFalse(screen.local_agent_status.isHidden())

    def test_settings_snapshot_is_public_and_cannot_mutate_screen_state(self):
        screen = SettingsScreen()
        screen._settings["default_question_type_weights"] = {"multiple_choice": 70}

        snapshot = screen.settings_snapshot()
        snapshot["ai_model"] = "changed-outside"
        snapshot["default_question_type_weights"]["multiple_choice"] = 5

        self.assertNotEqual("changed-outside", screen.get_setting("ai_model"))
        self.assertEqual(
            70,
            screen.get_setting("default_question_type_weights")["multiple_choice"],
        )

    def test_codex_is_detected_but_rejected_for_untrusted_content(self):
        result = validate_ai_settings(
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            api_key="",
            detected_agents=["codex"],
        )

        self.assertFalse(result.ok)
        self.assertIn("Codex", result.message)

    def test_claude_is_valid_when_detected(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = validate_ai_settings(
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "claude"},
                api_key="",
                detected_agents=["claude"],
            )

        self.assertTrue(result.ok)
        self.assertIn("claude", result.message)

    def test_auto_selects_eligible_claude(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = validate_ai_settings(
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "auto"},
                api_key="",
                detected_agents=["codex", "claude"],
            )

        self.assertTrue(result.ok)
        self.assertIn("claude", result.message)

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
        screen.model_combo.setCurrentText("claude")
        screen.api_key_input.clear()
        worker = ManualConnectionWorker()

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch.object(screen, "_create_connection_test_worker", return_value=worker) as create_worker, \
             patch("ui.screens.settings_screen.detect_local_agents", return_value=["claude"]), \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen.test_ai_btn.click()
            self.assertTrue(worker.start_called)
            self.assertFalse(info.called)

            worker.result_ready.emit(ConnectionProbeResult(
                ok=True,
                message="Connected to provider 'local_agent' with model 'claude'.",
                elapsed_ms=15,
                provider="local_agent",
                model="claude",
            ))

        settings_arg, api_key_arg = create_worker.call_args.args
        self.assertEqual("local_agent", settings_arg["ai_provider"])
        self.assertEqual("", api_key_arg)
        self.assertTrue(info.called)
        self.assertIn("claude", info.call_args.args[2])

    def test_settings_screen_rejects_codex_without_starting_probe(self):
        screen = SettingsScreen()
        screen.provider_combo.setCurrentIndex(screen.provider_combo.findData("local_agent"))
        screen.api_base_url.setText("local-agent://auto")
        screen.model_combo.setCurrentText("codex")

        with patch.object(screen, "_create_connection_test_worker") as create_worker, \
             patch("ui.screens.settings_screen.detect_local_agents", return_value=["codex"]), \
             patch("ui.screens.settings_screen.QMessageBox.warning") as warning:
            screen.test_ai_btn.click()

        create_worker.assert_not_called()
        warning.assert_called_once()
        self.assertIn("not eligible", warning.call_args.args[2])

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
        self.assertIn("Environment check: WARN", screen.environment_status.text())
        self.assertIn("Tesseract OCR", screen.environment_status.text())
        self.assertEqual("warn", screen.environment_status.property("envState"))
        self.assertTrue(info.called)
        message = info.call_args.args[2]
        self.assertIn("[WARN] Tesseract OCR", message)
        self.assertIn("winget install -e --id UB-Mannheim.TesseractOCR", message)

    def test_settings_screen_uses_warning_for_required_environment_failures(self):
        screen = SettingsScreen()
        report = EnvironmentReport(
            (
                CheckResult("Python", True, True, "3.13.5"),
                CheckResult("data directory", False, True, "not writable: denied"),
            )
        )

        with patch("ui.screens.settings_screen.collect_environment_report", return_value=report), \
             patch("ui.screens.settings_screen.QMessageBox.information") as info, \
             patch("ui.screens.settings_screen.QMessageBox.warning") as warning:
            screen.environment_check_btn.click()

        self.assertFalse(info.called)
        self.assertTrue(warning.called)
        self.assertIn("Environment check: FAIL", screen.environment_status.text())
        self.assertIn("data directory", screen.environment_status.text())
        self.assertEqual("fail", screen.environment_status.property("envState"))
        message = warning.call_args.args[2]
        self.assertIn("Environment check: FAIL", message)
        self.assertIn("[FAIL] data directory", message)

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
        screen.default_mc_weight_input.setValue(45)
        screen.default_scenario_weight_input.setValue(35)
        screen.default_true_false_weight_input.setValue(15)
        screen.default_fill_blank_weight_input.setValue(5)
        screen.default_matching_weight_input.setValue(10)
        screen.default_ordering_weight_input.setValue(8)
        screen.default_short_answer_weight_input.setValue(2)
        screen.default_easy_weight_input.setValue(10)
        screen.default_medium_weight_input.setValue(70)
        screen.default_hard_weight_input.setValue(20)
        screen.show_timer_checkbox.setChecked(True)

        with patch("ui.screens.settings_screen.write_json", return_value=True) as write_json:
            screen.save_settings(silent=True)

        saved = write_json.call_args.args[1]
        self.assertEqual(24, saved["default_question_count"])
        self.assertEqual("hard", saved["default_difficulty"])
        self.assertEqual("final_exam", saved["default_generation_template"])
        self.assertEqual(
            {
                "multiple_choice": 45,
                "scenario_choice": 35,
                "true_false": 15,
                "fill_in_blank": 5,
                "matching": 10,
                "ordering": 8,
                "short_answer": 2,
            },
            saved["default_question_type_weights"],
        )
        self.assertEqual(
            {"easy": 10, "medium": 70, "hard": 20},
            saved["default_difficulty_weights"],
        )
        self.assertTrue(saved["show_timer"])

    def test_settings_screen_shows_unsaved_and_saved_state_for_manual_save(self):
        screen = SettingsScreen()

        self.assertFalse(screen.settings_dirty)
        self.assertEqual("clean", screen.settings_save_status.property("saveState"))
        self.assertIn("无未保存", screen.settings_save_status.text())

        screen.default_question_count_input.setValue(
            screen.default_question_count_input.value() + 1
        )

        self.assertTrue(screen.settings_dirty)
        self.assertEqual("dirty", screen.settings_save_status.property("saveState"))
        self.assertIn("未保存", screen.settings_save_status.text())

        with patch("ui.screens.settings_screen.write_json", return_value=True):
            screen.save_settings(silent=True)

        self.assertFalse(screen.settings_dirty)
        self.assertEqual("saved", screen.settings_save_status.property("saveState"))
        self.assertIn("已保存", screen.settings_save_status.text())

    def test_settings_weight_preview_updates_normalized_effective_percentages_after_confirmation(self):
        screen = SettingsScreen()

        self.assertIn("选择题", screen.question_type_weight_preview.text())
        initial_preview = screen.question_type_weight_preview.text()

        screen.default_mc_weight_input.setValue(100)
        screen.default_scenario_weight_input.setValue(80)
        screen.default_true_false_weight_input.setValue(0)
        screen.default_fill_blank_weight_input.setValue(0)
        screen.default_matching_weight_input.setValue(20)
        screen.default_ordering_weight_input.setValue(0)
        screen.default_short_answer_weight_input.setValue(0)

        self.assertEqual(initial_preview, screen.question_type_weight_preview.text())

        screen.refresh_default_weight_preview_btn.click()

        self.assertIn("选择题 50%", screen.question_type_weight_preview.text())
        self.assertIn("情境选择题 40%", screen.question_type_weight_preview.text())
        self.assertIn("判断题 0%", screen.question_type_weight_preview.text())
        self.assertIn("填空题 0%", screen.question_type_weight_preview.text())
        self.assertIn("配对题 10%", screen.question_type_weight_preview.text())

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

    def test_save_settings_displays_secret_storage_warning_without_key_value(self):
        manager = SimpleNamespace(
            get_key=lambda: "",
            get_storage_location=lambda: "Windows DPAPI encrypted store",
            get_storage_warning=lambda: "system keychain write failed: RuntimeError: locked",
            set_key=unittest.mock.Mock(return_value="Windows DPAPI encrypted store"),
        )
        with patch("core.secrets_manager.SecretsManager.instance", return_value=manager), \
             patch("ui.screens.settings_screen.write_json", return_value=True), \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen = SettingsScreen()
            screen.api_key_input.setText("sk-new-secret")

            screen.save_settings()

        message = info.call_args.args[2]
        self.assertIn("system keychain write failed", message)
        self.assertNotIn("sk-new-secret", message)

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

    def test_clear_key_displays_storage_warning_without_key_value(self):
        manager = SimpleNamespace(
            get_key=lambda: "sk-existing",
            get_storage_location=lambda: "system keychain",
            get_storage_warning=lambda: "system keychain clear failed: RuntimeError: denied",
            set_key=unittest.mock.Mock(return_value="not set (system keychain clear failed)"),
        )
        with patch("core.secrets_manager.SecretsManager.instance", return_value=manager), \
             patch("ui.screens.settings_screen.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen = SettingsScreen()
            screen.clear_api_key_btn.click()

        message = info.call_args.args[2]
        self.assertIn("system keychain clear failed", message)
        self.assertNotIn("sk-existing", message)

    def test_import_progress_runs_validated_service_in_background(self):
        screen = SettingsScreen()
        worker = ManualAppDataWorker()
        result = SimpleNamespace(
            imported=8,
            overwritten=2,
            invalid=1,
            migrated_complete=3,
            migrated_incomplete=1,
        )

        with patch(
            "ui.screens.settings_screen.QFileDialog.getOpenFileName",
            return_value=("progress_export.json", ""),
        ), patch(
            "ui.screens.settings_screen.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ), patch.object(
            screen,
            "_create_progress_import_worker",
            return_value=worker,
        ) as create_worker, patch(
            "ui.screens.settings_screen.QMessageBox.information",
        ) as info:
            screen.import_btn.click()

            create_worker.assert_called_once_with("progress_export.json")
            self.assertTrue(worker.start_called)
            self.assertFalse(screen.import_btn.isEnabled())
            self.assertIn("验证", screen.app_data_status_label.text())
            self.assertFalse(info.called)

            worker.imported.emit(result)

        self.assertTrue(screen.import_btn.isEnabled())
        self.assertTrue(info.called)
        message = info.call_args.args[2]
        for value in ("8", "2", "1", "3"):
            self.assertIn(value, message)

    def test_app_data_export_runs_in_background_worker(self):
        screen = SettingsScreen()
        worker = ManualAppDataWorker()

        with patch("ui.screens.settings_screen.QFileDialog.getSaveFileName", return_value=("backup.quizdata", "")), \
             patch.object(screen, "_create_app_data_worker", return_value=worker) as create_worker, \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen.export_app_data_btn.click()

            create_worker.assert_called_once_with("export", "backup.quizdata")
            self.assertTrue(worker.start_called)
            self.assertFalse(screen.export_app_data_btn.isEnabled())
            self.assertFalse(screen.import_app_data_btn.isEnabled())
            self.assertFalse(info.called)

            worker.exported.emit("backup.quizdata")

        self.assertTrue(screen.export_app_data_btn.isEnabled())
        self.assertTrue(screen.import_app_data_btn.isEnabled())
        self.assertTrue(info.called)
        self.assertIn("backup.quizdata", info.call_args.args[2])

    def test_app_data_import_runs_in_background_worker(self):
        screen = SettingsScreen()
        worker = ManualAppDataWorker()
        result = SimpleNamespace(imported_files=12, skipped_files=["unsafe.txt"], ignored_settings=[])

        with patch("ui.screens.settings_screen.QFileDialog.getOpenFileName", return_value=("backup.quizdata", "")), \
             patch("ui.screens.settings_screen.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(screen, "_create_app_data_worker", return_value=worker) as create_worker, \
             patch("ui.screens.settings_screen.QMessageBox.information") as info:
            screen.import_app_data_btn.click()

            create_worker.assert_called_once_with("import", "backup.quizdata")
            self.assertTrue(worker.start_called)
            self.assertFalse(screen.export_app_data_btn.isEnabled())
            self.assertFalse(screen.import_app_data_btn.isEnabled())
            self.assertFalse(info.called)

            worker.imported.emit(result)

        self.assertTrue(screen.export_app_data_btn.isEnabled())
        self.assertTrue(screen.import_app_data_btn.isEnabled())
        self.assertTrue(info.called)
        self.assertIn("12", info.call_args.args[2])
        self.assertTrue("Skipped" in info.call_args.args[2] or "跳过" in info.call_args.args[2])

    def test_app_data_transfer_registers_progress_and_cancel_with_task_center(self):
        with tempfile.TemporaryDirectory():
            center = BackgroundTaskCenter()
            screen = SettingsScreen(task_center=center)
            worker = ManualAppDataWorker()

            with patch(
                "ui.screens.settings_screen.QFileDialog.getSaveFileName",
                return_value=("backup.quizdata", ""),
            ), patch(
                "ui.screens.settings_screen.AppDataBundleWorker",
                return_value=worker,
            ):
                screen.export_app_data_btn.click()

                snapshot = center.snapshots()[0]
                self.assertEqual("app_data_export", snapshot.kind)
                self.assertEqual("backup.quizdata", snapshot.metadata["path"])
                self.assertFalse(screen.app_data_status_label.isHidden())
                self.assertFalse(screen.cancel_app_data_btn.isHidden())
                for button in (
                    screen.export_btn,
                    screen.import_btn,
                    screen.export_app_data_btn,
                    screen.import_app_data_btn,
                    screen.reset_progress_btn,
                ):
                    self.assertFalse(button.isEnabled())

                worker.progressed.emit(TaskProgress("exporting", 3, 8, "questions/q3.json"))
                self.assertIn("3/8", screen.app_data_status_label.text())
                self.assertIn("questions/q3.json", screen.app_data_status_label.text())

                screen.cancel_app_data_btn.click()

            self.assertEqual(TaskStatus.CANCELLED, center.get(snapshot.task_id).status)
            self.assertTrue(worker.cancel_called)
            self.assertFalse(screen.cancel_app_data_btn.isEnabled())

    def test_app_data_worker_completes_persistent_export_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            (data_dir / "questions").mkdir(parents=True)
            (data_dir / "questions" / "q1.json").write_text(
                '{"question_id": "q1"}',
                encoding="utf-8",
            )
            output = root / "backup.quizdata"
            center = BackgroundTaskCenter()
            snapshot = center.create(
                kind="app_data_export",
                title="Export app data",
                metadata={"path": str(output)},
            )
            worker = AppDataBundleWorker(
                "export",
                str(output),
                str(data_dir),
                task_center=center,
                task_id=snapshot.task_id,
            )
            exported = []
            worker.exported.connect(exported.append)

            worker.run()

            completed = center.get(snapshot.task_id)
            self.assertEqual(TaskStatus.COMPLETED, completed.status)
            self.assertEqual(1, completed.result_count)
            self.assertEqual([output], exported)

    def test_progress_import_worker_routes_through_validated_service(self):
        result = SimpleNamespace(imported=4)
        service = SimpleNamespace(import_file=lambda path, task=None: result)
        worker = AppDataBundleWorker(
            "progress_import",
            "progress.json",
            "data",
        )
        imported = []
        worker.imported.connect(imported.append)

        with patch(
            "core.progress_import.ProgressImportService.from_data_dir",
            return_value=service,
        ) as service_factory:
            worker.run()

        service_factory.assert_called_once_with("data")
        self.assertEqual([result], imported)


if __name__ == "__main__":
    unittest.main()
