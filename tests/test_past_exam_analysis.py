import tempfile
import unittest
from pathlib import Path

from core.background_task import BackgroundTaskCancelled, TaskControl
from core.past_exam_analyzer import PastExamAnalyzer, PastExamAnalysisService
from models.course_project import CourseProject, CourseTopic
from models.past_exam import PastExamContent, PastExamManager, PastExamRecord


def _course(topics):
    return CourseProject(
        course_id="systems",
        title="计算机系统",
        source_folder="",
        summary_markdown="",
        summary_path="",
        topics=topics,
        documents=[],
        created_at="2026-07-13T00:00:00+00:00",
        updated_at="2026-07-13T00:00:00+00:00",
    )


class _CourseManager:
    def __init__(self, course):
        self.course = course

    def get(self, course_id):
        return self.course if course_id == self.course.course_id else None


class PastExamAnalysisTests(unittest.TestCase):
    def test_analysis_uses_explicit_sections_and_question_numbers(self):
        text = """
一、单项选择题（共3题）
1. 中断驱动 I/O 的特点是什么？
A. 选项一 B. 选项二 C. 选项三 D. 选项四
2. DMA 控制器的作用是什么？
A. 选项一 B. 选项二 C. 选项三 D. 选项四
3. 通道技术主要解决什么问题？
A. 选项一 B. 选项二 C. 选项三 D. 选项四
二、判断题
1. DMA 传输完全不需要 CPU 初始化。（ ）
2. 中断可用于设备完成通知。（ ）
三、简答题（2题）
1. 简述轮询与中断的区别。
2. 简述 DMA 的工作过程。
"""
        analysis = PastExamAnalyzer().analyze(text, _course([]), source_sha256="abc")

        self.assertEqual(
            {"multiple_choice": 3, "true_false": 2, "short_answer": 2},
            {item.question_type: item.count for item in analysis.question_types},
        )
        self.assertEqual(7, analysis.detected_question_count)
        self.assertEqual("local_rules_v1", analysis.method)
        self.assertTrue(all(item.evidence for item in analysis.question_types))

    def test_topic_profile_uses_stable_ids_and_downweights_shared_terms(self):
        course = _course([
            CourseTopic(
                topic_id="io_interrupts",
                title="中断驱动 I/O",
                aliases=["中断输入输出"],
                keywords=["CPU", "中断", "设备"],
            ),
            CourseTopic(
                topic_id="dma_transfer",
                title="DMA 传输",
                aliases=["直接存储器访问"],
                keywords=["CPU", "控制器", "总线"],
            ),
        ])
        text = "中断驱动 I/O 通过中断通知 CPU。中断输入输出减少轮询。CPU 也会初始化 DMA。"

        analysis = PastExamAnalyzer().analyze(text, course, source_sha256="abc")

        self.assertEqual("io_interrupts", analysis.topic_profile[0].topic_id)
        self.assertGreater(analysis.topic_profile[0].weight, analysis.topic_profile[1].weight)
        self.assertIn("中断驱动 i o", analysis.topic_profile[0].matched_terms)
        self.assertNotIn("cpu", analysis.topic_profile[0].matched_terms)
        self.assertEqual(100, sum(item.weight for item in analysis.topic_profile))

    def test_service_persists_analysis_and_course_change_invalidates_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PastExamManager(temp_dir)
            record = PastExamRecord(
                exam_id="exam-1",
                title="系统真题",
                source_filename="exam.txt",
                source_path="source.txt",
                content_path="content.json",
                source_sha256="abc",
                imported_at="2026-07-13T00:00:00+00:00",
                course_id="systems",
                assignment_mode="manual",
            )
            manager.exam_directory(record.exam_id).mkdir(parents=True)
            self.assertTrue(manager.save_record(record))
            self.assertTrue(manager.save_content(record.exam_id, PastExamContent("一、判断题\n1. 中断用于通知。（ ）")))
            course = _course([CourseTopic("io_interrupts", "中断驱动 I/O", ["中断"])])

            result = PastExamAnalysisService(manager, _CourseManager(course)).analyze("exam-1")

            self.assertEqual("complete", manager.get("exam-1").analysis_status)
            self.assertEqual(result.to_dict(), manager.get_analysis("exam-1").to_dict())
            self.assertTrue((Path(temp_dir) / "exam-1" / "analysis.json").is_file())

            manager.reassign_course("exam-1", "systems")
            self.assertEqual("complete", manager.get("exam-1").analysis_status)
            self.assertIsNotNone(manager.get_analysis("exam-1"))

            manager.reassign_course("exam-1", "")
            self.assertEqual("pending", manager.get("exam-1").analysis_status)
            self.assertIsNone(manager.get_analysis("exam-1"))

    def test_service_requires_an_assigned_existing_course(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PastExamManager(temp_dir)
            record = PastExamRecord(
                exam_id="exam-1",
                title="未归属真题",
                source_filename="exam.txt",
                source_path="source.txt",
                content_path="content.json",
                source_sha256="abc",
                imported_at="2026-07-13T00:00:00+00:00",
            )
            manager.exam_directory(record.exam_id).mkdir(parents=True)
            manager.save_record(record)
            manager.save_content(record.exam_id, PastExamContent("some text"))

            with self.assertRaisesRegex(ValueError, "assigned course"):
                PastExamAnalysisService(manager, _CourseManager(_course([]))).analyze("exam-1")

    def test_cancelled_analysis_does_not_publish_a_complete_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PastExamManager(temp_dir)
            record = PastExamRecord(
                exam_id="exam-1",
                title="系统真题",
                source_filename="exam.txt",
                source_path="source.txt",
                content_path="content.json",
                source_sha256="abc",
                imported_at="2026-07-13T00:00:00+00:00",
                course_id="systems",
                assignment_mode="manual",
            )
            manager.exam_directory(record.exam_id).mkdir(parents=True)
            manager.save_record(record)
            manager.save_content(record.exam_id, PastExamContent("一、判断题\n1. 中断用于通知。（ ）"))
            task = TaskControl()
            task.cancel()

            with self.assertRaises(BackgroundTaskCancelled):
                PastExamAnalysisService(
                    manager,
                    _CourseManager(_course([CourseTopic("io", "中断")])),
                ).analyze("exam-1", task=task)

            self.assertEqual("pending", manager.get("exam-1").analysis_status)
            self.assertIsNone(manager.get_analysis("exam-1"))


if __name__ == "__main__":
    unittest.main()
