import importlib.util
from types import SimpleNamespace

import pytest

from core.session_retry import SessionRetryMode


pytestmark = pytest.mark.qt


def test_result_flow_retries_only_incorrect_non_skipped_questions():
    assert importlib.util.find_spec("ui.result_flow_controller") is not None

    from ui.result_flow_controller import ResultFlowController

    record = SimpleNamespace(
        answers=[
            SimpleNamespace(
                question_id="q-skipped",
                skipped=True,
                is_correct=False,
            ),
            SimpleNamespace(
                question_id="q-correct",
                skipped=False,
                is_correct=True,
            ),
            SimpleNamespace(
                question_id="q-wrong",
                skipped=False,
                is_correct=False,
            ),
        ]
    )
    wrong_question = SimpleNamespace(question_id="q-wrong")
    started = {}

    class StudyFlowRecorder:
        def start_questions(self, intent, questions, *, label=""):
            started["intent"] = intent
            started["questions"] = questions
            started["label"] = label

    host = SimpleNamespace(
        results_screen=SimpleNamespace(current_record=record),
        question_bank=SimpleNamespace(
            get_many=lambda ids, course_id="": (
                [wrong_question] if list(ids) == ["q-wrong"] else []
            )
        ),
        lang_manager=SimpleNamespace(
            get_text=lambda zh, en: zh,
        ),
        study_flow=StudyFlowRecorder(),
        _current_course_id=lambda: "course-a",
    )

    ResultFlowController(host).retry(SessionRetryMode.INCORRECT)

    assert started["questions"] == [wrong_question]
    assert started["intent"].question_ids == ("q-wrong",)
    assert started["intent"].source == "results_incorrect"
    assert "错题" in started["label"]
