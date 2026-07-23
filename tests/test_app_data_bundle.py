import json
import os
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.app_data_bundle import (
    export_app_data_bundle,
    import_app_data_bundle,
    LOCAL_ONLY_SETTING_KEYS,
)
from core.background_task import BackgroundTaskCancelled, TaskControl


class AppDataBundleTests(unittest.TestCase):
    def test_cancelled_export_preserves_existing_bundle_and_removes_staging_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            questions = data_dir / "questions"
            questions.mkdir(parents=True)
            (questions / "q1.json").write_text('{"question_id": "q1"}', encoding="utf-8")
            output = root / "backup.quizdata"
            output.write_bytes(b"previous backup")

            task = TaskControl(
                lambda progress: task.cancel()
                if progress.stage == "exporting" and progress.current == 1
                else None
            )

            with self.assertRaises(BackgroundTaskCancelled):
                export_app_data_bundle(data_dir, output, task=task)

            self.assertEqual(b"previous backup", output.read_bytes())
            self.assertEqual([], list(root.glob(".backup.quizdata.*.tmp")))

    def test_cancelled_import_rolls_back_files_already_committed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "data"
            (target / "questions").mkdir(parents=True)
            existing = target / "questions" / "q1.json"
            existing.write_text('{"value": "old"}', encoding="utf-8")
            bundle = root / "backup.quizdata"
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("questions/q1.json", '{"value": "new"}')
                archive.writestr("questions/q2.json", '{"value": "new"}')

            task = TaskControl(
                lambda progress: task.cancel()
                if progress.stage == "committing" and progress.current == 2
                else None
            )

            with self.assertRaises(BackgroundTaskCancelled):
                import_app_data_bundle(bundle, target, task=task)

            self.assertEqual({"value": "old"}, json.loads(existing.read_text(encoding="utf-8")))
            self.assertFalse((target / "questions" / "q2.json").exists())

    def test_export_bundle_includes_runtime_data_without_api_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            (data_dir / "courses" / "course-a").mkdir(parents=True)
            (data_dir / "questions").mkdir()
            (data_dir / "question_sets").mkdir()
            (data_dir / "progress").mkdir()
            (data_dir / "quiz_snapshots").mkdir()
            (data_dir / "past_exams" / "past-exam-a").mkdir(parents=True)
            (data_dir / "current_event_materials").mkdir()
            (data_dir / "courses" / "course-a" / "summary.md").write_text("# 课程总结", encoding="utf-8")
            (data_dir / "questions" / "q1.json").write_text('{"question_id": "q1"}', encoding="utf-8")
            (data_dir / "questions" / ".question_index.sqlite3").write_bytes(b"derived index")
            (data_dir / "questions" / ".question_index.sqlite3-wal").write_bytes(b"derived wal")
            (data_dir / "questions" / ".question_index.sqlite3-shm").write_bytes(b"derived shm")
            (data_dir / "question_sets" / "set1.json").write_text('{"set_id": "set1"}', encoding="utf-8")
            (data_dir / "progress" / "p1.json").write_text('{"progress_id": "p1"}', encoding="utf-8")
            (data_dir / "quiz_snapshots" / "snapshot1.json").write_text(
                '{"snapshot_id": "snapshot1"}',
                encoding="utf-8",
            )
            (data_dir / "past_exams" / "past-exam-a" / "record.json").write_text(
                '{"exam_id": "past-exam-a"}',
                encoding="utf-8",
            )
            (data_dir / "current_event_materials" / "material-a.json").write_text(
                '{"pack_id": "material-a"}',
                encoding="utf-8",
            )
            (data_dir / "current_course.json").write_text('{"course_id": "course-a"}', encoding="utf-8")
            (data_dir / "mastery_overrides.json").write_text(
                '{"courses": {"course-a": ["cache"]}}',
                encoding="utf-8",
            )
            (data_dir / "settings.json").write_text(
                json.dumps({"language": "zh", "ai_api_key": "secret", "ai_model": "model"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / ".api_key.dpapi").write_text("encrypted-secret", encoding="utf-8")

            bundle_path = export_app_data_bundle(data_dir, Path(tmpdir) / "bundle.quizdata")

            with zipfile.ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("courses/course-a/summary.md", names)
                self.assertIn("questions/q1.json", names)
                self.assertIn("question_sets/set1.json", names)
                self.assertIn("progress/p1.json", names)
                self.assertIn("quiz_snapshots/snapshot1.json", names)
                self.assertIn("past_exams/past-exam-a/record.json", names)
                self.assertIn("current_event_materials/material-a.json", names)
                self.assertIn("current_course.json", names)
                self.assertIn("mastery_overrides.json", names)
                self.assertIn("settings.json", names)
                self.assertNotIn(".api_key.dpapi", names)
                self.assertNotIn("questions/.question_index.sqlite3", names)
                self.assertNotIn("questions/.question_index.sqlite3-wal", names)
                self.assertNotIn("questions/.question_index.sqlite3-shm", names)

                settings = json.loads(archive.read("settings.json").decode("utf-8"))
                self.assertEqual("zh", settings["language"])
                # All AI trust fields are excluded from portable settings
                for key in LOCAL_ONLY_SETTING_KEYS:
                    self.assertNotIn(key, settings)

    def test_import_bundle_restores_whitelisted_paths_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = Path(tmpdir) / "bundle.quizdata"
            target_dir = Path(tmpdir) / "target"

            with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("courses/course-a/summary.md", "# 课程总结")
                archive.writestr("questions/q1.json", '{"question_id": "q1"}')
                archive.writestr("questions/.question_index.sqlite3", "stale derived index")
                archive.writestr("quiz_snapshots/snapshot1.json", '{"snapshot_id": "snapshot1"}')
                archive.writestr("mastery_overrides.json", '{"courses": {"course-a": ["cache"]}}')
                archive.writestr("settings.json", '{"language": "en", "ai_api_key": "must-not-import"}')
                archive.writestr("../escape.txt", "bad")

            result = import_app_data_bundle(bundle_path, target_dir)

            self.assertEqual(5, result.imported_files)
            self.assertTrue((target_dir / "courses" / "course-a" / "summary.md").exists())
            self.assertTrue((target_dir / "questions" / "q1.json").exists())
            self.assertTrue((target_dir / "quiz_snapshots" / "snapshot1.json").exists())
            self.assertTrue((target_dir / "mastery_overrides.json").exists())
            imported_settings = json.loads((target_dir / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual({"language": "en"}, imported_settings)
            self.assertFalse((Path(tmpdir) / "escape.txt").exists())
            self.assertIn("../escape.txt", result.skipped_files)
            self.assertIn("questions/.question_index.sqlite3", result.skipped_files)
            self.assertFalse((target_dir / "questions" / ".question_index.sqlite3").exists())

    def test_import_rejects_invalid_json_without_changing_target_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle_path = root / "bundle.quizdata"
            target_dir = root / "target"
            existing = target_dir / "questions" / "q1.json"
            existing.parent.mkdir(parents=True)
            existing.write_text('{"question_id": "original"}', encoding="utf-8")

            with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("questions/q1.json", '{"question_id": "replacement"}')
                archive.writestr("questions/q2.json", '{"question_id":')

            with self.assertRaisesRegex(ValueError, "questions/q2.json"):
                import_app_data_bundle(bundle_path, target_dir)

            self.assertEqual(
                {"question_id": "original"},
                json.loads(existing.read_text(encoding="utf-8")),
            )
            self.assertFalse((target_dir / "questions" / "q2.json").exists())

    def test_import_rejects_duplicate_allowed_members_without_writing_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle_path = root / "bundle.quizdata"
            target_dir = root / "target"

            with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("questions/q1.json", '{"question_id": "first"}')
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr("questions/q1.json", '{"question_id": "second"}')

            with self.assertRaisesRegex(ValueError, "Duplicate.*questions/q1.json"):
                import_app_data_bundle(bundle_path, target_dir)

            self.assertFalse((target_dir / "questions" / "q1.json").exists())

    def test_import_rolls_back_overwrites_and_new_files_when_commit_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle_path = root / "bundle.quizdata"
            target_dir = root / "target"
            existing = target_dir / "questions" / "q1.json"
            existing.parent.mkdir(parents=True)
            existing.write_text('{"question_id": "original"}', encoding="utf-8")

            with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("questions/q1.json", '{"question_id": "replacement"}')
                archive.writestr("questions/q2.json", '{"question_id": "new"}')

            real_replace = os.replace
            forward_replacements = 0

            def fail_second_forward_replace(source, destination):
                nonlocal forward_replacements
                if ".app-data-import-" in str(source):
                    forward_replacements += 1
                    if forward_replacements == 2:
                        raise OSError("disk full")
                return real_replace(source, destination)

            from core import app_data_bundle

            fake_os = SimpleNamespace(replace=fail_second_forward_replace)
            with patch.object(app_data_bundle, "os", fake_os, create=True):
                with self.assertRaisesRegex(OSError, "disk full"):
                    import_app_data_bundle(bundle_path, target_dir)

            self.assertEqual(
                {"question_id": "original"},
                json.loads(existing.read_text(encoding="utf-8")),
            )
            self.assertFalse((target_dir / "questions" / "q2.json").exists())


    def test_portable_settings_exclude_all_ai_trust_keys(self):
        """Export removes all four AI trust fields from settings.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            (data_dir / "questions").mkdir(parents=True)
            (data_dir / "questions" / "q1.json").write_text('{"question_id": "q1"}', encoding="utf-8")
            (data_dir / "settings.json").write_text(
                json.dumps({
                    "language": "zh",
                    "ai_api_key": "secret",
                    "ai_provider": "custom",
                    "ai_base_url": "https://attacker.example/v1",
                    "ai_model": "hostile-model",
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            bundle_path = export_app_data_bundle(data_dir, root / "bundle.quizdata")

            with zipfile.ZipFile(bundle_path) as archive:
                settings = json.loads(archive.read("settings.json").decode("utf-8"))
                self.assertEqual("zh", settings["language"])
                for key in LOCAL_ONLY_SETTING_KEYS:
                    self.assertNotIn(key, settings, f"{key} must not be exported")

    def test_import_preserves_existing_ai_trust_settings(self):
        """Import replaces language but keeps the local machine AI trust fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_dir = root / "data"
            (target_dir / "questions").mkdir(parents=True)
            (target_dir / "questions" / "q1.json").write_text('{"question_id": "q1"}', encoding="utf-8")
            existing_settings = {
                "language": "zh",
                "ai_provider": "anthropic",
                "ai_base_url": "https://api.anthropic.com/v1",
                "ai_model": "claude-sonnet-4-6",
            }
            (target_dir / "settings.json").write_text(
                json.dumps(existing_settings, ensure_ascii=False),
                encoding="utf-8",
            )

            bundle = root / "bundle.quizdata"
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("questions/q2.json", '{"question_id": "q2"}')
                archive.writestr(
                    "settings.json",
                    json.dumps({
                        "language": "en",
                        "ai_provider": "custom",
                        "ai_base_url": "https://attacker.example/v1",
                        "ai_model": "hostile-model",
                    }, ensure_ascii=False),
                )

            result = import_app_data_bundle(bundle, target_dir)

            imported_settings = json.loads((target_dir / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual("en", imported_settings["language"])
            self.assertEqual("anthropic", imported_settings["ai_provider"])
            self.assertEqual("https://api.anthropic.com/v1", imported_settings["ai_base_url"])
            self.assertEqual("claude-sonnet-4-6", imported_settings["ai_model"])
            self.assertNotIn("ai_api_key", imported_settings)
            self.assertIn("ai_provider", result.ignored_settings)
            self.assertIn("ai_base_url", result.ignored_settings)
            self.assertIn("ai_model", result.ignored_settings)

    def test_export_omits_ai_trust_keys_from_synthetic_settings(self):
        """A settings dict with all four keys strips every one at the portable layer."""
        from core.app_data_bundle import _portable_settings

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text(json.dumps({
                "language": "zh",
                "ai_api_key": "sk-test",
                "ai_provider": "local_agent",
                "ai_base_url": "http://127.0.0.1:8080/v1",
                "ai_model": "test-model",
            }, ensure_ascii=False), encoding="utf-8")
            portable = _portable_settings(settings_path)
            self.assertEqual("zh", portable["language"])
            for key in LOCAL_ONLY_SETTING_KEYS:
                self.assertNotIn(key, portable, f"{key} must not appear in portable settings")


    def test_import_skips_unsafe_bundle_artifact_extensions(self):
        """Executables, scripts, shortcuts, HTML, and extensionless payloads are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "data"
            (target / "questions").mkdir(parents=True)
            bundle = root / "bundle.quizdata"

            unsafe_members = [
                "courses/c-a/source/payload.exe",
                "courses/c-a/source/setup.msi",
                "courses/c-a/source/launch.bat",
                "courses/c-a/source/run.cmd",
                "courses/c-a/source/script.ps1",
                "courses/c-a/source/shortcut.lnk",
                "courses/c-a/source/page.url",
                "courses/c-a/source/page.html",
                "courses/c-a/source/page.htm",
                "courses/c-a/source/malware.com",
                "courses/c-a/source/noextension",
                "questions/q-bad.js",
                "progress/p-bad.py",
            ]
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("courses/c-a/source/notes.pdf", "%PDF-1.4 fake")
                archive.writestr("courses/c-a/source/notes.txt", "safe text")
                archive.writestr("questions/q1.json", '{"question_id": "q1"}')
                for name in unsafe_members:
                    archive.writestr(name, b"unsafe")

            result = import_app_data_bundle(bundle, target)

            self.assertTrue((target / "courses" / "c-a" / "source" / "notes.pdf").exists())
            self.assertTrue((target / "courses" / "c-a" / "source" / "notes.txt").exists())
            self.assertTrue((target / "questions" / "q1.json").exists())
            for name in unsafe_members:
                self.assertIn(name, result.skipped_files, f"{name} must be skipped")
                self.assertFalse(
                    (target / name).exists(),
                    f"{name} must not exist on disk",
                )

    def test_import_allows_known_safe_data_bundle_suffixes(self):
        """All standard data files with safe suffixes pass validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "data"
            bundle = root / "bundle.quizdata"

            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("courses/c-a/source/slides.pdf", "%PDF safe")
                archive.writestr("courses/c-a/source/notes.txt", "safe text")
                archive.writestr("courses/c-a/source/lecture.md", "# safe")
                archive.writestr("courses/c-a/source/slides.pptx", "PK fake pptx")
                archive.writestr("courses/c-a/source/paper.docx", "PK fake docx")
                archive.writestr("past_exams/e-a/source/exam.pdf", "%PDF safe")
                archive.writestr("past_exams/e-a/source/exam.txt", "safe text")
                archive.writestr("questions/q1.json", '{"q": 1}')
                archive.writestr("question_sets/s1.json", '{"s": 1}')
                archive.writestr("quiz_snapshots/snap.json", '{"s": 1}')
                archive.writestr("progress/p1.json", '{"p": 1}')
                archive.writestr("current_event_materials/m1.json", '{"m": 1}')
                archive.writestr("mastery_overrides.json", '{"overrides": {}}')
                archive.writestr("current_course.json", '{"course_id": "c-a"}')
                archive.writestr("settings.json", '{"language": "zh"}')

            result = import_app_data_bundle(bundle, target)
            self.assertEqual(15, result.imported_files)
            self.assertEqual([], result.skipped_files)


if __name__ == "__main__":
    unittest.main()
