import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from ai.batch_generator import GenerationWorker
from ai.generation_config import GenerationConfig
from ai.generation_source_resolver import GenerationSourceResolver
from core.current_events import CurrentEventCandidate, CurrentEventMaterialPack
from core.question_set_builder import build_ai_question_set
from models.question import Question
from tests.test_current_events import law_project
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


def material_pack():
    candidate = CurrentEventCandidate.create(
        url="https://law.example/rule",
        title="Agency rule faces judicial review",
        context="A court reviews a regulation adopted through agency rulemaking.",
        seen_at="2026-07-15T05:00:00+00:00",
        domain="law.example",
        language="ENGLISH",
        query="agency regulation",
        retrieved_at="2026-07-15T06:00:00+00:00",
    )
    return CurrentEventMaterialPack.create(
        course_id="public-law",
        course_updated_at="2026-07-15T00:00:00+00:00",
        query="agency regulation",
        candidates=[candidate],
        selected_candidate_ids=[candidate.candidate_id],
        created_at="2026-07-15T06:01:00+00:00",
    )


class FakeClient:
    model = "test-model"


class CurrentEventGenerationTests(unittest.TestCase):
    def test_worker_combines_course_evidence_with_reviewed_untrusted_material(self):
        pack = material_pack()
        worker = GenerationWorker(
            FakeClient(),
            "course content",
            ["administrative_law"],
            3,
            "medium",
            course_project=law_project(),
            material_pack=pack,
        )

        with patch("ai.batch_generator.retrieve_course_context", return_value="COURSE EVIDENCE"), \
             patch("ai.batch_generator.retrieve_course_source_refs", return_value=[]):
            context = worker._build_course_context()

        self.assertIn("COURSE EVIDENCE", context)
        self.assertIn("非可信外部材料", context)
        self.assertIn("Agency rule faces judicial review", context)
        self.assertIn(pack.selected_candidate_ids[0], context)
        self.assertEqual(pack.pack_id, worker._course_metadata()["material_pack_id"])
        refs, status, invalid = worker._source_resolver.resolve({})
        self.assertEqual("fallback_global_evidence", status)
        self.assertEqual([], invalid)
        self.assertEqual("current_event", refs[0]["source_kind"])
        self.assertEqual(pack.selected_candidate_ids[0], refs[0]["candidate_id"])

    def test_source_resolver_validates_current_event_candidate_ids(self):
        pack = material_pack()
        candidate = pack.selected_candidates()[0]
        resolver = GenerationSourceResolver([{
            "source_kind": "current_event",
            "candidate_id": candidate.candidate_id,
            "url": candidate.url,
            "title": candidate.title,
            "domain": candidate.domain,
            "seen_at": candidate.seen_at,
            "retrieved_at": candidate.retrieved_at,
            "excerpt": candidate.context,
            "review_status": "user_selected",
        }])

        refs, status, invalid = resolver.resolve({
            "source_refs": [{
                "source_kind": "current_event",
                "candidate_id": candidate.candidate_id,
            }]
        })

        self.assertEqual("valid_model_ref", status)
        self.assertEqual([], invalid)
        self.assertEqual(candidate.url, refs[0]["url"])

    def test_dialog_passes_material_pack_to_generation_worker(self):
        class Signal:
            def connect(self, _callback):
                pass

        class FakeWorker:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs
                self.progress = Signal()
                self.question_ready = Signal()
                self.batch_done = Signal()
                self.partial_done = Signal()
                self.error = Signal()
                self.finished = Signal()

            def set_runtime_instruction(self, _instruction):
                pass

            def start(self):
                pass

        pack = material_pack()
        dialog = AIGenerationDialog(
            "course content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=law_project().topics,
            course_project=law_project(),
            material_pack=pack,
        )
        dialog.topic_list.item(0).setCheckState(Qt.CheckState.Checked)

        with patch("ui.dialogs.ai_generation_dialog.GenerationWorker", FakeWorker):
            dialog._start_generation()

        self.assertIs(pack, dialog.worker.kwargs["material_pack"])

    def test_question_set_records_material_pack_identity(self):
        pack = material_pack()
        question = Question(
            question_id="q1",
            type=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {"stem": "该说法是否正确？", "explanation": "这是一段足够完整的中文解释。"},
                "en": {"stem": "Is this statement correct?", "explanation": "This is a sufficiently complete explanation."},
            },
            correct_answer="true",
            topic="administrative_law",
        )

        qset = build_ai_question_set(
            [question],
            selected_difficulty="medium",
            generation_config=GenerationConfig(),
            course_project=law_project(),
            material_pack=pack,
        )

        self.assertEqual(pack.pack_id, qset.metadata["material_pack_id"])


if __name__ == "__main__":
    unittest.main()
