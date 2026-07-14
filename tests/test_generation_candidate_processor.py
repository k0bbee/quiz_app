import unittest

from ai.generation_candidate_processor import GenerationCandidateProcessor
from ai.generation_config import GenerationConfig
from ai.generation_quota_tracker import GenerationQuotaTracker
from ai.generation_source_resolver import GenerationSourceResolver
from ai.question_generation_service import QuestionGenerationService


def raw_question(*, topic="io", difficulty="medium"):
    return {
        "type": "multiple_choice",
        "difficulty": difficulty,
        "topic": topic,
        "subtopic": "interrupts",
        "correct_answer": "A",
        "bilingual": {
            "zh": {
                "stem": "哪一种机制允许设备在工作完成后通知处理器？",
                "options": ["A. 中断", "B. 忙等待", "C. 缓存", "D. 分页"],
                "explanation": "中断允许设备在操作完成后主动通知处理器，处理器无需持续轮询设备状态。",
            },
            "en": {
                "stem": "Which mechanism lets a device notify the processor after completing work?",
                "options": ["A. Interrupt", "B. Busy wait", "C. Cache", "D. Paging"],
                "explanation": "An interrupt lets the device notify the processor after completion without continuous polling.",
            },
        },
    }


def quota_tracker(*, evidence_refs_by_topic=None):
    return GenerationQuotaTracker(
        GenerationConfig(
            question_type_weights={"multiple_choice": 100},
            difficulty_weights={"medium": 100},
            topic_weights={"io": 100},
        ),
        topics=["io"],
        count=1,
        evidence_refs_by_topic=evidence_refs_by_topic,
    )


class GenerationCandidateProcessorTests(unittest.TestCase):
    def test_accepts_candidate_and_attaches_plan_course_and_trusted_source_metadata(self):
        source_ref = {
            "chunk_id": "chunk-io-1",
            "source_file": "io.pdf",
            "page_or_slide": 12,
            "heading": "Interrupt-driven I/O",
            "excerpt": "A device raises an interrupt after completing an operation.",
        }
        tracker = quota_tracker(evidence_refs_by_topic={"io": [source_ref]})
        processor = GenerationCandidateProcessor(
            QuestionGenerationService(["io"]),
            tracker,
            GenerationSourceResolver([source_ref], {"io": [source_ref]}),
            ai_model="test-model",
            course_metadata={"course_id": "course-os", "course_title": "Operating Systems"},
        )

        result = processor.process(raw_question())

        self.assertTrue(result.accepted)
        self.assertEqual("", result.rejection_reason)
        self.assertEqual("io", result.question.topic_id())
        self.assertEqual("test-model", result.question.metadata["ai_model"])
        self.assertEqual("course-os", result.question.metadata["course_id"])
        self.assertEqual("plan-001", result.question.metadata["plan_id"])
        self.assertEqual("matched_by_shape", result.question.metadata["plan_match_status"])
        self.assertEqual("fallback_plan_evidence", result.question.metadata["source_ref_status"])
        self.assertEqual([source_ref], result.question.metadata["source_refs"])
        self.assertEqual([], tracker.missing_plan_items())

    def test_rejects_unselected_topic_without_consuming_quota(self):
        tracker = quota_tracker()
        processor = GenerationCandidateProcessor(
            QuestionGenerationService(["io"]),
            tracker,
            GenerationSourceResolver(),
            ai_model="test-model",
        )
        before = tracker.missing_quotas()

        result = processor.process(raw_question(topic="raid"))

        self.assertFalse(result.accepted)
        self.assertIsNone(result.question)
        self.assertIn("not selected", result.rejection_reason)
        self.assertEqual(before, tracker.missing_quotas())
        self.assertEqual(1, len(tracker.missing_plan_items()))

    def test_returns_stable_malformed_rejection_for_invalid_enum_value(self):
        processor = GenerationCandidateProcessor(
            QuestionGenerationService(["io"]),
            quota_tracker(),
            GenerationSourceResolver(),
            ai_model="test-model",
        )

        result = processor.process(raw_question(difficulty="impossible"))

        self.assertFalse(result.accepted)
        self.assertEqual("malformed question", result.rejection_reason)
        self.assertIn("impossible", result.detail)


if __name__ == "__main__":
    unittest.main()
