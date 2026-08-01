import unittest

from models.remediation import RemediationRequest, TopicSignal


class RemediationRequestTests(unittest.TestCase):
    def test_request_round_trips_concrete_answer_signals(self):
        request = RemediationRequest(
            course_id="course-1",
            signals=(
                TopicSignal(
                    topic_id="cache",
                    question_ids=("q-1",),
                    observed_wrong_answers=("B",),
                    unsure_question_ids=("q-2",),
                ),
            ),
            max_questions=8,
        )

        restored = RemediationRequest.from_mapping(request.to_dict())

        self.assertEqual(request, restored)
        self.assertIn("q-1", request.instruction("zh"))
        self.assertIn("B", request.instruction("zh"))
        self.assertIn("不要复述原题", request.instruction("zh"))


if __name__ == "__main__":
    unittest.main()
