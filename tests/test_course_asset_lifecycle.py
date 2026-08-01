import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from core.course_asset_lifecycle import (
    CourseRemovalMode,
    analyze_course_asset_impact,
    remove_course_assets,
)
from core.generation_draft_store import GenerationDraftStore
from ai.exam_plan import ExamGenerationPlan
from models.past_exam import PastExamRecord
from models.progress import AnswerRecord, ProgressRecord
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType


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

    def archive(self, item_id):
        item = self.get(item_id)
        if item is None:
            return False
        item.status = "archived"
        self.save(item, make_current=False)
        if self.current_id == item_id:
            self.current_id = ""
        return True


class _PastExamManager(_StoreManager):
    def __init__(self, items):
        super().__init__(items, "exam_id")

    def save_record(self, item):
        return self.save(item)


class _CurrentEventManager(_StoreManager):
    def __init__(self, items):
        super().__init__(items, "pack_id")


class CourseAssetLifecycleTests(unittest.TestCase):
    def test_course_removal_cleans_review_pending_generation_drafts(self):
        managers = self._lifecycle_managers()
        with TemporaryDirectory() as tmpdir:
            draft_store = GenerationDraftStore(Path(tmpdir) / "drafts.json")
            draft_store.save(
                course_id="course-a",
                draft_id="generation-draft-a",
                questions=[self._draft_question()],
                question_set_title="待审核题目",
                exam_plan=ExamGenerationPlan(question_count=3),
            )

            result = remove_course_assets(
                "course-a",
                CourseRemovalMode.UNLINK_ASSETS,
                generation_draft_store=draft_store,
                **managers,
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(("generation-draft-a",), result.impact.generation_draft_ids)
            self.assertEqual(1, result.impact.generation_draft_count)
            self.assertEqual(0, len(draft_store.list_all()))

    def test_failed_course_removal_restores_generation_drafts(self):
        managers = self._lifecycle_managers()
        real_delete = managers["question_bank"].delete

        def fail_question_delete(item_id):
            if item_id == "q-course":
                return False
            return real_delete(item_id)

        managers["question_bank"].delete = fail_question_delete
        with TemporaryDirectory() as tmpdir:
            draft_store = GenerationDraftStore(Path(tmpdir) / "drafts.json")
            draft_store.save(
                course_id="course-a",
                draft_id="generation-draft-a",
                questions=[self._draft_question()],
                question_set_title="待审核题目",
                exam_plan=ExamGenerationPlan(question_count=3),
            )

            result = remove_course_assets(
                "course-a",
                CourseRemovalMode.DELETE_LINKED_BANK,
                generation_draft_store=draft_store,
                **managers,
            )

            self.assertFalse(result.success)
            restored = draft_store.get_by_id("generation-draft-a")
            self.assertIsNotNone(restored)
            self.assertEqual("待审核题目", restored.question_set_title)
            self.assertTrue(restored.updated_at)

    @staticmethod
    def _draft_question():
        return Question(
            question_id="generation-q",
            type=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "草稿题",
                    "options": ["正确", "错误"],
                    "explanation": "草稿解释",
                },
                "en": {
                    "stem": "Draft question",
                    "options": ["True", "False"],
                    "explanation": "Draft explanation",
                },
            },
            correct_answer=True,
            topic="topic-a",
            metadata={"course_id": "course-a"},
        )

    def test_impact_classifies_completed_history_archive_state(self):
        progress = _Manager([
            SimpleNamespace(
                progress_id="progress-complete",
                set_id="set-deleted",
                status="completed",
                course_id_snapshot="course-a",
                archive_status="complete",
            ),
            SimpleNamespace(
                progress_id="progress-incomplete",
                set_id="set-deleted",
                status="completed",
                course_id_snapshot="course-a",
                archive_status="incomplete",
            ),
            SimpleNamespace(
                progress_id="progress-legacy",
                set_id="set-deleted",
                status="completed",
                course_id_snapshot="course-a",
                archive_status="legacy",
            ),
        ])

        impact = analyze_course_asset_impact(
            "course-a",
            progress_manager=progress,
        )

        self.assertEqual(("progress-complete",), impact.complete_archive_ids)
        self.assertEqual(("progress-incomplete",), impact.incomplete_archive_ids)
        self.assertEqual(("progress-legacy",), impact.legacy_archive_ids)
        self.assertEqual(1, impact.complete_archive_count)
        self.assertEqual(1, impact.incomplete_archive_count)
        self.assertEqual(1, impact.legacy_archive_count)

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

    def test_course_removal_archives_legacy_history_before_deleting_course(self):
        managers = self._archive_lifecycle_managers()

        result = remove_course_assets(
            "course-a",
            CourseRemovalMode.DELETE_LINKED_BANK,
            **managers,
        )

        self.assertTrue(result.success, result.error)
        stored = managers["progress_manager"].get("progress-legacy")
        self.assertEqual("complete", stored.archive_status)
        self.assertEqual(1, stored.archive_schema_version)
        self.assertEqual("设备如何通知 CPU？", stored.question_snapshots[0].stem)
        self.assertEqual(1, result.impact.complete_archive_count)
        self.assertEqual(0, result.impact.legacy_archive_count)

    @staticmethod
    def _archive_lifecycle_managers():
        course = SimpleNamespace(course_id="course-a", title="操作系统")
        question = Question(
            question_id="q-io",
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": "设备如何通知 CPU？",
                    "options": ["A. 中断", "B. 轮询"],
                    "explanation": "设备通过中断通知 CPU。",
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
                "course_id": "course-a",
                "course_title": "操作系统",
            },
        )
        question_set = QuestionSet(
            set_id="set-io",
            title={"zh": "I/O 专项", "en": "I/O Practice"},
            description={"zh": "", "en": ""},
            topics=["input-output"],
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=10,
            questions=["q-io"],
            metadata={
                "course_id": "course-a",
                "course_title": "操作系统",
            },
        )
        progress = ProgressRecord(
            progress_id="progress-legacy",
            set_id="set-io",
            language="zh",
            started_at="2026-07-01T00:00:00+00:00",
            completed_at="2026-07-01T00:10:00+00:00",
            status="completed",
            answers=[AnswerRecord("q-io", 0, "A", True)],
            archive_status="legacy",
        )
        return {
            "course_manager": _CourseManager([course], current_id="course-a"),
            "question_bank": _StoreManager([question], "question_id"),
            "set_manager": _StoreManager([question_set], "set_id"),
            "progress_manager": _StoreManager([progress], "progress_id"),
        }

    def test_course_removal_stops_when_legacy_archive_cannot_be_saved(self):
        managers = self._archive_lifecycle_managers()
        managers["progress_manager"].save = lambda _record: False

        result = remove_course_assets(
            "course-a",
            CourseRemovalMode.DELETE_LINKED_BANK,
            **managers,
        )

        self.assertFalse(result.success)
        self.assertIn("Failed to prepare completed history archives", result.error)
        self.assertIsNotNone(managers["course_manager"].get("course-a"))
        self.assertIsNotNone(managers["question_bank"].get("q-io"))
        stored = managers["progress_manager"].get("progress-legacy")
        self.assertEqual("legacy", stored.archive_status)

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

    def test_archive_mode_preserves_course_identity_and_every_linked_asset(self):
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
            CourseRemovalMode.ARCHIVE,
            **managers,
        )

        self.assertTrue(result.success, result.error)
        course = managers["course_manager"].get("course-a")
        self.assertIsNotNone(course)
        self.assertEqual("archived", course.status)
        self.assertEqual("", managers["course_manager"].current_id)
        self.assertIsNotNone(managers["question_bank"].get("q-course"))
        self.assertIsNotNone(managers["set_manager"].get("set-direct"))
        self.assertIsNotNone(
            managers["progress_manager"].get("progress-draft")
        )
        self.assertIsNotNone(
            managers["snapshot_manager"].get("snapshot-direct")
        )
        self.assertEqual(
            "course-a",
            managers["past_exam_manager"].get("exam-course").course_id,
        )
        self.assertIsNotNone(
            managers["current_event_manager"].get("pack-course")
        )

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
