import tempfile
import unittest

from core.past_exam_prediction import PastExamPredictionPlanner
from models.course_project import CourseProject, CourseTopic
from models.past_exam import (
    PastExamAnalysis,
    PastExamManager,
    PastExamQuestionTypeProfile,
    PastExamRecord,
    PastExamTopicProfile,
)


class PastExamPredictionTests(unittest.TestCase):
    def test_planner_aggregates_only_completed_profiles_for_the_course(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PastExamManager(temp_dir)
            self._save_profile(
                manager,
                "exam-a",
                "course-a",
                types={"multiple_choice": 15, "true_false": 5},
                topics={"io": 80, "dma": 20},
            )
            self._save_profile(
                manager,
                "exam-b",
                "course-a",
                types={"multiple_choice": 15, "short_answer": 15},
                topics={"io": 20, "dma": 80},
            )
            self._save_profile(
                manager,
                "other-course",
                "course-b",
                types={"true_false": 60},
                topics={"other": 100},
            )

            prediction = PastExamPredictionPlanner(manager).build(self._course())

            self.assertEqual(2, prediction.source_count)
            self.assertEqual(("exam-a", "exam-b"), prediction.exam_ids)
            self.assertEqual(25, prediction.plan.question_count)
            self.assertEqual({"io", "dma"}, set(prediction.plan.selected_topics))
            self.assertEqual({"io": 50, "dma": 50}, dict(prediction.plan.topic_weights))
            self.assertEqual(60, prediction.plan.question_type_weights["multiple_choice"])
            self.assertEqual(10, prediction.plan.question_type_weights["true_false"])
            self.assertEqual(30, prediction.plan.question_type_weights["short_answer"])
            self.assertEqual(0, prediction.plan.question_type_weights["scenario_choice"])
            self.assertFalse(any("short_answer" in warning for warning in prediction.warnings))
            self.assertEqual("final_exam", prediction.plan.template)

    def test_planner_requires_a_reliable_topic_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PastExamManager(temp_dir)
            self._save_profile(
                manager,
                "exam-a",
                "course-a",
                types={"multiple_choice": 10},
                topics={},
            )

            with self.assertRaisesRegex(ValueError, "topic evidence"):
                PastExamPredictionPlanner(manager).build(self._course())

    @staticmethod
    def _course():
        return CourseProject(
            course_id="course-a",
            title="Systems",
            source_folder="",
            summary_markdown="summary",
            summary_path="",
            topics=[
                CourseTopic("io", "I/O"),
                CourseTopic("dma", "DMA"),
            ],
            documents=[],
            created_at="2026-07-13T00:00:00+00:00",
            updated_at="2026-07-13T00:00:00+00:00",
        )

    @staticmethod
    def _save_profile(manager, exam_id, course_id, *, types, topics):
        record = PastExamRecord(
            exam_id=exam_id,
            title=exam_id,
            source_filename=f"{exam_id}.txt",
            source_path=f"source/{exam_id}.txt",
            content_path="content.json",
            source_sha256=f"hash-{exam_id}",
            imported_at=f"2026-07-13T00:00:0{len(manager.load_all())}+00:00",
            course_id=course_id,
            assignment_mode="manual",
            analysis_status="complete",
        )
        manager.exam_directory(exam_id).mkdir(parents=True)
        manager.save_record(record)
        analysis = PastExamAnalysis(
            source_sha256=record.source_sha256,
            analyzed_at="2026-07-13T00:00:00+00:00",
            detected_question_count=sum(types.values()),
            question_types=tuple(
                PastExamQuestionTypeProfile(key, count, 0.9, (key,))
                for key, count in types.items()
            ),
            topic_profile=tuple(
                PastExamTopicProfile(key, key.upper(), weight, weight, (key,))
                for key, weight in topics.items()
            ),
        )
        manager.save_analysis(exam_id, analysis)


if __name__ == "__main__":
    unittest.main()
