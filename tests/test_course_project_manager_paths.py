import tempfile
import unittest
from pathlib import Path

from models.course_project import CourseProject, CourseProjectManager, CourseTopic


class CourseProjectManagerPathTests(unittest.TestCase):
    @staticmethod
    def _project(course_id: str = "demo-course") -> CourseProject:
        return CourseProject(
            course_id=course_id,
            title="演示课程",
            source_folder="",
            summary_markdown="# 演示课程\n",
            summary_path="",
            topics=[CourseTopic("demo-topic", "演示主题")],
            documents=[],
            created_at="2026-07-21T00:00:00+00:00",
            updated_at="2026-07-21T00:00:00+00:00",
        )

    def test_custom_project_directory_keeps_current_pointer_on_same_storage_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = CourseProjectManager(str(root / "courses"))

            self.assertEqual(
                root / "current_course.json",
                manager._current_course_file,
            )

    def test_legacy_course_without_status_remains_active(self):
        payload = self._project().to_dict()
        payload.pop("status")

        restored = CourseProject.from_dict(payload)

        self.assertEqual("active", restored.status)
        self.assertFalse(restored.is_archived)

    def test_current_course_pointer_can_be_isolated_with_project_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_file = root / "state" / "current_course.json"
            manager = CourseProjectManager(
                str(root / "courses"),
                current_course_file=current_file,
            )
            project = self._project()

            self.assertTrue(manager.save(project))
            self.assertEqual(project.course_id, manager.current().course_id)
            self.assertTrue(current_file.exists())

            self.assertTrue(manager.delete(project.course_id))
            self.assertFalse(current_file.exists())

    def test_archived_course_is_hidden_and_cannot_remain_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CourseProjectManager(str(Path(temp_dir) / "courses"))
            project = self._project()
            self.assertTrue(manager.save(project))

            self.assertTrue(manager.archive(project.course_id))

            archived = manager.get(project.course_id)
            self.assertIsNotNone(archived)
            self.assertEqual("archived", archived.status)
            self.assertTrue(archived.is_archived)
            self.assertEqual([], manager.load_all())
            self.assertEqual(
                [project.course_id],
                [
                    item.course_id
                    for item in manager.load_all(include_archived=True)
                ],
            )
            self.assertIsNone(manager.current())
            self.assertFalse(manager.set_current(project.course_id))

    def test_archived_course_can_be_restored_and_selected_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CourseProjectManager(str(Path(temp_dir) / "courses"))
            project = self._project()
            self.assertTrue(manager.save(project))
            self.assertTrue(manager.archive(project.course_id))

            self.assertTrue(manager.restore(project.course_id, make_current=True))

            restored = manager.current()
            self.assertIsNotNone(restored)
            self.assertEqual("active", restored.status)
            self.assertFalse(restored.is_archived)
            self.assertEqual(
                [project.course_id],
                [item.course_id for item in manager.load_all()],
            )


if __name__ == "__main__":
    unittest.main()
