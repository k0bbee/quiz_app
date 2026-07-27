import unittest
from copy import deepcopy
from types import SimpleNamespace

from core.course_asset_lifecycle import (
    CourseRemovalMode,
    analyze_course_asset_impact,
    remove_course_assets,
)
from models.past_exam import PastExamRecord


class _Manager:
    def __init__(self, items):
        self._items = items

    def load_all(self):
        return list(self._items)


class _StoreManager:
    def __init__(self, items, id_field):
        self.id_field = id_field
        self.items = {
            getattr(item, id_field): deepcopy(item)
            for item in items
        }

    def load_all(self):
        return [deepcopy(item) for item in self.items.values()]

    def get(self, item_id):
        item = self.items.get(item_id)
        return deepcopy(item) if item is not None else None

    def save(self, item, **_kwargs):
        self.items[getattr(item, self.id_field)] = deepcopy(item)
        return True

    def delete(self, item_id):
        return self.items.pop(item_id, None) is not None


class _CourseManager(_StoreManager):
    def __init__(self, courses, current_id=""):
        super().__init__(courses, "course_id")
        self.current_id = current_id

    def current(self):
        return self.get(self.current_id)

    def save(self, item, make_current=True):
        saved = super().save(item)
        if make_current:
            self.current_id = item.course_id
        return saved

    def delete(self, item_id):
        deleted = super().delete(item_id)
        if self.current_id == item_id:
            self.current_id = ""
        return deleted


class _PastExamManager(_StoreManager):
    def __init__(self, items):
        super().__init__(items, "exam_id")

    def save_record(self, item):
        return self.save(item)


class _CurrentEventManager(_StoreManager):
    def __init__(self, items):
        super().__init__(items, "pack_id")


