import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_windows_portable import package_windows_portable


class WindowsPortablePackageTests(unittest.TestCase):
    def test_cli_builds_a_legal_portable_zip_with_an_empty_data_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = root / "project"
            dist = root / "dist"
            package = dist / "AI课程刷题软件"
            internal = package / "_internal"
            internal.mkdir(parents=True)
            (package / "AI课程刷题软件.exe").write_bytes(b"portable-exe")
            (internal / "style.qss").write_text("QWidget {}", encoding="utf-8")
            for name in ("LICENSE", "COPYRIGHT.md", "THIRD_PARTY_NOTICES.md"):
                project.mkdir(parents=True, exist_ok=True)
                (project / name).write_text(f"{name}\n", encoding="utf-8")

            archive, checksum = package_windows_portable(
                project_root=project,
                dist_root=dist,
                version="1.0.0",
            )

            self.assertEqual(
                (dist / "AI-Course-Quiz-1.0.0-Windows-x64.zip").resolve(),
                archive,
            )
            self.assertTrue(archive.is_file())
            self.assertTrue(checksum.is_file())
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                self.assertIn("AI课程刷题软件/AI课程刷题软件.exe", names)
                self.assertIn("AI课程刷题软件/_internal/style.qss", names)
                self.assertIn("AI课程刷题软件/LICENSE", names)
                self.assertIn("AI课程刷题软件/COPYRIGHT.md", names)
                self.assertIn("AI课程刷题软件/THIRD_PARTY_NOTICES.md", names)
                self.assertIn("AI课程刷题软件/data/", names)

            expected_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(
                f"{expected_hash}  {archive.name}",
                checksum.read_text(encoding="ascii").strip(),
            )

    def test_cli_refuses_to_archive_existing_user_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = root / "project"
            dist = root / "dist"
            package = dist / "AI课程刷题软件"
            data_dir = package / "data"
            data_dir.mkdir(parents=True)
            (package / "AI课程刷题软件.exe").write_bytes(b"portable-exe")
            (data_dir / "settings.json").write_text(
                '{"ai_api_key": "must-not-ship"}',
                encoding="utf-8",
            )
            for name in ("LICENSE", "COPYRIGHT.md", "THIRD_PARTY_NOTICES.md"):
                project.mkdir(parents=True, exist_ok=True)
                (project / name).write_text(f"{name}\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "portable data directory is not empty",
            ):
                package_windows_portable(
                    project_root=project,
                    dist_root=dist,
                    version="1.0.0",
                )
            self.assertFalse(
                (dist / "AI-Course-Quiz-1.0.0-Windows-x64.zip").exists()
            )

    def test_cli_rejects_version_text_that_is_unsafe_for_a_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = root / "project"
            dist = root / "dist"
            package = dist / "AI课程刷题软件"
            package.mkdir(parents=True)
            (package / "AI课程刷题软件.exe").write_bytes(b"portable-exe")
            for name in ("LICENSE", "COPYRIGHT.md", "THIRD_PARTY_NOTICES.md"):
                project.mkdir(parents=True, exist_ok=True)
                (project / name).write_text(f"{name}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid package version"):
                package_windows_portable(
                    project_root=project,
                    dist_root=dist,
                    version="1.0/preview",
                )


if __name__ == "__main__":
    unittest.main()
