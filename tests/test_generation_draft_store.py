import tempfile
import unittest
from pathlib import Path

from ai.exam_plan import ExamGenerationPlan
from core.generation_draft_store import GenerationDraftStore
from models.question import Question
from utils.constants import Difficulty, QuestionType


class GenerationDraftStoreTests(unittest.TestCase):
    @staticmethod
    def _question(question_id: str = "draft-q1") -> Question:
        return Question(
            question_id=question_id,
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
            topic="topic-io",
            metadata={"course_id": "course-a"},
        )

    def test_review_pending_draft_survives_store_recreation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "generation-drafts.json"
            store = GenerationDraftStore(
                path,
                clock=lambda: "2026-07-29T08:00:00+00:00",
            )
            plan = ExamGenerationPlan(
                question_count=10,
                difficulty="mixed",
                selected_topics=("topic-io",),
                topic_weights={"topic-io": 100},
            )

            saved = store.save(
                course_id="course-a",
                questions=[self._question()],
                question_set_title="操作系统快速复习",
                exam_plan=plan,
                review_warnings_only=True,
                source="first_run",
                task_id="task-1",
            )
            restored = GenerationDraftStore(path).get("course-a")

            self.assertEqual("review_pending", saved.stage)
            self.assertIsNotNone(restored)
            self.assertEqual("course-a", restored.course_id)
            self.assertEqual("操作系统快速复习", restored.question_set_title)
            self.assertEqual("draft-q1", restored.questions[0].question_id)
            self.assertEqual(("topic-io",), restored.exam_plan.selected_topics)
            self.assertTrue(restored.review_warnings_only)
            self.assertEqual("first_run", restored.source)
            self.assertEqual("task-1", restored.task_id)
            self.assertEqual("2026-07-29T08:00:00+00:00", restored.updated_at)

    def test_drafts_are_isolated_by_course_and_delete_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "generation-drafts.json"
            store = GenerationDraftStore(path)
            plan = ExamGenerationPlan(
                question_count=3,
                selected_topics=("topic-io",),
            )
            store.save(
                course_id="course-a",
                questions=[self._question("a-q")],
                question_set_title="A",
                exam_plan=plan,
            )
            question_b = self._question("b-q")
            question_b.metadata["course_id"] = "course-b"
            store.save(
                course_id="course-b",
                questions=[question_b],
                question_set_title="B",
                exam_plan=plan,
            )

            self.assertTrue(store.delete("course-a"))
            self.assertTrue(store.delete("course-a"))
            self.assertIsNone(GenerationDraftStore(path).get("course-a"))
            self.assertEqual(
                "b-q",
                GenerationDraftStore(path).get("course-b").questions[0].question_id,
            )

    def test_empty_question_list_removes_stale_draft(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "generation-drafts.json"
            store = GenerationDraftStore(path)
            plan = ExamGenerationPlan(
                question_count=3,
                selected_topics=("topic-io",),
            )
            store.save(
                course_id="course-a",
                questions=[self._question()],
                question_set_title="A",
                exam_plan=plan,
            )

            result = store.save(
                course_id="course-a",
                questions=[],
                question_set_title="A",
                exam_plan=plan,
            )

            self.assertIsNone(result)
            self.assertIsNone(store.get("course-a"))

    def test_list_all_returns_valid_drafts_newest_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            timestamps = iter([
                "2026-07-29T08:00:00+00:00",
                "2026-07-29T09:00:00+00:00",
            ])
            store = GenerationDraftStore(
                Path(tmpdir) / "generation-drafts.json",
                clock=lambda: next(timestamps),
            )
            plan = ExamGenerationPlan(question_count=3)
            store.save(
                course_id="course-a",
                questions=[self._question("a-q")],
                question_set_title="A",
                exam_plan=plan,
            )
            question_b = self._question("b-q")
            question_b.metadata["course_id"] = "course-b"
            store.save(
                course_id="course-b",
                questions=[question_b],
                question_set_title="B",
                exam_plan=plan,
                source="prediction",
            )

            drafts = store.list_all()

            self.assertEqual(
                ["course-b", "course-a"],
                [draft.course_id for draft in drafts],
            )
            self.assertEqual("prediction", drafts[0].source)


if __name__ == "__main__":
    unittest.main()
