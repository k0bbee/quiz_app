import unittest

from ai.generation_source_resolver import GenerationSourceResolver
from ai.question_plan import QuestionPlanItem


def _ref(chunk_id="source-1", source_file="io.pdf", page=3, excerpt="DMA content"):
    return {
        "chunk_id": chunk_id,
        "source_file": source_file,
        "page_or_slide": page,
        "excerpt": excerpt,
    }


class GenerationSourceResolverTests(unittest.TestCase):
    def test_valid_model_ref_resolves_to_authoritative_registry_record(self):
        authoritative = _ref(excerpt="Authoritative course excerpt")
        resolver = GenerationSourceResolver([authoritative], {"io": [authoritative]})
        plan_item = QuestionPlanItem(
            plan_id="plan-1",
            topic_id="io",
            topic_title="I/O",
            question_type="multiple_choice",
            difficulty="medium",
            target_skill="concept",
            evidence_chunk_ids=("source-1",),
        )

        refs, status, invalid = resolver.resolve(
            {"source_refs": [_ref(excerpt="Model supplied text")]},
            plan_item=plan_item,
        )

        self.assertEqual("valid_model_ref", status)
        self.assertEqual([], invalid)
        self.assertEqual("Authoritative course excerpt", refs[0]["excerpt"])

    def test_forged_model_ref_is_rejected_and_uses_plan_fallback(self):
        authoritative = _ref()
        resolver = GenerationSourceResolver([authoritative], {"io": [authoritative]})
        plan_item = QuestionPlanItem(
            plan_id="plan-1",
            topic_id="io",
            topic_title="I/O",
            question_type="multiple_choice",
            difficulty="medium",
            target_skill="concept",
            evidence_chunk_ids=("source-1",),
        )

        refs, status, invalid = resolver.resolve(
            {"source_refs": [_ref(source_file="forged.pdf")]},
            plan_item=plan_item,
            plan_refs=[authoritative],
        )

        self.assertEqual("invalid_model_ref", status)
        self.assertEqual(["source-1"], invalid)
        self.assertEqual([authoritative], refs)

    def test_missing_model_ref_prefers_plan_then_global_evidence(self):
        global_ref = _ref("global-1", "course.pdf")
        plan_ref = _ref("plan-1", "topic.pdf")
        resolver = GenerationSourceResolver([global_ref], {})

        refs, status, invalid = resolver.resolve({}, plan_refs=[plan_ref])
        self.assertEqual(([plan_ref], "fallback_plan_evidence", []), (refs, status, invalid))

        refs, status, invalid = resolver.resolve({})
        self.assertEqual(([global_ref], "fallback_global_evidence", []), (refs, status, invalid))

    def test_source_sanitization_bounds_excerpt_and_normalizes_page(self):
        resolver = GenerationSourceResolver([], {})

        refs, status, invalid = resolver.resolve({
            "source_refs": [{
                "chunk_id": "model-only",
                "page_or_slide": "7",
                "excerpt": "x" * 500,
            }]
        })

        self.assertEqual("valid_model_ref", status)
        self.assertEqual([], invalid)
        self.assertEqual(7, refs[0]["page_or_slide"])
        self.assertLessEqual(len(refs[0]["excerpt"]), 321)


if __name__ == "__main__":
    unittest.main()
