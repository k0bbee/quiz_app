import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.qt


def test_question_set_action_exports_selected_set_with_current_language(tmp_path):
    assert importlib.util.find_spec(
        "ui.question_set_action_controller"
    ) is not None

    from ui.question_set_action_controller import QuestionSetActionController

    question_set = SimpleNamespace(
        set_id="set-1",
        questions=["q-1"],
    )
    question = SimpleNamespace(question_id="q-1")
    exported = {}

    class FileDialog:
        @staticmethod
        def getSaveFileName(*_args):
            return str(tmp_path / "exam.md"), ""

    class Exporter:
        @staticmethod
        def write_markdown(
            output_path,
            selected_set,
            questions,
            *,
            lang,
            include_answers,
        ):
            exported.update(
                path=Path(output_path),
                question_set=selected_set,
                questions=list(questions),
                lang=lang,
                include_answers=include_answers,
            )
            return Path(output_path)

    class MessageBox:
        information_calls = []

        @classmethod
        def information(cls, *args):
            cls.information_calls.append(args)

    host = SimpleNamespace(
        lang_manager=SimpleNamespace(
            current="zh",
            get_text=lambda zh, en: zh,
        ),
        set_manager=SimpleNamespace(get=lambda set_id: question_set),
        question_bank=SimpleNamespace(get_many=lambda ids: [question]),
    )

    controller = QuestionSetActionController(
        host,
        file_dialog=FileDialog,
        message_box=MessageBox,
        exporter=Exporter,
    )
    controller.export_mock_exam("set-1")

    assert exported == {
        "path": tmp_path / "exam.md",
        "question_set": question_set,
        "questions": [question],
        "lang": "zh",
        "include_answers": True,
    }
    assert len(MessageBox.information_calls) == 1
