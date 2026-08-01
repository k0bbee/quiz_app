import unittest

from models.remediation import AnswerEvidence, RemediationRequest, TopicSignal


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
                    source_refs=("lecture-1",),
                    observed_question_stems=("What is cache?",),
                ),
            ),
            max_questions=8,
        )

        restored = RemediationRequest.from_mapping(request.to_dict())

        self.assertEqual(request, restored)
        self.assertIn("q-1", request.instruction("zh"))
        self.assertIn("B", request.instruction("zh"))
        self.assertIn("lecture-1", request.instruction("zh"))
        self.assertIn("What is cache?", request.instruction("zh"))
        self.assertIn("不要复述原题", request.instruction("zh"))

    def test_request_preserves_structured_answer_evidence_for_targeted_generation(self):
        evidence = AnswerEvidence(
            question_id="q-1",
            topic_id="cache",
            question_type="multiple_choice",
            stem="哪种缓存策略命中率更高？",
            options=["A. LRU", "B. 随机"],
            user_answer="B",
            correct_answer="A",
            explanation="局部性使 LRU 更可能保留近期访问数据。",
            source_refs=("lecture-1",),
        )
        request = RemediationRequest(
            course_id="course-1",
            signals=(TopicSignal(topic_id="cache", evidence=(evidence,)),),
        )

        restored = RemediationRequest.from_mapping(request.to_dict())

        self.assertEqual(request, restored)
        instruction = request.instruction("zh")
        self.assertIn("用户答案：B", instruction)
        self.assertIn("正确答案：A", instruction)
        self.assertIn("A. LRU", instruction)
        self.assertIn("局部性", instruction)


if __name__ == "__main__":
    unittest.main()
