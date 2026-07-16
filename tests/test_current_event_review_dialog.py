import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog

from core.current_events import (
    CurrentEventCandidate,
    CurrentEventMaterialManager,
    build_course_event_query,
)
from tests.test_current_events import law_project
from ui.dialogs.current_event_review_dialog import CurrentEventReviewDialog


_APP = QApplication.instance() or QApplication([])


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def search(self, query, *, hours, limit):
        self.calls.append((query, hours, limit))
        return []


def candidates(project):
    query = build_course_event_query(project)
    return [
        CurrentEventCandidate.create(
            url="https://law.example/rule",
            title="Agency rule faces judicial review",
            context="A court reviews a regulation adopted through agency rulemaking.",
            seen_at="2026-07-15T05:00:00+00:00",
            domain="law.example",
            language="ENGLISH",
            query=query,
            retrieved_at="2026-07-15T06:00:00+00:00",
        ),
        CurrentEventCandidate.create(
            url="https://weather.example/storm",
            title="Coastal storm update",
            context="Emergency crews issued a weather advisory for residents.",
            seen_at="2026-07-15T04:00:00+00:00",
            domain="weather.example",
            language="ENGLISH",
            query=query,
            retrieved_at="2026-07-15T06:00:00+00:00",
        ),
    ]


class CurrentEventReviewDialogTests(unittest.TestCase):
    def test_opening_dialog_does_not_search_or_accept_candidates(self):
        provider = RecordingProvider()
        project = law_project()

        with tempfile.TemporaryDirectory() as tmpdir:
            dialog = CurrentEventReviewDialog(
                project,
                provider=provider,
                material_manager=CurrentEventMaterialManager(tmpdir),
            )

            self.assertEqual([], provider.calls)
            self.assertIn("Administrative Law", dialog.query_input.text())
            self.assertEqual(0, dialog.candidate_list.topLevelItemCount())
            self.assertFalse(dialog.save_btn.isEnabled())
            self.assertFalse(dialog.save_generate_btn.isEnabled())

    def test_review_shows_low_relevance_and_source_timestamps(self):
        project = law_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            dialog = CurrentEventReviewDialog(
                project,
                provider=RecordingProvider(),
                material_manager=CurrentEventMaterialManager(tmpdir),
            )

            dialog._show_candidates(candidates(project))

            self.assertEqual(2, dialog.candidate_list.topLevelItemCount())
            relevant = dialog.candidate_list.topLevelItem(0)
            low = dialog.candidate_list.topLevelItem(1)
            self.assertEqual(Qt.CheckState.Unchecked, relevant.checkState(0))
            self.assertIn("低相关", low.text(1))
            dialog.candidate_list.setCurrentItem(low)
            self.assertIn("weather.example", dialog.detail_view.toPlainText())
            self.assertIn("2026-07-15T04:00:00+00:00", dialog.detail_view.toPlainText())
            self.assertIn("2026-07-15T06:00:00+00:00", dialog.detail_view.toPlainText())

    def test_user_selection_can_be_saved_and_forwarded_to_generation(self):
        project = law_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CurrentEventMaterialManager(tmpdir)
            dialog = CurrentEventReviewDialog(
                project,
                provider=RecordingProvider(),
                material_manager=manager,
            )
            dialog._show_candidates(candidates(project))
            selected = dialog.candidate_list.topLevelItem(0)
            selected.setCheckState(0, Qt.CheckState.Checked)

            self.assertTrue(dialog.save_generate_btn.isEnabled())
            dialog.save_generate_btn.click()

            self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
            self.assertTrue(dialog.generate_after_save)
            self.assertIsNotNone(dialog.saved_pack)
            self.assertEqual(
                dialog.saved_pack,
                manager.get(dialog.saved_pack.pack_id),
            )
            self.assertEqual(
                (selected.data(0, dialog.CANDIDATE_ID_ROLE),),
                dialog.saved_pack.selected_candidate_ids,
            )


if __name__ == "__main__":
    unittest.main()
