import tempfile
import unittest
from pathlib import Path

from core.example_course import (
    EXAMPLE_COURSE_ID,
    EXAMPLE_MATERIAL_FILENAME,
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
            self.assertEqual(1, len(project.documents))
            material_path = Path(project.documents[0]["path"])
            self.assertEqual(EXAMPLE_MATERIAL_FILENAME, material_path.name)
            self.assertTrue(material_path.is_file())
            self.assertIn("主动回忆", material_path.read_text(encoding="utf-8"))
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
            for question in questions:
                refs = (question.metadata or {}).get("source_refs", [])
                self.assertEqual(1, len(refs))
                self.assertEqual(EXAMPLE_MATERIAL_FILENAME, refs[0]["source_file"])
                self.assertTrue(refs[0]["heading"])
                self.assertTrue(refs[0]["excerpt"])
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

    def test_install_upgrades_a_legacy_example_with_missing_source_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(str(root / "courses"))
            question_bank = QuestionBank(str(root / "questions"))
            set_manager = SetManager(str(root / "sets"))
            _project, question_set = install_example_course(
                course_manager=course_manager,
                question_bank=question_bank,
                set_manager=set_manager,
            )
            legacy_project = course_manager.get(EXAMPLE_COURSE_ID)
            legacy_project.source_folder = ""
            legacy_project.documents = []
            self.assertTrue(course_manager.save(legacy_project))
            legacy_questions = question_bank.get_many(question_set.questions)
            for question in legacy_questions:
                question.metadata.pop("source_refs", None)
            self.assertEqual(len(legacy_questions), question_bank.save_many(legacy_questions))

            upgraded, _question_set = install_example_course(
                course_manager=course_manager,
                question_bank=question_bank,
                set_manager=set_manager,
            )

            self.assertEqual(1, len(upgraded.documents))
            self.assertTrue(Path(upgraded.documents[0]["path"]).is_file())
            upgraded_questions = question_bank.get_many(
                question_set.questions,
                course_id=EXAMPLE_COURSE_ID,
            )
            self.assertTrue(all(
                (question.metadata or {}).get("source_refs")
                for question in upgraded_questions
            ))


if __name__ == "__main__":
    unittest.main()
