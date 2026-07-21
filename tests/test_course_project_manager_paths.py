import tempfile
import unittest
from pathlib import Path

from models.course_project import CourseProject, CourseProjectManager, CourseTopic


class CourseProjectManagerPathTests(unittest.TestCase):
    def test_current_course_pointer_can_be_isolated_with_project_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_file = root / "state" / "current_course.json"
            manager = CourseProjectManager(
                str(root / "courses"),
                current_course_file=current_file,
            )
            project = CourseProject(
                course_id="demo-course",
                title="演示课程",
                source_folder="",
                summary_markdown="# 演示课程\n",
                summary_path="",
                topics=[CourseTopic("demo-topic", "演示主题")],
                documents=[],
                created_at="2026-07-21T00:00:00+00:00",
                updated_at="2026-07-21T00:00:00+00:00",
            )

            self.assertTrue(manager.save(project))
            self.assertEqual(project.course_id, manager.current().course_id)
            self.assertTrue(current_file.exists())

            self.assertTrue(manager.delete(project.course_id))
            self.assertFalse(current_file.exists())


if __name__ == "__main__":
    unittest.main()
