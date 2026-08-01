import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai.exam_plan import ExamGenerationPlan
from core.session_retry import SessionRetryMode
from models.question import Question
from utils.constants import Difficulty, QuestionType
from ui.first_run_controller import FirstRunController
from ui.generation_workspace_controller import (
    GenerationWorkspaceController,
    find_generation_gap_topic_ids,
)
from ui.history_protection_controller import HistoryProtectionController
from ui.main_window import MainWindow
from ui.question_set_action_controller import QuestionSetActionController
from ui.result_flow_controller import ResultFlowController


pytestmark = pytest.mark.qt


class HistoryProtectionControllerTests(unittest.TestCase):
    def test_message_reports_failed_records_and_bounded_error_details(self):
        report = SimpleNamespace(
            failed_progress_ids=("one", "two"),
            errors=("first", "second", "third", "fourth"),
        )
        host = SimpleNamespace(
            startup_migration_report=report,
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text
            ),
        )

        message = HistoryProtectionController(host).message()

        self.assertIn("2 条旧练习记录", message)
        self.assertIn("first", message)
        self.assertIn("third", message)
        self.assertNotIn("fourth", message)


class FirstRunControllerTests(unittest.TestCase):
    def test_practice_candidates_stay_with_the_current_course(self):
        current_set = SimpleNamespace(
            set_id="set-current",
            questions=["q-current"],
            metadata={"course_id": "course-current"},
        )
        other_set = SimpleNamespace(
            set_id="set-other",
            questions=["q-other"],
            metadata={"course_id": "course-other"},
        )
        questions = {
            "q-current": SimpleNamespace(question_id="q-current"),
            "q-other": SimpleNamespace(question_id="q-other"),
        }
        host = SimpleNamespace(
            course_context=SimpleNamespace(
                current_course_id=lambda: "course-current",
            ),
            set_manager=SimpleNamespace(
                load_all=lambda: [current_set, other_set]
            ),
            question_bank=SimpleNamespace(
                get_many=lambda question_ids, course_id: [
                    questions[question_id]
                    for question_id in question_ids
                    if course_id == "course-current"
                ],
            ),
        )

        candidates = FirstRunController(host).practice_candidates()

        self.assertEqual([(current_set, ["q-current"])], candidates)


class ResultFlowControllerTests(unittest.TestCase):
    def test_retries_only_incorrect_non_skipped_questions(self):
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
                ),
            ),
            lang_manager=SimpleNamespace(
                get_text=lambda zh, en: zh,
            ),
            study_flow=StudyFlowRecorder(),
            course_context=SimpleNamespace(
                current_course_id=lambda: "course-a",
            ),
        )

        ResultFlowController(host).retry(SessionRetryMode.INCORRECT)

        assert started["questions"] == [wrong_question]
        assert started["intent"].question_ids == ("q-wrong",)
        assert started["intent"].source == "results_incorrect"
        assert "错题" in started["label"]


class QuestionSetActionControllerTests(unittest.TestCase):
    def test_exports_selected_set_with_current_language(self):
        question_set = SimpleNamespace(
            set_id="set-1",
            questions=["q-1"],
        )
        question = SimpleNamespace(question_id="q-1")
        exported = {}
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        output_path = Path(temp_dir.name) / "exam.md"

        class FileDialog:
            @staticmethod
            def getSaveFileName(*_args):
                return str(output_path), ""

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
            "path": output_path,
            "question_set": question_set,
            "questions": [question],
            "lang": "zh",
            "include_answers": True,
        }
        assert len(MessageBox.information_calls) == 1


