import tempfile
import unittest
from pathlib import Path

from core.current_events import (
    CurrentEventCandidate,
    CurrentEventMaterialManager,
    CurrentEventMaterialPack,
)
from core.background_task import TaskControl
from core.mastery_overrides import MasteryOverrideStore
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.past_exam import PastExamManager, PastExamRecord
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

            result = merge_courses(
                target.course_id,
                [source.course_id],
                course_manager=course_manager,
                question_bank=question_bank,
                set_manager=set_manager,
                past_exam_manager=past_exam_manager,
                mastery_overrides=mastery,
                current_event_manager=materials,
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
