import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.source_navigation import resolve_source_location
from models.course_project import CourseProject
from ui.widgets.source_refs_panel import SourceRefsPanel


_APP = QApplication.instance() or QApplication([])


def _project(documents: list[dict], root: Path) -> CourseProject:
    return CourseProject(
        course_id="course-source",
        title="Systems",
        source_folder=str(root),
        summary_markdown="",
        summary_path="",
        topics=[],
        documents=documents,
        created_at="2026-07-12T00:00:00+00:00",
        updated_at="2026-07-12T00:00:00+00:00",
    )


class SourceNavigationTests(unittest.TestCase):
    def test_resolve_source_location_only_uses_registered_course_documents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            registered = root / "lecture.pdf"
            registered.write_bytes(b"pdf")
            project = _project([{"path": str(registered)}], root)

            location = resolve_source_location(
                project,
                {"source_file": "lecture.pdf", "page_or_slide": 12},
            )
            rejected = resolve_source_location(
                project,
                {"source_file": str(root / ".." / "secret.txt")},
            )

            self.assertEqual(registered.resolve(), location.path)
            self.assertEqual(12, location.page_or_slide)
            self.assertTrue(location.exists)
            self.assertIsNone(rejected)

    def test_resolve_source_location_rejects_ambiguous_basenames(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = _project([
                {"path": str(root / "week1" / "slides.pdf")},
                {"path": str(root / "week2" / "slides.pdf")},
            ], root)

            self.assertIsNone(resolve_source_location(
                project, {"source_file": "slides.pdf", "page_or_slide": 3}
            ))

    def test_source_panel_copies_registered_path_and_page_location(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "IO Devices.pdf"
            source.write_bytes(b"pdf")
            project = _project([{"path": str(source)}], root)
            panel = SourceRefsPanel()
            panel.set_source_refs(
                [{"source_file": source.name, "page_or_slide": 8, "heading": "DMA"}],
                course_project=project,
                language="zh",
            )
            panel.source_list.setCurrentRow(0)

            panel.copy_selected_location()

            copied = QApplication.clipboard().text()
            self.assertIn(str(source.resolve()), copied)
            self.assertIn("页码/幻灯片 8", copied)
            self.assertTrue(panel.open_btn.isEnabled())
            self.assertTrue(panel.copy_btn.isEnabled())

    def test_source_panel_disables_actions_for_unresolved_reference(self):
        panel = SourceRefsPanel()
        panel.set_source_refs(
            [{"source_file": "unknown.pdf", "page_or_slide": 4}],
            course_project=None,
            language="zh",
        )
        panel.source_list.setCurrentRow(0)

        self.assertFalse(panel.open_btn.isEnabled())
        self.assertFalse(panel.copy_btn.isEnabled())
        self.assertTrue(panel.details_btn.isEnabled())

    def test_source_panel_shows_selected_excerpt_inline(self):
        panel = SourceRefsPanel()
        panel.set_source_refs([
            {
                "source_file": "lecture.pdf",
                "page_or_slide": 4,
                "heading": "Interrupts",
                "excerpt": "设备完成操作后通过中断通知 CPU。",
            },
            {
                "source_file": "lecture.pdf",
                "page_or_slide": 5,
                "heading": "DMA",
                "excerpt": "DMA 在设备与内存之间直接传输数据。",
            },
        ], language="zh")

        self.assertFalse(panel.excerpt_label.isHidden())
        self.assertIn("设备完成操作后", panel.excerpt_label.text())

        panel.source_list.setCurrentRow(1)

        self.assertIn("DMA", panel.excerpt_label.text())
        self.assertIn("直接传输数据", panel.excerpt_label.text())

    def test_source_panel_opens_pdf_with_page_fragment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "lecture.pdf"
            source.write_bytes(b"pdf")
            panel = SourceRefsPanel()
            panel.set_source_refs(
                [{"source_file": source.name, "page_or_slide": 9}],
                course_project=_project([{"path": str(source)}], root),
                language="en",
            )
            panel.source_list.setCurrentRow(0)

            with patch(
                "ui.widgets.source_refs_panel.QDesktopServices.openUrl",
                return_value=True,
            ) as open_url:
                panel.open_selected_source()

            url = open_url.call_args.args[0]
            self.assertTrue(url.isLocalFile())
            self.assertEqual("page=9", url.fragment())

    def test_source_panel_opens_and_copies_revalidated_public_event_url(self):
        panel = SourceRefsPanel()
        panel.set_source_refs([{
            "source_kind": "current_event",
            "candidate_id": "event-123",
            "url": "https://law.example/rule?utm_source=test",
            "title": "Agency rule faces review",
            "domain": "law.example",
            "seen_at": "2026-07-15T05:00:00+00:00",
            "retrieved_at": "2026-07-15T06:00:00+00:00",
            "matched_topic_ids": ["administrative_law"],
            "excerpt": "A court reviews an agency regulation.",
        }], language="zh")
        panel.source_list.setCurrentRow(0)

        self.assertTrue(panel.open_btn.isEnabled())
        self.assertTrue(panel.copy_btn.isEnabled())
        self.assertIn("Agency rule faces review", panel.source_list.currentItem().text())

        panel.copy_selected_location()
        self.assertEqual("https://law.example/rule", QApplication.clipboard().text())

        with patch(
            "ui.widgets.source_refs_panel.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            panel.open_selected_source()

        self.assertEqual("https://law.example/rule", open_url.call_args.args[0].toString())

    def test_source_panel_rejects_tampered_private_event_url_before_open(self):
        panel = SourceRefsPanel()
        panel.set_source_refs([{
            "source_kind": "current_event",
            "candidate_id": "event-123",
            "url": "http://127.0.0.1/private",
            "title": "Tampered source",
        }], language="zh")
        panel.source_list.setCurrentRow(0)

        self.assertFalse(panel.open_btn.isEnabled())
        self.assertFalse(panel.copy_btn.isEnabled())
        with patch(
            "ui.widgets.source_refs_panel.QDesktopServices.openUrl",
        ) as open_url:
            panel.open_selected_source()
        open_url.assert_not_called()


    def test_source_navigation_rejects_unsafe_extensions(self):
        """Registered files with unsafe extensions cannot be resolved or opened."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unsafe = [
                root / "launcher.exe",
                root / "script.bat",
                root / "run.cmd",
                root / "evil.ps1",
                root / "link.lnk",
                root / "site.url",
                root / "page.html",
                root / "page.htm",
                root / "malware.com",
                root / "noextension",
            ]
            for path in unsafe:
                path.write_bytes(b"unsafe")
            project = _project([{"path": str(p)} for p in unsafe], root)

            for path in unsafe:
                location = resolve_source_location(
                    project, {"source_file": path.name}
                )
                self.assertIsNone(
                    location,
                    f"resolve_source_location must reject {path.name}",
                )

    def test_source_panel_disables_open_for_unsafe_extension(self):
        """Open button stays disabled when resolved source has unsafe extension."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = root / "payload.exe"
            payload.write_bytes(b"unsafe")
            project = _project([{"path": str(payload)}], root)
            panel = SourceRefsPanel()
            panel.set_source_refs(
                [{"source_file": payload.name}],
                course_project=project,
                language="zh",
            )
            panel.source_list.setCurrentRow(0)

            self.assertFalse(panel.open_btn.isEnabled())


    def test_source_navigation_rejects_unc_and_device_paths(self):
        """UNC, device, and URI paths are rejected before any filesystem call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = _project([
                {"path": r"\\server\share\slides.pdf"},
                {"path": r"\\?\C:\device.pdf"},
                {"path": r"\\.\COM1"},
                {"path": "https://example.com/doc.pdf"},
            ], root)

            for ref in [
                {"source_file": r"\\server\share\slides.pdf"},
                {"source_file": r"\\?\C:\device.pdf"},
                {"source_file": r"\\.\COM1"},
                {"source_file": "https://example.com/doc.pdf"},
            ]:
                self.assertIsNone(
                    resolve_source_location(project, ref),
                    f"must reject remote/device source: {ref}",
                )


if __name__ == "__main__":
    unittest.main()
