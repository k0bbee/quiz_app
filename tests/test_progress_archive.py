import unittest
from copy import deepcopy
from types import SimpleNamespace

from models.progress import AnswerRecord, ProgressRecord, QuestionReviewSnapshot
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType


class _Store:
    def __init__(self, items, id_field, *, save_succeeds=True):
        self._id_field = id_field
        self._save_succeeds = save_succeeds
        self.save_calls = 0
        self._items = {
            getattr(item, id_field): deepcopy(item)
            for item in items
        }

    def get(self, item_id):
        item = self._items.get(item_id)
        return deepcopy(item) if item is not None else None

    def load_all(self):
        return [deepcopy(item) for item in self._items.values()]

    def save(self, item, **_kwargs):
        self.save_calls += 1
        if not self._save_succeeds:
            return False
        self._items[getattr(item, self._id_field)] = deepcopy(item)
        return True


class _RaisingStore(_Store):
    def save(self, item, **_kwargs):
        raise OSError("disk unavailable")


class ProgressArchiveTests(unittest.TestCase):
    def _question(self, question_id="q-io") -> Question:
        return Question(
            question_id=question_id,
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": "设备完成后如何通知 CPU？",
                    "options": ["A. 中断", "B. 轮询"],
                    "explanation": "中断由设备主动发出。",
                },
                "en": {
                    "stem": "How does the device notify the CPU?",
                    "options": ["A. Interrupt", "B. Polling"],
                    "explanation": "The device raises an interrupt.",
                },
            },
            correct_answer="A",
            topic="input-output",
            metadata={
                "course_id": "course-os",
                "course_title": "操作系统",
                "topic_title": "输入输出",
                "source_refs": [
                    {
                        "source_file": "lecture.pdf",
                        "page_or_slide": 8,
                        "excerpt": "设备完成后发出中断。",
                    }
                ],
            },
        )

    def _question_set(self) -> QuestionSet:
        return QuestionSet(
            set_id="set-io",
            title={"zh": "I/O 专项", "en": "I/O Practice"},
            description={"zh": "", "en": ""},
            topics=["input-output"],
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=10,
            questions=["q-io"],
            metadata={
                "course_id": "course-os",
                "course_title": "操作系统",
            },
        )

    def _legacy_record(self) -> ProgressRecord:
        return ProgressRecord(
            progress_id="progress-legacy",
            set_id="set-io",
            language="zh",
            started_at="2026-07-01T00:00:00+00:00",
            completed_at="2026-07-01T00:10:00+00:00",
            status="completed",
            answers=[
                AnswerRecord(
                    question_id="q-io",
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                )
            ],
            archive_status="legacy",
        )

    def test_migrates_legacy_record_when_live_assets_are_available(self):
        try:
            from core.progress_archive import ProgressArchiveMigrator
        except ModuleNotFoundError:
            self.fail("ProgressArchiveMigrator is not implemented")
        record = self._legacy_record()
        progress = _Store([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([self._question()], "question_id"),
            set_manager=_Store([self._question_set()], "set_id"),
            course_manager=_Store(
                [SimpleNamespace(course_id="course-os", title="操作系统")],
                "course_id",
            ),
        )

        result = migrator.migrate_record(record)

        self.assertTrue(result.changed)
        self.assertEqual("complete", result.status)
        self.assertEqual((), result.missing_fields)
        self.assertEqual("", result.error)
        stored = progress.get(record.progress_id)
        self.assertEqual(1, stored.archive_schema_version)
        self.assertEqual("complete", stored.archive_status)
        self.assertEqual("I/O 专项", stored.set_title_snapshot)
        self.assertEqual("course-os", stored.course_id_snapshot)
        self.assertEqual("操作系统", stored.course_title_snapshot)
        self.assertEqual(1, len(stored.question_snapshots))
        self.assertEqual("设备完成后如何通知 CPU？", stored.question_snapshots[0].stem)
        self.assertEqual("lecture.pdf", stored.question_snapshots[0].source_refs[0]["source_file"])

    def test_marks_archive_incomplete_when_question_set_is_missing(self):
        from core.progress_archive import ProgressArchiveMigrator

        record = self._legacy_record()
        progress = _Store([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([self._question()], "question_id"),
            set_manager=_Store([], "set_id"),
            course_manager=_Store(
                [SimpleNamespace(course_id="course-os", title="操作系统")],
                "course_id",
            ),
        )

        result = migrator.migrate_record(record)

        self.assertEqual("incomplete", result.status)
        self.assertEqual(("set_title_snapshot",), result.missing_fields)
        stored = progress.get(record.progress_id)
        self.assertEqual("incomplete", stored.archive_status)
        self.assertEqual(["set_title_snapshot"], stored.archive_missing_fields)
        self.assertEqual(1, len(stored.question_snapshots))
        self.assertEqual("course-os", stored.course_id_snapshot)
        self.assertEqual("操作系统", stored.course_title_snapshot)

    def test_preserves_available_snapshots_when_one_question_is_missing(self):
        from core.progress_archive import ProgressArchiveMigrator

        record = self._legacy_record()
        record.answers.append(
            AnswerRecord(
                question_id="q-deleted",
                index_in_session=1,
                user_answer="B",
                is_correct=False,
            )
        )
        progress = _Store([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([self._question()], "question_id"),
            set_manager=_Store([self._question_set()], "set_id"),
            course_manager=_Store([], "course_id"),
        )

        result = migrator.migrate_record(record)

        self.assertEqual("incomplete", result.status)
        self.assertEqual(("question:q-deleted",), result.missing_fields)
        stored = progress.get(record.progress_id)
        self.assertEqual(["q-io"], [
            snapshot.question_id for snapshot in stored.question_snapshots
        ])
        self.assertEqual(["question:q-deleted"], stored.archive_missing_fields)

    def test_save_failure_keeps_the_original_legacy_record(self):
        from core.progress_archive import ProgressArchiveMigrator

        record = self._legacy_record()
        progress = _RaisingStore([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([self._question()], "question_id"),
            set_manager=_Store([self._question_set()], "set_id"),
            course_manager=_Store([], "course_id"),
        )

        result = migrator.migrate_record(record)

        self.assertFalse(result.changed)
        self.assertEqual("legacy", result.status)
        self.assertIn("disk unavailable", result.error)
        self.assertEqual("legacy", record.archive_status)
        self.assertEqual([], record.question_snapshots)
        stored = progress.get(record.progress_id)
        self.assertEqual("legacy", stored.archive_status)
        self.assertEqual([], stored.question_snapshots)

    def test_existing_snapshot_remains_authoritative_after_live_question_deletion(self):
        from core.progress_archive import ProgressArchiveMigrator

        record = self._legacy_record()
        record.question_snapshots = [
            QuestionReviewSnapshot(
                question_id="q-io",
                question_type="multiple_choice",
                topic_id="input-output",
                topic_title="输入输出",
                stem="历史题干",
                options=["A. 中断", "B. 轮询"],
                correct_answer="A",
                explanation="历史解析",
                source_refs=[],
            )
        ]
        progress = _Store([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([], "question_id"),
            set_manager=_Store([self._question_set()], "set_id"),
            course_manager=_Store([], "course_id"),
        )

        result = migrator.migrate_record(record)

        self.assertEqual("complete", result.status)
        self.assertEqual((), result.missing_fields)
        stored = progress.get(record.progress_id)
        self.assertEqual(1, len(stored.question_snapshots))
        self.assertEqual("历史题干", stored.question_snapshots[0].stem)

    def test_completed_record_without_question_identity_stays_incomplete(self):
        from core.progress_archive import ProgressArchiveMigrator

        record = self._legacy_record()
        record.answers = []
        progress = _Store([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([], "question_id"),
            set_manager=_Store([self._question_set()], "set_id"),
            course_manager=_Store([], "course_id"),
        )

        result = migrator.migrate_record(record)

        self.assertEqual("incomplete", result.status)
        self.assertEqual(("question_snapshots",), result.missing_fields)
        stored = progress.get(record.progress_id)
        self.assertEqual(["question_snapshots"], stored.archive_missing_fields)

    def test_does_not_archive_an_unfinished_record(self):
        from core.progress_archive import ProgressArchiveMigrator

        record = self._legacy_record()
        record.status = "abandoned"
        record.archive_status = ""
        progress = _Store([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([self._question()], "question_id"),
            set_manager=_Store([self._question_set()], "set_id"),
            course_manager=_Store([], "course_id"),
        )

        result = migrator.migrate_record(record)

        self.assertFalse(result.changed)
        self.assertEqual("", result.status)
        self.assertEqual(0, progress.save_calls)
        self.assertEqual("", progress.get(record.progress_id).archive_status)

    def test_complete_current_archive_is_not_rewritten(self):
        from core.progress_archive import ProgressArchiveMigrator

        record = self._legacy_record()
        record.set_title_snapshot = "I/O 专项"
        record.course_id_snapshot = "course-os"
        record.course_title_snapshot = "操作系统"
        record.question_snapshots = [
            QuestionReviewSnapshot(
                question_id="q-io",
                question_type="multiple_choice",
                topic_id="input-output",
                topic_title="输入输出",
                stem="历史题干",
                options=["A. 中断", "B. 轮询"],
                correct_answer="A",
                explanation="历史解析",
            )
        ]
        record.archive_schema_version = 1
        record.archive_status = "complete"
        progress = _Store([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([], "question_id"),
            set_manager=_Store([], "set_id"),
            course_manager=_Store([], "course_id"),
        )

        result = migrator.migrate_record(record)

        self.assertFalse(result.changed)
        self.assertEqual("complete", result.status)
        self.assertEqual(0, progress.save_calls)

    def test_known_course_without_title_is_marked_incomplete(self):
        from core.progress_archive import ProgressArchiveMigrator

        record = self._legacy_record()
        question = self._question()
        question.metadata.pop("course_title")
        question_set = self._question_set()
        question_set.metadata.pop("course_title")
        progress = _Store([record], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([question], "question_id"),
            set_manager=_Store([question_set], "set_id"),
            course_manager=_Store([], "course_id"),
        )

        result = migrator.migrate_record(record)

        self.assertEqual("incomplete", result.status)
        self.assertEqual(("course_title_snapshot",), result.missing_fields)
        self.assertEqual(
            ["course_title_snapshot"],
            progress.get(record.progress_id).archive_missing_fields,
        )

    def test_migrate_all_processes_only_completed_records(self):
        from core.progress_archive import ProgressArchiveMigrator

        completed = self._legacy_record()
        draft = self._legacy_record()
        draft.progress_id = "progress-draft"
        draft.status = "abandoned"
        draft.archive_status = ""
        progress = _Store([completed, draft], "progress_id")
        migrator = ProgressArchiveMigrator(
            progress_manager=progress,
            question_bank=_Store([self._question()], "question_id"),
            set_manager=_Store([self._question_set()], "set_id"),
            course_manager=_Store([], "course_id"),
        )

        results = migrator.migrate_all()

        self.assertEqual(["progress-legacy"], [
            result.progress_id for result in results
        ])
        self.assertEqual("complete", results[0].status)
        self.assertEqual("", progress.get("progress-draft").archive_status)


if __name__ == "__main__":
    unittest.main()
