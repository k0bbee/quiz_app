import unittest
from types import SimpleNamespace

from ui.course_context_controller import CourseContextController


class CourseContextControllerTests(unittest.TestCase):
    def test_generation_context_uses_the_selected_exam_scope(self):
        selected_topic = SimpleNamespace(topic_id="io", title="I/O")
        course = SimpleNamespace(
            course_id="course-os",
            summary_markdown="# Operating Systems",
            exam_scope_mode="selected",
            topics=[SimpleNamespace(topic_id="all", title="All")],
            exam_topics=lambda: [selected_topic],
        )
        host = SimpleNamespace(
            course_manager=SimpleNamespace(current=lambda: course),
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text
            ),
        )

        content, topics, returned_course = CourseContextController(
            host
        ).generation_context()

        self.assertEqual("# Operating Systems", content)
        self.assertEqual([selected_topic], topics)
        self.assertIs(course, returned_course)


if __name__ == "__main__":
    unittest.main()
