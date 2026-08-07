import unittest

from ai.course_qa import CourseQAError, CourseQAService
from models.course_project import CourseProject, CourseTopic


def make_project(*, selected=None, with_source=True):
    project = CourseProject(
        course_id="course-qa",
        title="Operating Systems",
        source_folder="C:/materials",
        summary_markdown="# I/O\nDMA transfers data without CPU copying every byte.",
        summary_path="C:/materials/summary.md",
        topics=[
            CourseTopic(
                "io",
                "I/O",
                keywords=["DMA", "interrupt"],
                aliases=["input output"],
            ),
            CourseTopic("memory", "Memory", keywords=["page table"], aliases=["页表"]),
        ],
        documents=[],
        created_at="",
        updated_at="",
    )
    if selected is not None:
        project.set_exam_scope("selected", selected)
    if with_source:
        project.documents = [{
            "_source_index": [{
                "chunk_id": "source-1",
                "course_id": project.course_id,
                "source_file": "lecture.pdf",
                "source_type": "pdf",
                "page_or_slide": 4,
                "heading": "I/O and DMA",
                "text": "DMA transfers blocks while the CPU can do other work.",
                "terms": ["dma", "cpu"],
                "topic_ids": ["io"],
                "content_hash": "abcdef1234567890",
            }],
        }]
    return project


class FakeClient:
    def __init__(self, response="回答 [来源 1]"):
        self.response = response
        self.last_error = ""
        self.messages = []
        self.cancelled = False

    def generate(self, messages, **kwargs):
        self.messages = messages
        return self.response

    def cancel(self):
        self.cancelled = True


class CourseQATests(unittest.TestCase):
    def test_ask_is_scoped_to_exam_topics_and_returns_verified_sources(self):
        client = FakeClient()
        response = CourseQAService(client, make_project()).ask("DMA 如何减轻 CPU 搬运？")

        self.assertEqual("回答 [来源 1]", response.answer)
        self.assertEqual(("source-1",), tuple(ref["chunk_id"] for ref in response.source_refs))
        self.assertEqual("cited", response.citation_status)
        self.assertIn("I/O and DMA", client.messages[-1]["content"])
        self.assertIn("只能依据", client.messages[0]["content"])

    def test_ask_rejects_topics_outside_selected_exam_scope(self):
        client = FakeClient()
        service = CourseQAService(client, make_project(selected=["io"]))

        with self.assertRaises(CourseQAError) as raised:
            service.ask("页表如何完成地址转换？")

        self.assertEqual("QA-SCOPE-001", raised.exception.error.code)
        self.assertEqual([], client.messages)

    def test_ask_reports_invalid_citation_without_trusting_unknown_sources(self):
        response = CourseQAService(
            FakeClient("回答 [来源 9]"),
            make_project(),
        ).ask("DMA 是什么？")

        self.assertEqual("invalid", response.citation_status)
        self.assertEqual((9,), response.invalid_citation_numbers)
        self.assertEqual((), response.source_refs)

    def test_ask_requires_question_and_limits_oversized_input(self):
        service = CourseQAService(FakeClient(), make_project())

        for question in ("", "x" * 4001):
            with self.subTest(question_length=len(question)):
                with self.assertRaises(CourseQAError) as raised:
                    service.ask(question)
                self.assertEqual("QA-INPUT-001", raised.exception.error.code)

    def test_ask_reports_missing_course_context(self):
        project = make_project(with_source=False)
        project.summary_markdown = ""

        with self.assertRaises(CourseQAError) as raised:
            CourseQAService(FakeClient(), project).ask("DMA 是什么？")

        self.assertEqual("QA-CONTEXT-001", raised.exception.error.code)

    def test_cancel_delegates_to_the_active_llm_client(self):
        client = FakeClient()
        CourseQAService(client, make_project()).cancel()

        self.assertTrue(client.cancelled)


if __name__ == "__main__":
    unittest.main()
