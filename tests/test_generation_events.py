import unittest

from ai.generation_events import (
    CompletedEvent,
    FailedEvent,
    PartialResultEvent,
    ProgressEvent,
    QuestionsReadyEvent,
)
from ai.generation_report import GenerationReport


class GenerationEventTests(unittest.TestCase):
    def test_progress_and_failure_events_preserve_payloads(self):
        progress = ProgressEvent("Generating question 1/3")
        failure = FailedEvent("provider timed out")

        self.assertEqual("Generating question 1/3", progress.message)
        self.assertEqual("provider timed out", failure.error)

    def test_question_events_snapshot_mutable_input_lists(self):
        first = object()
        questions = [first]
        ready = QuestionsReadyEvent.from_questions(questions)
        completed = CompletedEvent.from_questions(questions)
        questions.append(object())

        self.assertEqual((first,), ready.questions)
        self.assertEqual((first,), completed.questions)

    def test_partial_event_keeps_questions_and_structured_report(self):
        question = object()
        report = GenerationReport(
            requested_count=2,
            accepted_count=1,
            rejected_count=0,
            attempts=1,
            max_attempts=3,
            status="partial",
        )

        event = PartialResultEvent.from_questions([question], report)

        self.assertEqual((question,), event.questions)
        self.assertIs(report, event.report)


if __name__ == "__main__":
    unittest.main()
