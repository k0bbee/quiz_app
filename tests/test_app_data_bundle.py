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
    canonical_bundle_target,
    export_app_data_bundle,
    import_app_data_bundle,
    LOCAL_ONLY_SETTING_KEYS,
)
from core.background_task import BackgroundTaskCancelled, TaskControl
from core.input_limits import InputLimitError
from core.progress_tracker import ProgressManager
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.progress import AnswerRecord, ProgressRecord, QuestionReviewSnapshot
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from utils.constants import Difficulty, QuestionType


class AppDataBundleTests(unittest.TestCase):
    def test_import_backfills_legacy_completed_history_from_bundle_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            course_manager = CourseProjectManager(
                source / "courses",
                current_course_file=source / "current_course.json",
            )
            question_bank = QuestionBank(str(source / "questions"))
            set_manager = SetManager(str(source / "question_sets"))
            progress_manager = ProgressManager(str(source / "progress"))
            course = CourseProject(
                course_id="course-os",
                title="操作系统",
                source_folder="",
                summary_markdown="# 操作系统",
                summary_path="",
                topics=[CourseTopic("input-output", "输入输出")],
                documents=[],
                created_at="2026-07-01T00:00:00+00:00",
                updated_at="2026-07-01T00:00:00+00:00",
            )
            self.assertTrue(course_manager.save(course))
            question = Question(
                question_id="q-io",
                type=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "设备如何通知 CPU？",
                        "options": ["A. 中断", "B. 轮询"],
                        "explanation": "设备发出中断。",
                    },
                    "en": {
                        "stem": "How does a device notify the CPU?",
                        "options": ["A. Interrupt", "B. Polling"],
                        "explanation": "The device raises an interrupt.",
                    },
                },
                correct_answer="A",
                topic="input-output",
                metadata={
                    "course_id": course.course_id,
                    "course_title": course.title,
                },
            )
            self.assertTrue(question_bank.save(question))
            question_set = QuestionSet.create_new(
                title={"zh": "I/O 专项", "en": "I/O Practice"},
                description={"zh": "", "en": ""},
                topics=["input-output"],
                question_ids=[question.question_id],
            )
            question_set.metadata.update({
                "course_id": course.course_id,
                "course_title": course.title,
            })
            self.assertTrue(set_manager.save(question_set))
            record = ProgressRecord(
                progress_id="progress-legacy",
                set_id=question_set.set_id,
                language="zh",
                started_at="2026-07-01T00:00:00+00:00",
                completed_at="2026-07-01T00:10:00+00:00",
                status="completed",
                answers=[AnswerRecord(question.question_id, 0, "A", True)],
                archive_status="legacy",
            )
            self.assertTrue(progress_manager.save(record))

            bundle = export_app_data_bundle(source, root / "legacy.quizdata")
            target = root / "target"
            result = import_app_data_bundle(bundle, target)

            loaded = ProgressManager(str(target / "progress")).get(record.progress_id)
            self.assertEqual("complete", loaded.archive_status)
            self.assertEqual(1, loaded.archive_schema_version)
            self.assertEqual("设备如何通知 CPU？", loaded.question_snapshots[0].stem)
            self.assertEqual(course.title, loaded.course_title_snapshot)
            self.assertEqual(1, result.migrated_archives)
            self.assertEqual(0, result.incomplete_archives)
            self.assertEqual([], result.archive_errors)

    def test_bundle_round_trip_preserves_quiz_review_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            manager = ProgressManager(str(source / "progress"))
            record = ProgressRecord.create_new("set-deleted")
            record.set_title_snapshot = "I/O 专项"
            record.course_title_snapshot = "操作系统"
            record.question_snapshots = [
                QuestionReviewSnapshot(
                    question_id="q-io",
                    question_type="multiple_choice",
                    topic_id="input-output",
                    topic_title="输入输出",
                    stem="哪种方式由设备主动通知 CPU？",
                    options=["A. 轮询", "B. 中断"],
                    correct_answer="B",
                    explanation="设备通过中断通知 CPU。",
                    source_refs=[{"source_file": "lecture.pdf", "page_or_slide": 8}],
                )
            ]
            manager.save(record)

            bundle = export_app_data_bundle(source, root / "history.quizdata")
            target = root / "target"
            import_app_data_bundle(bundle, target)
            loaded = ProgressManager(str(target / "progress")).get(record.progress_id)

            self.assertIsNotNone(loaded)
            self.assertEqual("I/O 专项", loaded.set_title_snapshot)
            self.assertEqual("操作系统", loaded.course_title_snapshot)
            self.assertEqual("哪种方式由设备主动通知 CPU？", loaded.question_snapshots[0].stem)
            self.assertEqual("lecture.pdf", loaded.question_snapshots[0].source_refs[0]["source_file"])

    def test_bundle_targets_reject_nonportable_windows_segments(self):
        invalid = (
            "courses/report.txt:payload.txt",
            "courses/NUL.txt",
            "courses/alias. /file.txt",
            "courses/trailing./file.txt",
        )

        for name in invalid:
            with self.subTest(name=name):
                self.assertIsNone(canonical_bundle_target(name))

    def test_oversized_archive_is_rejected_before_zip_open(self):
        from core.input_limits import MAX_BUNDLE_ARCHIVE_BYTES

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = root / "oversized.quizdata"
            bundle.write_bytes(b"not opened")
            real_stat = Path.stat

            def stat_with_oversized_bundle(path, *args, **kwargs):
                if Path(path) == bundle:
                    actual = real_stat(path, *args, **kwargs)
                    values = list(actual)
                    values[6] = MAX_BUNDLE_ARCHIVE_BYTES + 1
                    return os.stat_result(values)
                return real_stat(path, *args, **kwargs)

            with (
                patch.object(
                    Path,
                    "stat",
                    autospec=True,
                    side_effect=stat_with_oversized_bundle,
                ),
                patch("core.app_data_bundle.zipfile.ZipFile") as zip_file,
            ):
                with self.assertRaises(InputLimitError) as context:
                    import_app_data_bundle(bundle, root / "data")

            zip_file.assert_not_called()
            self.assertEqual("DATA-IMPORT-002", context.exception.code)

    def test_manifest_must_be_a_json_object(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = root / "invalid-manifest.quizdata"
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", "[]")

            with self.assertRaisesRegex(ValueError, "manifest"):
                import_app_data_bundle(bundle, root / "data")

    def test_manifest_is_read_with_a_dedicated_small_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = root / "large-manifest.quizdata"
            manifest = {
                "format": "quiz_app_data_bundle",
                "version": 1,
                "padding": "x" * 4096,
            }
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))

            with patch("core.input_limits.MAX_BUNDLE_MANIFEST_BYTES", 128):
                with self.assertRaises(InputLimitError) as context:
                    import_app_data_bundle(bundle, root / "data")

            self.assertEqual("DATA-IMPORT-006", context.exception.code)

    def test_export_uses_the_same_member_allowlist_as_import(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            source_dir = data_dir / "courses" / "course-a" / "source"
            source_dir.mkdir(parents=True)
            (source_dir / "notes.txt").write_text("safe", encoding="utf-8")
            (source_dir / "payload.exe").write_bytes(b"unsafe")
            bundle = root / "export.quizdata"

            export_app_data_bundle(data_dir, bundle)

            with zipfile.ZipFile(bundle) as archive:
                names = archive.namelist()
            self.assertIn("courses/course-a/source/notes.txt", names)
            self.assertNotIn("courses/course-a/source/payload.exe", names)

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
                archive.writestr("questions/q1.json", '{"q": 1}')
                archive.writestr("question_sets/s1.json", '{"s": 1}')
                archive.writestr("quiz_snapshots/snap.json", '{"s": 1}')
                archive.writestr("progress/p1.json", '{"p": 1}')
                archive.writestr("mastery_overrides.json", '{"overrides": {}}')
                archive.writestr("current_course.json", '{"course_id": "c-a"}')
                archive.writestr("settings.json", '{"language": "zh"}')

            result = import_app_data_bundle(bundle, target)
            self.assertEqual(12, result.imported_files)
            self.assertEqual([], result.skipped_files)


    def test_normal_bundle_imports_without_compression_ratio_rejection(self):
        """Compression ratio is advisory; legitimate data round-trips."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            (data_dir / "questions").mkdir(parents=True)
            (data_dir / "questions" / "q1.json").write_text(
                json.dumps({"key": "A" * 10000}), encoding="utf-8"
            )
            bundle = root / "roundtrip.quizdata"
            export_app_data_bundle(data_dir, bundle)

            target = root / "target"
            result = import_app_data_bundle(bundle, target)
            self.assertGreater(result.imported_files, 0)
            self.assertTrue((target / "questions" / "q1.json").exists())

    def test_import_rejects_more_members_than_budget(self):
        """Budget check happens before reading any payload."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "data"
            from core.input_limits import MAX_BUNDLE_MEMBERS

            # Build a valid bundle and patch infolist to simulate too many members.
            bundle = root / "bomb.quizdata"
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("questions/q1.json", "{}")

            original_infolist = zipfile.ZipFile.infolist

            def fake_infolist(zf_self):
                real = list(original_infolist(zf_self))
                for i in range(MAX_BUNDLE_MEMBERS + 1):
                    info = zipfile.ZipInfo(f"questions/q{i:05d}.json")
                    info.file_size = 10
                    real.append(info)
                return real

            with patch.object(zipfile.ZipFile, "infolist", fake_infolist):
                with self.assertRaisesRegex(ValueError, "DATA-IMPORT-003"):
                    import_app_data_bundle(bundle, target)


    def test_import_rejects_case_insensitive_duplicate_members(self):
        """questions/q1.json and questions/Q1.json collide on Windows FS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = root / "dupe.quizdata"
            target = root / "data"

            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("questions/q1.json", '{"a": 1}')
                archive.writestr("questions/Q1.json", '{"a": 2}')

            with self.assertRaisesRegex(ValueError, "Duplicate"):
                import_app_data_bundle(bundle, target)

    def test_import_rejects_double_slash_and_backslash_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "data"
            bundle = root / "paths.quizdata"

            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("questions//q1.json", "{}")

            result = import_app_data_bundle(bundle, target)
            self.assertIn("questions//q1.json", result.skipped_files)


if __name__ == "__main__":
    unittest.main()
