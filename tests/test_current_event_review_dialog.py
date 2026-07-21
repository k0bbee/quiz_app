import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog

from core.current_events import (
    CurrentEventCandidate,
    CurrentEventMaterialManager,
    build_course_event_query,
)
from tests.test_current_events import law_project
from ui.dialogs.current_event_review_dialog import (
    CurrentEventReviewDialog,
    CurrentEventSearchWorker,
)


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
    def test_interrupted_worker_drops_success_result(self):
        provider = RecordingProvider()
        worker = CurrentEventSearchWorker(provider, "law", 24, 10)
        succeeded = []
        failed = []
        worker.succeeded.connect(succeeded.append)
        worker.failed.connect(failed.append)

        with patch.object(worker, "isInterruptionRequested", return_value=True):
            worker.run()

        self.assertEqual([("law", 24, 10)], provider.calls)
        self.assertEqual([], succeeded)
        self.assertEqual([], failed)

    def test_reject_requests_search_cancellation_and_waits_without_blocking(self):
        project = law_project()
        worker = Mock()
        worker.isRunning.return_value = True
        with tempfile.TemporaryDirectory() as tmpdir:
            dialog = CurrentEventReviewDialog(
                project,
                provider=RecordingProvider(),
                material_manager=CurrentEventMaterialManager(tmpdir),
            )
            dialog.search_worker = worker

            with patch.object(QDialog, "reject") as base_reject:
                dialog.reject()

                worker.requestInterruption.assert_called_once_with()
                base_reject.assert_not_called()
                self.assertIn("取消", dialog.status_label.text())

                dialog._finish_search(worker)

                base_reject.assert_called_once_with()

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

    def test_search_busy_state_locks_candidate_selection_and_save_actions(self):
        project = law_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            dialog = CurrentEventReviewDialog(
                project,
                provider=RecordingProvider(),
                material_manager=CurrentEventMaterialManager(tmpdir),
            )
            dialog._show_candidates(candidates(project))
            dialog.candidate_list.topLevelItem(0).setCheckState(
                0, Qt.CheckState.Checked
            )
            self.assertTrue(dialog.save_generate_btn.isEnabled())

            dialog._set_busy(True)

            self.assertFalse(dialog.candidate_list.isEnabled())
            self.assertFalse(dialog.save_btn.isEnabled())
            self.assertFalse(dialog.save_generate_btn.isEnabled())

            dialog._set_busy(False)

            self.assertTrue(dialog.candidate_list.isEnabled())
            self.assertTrue(dialog.save_generate_btn.isEnabled())

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
