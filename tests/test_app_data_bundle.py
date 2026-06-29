import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.app_data_bundle import export_app_data_bundle, import_app_data_bundle


class AppDataBundleTests(unittest.TestCase):
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

                settings = json.loads(archive.read("settings.json").decode("utf-8"))
                self.assertEqual("zh", settings["language"])
                self.assertEqual("model", settings["ai_model"])
                self.assertNotIn("ai_api_key", settings)

    def test_import_bundle_restores_whitelisted_paths_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = Path(tmpdir) / "bundle.quizdata"
            target_dir = Path(tmpdir) / "target"

            with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", '{"format": "quiz_app_data_bundle", "version": 1}')
                archive.writestr("courses/course-a/summary.md", "# 课程总结")
                archive.writestr("questions/q1.json", '{"question_id": "q1"}')
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


if __name__ == "__main__":
    unittest.main()
