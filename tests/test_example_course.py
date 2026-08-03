import tempfile
import unittest
from pathlib import Path

from core.example_course import (
    EXAMPLE_COURSE_ID,
    EXAMPLE_SET_ID,
    install_example_course,
)
from models.course_project import CourseProjectManager
from models.question import QuestionBank
from models.question_set import SetManager


class ExampleCourseTests(unittest.TestCase):
    def test_install_creates_a_complete_offline_practice_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(str(root / "courses"))
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))

            project, question_set = install_example_course(
                course_manager=course_manager,
                question_bank=question_bank,
                set_manager=set_manager,
            )

            self.assertEqual(EXAMPLE_COURSE_ID, project.course_id)
            self.assertEqual("示例课程：有效学习方法", project.title)
            self.assertEqual(3, len(project.topics))
            self.assertEqual(EXAMPLE_SET_ID, question_set.set_id)
            self.assertEqual(10, len(question_set.questions))
            questions = question_bank.get_many(
                question_set.questions,
                course_id=project.course_id,
            )
            self.assertEqual(10, len(questions))
            self.assertEqual(
                {project.course_id},
                {
                    str((question.metadata or {}).get("course_id", ""))
                    for question in questions
                },
            )
            self.assertEqual(EXAMPLE_COURSE_ID, course_manager.current().course_id)

    def test_install_is_idempotent_and_does_not_duplicate_questions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(str(root / "courses"))
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))
            first = install_example_course(
                course_manager=course_manager,
                question_bank=question_bank,
                set_manager=set_manager,
            )
            second = install_example_course(
                course_manager=course_manager,
                question_bank=question_bank,
                set_manager=set_manager,
            )

            self.assertEqual(first[0].course_id, second[0].course_id)
            self.assertEqual(first[1].questions, second[1].questions)
            self.assertEqual(10, len(question_bank.load_all()))
            self.assertEqual(1, len(set_manager.load_all()))


if __name__ == "__main__":
    unittest.main()