class GenerationWorkspaceControllerTests(unittest.TestCase):
    def test_generation_gap_scan_uses_exam_scope_and_question_index(self):
        course = SimpleNamespace(
            course_id="course-1",
            topics=[
                SimpleNamespace(topic_id="cache"),
                SimpleNamespace(topic_id="process"),
                SimpleNamespace(topic_id="io"),
            ],
            exam_topics=lambda: [
                SimpleNamespace(topic_id="cache"),
                SimpleNamespace(topic_id="process"),
            ],
        )
        bank = SimpleNamespace(
            topic_index=lambda course_id: {
                "q-1": ("cache", "Cache"),
                "q-2": ("io", "I/O"),
            }
        )

        self.assertEqual(
            ("process",),
            find_generation_gap_topic_ids(course, bank),
        )

    def test_prepare_attaches_generation_gaps_to_dialog(self):
        course = SimpleNamespace(
            course_id="course-1",
            topics=[SimpleNamespace(topic_id="cache"), SimpleNamespace(topic_id="process")],
            exam_topics=lambda: [SimpleNamespace(topic_id="cache"), SimpleNamespace(topic_id="process")],
        )
        dialog = SimpleNamespace(set_generation_gap_topics=Mock())
        preparation = SimpleNamespace(ok=True, dialog=dialog, course_project=course)
        host = SimpleNamespace(
            lang_manager=SimpleNamespace(get_text=lambda zh_text, _en_text: zh_text),
            settings_screen=SimpleNamespace(settings_snapshot=lambda: {}),
            course_context=SimpleNamespace(generation_context=lambda: ("# Course", [], course)),
            task_center=None,
            question_bank=SimpleNamespace(
                topic_index=lambda course_id: {"q-1": ("cache", "Cache")}
            ),
        )
        launcher = Mock()
        launcher.prepare.return_value = preparation

        with patch(
            "ui.generation_workspace_controller.GenerationLaunchController",
            return_value=launcher,
        ):
            result = GenerationWorkspaceController(host).prepare()

        self.assertIs(preparation, result)
        dialog.set_generation_gap_topics.assert_called_once_with(("process",))

    def test_result_reinforcement_carries_answer_evidence_into_generation(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.course_context.current_course_id = Mock(return_value="course-1")
        window.generation_flow.open = Mock()

        window._on_generate_result_reinforcement({
            "course_id": "course-1",
            "topic_ids": ["cache"],
            "question_count": 3,
            "signals": [{
                "topic_id": "cache",
                "question_ids": ["q-1"],
                "observed_wrong_answers": ["B"],
            }],
        })

        call = window.generation_flow.open.call_args
        instruction = call.kwargs["recovery_context"]["runtime_instruction"]
        self.assertIn("q-1", instruction)
        self.assertIn("B", instruction)
        self.assertIn("不要复述原题", instruction)
        self.assertTrue(call.kwargs["start_after_save"])

    def test_sync_draft_persists_the_explicit_publish_destination(self):
        question = Question(
            question_id="draft-q",
            type=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {"stem": "草稿题", "options": ["正确", "错误"]},
                "en": {"stem": "Draft", "options": ["True", "False"]},
            },
            correct_answer=True,
            topic="topic-io",
        )
        store = Mock()
        host = SimpleNamespace(generation_draft_store=store)
        dialog = SimpleNamespace(
            generated_questions=[question],
            question_set_title=lambda: "补强题集",
            build_exam_plan=lambda: ExamGenerationPlan(
                question_count=3,
                selected_topics=("topic-io",),
            ),
            _review_warnings_only=False,
            publish_destination="practice_now",
            review_state={"draft-q": "rejected"},
            _generation_draft_id="session-reinforcement",
        )
        course = SimpleNamespace(course_id="course-1")

        saved = GenerationWorkspaceController(host).sync_draft(
            dialog,
            course,
            source="reinforcement",
        )

        self.assertTrue(saved)
        self.assertEqual(
            "practice_now",
            store.save.call_args.kwargs["publish_destination"],
        )
        self.assertEqual(
            {"draft-q": "rejected"},
            store.save.call_args.kwargs["review_state"],
        )
        self.assertEqual(
            "session-reinforcement",
            store.save.call_args.kwargs["draft_id"],
        )

    def test_main_window_reuses_one_generation_controller(self):
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertIsInstance(
            window.generation_flow,
            GenerationWorkspaceController,
        )

    def test_open_reuses_the_active_course_generation_workspace(self):
        workspace = Mock()
        workspace.generation_widget.return_value = object()
        host = SimpleNamespace(
            _generation_workspace=workspace,
            SCREEN_GENERATION=8,
            navigate_to=Mock(return_value=True),
        )

        opened = GenerationWorkspaceController(host).open()

        self.assertTrue(opened)
        host.navigate_to.assert_called_once_with(
            8,
            allow_first_run_redirect=False,
        )

    def test_open_switches_to_a_new_session_without_destroying_the_active_one(self):
        active = SimpleNamespace(
            course_id="course-a",
            _generation_draft_id="session-a",
            _draft_source="course_hub_gap",
        )
        workspace = Mock()
        workspace.course_id = "course-a"
        workspace.generation_widget.return_value = active
        dialog = SimpleNamespace(
            _generation_draft_id="session-b",
            accepted=Mock(),
            rejected=Mock(),
        )
        course = SimpleNamespace(course_id="course-a", title="课程 A")
        host = SimpleNamespace(
            _generation_workspace=workspace,
            SCREEN_GENERATION=8,
            navigate_to=Mock(return_value=True),
            course_manager=SimpleNamespace(
                current=lambda: course,
            ),
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text,
            ),
        )

        controller = GenerationWorkspaceController(host)
        with patch.object(
            controller,
            "configure",
            return_value=(dialog, course, False, "result_reinforcement"),
        ) as configure:
            opened = controller.open(draft_source="result_reinforcement")

        self.assertTrue(opened)
        configure.assert_called_once()
        workspace.show_generation_widget.assert_called_once_with(
            dialog,
            course_id="course-a",
            course_title="课程 A",
            draft_id="session-b",
        )
        workspace.clear_generation_widget.assert_not_called()

    def test_open_with_a_new_plan_does_not_reuse_same_source_session(self):
        active = SimpleNamespace(
            course_id="course-a",
            _generation_draft_id="session-a",
            _draft_source="course_hub_gap",
        )
        workspace = Mock()
        workspace.course_id = "course-a"
        workspace.generation_widget.return_value = active
        dialog = SimpleNamespace(
            _generation_draft_id="session-b",
            accepted=Mock(),
            rejected=Mock(),
        )
        course = SimpleNamespace(course_id="course-a", title="课程 A")
        host = SimpleNamespace(
            _generation_workspace=workspace,
            SCREEN_GENERATION=8,
            navigate_to=Mock(return_value=True),
            course_manager=SimpleNamespace(current=lambda: course),
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text,
            ),
        )
        controller = GenerationWorkspaceController(host)
        plan = ExamGenerationPlan(
            question_count=4,
            selected_topics=("topic-a",),
        )

        with patch.object(
            controller,
            "configure",
            return_value=(dialog, course, False, "course_hub_gap"),
        ) as configure:
            opened = controller.open(
                initial_plan=plan,
                draft_source="course_hub_gap",
            )

        self.assertTrue(opened)
        configure.assert_called_once()
        workspace.show_generation_widget.assert_called_once_with(
            dialog,
            course_id="course-a",
            course_title="课程 A",
            draft_id="session-b",
        )

    def test_open_selects_an_existing_hidden_session_by_draft_id(self):
        workspace = Mock()
        workspace.course_id = "course-a"
        workspace.generation_widget.return_value = SimpleNamespace(
            _generation_draft_id="session-b",
            _draft_source="result_reinforcement",
        )
        workspace.session_course_id.return_value = "course-a"
        workspace.select_session.return_value = True
        host = SimpleNamespace(
            _generation_workspace=workspace,
            SCREEN_GENERATION=8,
            navigate_to=Mock(return_value=True),
            course_manager=SimpleNamespace(
                current=lambda: SimpleNamespace(course_id="course-a"),
            ),
        )

        controller = GenerationWorkspaceController(host)
        with patch.object(controller, "configure") as configure:
            opened = controller.open(draft_id="session-b")

        self.assertTrue(opened)
        workspace.select_session.assert_called_once_with("session-b")
        configure.assert_not_called()
        host.navigate_to.assert_called_once_with(
            8,
            allow_first_run_redirect=False,
        )

    def test_configure_rejects_missing_explicit_draft(self):
        course = SimpleNamespace(course_id="course-a")
        host = SimpleNamespace(
            course_manager=SimpleNamespace(current=lambda: course),
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text,
            ),
            _last_generation_launch_error="",
        )
        controller = GenerationWorkspaceController(host)
        with patch.object(controller, "draft_by_id", return_value=None), patch.object(
            controller, "prepare"
        ) as prepare:
            configured = controller.configure(
                draft_id="missing-draft",
                present_error=False,
            )

        self.assertIsNone(configured)
        self.assertIn("找不到指定", host._last_generation_launch_error)
        prepare.assert_not_called()

    def test_configure_rejects_explicit_draft_from_another_course(self):
        course = SimpleNamespace(course_id="course-a")
        foreign_draft = SimpleNamespace(course_id="course-b")
        host = SimpleNamespace(
            course_manager=SimpleNamespace(current=lambda: course),
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text,
            ),
            _last_generation_launch_error="",
        )
        controller = GenerationWorkspaceController(host)
        with patch.object(
            controller, "draft_by_id", return_value=foreign_draft
        ), patch.object(controller, "prepare") as prepare:
            configured = controller.configure(
                draft_id="foreign-draft",
                present_error=False,
            )

        self.assertIsNone(configured)
        self.assertIn("不匹配", host._last_generation_launch_error)
        prepare.assert_not_called()

    def test_reject_during_workspace_shutdown_does_not_navigate_away(self):
        workspace = SimpleNamespace(
            _shutting_down=True,
            clear_generation_widget=Mock(),
            generation_widget=Mock(return_value=object()),
        )
        host = SimpleNamespace(
            _generation_workspace=workspace,
            _generation_close_pending=True,
            navigate_to=Mock(),
        )
        dialog = SimpleNamespace(deleteLater=Mock())
        course = SimpleNamespace(course_id="course-a")
        controller = GenerationWorkspaceController(host)

        controller.reject(
            dialog,
            course,
            draft_source="manual",
            material_pack=object(),
        )

        host.navigate_to.assert_not_called()
        self.assertTrue(host._generation_close_pending)
        dialog.deleteLater.assert_called_once_with()

    def test_open_starts_a_new_session_for_another_course(self):
        workspace = Mock()
        workspace.generation_widget.return_value = object()
        workspace.course_id = "course-a"
        dialog = SimpleNamespace(
            _generation_draft_id="session-b",
            accepted=Mock(),
            rejected=Mock(),
        )
        course = SimpleNamespace(course_id="course-b", title="课程 B")
        host = SimpleNamespace(
            _generation_workspace=workspace,
            SCREEN_GENERATION=8,
            navigate_to=Mock(return_value=True),
            course_manager=SimpleNamespace(
                current=lambda: course,
            ),
            lang_manager=SimpleNamespace(
                get_text=lambda zh_text, _en_text: zh_text,
            ),
        )

        controller = GenerationWorkspaceController(host)
        with patch.object(
            controller,
            "configure",
            return_value=(dialog, course, False, "manual"),
        ) as configure:
            opened = controller.open()

        self.assertTrue(opened)
        configure.assert_called_once()
        workspace.show_generation_widget.assert_called_once_with(
            dialog,
            course_id="course-b",
            course_title="课程 B",
            draft_id="session-b",
        )
