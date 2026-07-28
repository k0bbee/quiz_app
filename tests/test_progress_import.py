import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.background_task import BackgroundTaskCancelled, TaskControl
from core.progress_tracker import ProgressManager
from models.progress import AnswerRecord, ProgressRecord, SessionSummary
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from utils.constants import Difficulty, QuestionType


class ProgressImportTests(unittest.TestCase):
    def _question(self) -> Question:
        return Question(
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
                "course_id": "course-os",
                "course_title": "操作系统",
                "topic_title": "输入输出",
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

    def _legacy_record(self, progress_id: str = "progress-imported") -> ProgressRecord:
        answers = [AnswerRecord("q-io", 0, "A", True)]
        return ProgressRecord(
            progress_id=progress_id,
            set_id="set-io",
            language="zh",
            started_at="2026-07-01T00:00:00+00:00",
            completed_at="2026-07-01T00:05:00+00:00",
            status="completed",
            answers=answers,
            summary=SessionSummary.compute(answers, 1, 300),
            archive_status="legacy",
        )

    def _prepare_data_root(self, root: Path) -> None:
        bank = QuestionBank(str(root / "questions"))
        self.assertTrue(bank.save(self._question()))
        sets = SetManager(str(root / "question_sets"))
        self.assertTrue(sets.save(self._question_set()))

    def test_import_validates_and_migrates_legacy_records_before_commit(self):
        from core.progress_import import ProgressImportService

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._prepare_data_root(root)
            source = root / "progress-export.json"
            source.write_text(
                json.dumps(
                    [self._legacy_record().to_dict()],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = ProgressImportService.from_data_dir(root).import_file(source)

            self.assertEqual(1, result.imported)
            self.assertEqual(0, result.invalid)
            self.assertEqual(1, result.migrated_complete)
            stored = ProgressManager(str(root / "progress")).get(
                "progress-imported"
            )
            self.assertEqual("complete", stored.archive_status)
            self.assertEqual("设备如何通知 CPU？", stored.question_snapshots[0].stem)

    def test_import_skips_invalid_records_and_reports_them(self):
        from core.progress_import import ProgressImportService

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._prepare_data_root(root)
            source = root / "progress-export.json"
            source.write_text(
                json.dumps(
                    [
                        self._legacy_record().to_dict(),
                        {"progress_id": "../outside", "answers": []},
                        "not-an-object",
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = ProgressImportService.from_data_dir(root).import_file(source)

            self.assertEqual(1, result.imported)
            self.assertEqual(2, result.invalid)
            self.assertEqual(2, len(result.invalid_details))
            self.assertFalse((root / "outside.json").exists())

    def test_commit_failure_restores_every_overwritten_record(self):
        from core.progress_import import (
            ProgressImportCommitError,
            ProgressImportService,
            _replace_staged_file,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._prepare_data_root(root)
            progress = ProgressManager(str(root / "progress"))
            first_original = self._legacy_record("progress-a")
            first_original.set_id = "set-original-a"
            second_original = self._legacy_record("progress-b")
            second_original.set_id = "set-original-b"
            self.assertTrue(progress.save(first_original))
            self.assertTrue(progress.save(second_original))

            first_imported = self._legacy_record("progress-a")
            second_imported = self._legacy_record("progress-b")
            source = root / "progress-export.json"
            source.write_text(
                json.dumps(
                    [first_imported.to_dict(), second_imported.to_dict()],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            replace_calls = 0

            def fail_second_replace(source_path, target_path):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise OSError("simulated disk failure")
                return _replace_staged_file(source_path, target_path)

            with patch(
                "core.progress_import._replace_staged_file",
                side_effect=fail_second_replace,
            ):
                with self.assertRaises(ProgressImportCommitError):
                    ProgressImportService.from_data_dir(root).import_file(source)

            reopened = ProgressManager(str(root / "progress"))
            self.assertEqual("set-original-a", reopened.get("progress-a").set_id)
            self.assertEqual("set-original-b", reopened.get("progress-b").set_id)

    def test_cancellation_during_commit_restores_every_overwritten_record(self):
        from core.progress_import import ProgressImportService

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._prepare_data_root(root)
            progress = ProgressManager(str(root / "progress"))
            first_original = self._legacy_record("progress-a")
            first_original.set_id = "set-original-a"
            second_original = self._legacy_record("progress-b")
            second_original.set_id = "set-original-b"
            self.assertTrue(progress.save(first_original))
            self.assertTrue(progress.save(second_original))
            source = root / "progress-export.json"
            source.write_text(
                json.dumps(
                    [
                        self._legacy_record("progress-a").to_dict(),
                        self._legacy_record("progress-b").to_dict(),
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            task = None

            def cancel_before_second_commit(progress_update):
                if (
                    progress_update.stage == "committing"
                    and progress_update.current == 2
                ):
                    task.cancel()

            task = TaskControl(cancel_before_second_commit)

            with self.assertRaises(BackgroundTaskCancelled):
                ProgressImportService.from_data_dir(root).import_file(
                    source,
                    task=task,
                )

            reopened = ProgressManager(str(root / "progress"))
            self.assertEqual("set-original-a", reopened.get("progress-a").set_id)
            self.assertEqual("set-original-b", reopened.get("progress-b").set_id)


if __name__ == "__main__":
    unittest.main()