class CourseAssetLifecycleTests(unittest.TestCase):
    def test_impact_uses_historical_course_identity_after_question_set_is_gone(self):
        progress = _Manager([
            SimpleNamespace(
                progress_id="progress-completed",
                set_id="set-deleted",
                status="completed",
                course_id_snapshot="course-a",
            ),
            SimpleNamespace(
                progress_id="progress-draft",
                set_id="set-deleted",
                status="abandoned",
                course_id_snapshot="course-a",
            ),
            SimpleNamespace(
                progress_id="progress-other",
                set_id="set-deleted",
                status="completed",
                course_id_snapshot="course-b",
            ),
        ])

        impact = analyze_course_asset_impact(
            "course-a",
            progress_manager=progress,
        )

        self.assertEqual(("progress-completed",), impact.progress_ids)
        self.assertEqual(("progress-draft",), impact.draft_progress_ids)
        self.assertEqual(1, impact.progress_count)
        self.assertEqual(1, impact.draft_progress_count)

    def test_course_removal_cancels_drafts_but_preserves_completed_history(self):
        managers = self._lifecycle_managers()
        managers["progress_manager"].save(
            SimpleNamespace(
                progress_id="progress-draft",
                set_id="set-direct",
                status="abandoned",
            )
        )

        result = remove_course_assets(
            "course-a",
            CourseRemovalMode.UNLINK_ASSETS,
            **managers,
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            {"progress-direct", "progress-mixed"},
            set(managers["progress_manager"].items),
        )
        self.assertEqual({}, managers["snapshot_manager"].items)

    def test_impact_follows_direct_course_links_and_indirect_set_references(self):
        questions = _Manager([
            SimpleNamespace(question_id="q-course-1", metadata={"course_id": "course-a"}),
            SimpleNamespace(question_id="q-course-2", metadata={"course_id": "course-a"}),
            SimpleNamespace(question_id="q-other", metadata={"course_id": "course-b"}),
        ])
        sets = _Manager([
            SimpleNamespace(
                set_id="set-direct",
                questions=["q-course-1", "q-other"],
                metadata={"course_id": "course-a"},
            ),
            SimpleNamespace(
                set_id="set-mixed",
                questions=["q-course-2", "q-other"],
                metadata={},
            ),
            SimpleNamespace(
                set_id="set-other",
                questions=["q-other"],
                metadata={"course_id": "course-b"},
            ),
        ])
        progress = _Manager([
            SimpleNamespace(progress_id="progress-direct", set_id="set-direct"),
            SimpleNamespace(progress_id="progress-mixed", set_id="set-mixed"),
            SimpleNamespace(progress_id="progress-other", set_id="set-other"),
        ])
        snapshots = _Manager([
            SimpleNamespace(snapshot_id="snapshot-direct", set_id="set-direct"),
            SimpleNamespace(snapshot_id="snapshot-mixed", set_id="set-mixed"),
            SimpleNamespace(snapshot_id="snapshot-other", set_id="set-other"),
        ])
        past_exams = _Manager([
            SimpleNamespace(exam_id="exam-course", course_id="course-a"),
            SimpleNamespace(exam_id="exam-other", course_id="course-b"),
        ])
        current_events = _Manager([
            SimpleNamespace(pack_id="pack-course", course_id="course-a"),
            SimpleNamespace(pack_id="pack-other", course_id="course-b"),
        ])

        impact = analyze_course_asset_impact(
            "course-a",
            questions,
            sets,
            progress,
            snapshots,
            past_exams,
            current_events,
        )

        self.assertEqual(("q-course-1", "q-course-2"), impact.question_ids)
        self.assertEqual(("set-direct",), impact.direct_set_ids)
        self.assertEqual(("set-direct", "set-mixed"), impact.affected_set_ids)
        self.assertEqual(("progress-direct", "progress-mixed"), impact.progress_ids)
        self.assertEqual(("snapshot-direct", "snapshot-mixed"), impact.snapshot_ids)
        self.assertEqual(("exam-course",), impact.past_exam_ids)
        self.assertEqual(("pack-course",), impact.current_event_pack_ids)
        self.assertEqual(2, impact.question_count)
        self.assertEqual(2, impact.question_set_count)
        self.assertEqual(2, impact.progress_count)
        self.assertEqual(2, impact.snapshot_count)
        self.assertEqual(1, impact.past_exam_count)
        self.assertEqual(1, impact.current_event_pack_count)

    def test_impact_supports_missing_optional_managers(self):
        impact = analyze_course_asset_impact("course-a", None, None, None, None)

        self.assertEqual(0, impact.question_count)
        self.assertEqual(0, impact.question_set_count)
        self.assertEqual(0, impact.progress_count)
        self.assertEqual(0, impact.snapshot_count)

    def test_unlink_mode_preserves_completed_assets_and_cancels_drafts(self):
        managers = self._lifecycle_managers()

        result = remove_course_assets(
            "course-a",
            CourseRemovalMode.UNLINK_ASSETS,
            **managers,
        )

        self.assertTrue(result.success, result.error)
        self.assertIsNone(managers["course_manager"].get("course-a"))
        question = managers["question_bank"].get("q-course")
        self.assertIsNotNone(question)
        self.assertNotIn("course_id", question.metadata)
        self.assertNotIn("source_refs", question.metadata)
        self.assertEqual("cache", question.metadata["topic_title"])
        direct_set = managers["set_manager"].get("set-direct")
        self.assertEqual(["q-course", "q-other"], direct_set.questions)
        self.assertNotIn("course_id", direct_set.metadata)
        exam = managers["past_exam_manager"].get("exam-course")
        self.assertEqual("", exam.course_id)
        self.assertEqual("unassigned", exam.assignment_mode)
        self.assertEqual("pending", exam.analysis_status)
        self.assertIsNone(
            managers["current_event_manager"].get("pack-course")
        )
        self.assertEqual(2, len(managers["progress_manager"].items))
        self.assertEqual(0, len(managers["snapshot_manager"].items))

    def test_delete_bank_mode_prunes_sets_and_drafts_but_preserves_history(self):
        managers = self._lifecycle_managers()

        result = remove_course_assets(
            "course-a",
            CourseRemovalMode.DELETE_LINKED_BANK,
            **managers,
        )

        self.assertTrue(result.success, result.error)
        self.assertIsNone(managers["course_manager"].get("course-a"))
        self.assertIsNone(managers["question_bank"].get("q-course"))
        self.assertIsNotNone(managers["question_bank"].get("q-other"))
        self.assertIsNone(managers["set_manager"].get("set-direct"))
        self.assertEqual(["q-other"], managers["set_manager"].get("set-mixed").questions)
        self.assertEqual(2, len(managers["progress_manager"].items))
        self.assertIsNone(managers["snapshot_manager"].get("snapshot-direct"))
        self.assertIsNone(managers["snapshot_manager"].get("snapshot-mixed"))
        self.assertEqual(
            "",
            managers["past_exam_manager"].get("exam-course").course_id,
        )
        self.assertIsNone(
            managers["current_event_manager"].get("pack-course")
        )

    def test_failed_cleanup_restores_every_asset(self):
        managers = self._lifecycle_managers()
        managers["progress_manager"].save(
            SimpleNamespace(
                progress_id="progress-draft",
                set_id="set-direct",
                status="abandoned",
            )
        )
        question_bank = managers["question_bank"]
        real_delete = question_bank.delete

        def fail_delete(item_id):
            if item_id == "q-course":
                return False
            return real_delete(item_id)

        question_bank.delete = fail_delete

        result = remove_course_assets(
            "course-a",
            CourseRemovalMode.DELETE_LINKED_BANK,
            **managers,
        )

        self.assertFalse(result.success)
        self.assertIn("q-course", result.error)
        self.assertIsNotNone(managers["course_manager"].get("course-a"))
        self.assertIsNotNone(question_bank.get("q-course"))
        self.assertIsNotNone(managers["set_manager"].get("set-direct"))
        self.assertEqual(
            ["q-course", "q-other"],
            managers["set_manager"].get("set-mixed").questions,
        )
        self.assertIsNotNone(
            managers["progress_manager"].get("progress-draft")
        )
        self.assertEqual(2, len(managers["snapshot_manager"].items))
        restored_exam = managers["past_exam_manager"].get("exam-course")
        self.assertEqual("course-a", restored_exam.course_id)
        self.assertEqual("complete", restored_exam.analysis_status)
        self.assertIsNotNone(
            managers["current_event_manager"].get("pack-course")
        )

    @staticmethod
    def _lifecycle_managers():
        course = SimpleNamespace(course_id="course-a")
        questions = [
            SimpleNamespace(
                question_id="q-course",
                metadata={
                    "course_id": "course-a",
                    "course_title": "Systems",
                    "source_refs": [{"source_file": "slides.pdf"}],
                    "topic_title": "cache",
                },
            ),
            SimpleNamespace(
                question_id="q-other",
                metadata={"course_id": "course-b"},
            ),
        ]
        sets = [
            SimpleNamespace(
                set_id="set-direct",
                questions=["q-course", "q-other"],
                metadata={"course_id": "course-a", "course_title": "Systems"},
            ),
            SimpleNamespace(
                set_id="set-mixed",
                questions=["q-course", "q-other"],
                metadata={},
            ),
        ]
        progress = [
            SimpleNamespace(progress_id="progress-direct", set_id="set-direct"),
            SimpleNamespace(progress_id="progress-mixed", set_id="set-mixed"),
        ]
        snapshots = [
            SimpleNamespace(snapshot_id="snapshot-direct", set_id="set-direct"),
            SimpleNamespace(snapshot_id="snapshot-mixed", set_id="set-mixed"),
        ]
        past_exams = [
            PastExamRecord(
                exam_id="exam-course",
                title="Course Exam",
                source_filename="course-exam.pdf",
                source_path="source/course-exam.pdf",
                content_path="content.json",
                source_sha256="course-exam-hash",
                imported_at="2026-07-26T00:00:00+00:00",
                course_id="course-a",
                assignment_mode="manual",
                analysis_status="complete",
            ),
            PastExamRecord(
                exam_id="exam-other",
                title="Other Exam",
                source_filename="other-exam.pdf",
                source_path="source/other-exam.pdf",
                content_path="content.json",
                source_sha256="other-exam-hash",
                imported_at="2026-07-26T00:00:00+00:00",
                course_id="course-b",
                assignment_mode="manual",
                analysis_status="complete",
            ),
        ]
        current_events = [
            SimpleNamespace(pack_id="pack-course", course_id="course-a"),
            SimpleNamespace(pack_id="pack-other", course_id="course-b"),
        ]
        return {
            "course_manager": _CourseManager([course], current_id="course-a"),
            "question_bank": _StoreManager(questions, "question_id"),
            "set_manager": _StoreManager(sets, "set_id"),
            "progress_manager": _StoreManager(progress, "progress_id"),
            "snapshot_manager": _StoreManager(snapshots, "snapshot_id"),
            "past_exam_manager": _PastExamManager(past_exams),
            "current_event_manager": _CurrentEventManager(current_events),
        }


if __name__ == "__main__":
    unittest.main()
