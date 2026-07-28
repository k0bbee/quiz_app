import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import course_index
from core.progress_tracker import ProgressManager
from core.question_bank_maintenance import (
    backfill_source_refs_from_course,
    delete_unreferenced_ai_questions,
    remove_question_from_sets,
)
from models.course_project import CourseProject, CourseTopic
from models.progress import AnswerRecord, ProgressRecord
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from utils.constants import Difficulty, QuestionType
from utils.json_io import read_json, write_json


class QuestionBankCoreTests(unittest.TestCase):
    def _question(self, question_id: str, topic: str = "cache") -> Question:
        return Question(
            question_id=question_id,
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": f"{topic} question",
                    "options": ["A. one", "B. two", "C. three", "D. four"],
                    "explanation": "A valid explanation with enough detail.",
                },
                "en": {
                    "stem": f"{topic} question",
                    "options": ["A. one", "B. two", "C. three", "D. four"],
                    "explanation": "A valid explanation with enough detail.",
                },
            },
            correct_answer="A",
            topic=topic,
        )

    def _set(self, set_id: str, question_ids: list[str]) -> QuestionSet:
        return QuestionSet(
            set_id=set_id,
            title={"zh": set_id, "en": set_id},
            description={"zh": "", "en": ""},
            topics=["cache"],
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=20,
            questions=question_ids,
        )

    def test_remove_question_from_sets_prunes_stale_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SetManager(tmpdir)
            manager.save(self._set("set-a", ["q1", "q2"]))
            manager.save(self._set("set-b", ["q1"]))
            manager.save(self._set("set-c", ["q3"]))

            changed = remove_question_from_sets(manager, "q1")

            self.assertEqual(2, changed)
            self.assertEqual(["q2"], manager.get("set-a").questions)
            self.assertEqual([], manager.get("set-b").questions)
            self.assertEqual(["q3"], manager.get("set-c").questions)
            self.assertEqual(
                "question_deleted",
                manager.get("set-a").metadata["source"],
            )
            self.assertIn("updated_at", manager.get("set-a").metadata)

    def test_question_bank_search_reuses_loaded_questions_until_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save_many([self._question("q1"), self._question("q2")])

            with patch("models.question.read_json", wraps=read_json) as read:
                first_page, first_total = question_bank.search(
                    query="cache",
                    limit=1,
                )
                reads_after_first_search = read.call_count
                second_page, second_total = question_bank.search(
                    query="cache",
                    limit=1,
                )

                self.assertEqual(2, first_total)
                self.assertEqual(2, second_total)
                self.assertEqual(
                    [question.question_id for question in first_page],
                    [question.question_id for question in second_page],
                )
                self.assertEqual(reads_after_first_search, read.call_count)

                question_bank.save(self._question("q3"))
                _page, updated_total = question_bank.search(
                    query="cache",
                    limit=5,
                )

                self.assertEqual(3, updated_total)
                self.assertEqual(reads_after_first_search, read.call_count)

    def test_question_bank_count_existing_skips_unsafe_question_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question_bank.save(self._question("q-safe"))

            count = question_bank.count_existing(
                ["q-safe", "../escape", "???", "q-safe"]
            )

            self.assertEqual(1, count)

    def test_question_bank_topic_index_is_lightweight_and_course_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_question = self._question("q-course", "cache")
            course_question.metadata.update(
                {
                    "course_id": "course-a",
                    "topic_title": "Cache Mapping",
                }
            )
            other_question = self._question("q-other", "process")
            other_question.metadata["course_id"] = "course-b"
            question_bank.save_many([course_question, other_question])

            with patch.object(
                question_bank,
                "load_all",
                side_effect=AssertionError(
                    "topic index must not construct all questions"
                ),
            ):
                index = question_bank.topic_index(course_id="course-a")

            self.assertEqual(
                {"q-course": ("cache", "Cache Mapping")},
                index,
            )

    def test_question_bank_scheduling_index_includes_topic_and_difficulty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_question = self._question("q-course", "cache")
            course_question.difficulty = Difficulty.HARD
            course_question.metadata.update(
                {
                    "course_id": "course-a",
                    "topic_title": "Cache Mapping",
                }
            )
            other_question = self._question("q-other", "process")
            other_question.metadata["course_id"] = "course-b"
            question_bank.save_many([course_question, other_question])

            with patch.object(
                question_bank,
                "load_all",
                side_effect=AssertionError(
                    "scheduling index must not construct all questions"
                ),
            ):
                index = question_bank.scheduling_index(course_id="course-a")

            self.assertEqual(
                {"q-course": ("cache", "Cache Mapping", "hard")},
                index,
            )

    def test_backfill_source_refs_from_course_updates_stale_question_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            project = CourseProject(
                course_id="course-source-backfill",
                title="Systems",
                source_folder="",
                summary_markdown="## Cache\nCache mapping.",
                summary_path="",
                topics=[
                    CourseTopic(
                        topic_id="cache",
                        title="Cache",
                        keywords=["cache"],
                        source_files=["cache.pdf"],
                    )
                ],
                documents=[
                    {
                        "path": "cache.pdf",
                        "title": "Cache lecture",
                        "extension": ".pdf",
                        "pages": ["Cache lines and cache mapping details."],
                    }
                ],
                created_at="2026-07-02T00:00:00+00:00",
                updated_at="2026-07-02T00:00:00+00:00",
            )
            index = course_index.build_source_index(project)
            question = self._question("q-source-backfill", "cache")
            question.metadata["course_id"] = project.course_id
            question.metadata["source_refs"] = [
                {
                    "chunk_id": "old-source-01",
                    "source_file": "cache.pdf",
                    "page_or_slide": 1,
                    "content_hash": index[0]["content_hash"][:12],
                }
            ]
            question_bank.save(question)

            changed = backfill_source_refs_from_course(question_bank, project)

            saved = question_bank.get("q-source-backfill")
            ref = saved.metadata["source_refs"][0]
            self.assertEqual(1, changed)
            self.assertEqual(index[0]["chunk_id"], ref["chunk_id"])
            self.assertEqual("old-source-01", ref["resolved_from_chunk_id"])
            self.assertIn("Cache lines and cache mapping", ref["excerpt"])

    def test_question_bank_search_filters_generated_questions_by_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_a = self._question("q-course-a")
            course_a.metadata["course_id"] = "course-a"
            course_b = self._question("q-course-b")
            course_b.metadata["course_id"] = "course-b"
            manual = self._question("q-manual")
            question_bank.save_many([course_a, course_b, manual])

            items, total = question_bank.search(course_id="course-a")

            self.assertEqual(1, total)
            self.assertEqual(
                {"q-course-a"},
                {question.question_id for question in items},
            )

    def test_question_bank_get_many_filters_generated_questions_by_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            course_a = self._question("q-course-a")
            course_a.metadata["course_id"] = "course-a"
            course_b = self._question("q-course-b")
            course_b.metadata["course_id"] = "course-b"
            manual = self._question("q-manual")
            question_bank.save_many([course_a, course_b, manual])

            questions = question_bank.get_many(
                ["q-course-a", "q-course-b", "q-manual"],
                course_id="course-a",
            )

            self.assertEqual(
                {"q-course-a"},
                {question.question_id for question in questions},
            )

    def test_question_and_set_save_reject_path_traversal_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            question_bank = QuestionBank(str(root / "questions"))
            unsafe_question = self._question("../outside")

            with self.assertRaises(ValueError):
                question_bank.save(unsafe_question)

            self.assertFalse((root / "outside.json").exists())

            set_manager = SetManager(str(root / "sets"))
            unsafe_set = self._set("../outside-set", ["q1"])

            with self.assertRaises(ValueError):
                set_manager.save(unsafe_set)

            self.assertFalse((root / "outside-set.json").exists())

    def test_question_bank_save_does_not_cache_question_when_disk_write_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
            question = self._question("q-unsaved")

            with patch("models.question.write_json", return_value=False):
                ok = question_bank.save(question)

            self.assertFalse(ok)
            self.assertIsNone(question_bank.get("q-unsaved"))
            self.assertEqual([], question_bank.load_all())

    def test_set_manager_save_does_not_cache_set_when_disk_write_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            question_set = self._set("set-unsaved", ["q1"])

            with patch("models.question_set.write_json", return_value=False):
                ok = set_manager.save(question_set)

            self.assertFalse(ok)
            self.assertIsNone(set_manager.get("set-unsaved"))
            self.assertEqual([], set_manager.load_all())

    def test_set_manager_get_refreshes_when_cached_file_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_manager = SetManager(str(Path(tmpdir) / "sets"))
            question_set = self._set("set-stale", ["q1"])
            set_manager.save(question_set)

            cached = set_manager.get("set-stale")
            self.assertEqual(["q1"], cached.questions)

            changed = self._set("set-stale", ["q2"])
            changed.title = {"zh": "更新后", "en": "Updated"}
            write_json(
                str(Path(tmpdir) / "sets" / "set-stale.json"),
                changed.to_dict(),
            )

            refreshed = set_manager.get("set-stale")

            self.assertEqual(["q2"], refreshed.questions)
            self.assertEqual("更新后", refreshed.get_title("zh"))

    def test_progress_save_rejects_path_traversal_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = ProgressManager(str(root / "progress"))
            record = ProgressRecord.create_new("set-a")
            record.progress_id = "../outside-progress"

            with self.assertRaises(ValueError):
                manager.save(record)

            self.assertFalse((root / "outside-progress.json").exists())

    def test_regeneration_cleanup_deletes_only_truly_orphaned_ai_questions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))
            progress_manager = ProgressManager(str(root / "progress"))

            orphan = self._question("q-orphan")
            orphan.metadata["source"] = "ai_generated"
            shared = self._question("q-shared")
            shared.metadata["source"] = "ai_generated"
            historical = self._question("q-history")
            historical.metadata["source"] = "ai_generated"
            manual = self._question("q-manual")
            manual.metadata["source"] = "manual"
            question_bank.save_many([orphan, shared, historical, manual])

            set_manager.save(self._set("set-other", ["q-shared"]))
            record = ProgressRecord.create_new("set-regenerated")
            record.answers = [
                AnswerRecord(
                    question_id="q-history",
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                )
            ]
            progress_manager.save(record)

            deleted = delete_unreferenced_ai_questions(
                question_bank,
                set_manager,
                ["q-orphan", "q-shared", "q-history", "q-manual"],
                progress_manager=progress_manager,
            )

            self.assertEqual(["q-orphan"], deleted)
            self.assertIsNone(question_bank.get("q-orphan"))
            self.assertIsNotNone(question_bank.get("q-shared"))
            self.assertIsNotNone(question_bank.get("q-history"))
            self.assertIsNotNone(question_bank.get("q-manual"))


if __name__ == "__main__":
    unittest.main()
