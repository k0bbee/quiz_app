import tempfile
import unittest
from pathlib import Path

from core.current_events import (
    CurrentEventCandidate,
    CurrentEventMaterialManager,
    CurrentEventMaterialPack,
)
from core.generation_draft_store import GenerationDraftStore
from ai.exam_plan import ExamGenerationPlan
from core.background_task import TaskControl
from core.mastery_overrides import MasteryOverrideStore
from core.progress_tracker import ProgressManager
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.past_exam import PastExamManager, PastExamRecord
from models.progress import AnswerRecord, ProgressRecord
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from utils.constants import Difficulty, QuestionType


class CourseMergeTests(unittest.TestCase):
    @staticmethod
    def _project(course_id: str, title: str, topic_id: str) -> CourseProject:
        return CourseProject(
            course_id=course_id,
            title=title,
            source_folder=f"C:/{course_id}",
            summary_markdown=f"# {title}\n\n{topic_id} summary",
            summary_path="",
            topics=[CourseTopic(topic_id, topic_id.upper())],
            documents=[{"path": f"{course_id}.md", "title": title}],
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
        )

    @staticmethod
    def _question(course_id: str, topic_id: str) -> Question:
        return Question(
            question_id=f"q-{course_id}",
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": "题目",
                    "options": ["A. 对", "B. 错"],
                    "explanation": "解析",
                },
                "en": {
                    "stem": "Question",
                    "options": ["A. Right", "B. Wrong"],
                    "explanation": "Explanation",
                },
            },
            correct_answer="A",
            topic=topic_id,
            metadata={"course_id": course_id, "course_title": course_id},
        )

    @staticmethod
    def _candidate(name: str) -> CurrentEventCandidate:
        return CurrentEventCandidate.create(
            url=f"https://example.com/{name}",
            title=name,
            context=f"{name} context",
            seen_at="2026-07-01T00:00:00+00:00",
            domain="example.com",
            language="en",
            query="same",
            retrieved_at="2026-07-01T00:00:00+00:00",
        )

    def test_merge_migrates_linked_assets_and_keeps_target_identity(self):
        from core.course_merge import merge_courses

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))
            past_exam_manager = PastExamManager(root / "past-exams")
            mastery = MasteryOverrideStore(root / "mastery.json")
            materials = CurrentEventMaterialManager(root / "events")
            target = self._project("course-target", "Target", "io")
            source = self._project("course-source", "Source", "memory")
            target.set_exam_scope("selected", ["io"])
            target.topics[0].keywords = ["interrupt"]
            source.topics.insert(
                0,
                CourseTopic("io", "Source I/O", keywords=["dma"]),
            )
            self.assertTrue(course_manager.save(target, make_current=False))
            self.assertTrue(course_manager.save(source, make_current=True))
            question = self._question(source.course_id, "memory")
            self.assertTrue(question_bank.save(question))
            question_set = QuestionSet.create_new(
                title={"zh": "来源题集", "en": "Source Set"},
                description={"zh": "", "en": ""},
                topics=["memory"],
                question_ids=[question.question_id],
            )
            question_set.metadata["course_id"] = source.course_id
            self.assertTrue(set_manager.save(question_set))
            exam = PastExamRecord(
                exam_id="exam-source",
                title="Source Exam",
                source_filename="exam.txt",
                source_path="source.txt",
                content_path="content.json",
                source_sha256="hash-source",
                imported_at="2026-07-01T00:00:00+00:00",
                course_id=source.course_id,
                assignment_mode="manual",
                analysis_status="complete",
            )
            self.assertTrue(past_exam_manager.save_record(exam))
            self.assertTrue(mastery.mark_topic_mastered(target.course_id, "io"))
            self.assertTrue(mastery.mark_topic_mastered(source.course_id, "memory"))
            candidate = CurrentEventCandidate.create(
                url="https://example.com/source-event",
                title="Source Event",
                context="Context",
                seen_at="2026-07-01T00:00:00+00:00",
                domain="example.com",
                language="en",
                query="source",
                retrieved_at="2026-07-01T00:00:00+00:00",
            )
            pack = CurrentEventMaterialPack.create(
                course_id=source.course_id,
                course_updated_at=source.updated_at,
                query="source",
                candidates=[candidate],
                selected_candidate_ids=[candidate.candidate_id],
            )
            self.assertTrue(materials.save(pack))
            draft_store = GenerationDraftStore(root / "generation-drafts.json")
            self.assertIsNotNone(
                draft_store.save(
                    course_id=source.course_id,
                    draft_id="source-generation-draft",
                    questions=[question],
                    question_set_title="来源待审核",
                    exam_plan=ExamGenerationPlan(question_count=3),
                    source="course_hub_gap",
                )
            )

            result = merge_courses(
                target.course_id,
                [source.course_id],
                course_manager=course_manager,
                question_bank=question_bank,
                set_manager=set_manager,
                past_exam_manager=past_exam_manager,
                mastery_overrides=mastery,
                current_event_manager=materials,
                generation_draft_store=draft_store,
            )

            self.assertTrue(result.success, result.error)
            merged = course_manager.get(target.course_id)
            self.assertIsNotNone(merged)
            self.assertIsNone(course_manager.get(source.course_id))
            self.assertEqual(target.course_id, course_manager.current().course_id)
            self.assertEqual(["io", "memory"], [topic.topic_id for topic in merged.topics])
            self.assertEqual("selected", merged.exam_scope_mode)
            self.assertEqual(["io"], merged.exam_scope_topic_ids)
            self.assertEqual(
                ["interrupt", "dma"],
                merged.topics[0].keywords,
            )
            self.assertIn("Source I/O", merged.topics[0].aliases)
            self.assertIn("Source", merged.summary_markdown)
            self.assertIn(source.course_id, merged.merged_course_ids)
            self.assertEqual(
                target.course_id,
                question_bank.get(question.question_id).metadata["course_id"],
            )
            self.assertEqual(
                target.course_id,
                set_manager.get(question_set.set_id).metadata["course_id"],
            )
            reassigned_exam = past_exam_manager.get(exam.exam_id)
            self.assertEqual(target.course_id, reassigned_exam.course_id)
            self.assertEqual("pending", reassigned_exam.analysis_status)
            self.assertEqual({"io", "memory"}, mastery.mastered_topics(target.course_id))
            self.assertEqual(set(), mastery.mastered_topics(source.course_id))
            self.assertEqual(1, len(materials.load_all(target.course_id)))
            self.assertEqual([], materials.load_all(source.course_id))
            self.assertEqual(1, result.question_count)
            self.assertEqual(1, result.question_set_count)
            self.assertEqual(1, result.past_exam_count)
            self.assertEqual(1, result.current_event_pack_count)
            self.assertEqual(1, result.generation_draft_count)
            migrated_draft = draft_store.get_by_id("source-generation-draft")
            self.assertIsNotNone(migrated_draft)
            self.assertEqual(target.course_id, migrated_draft.course_id)
            self.assertEqual("course_hub_gap", migrated_draft.source)
            self.assertEqual(
                target.course_id,
                migrated_draft.questions[0].metadata["course_id"],
            )

    def test_merge_archives_source_course_history_before_reassigning_assets(self):
        from core.course_merge import merge_courses

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))
            progress_manager = ProgressManager(str(root / "progress"))
            target = self._project("course-target", "Target", "io")
            source = self._project("course-source", "Source", "memory")
            self.assertTrue(course_manager.save(target, make_current=False))
            self.assertTrue(course_manager.save(source, make_current=True))
            question = self._question(source.course_id, "memory")
            question.metadata["course_title"] = source.title
            self.assertTrue(question_bank.save(question))
            question_set = QuestionSet.create_new(
                title={"zh": "来源题集", "en": "Source Set"},
                description={"zh": "", "en": ""},
                topics=["memory"],
                question_ids=[question.question_id],
            )
            question_set.metadata.update({
                "course_id": source.course_id,
                "course_title": source.title,
            })
            self.assertTrue(set_manager.save(question_set))
            record = ProgressRecord(
                progress_id="progress-source",
                set_id=question_set.set_id,
                language="zh",
                started_at="2026-07-01T00:00:00+00:00",
                completed_at="2026-07-01T00:10:00+00:00",
                status="completed",
                answers=[
                    AnswerRecord(
                        question.question_id,
                        0,
                        "A",
                        True,
                    )
                ],
                archive_status="legacy",
            )
            self.assertTrue(progress_manager.save(record))

            try:
                result = merge_courses(
                    target.course_id,
                    [source.course_id],
                    course_manager=course_manager,
                    question_bank=question_bank,
                    set_manager=set_manager,
                    progress_manager=progress_manager,
                )
            except TypeError:
                self.fail("merge_courses does not accept progress_manager")

            self.assertTrue(result.success, result.error)
            stored = progress_manager.get(record.progress_id)
            self.assertEqual("complete", stored.archive_status)
            self.assertEqual(source.course_id, stored.course_id_snapshot)
            self.assertEqual(source.title, stored.course_title_snapshot)
            self.assertEqual("题目", stored.question_snapshots[0].stem)

    def test_merge_rolls_back_before_deleting_source_when_asset_save_fails(self):
        from core.course_merge import merge_courses

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            question_bank = QuestionBank(str(root / "questions"))
            real_set_manager = SetManager(str(root / "sets"))
            target = self._project("course-target", "Target", "io")
            source = self._project("course-source", "Source", "memory")
            self.assertTrue(course_manager.save(target, make_current=False))
            self.assertTrue(course_manager.save(source, make_current=True))
            question = self._question(source.course_id, "memory")
            self.assertTrue(question_bank.save(question))
            question_set = QuestionSet.create_new(
                title={"zh": "来源题集", "en": "Source Set"},
                description={"zh": "", "en": ""},
                topics=["memory"],
                question_ids=[question.question_id],
            )
            question_set.metadata["course_id"] = source.course_id
            self.assertTrue(real_set_manager.save(question_set))

            class FailingSetManager:
                def load_all(self):
                    return real_set_manager.load_all()

                def get(self, set_id):
                    return real_set_manager.get(set_id)

                def save(self, value):
                    if value.metadata.get("course_id") == target.course_id:
                        return False
                    return real_set_manager.save(value)

            result = merge_courses(
                target.course_id,
                [source.course_id],
                course_manager=course_manager,
                question_bank=question_bank,
                set_manager=FailingSetManager(),
            )

            self.assertFalse(result.success)
            self.assertEqual((), result.rollback_errors)
            self.assertIsNotNone(course_manager.get(source.course_id))
            restored_target = course_manager.get(target.course_id)
            self.assertEqual(["io"], [topic.topic_id for topic in restored_target.topics])
            self.assertEqual(
                source.course_id,
                question_bank.get(question.question_id).metadata["course_id"],
            )
            self.assertEqual(
                source.course_id,
                real_set_manager.get(question_set.set_id).metadata["course_id"],
            )
            self.assertEqual(source.course_id, course_manager.current().course_id)

    def test_merge_consolidates_colliding_material_packs_without_losing_candidates(self):
        from core.course_merge import merge_courses

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            materials = CurrentEventMaterialManager(root / "events")
            target = self._project("course-target", "Target", "io")
            source_a = self._project("course-a", "Source A", "memory")
            source_b = self._project("course-b", "Source B", "process")
            for course in (target, source_a, source_b):
                self.assertTrue(course_manager.save(course, make_current=False))

            selected = self._candidate("selected")
            extra_a = self._candidate("extra-a")
            extra_b = self._candidate("extra-b")
            pack_a = CurrentEventMaterialPack.create(
                course_id=source_a.course_id,
                course_updated_at=source_a.updated_at,
                query="same",
                candidates=[selected, extra_a],
                selected_candidate_ids=[selected.candidate_id],
                created_at="2026-07-01T01:00:00+00:00",
            )
            pack_b = CurrentEventMaterialPack.create(
                course_id=source_b.course_id,
                course_updated_at=source_b.updated_at,
                query="same",
                candidates=[selected, extra_b],
                selected_candidate_ids=[selected.candidate_id],
                created_at="2026-07-01T02:00:00+00:00",
            )
            self.assertNotEqual(pack_a.pack_id, pack_b.pack_id)
            self.assertTrue(materials.save(pack_a))
            self.assertTrue(materials.save(pack_b))

            result = merge_courses(
                target.course_id,
                [source_a.course_id, source_b.course_id],
                course_manager=course_manager,
                current_event_manager=materials,
            )

            self.assertTrue(result.success, result.error)
            saved = materials.load_all(target.course_id)
            self.assertEqual(1, result.current_event_pack_count)
            self.assertEqual(1, len(saved))
            self.assertEqual(
                {selected.candidate_id, extra_a.candidate_id, extra_b.candidate_id},
                {candidate.candidate_id for candidate in saved[0].candidates},
            )
            self.assertEqual("2026-07-01T01:00:00+00:00", saved[0].created_at)
            self.assertEqual(
                {pack_a.pack_id, pack_b.pack_id},
                set(saved[0].source_pack_ids),
            )

    def test_merge_consolidates_with_existing_target_material_pack(self):
        from core.course_merge import merge_courses

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            materials = CurrentEventMaterialManager(root / "events")
            target = self._project("course-target", "Target", "io")
            source = self._project("course-source", "Source", "memory")
            self.assertTrue(course_manager.save(target, make_current=False))
            self.assertTrue(course_manager.save(source, make_current=False))

            selected = self._candidate("selected")
            target_extra = self._candidate("target-extra")
            source_extra = self._candidate("source-extra")
            target_pack = CurrentEventMaterialPack.create(
                course_id=target.course_id,
                course_updated_at=target.updated_at,
                query="same",
                candidates=[selected, target_extra],
                selected_candidate_ids=[selected.candidate_id],
                created_at="2026-06-30T23:00:00+00:00",
            )
            source_pack = CurrentEventMaterialPack.create(
                course_id=source.course_id,
                course_updated_at=source.updated_at,
                query="same",
                candidates=[selected, source_extra],
                selected_candidate_ids=[selected.candidate_id],
                created_at="2026-07-01T01:00:00+00:00",
            )
            self.assertTrue(materials.save(target_pack))
            self.assertTrue(materials.save(source_pack))

            result = merge_courses(
                target.course_id,
                [source.course_id],
                course_manager=course_manager,
                current_event_manager=materials,
            )

            self.assertTrue(result.success, result.error)
            saved = materials.load_all(target.course_id)
            self.assertEqual(1, result.current_event_pack_count)
            self.assertEqual(1, len(saved))
            self.assertEqual(
                {selected.candidate_id, target_extra.candidate_id, source_extra.candidate_id},
                {candidate.candidate_id for candidate in saved[0].candidates},
            )
            self.assertEqual("2026-06-30T23:00:00+00:00", saved[0].created_at)

    def test_merge_keeps_material_packs_with_different_selections_separate(self):
        from core.course_merge import merge_courses

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            materials = CurrentEventMaterialManager(root / "events")
            target = self._project("course-target", "Target", "io")
            source_a = self._project("course-a", "Source A", "memory")
            source_b = self._project("course-b", "Source B", "process")
            for course in (target, source_a, source_b):
                self.assertTrue(course_manager.save(course, make_current=False))

            selected_a = self._candidate("selected-a")
            selected_b = self._candidate("selected-b")
            packs = [
                CurrentEventMaterialPack.create(
                    course_id=course.course_id,
                    course_updated_at=course.updated_at,
                    query="same",
                    candidates=[candidate],
                    selected_candidate_ids=[candidate.candidate_id],
                )
                for course, candidate in (
                    (source_a, selected_a),
                    (source_b, selected_b),
                )
            ]
            for pack in packs:
                self.assertTrue(materials.save(pack))

            result = merge_courses(
                target.course_id,
                [source_a.course_id, source_b.course_id],
                course_manager=course_manager,
                current_event_manager=materials,
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(2, result.current_event_pack_count)
            self.assertEqual(2, len(materials.load_all(target.course_id)))

    def test_merge_rolls_back_materials_when_second_target_pack_save_fails(self):
        from core.course_merge import merge_courses

        class FailSecondTargetSaveManager(CurrentEventMaterialManager):
            def __init__(self, directory, target_course_id):
                super().__init__(directory)
                self.target_course_id = target_course_id
                self.target_save_count = 0

            def save(self, pack):
                if pack.course_id == self.target_course_id:
                    self.target_save_count += 1
                    if self.target_save_count == 2:
                        return False
                return super().save(pack)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            target = self._project("course-target", "Target", "io")
            source_a = self._project("course-a", "Source A", "memory")
            source_b = self._project("course-b", "Source B", "process")
            materials = FailSecondTargetSaveManager(root / "events", target.course_id)
            for course in (target, source_a, source_b):
                self.assertTrue(course_manager.save(course, make_current=False))
            source_packs = [
                CurrentEventMaterialPack.create(
                    course_id=course.course_id,
                    course_updated_at=course.updated_at,
                    query="same",
                    candidates=[candidate],
                    selected_candidate_ids=[candidate.candidate_id],
                )
                for course, candidate in (
                    (source_a, self._candidate("selected-a")),
                    (source_b, self._candidate("selected-b")),
                )
            ]
            for pack in source_packs:
                self.assertTrue(materials.save(pack))

            result = merge_courses(
                target.course_id,
                [source_a.course_id, source_b.course_id],
                course_manager=course_manager,
                current_event_manager=materials,
            )

            self.assertFalse(result.success)
            self.assertEqual((), result.rollback_errors)
            self.assertEqual([], materials.load_all(target.course_id))
            self.assertEqual(
                {pack.pack_id for pack in source_packs},
                {
                    pack.pack_id
                    for course_id in (source_a.course_id, source_b.course_id)
                    for pack in materials.load_all(course_id)
                },
            )
            self.assertIsNotNone(course_manager.get(source_a.course_id))
            self.assertIsNotNone(course_manager.get(source_b.course_id))

    def test_merge_rolls_back_materials_when_cancelled_after_first_target_save(self):
        from core.course_merge import merge_courses

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            materials = CurrentEventMaterialManager(root / "events")
            target = self._project("course-target", "Target", "io")
            source_a = self._project("course-a", "Source A", "memory")
            source_b = self._project("course-b", "Source B", "process")
            for course in (target, source_a, source_b):
                self.assertTrue(course_manager.save(course, make_current=False))
            source_packs = [
                CurrentEventMaterialPack.create(
                    course_id=course.course_id,
                    course_updated_at=course.updated_at,
                    query="same",
                    candidates=[candidate],
                    selected_candidate_ids=[candidate.candidate_id],
                )
                for course, candidate in (
                    (source_a, self._candidate("selected-a")),
                    (source_b, self._candidate("selected-b")),
                )
            ]
            for pack in source_packs:
                self.assertTrue(materials.save(pack))

            task = None

            def cancel_before_second_material(progress):
                if progress.stage == "merging_materials" and progress.current == 1:
                    task.cancel()

            task = TaskControl(cancel_before_second_material)
            result = merge_courses(
                target.course_id,
                [source_a.course_id, source_b.course_id],
                course_manager=course_manager,
                current_event_manager=materials,
                task=task,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.cancelled)
            self.assertEqual((), result.rollback_errors)
            self.assertEqual([], materials.load_all(target.course_id))
            self.assertEqual(
                {pack.pack_id for pack in source_packs},
                {
                    pack.pack_id
                    for course_id in (source_a.course_id, source_b.course_id)
                    for pack in materials.load_all(course_id)
                },
            )

    def test_merge_honors_cancellation_before_writing(self):
        from core.course_merge import merge_courses

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(root / "courses")
            target = self._project("course-target", "Target", "io")
            source = self._project("course-source", "Source", "memory")
            self.assertTrue(course_manager.save(target, make_current=False))
            self.assertTrue(course_manager.save(source, make_current=True))
            task = TaskControl()
            task.cancel()

            result = merge_courses(
                target.course_id,
                [source.course_id],
                course_manager=course_manager,
                task=task,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.cancelled)
            self.assertIsNotNone(course_manager.get(source.course_id))
            self.assertEqual(["io"], [
                topic.topic_id
                for topic in course_manager.get(target.course_id).topics
            ])


if __name__ == "__main__":
    unittest.main()
