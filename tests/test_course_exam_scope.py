"""Course exam-scope persistence and behavior tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication, QMessageBox

import core.past_exam_prediction as past_exam_prediction
from core.course_initializer import CourseInitializer
from core.document_parser import ExtractedDocument
from core.past_exam_prediction import PastExamPredictionPlanner
from core.today_learning_plan import LearningPlanAction
from models.course_project import CourseProject, CourseTopic
from models.past_exam import (
    PastExamAnalysis,
    PastExamQuestionTypeProfile,
    PastExamTopicProfile,
)
from ui.main_window import MainWindow
from ui.screens.home_screen import HomeScreen


def _project(**overrides) -> CourseProject:
    values = {
        "course_id": "course-systems",
        "title": "Systems",
        "source_folder": "",
        "summary_markdown": "# Systems",
        "summary_path": "",
        "topics": [
            CourseTopic(topic_id="io", title="I/O"),
            CourseTopic(topic_id="memory", title="Memory"),
            CourseTopic(topic_id="concurrency", title="Concurrency"),
        ],
        "documents": [],
        "created_at": "2026-07-14T00:00:00+00:00",
        "updated_at": "2026-07-14T00:00:00+00:00",
    }
    values.update(overrides)
    return CourseProject(**values)


class CourseExamScopeModelTests(unittest.TestCase):
    def test_legacy_payload_defaults_to_all_topics(self):
        payload = _project().to_dict()
        payload.pop("exam_scope_mode", None)
        payload.pop("exam_scope_topic_ids", None)

        restored = CourseProject.from_dict(payload)

        self.assertEqual("all", restored.exam_scope_mode)
        self.assertEqual([], restored.exam_scope_topic_ids)
        self.assertEqual(["io", "memory", "concurrency"], [topic.topic_id for topic in restored.exam_topics()])

    def test_selected_scope_uses_course_order_and_discards_unknown_or_duplicate_ids(self):
        project = _project()

        project.set_exam_scope("selected", ["concurrency", "missing", "io", "concurrency"])

        self.assertEqual("selected", project.exam_scope_mode)
        self.assertEqual(["io", "concurrency"], project.exam_scope_topic_ids)
        self.assertEqual(["io", "concurrency"], [topic.topic_id for topic in project.exam_topics()])

    def test_invalid_persisted_mode_falls_back_to_all(self):
        payload = _project().to_dict()
        payload["exam_scope_mode"] = "mystery"
        payload["exam_scope_topic_ids"] = ["io"]

        restored = CourseProject.from_dict(payload)

        self.assertEqual("all", restored.exam_scope_mode)
        self.assertEqual([], restored.exam_scope_topic_ids)
        self.assertEqual(3, len(restored.exam_topics()))

    def test_selected_scope_stays_selected_when_all_saved_topics_are_removed(self):
        payload = _project().to_dict()
        payload["exam_scope_mode"] = "selected"
        payload["exam_scope_topic_ids"] = ["removed-topic"]

        restored = CourseProject.from_dict(payload)

        self.assertEqual("selected", restored.exam_scope_mode)
        self.assertEqual([], restored.exam_scope_topic_ids)
        self.assertEqual([], restored.exam_topics())

    def test_nonempty_course_rejects_empty_selected_scope(self):
        project = _project()

        with self.assertRaisesRegex(ValueError, "at least one topic"):
            project.set_exam_scope("selected", [])

    def test_empty_course_allows_empty_selected_scope(self):
        project = _project(topics=[])

        project.set_exam_scope("selected", [])

        self.assertEqual("selected", project.exam_scope_mode)
        self.assertEqual([], project.exam_topics())

    def test_scope_round_trip_preserves_stable_topic_ids(self):
        project = _project()
        project.set_exam_scope("selected", ["memory", "io"])

        restored = CourseProject.from_dict(project.to_dict())

        self.assertEqual("selected", restored.exam_scope_mode)
        self.assertEqual(["io", "memory"], restored.exam_scope_topic_ids)
        self.assertEqual(["io", "memory"], [topic.topic_id for topic in restored.exam_topics()])


class CourseExamScopeRegenerationTests(unittest.TestCase):
    def test_regeneration_preserves_selected_stable_ids_and_drops_removed_topics(self):
        project = _project(source_folder="source")
        project.set_exam_scope("selected", ["io", "memory"])
        document = ExtractedDocument(
            path="source/systems.md",
            title="Systems",
            extension=".md",
            text="I/O interrupt DMA processor scheduling " * 20,
            pages=["I/O interrupt DMA processor scheduling " * 20],
        )

        class Parser:
            @staticmethod
            def parse_folder(_folder, task=None):
                return [document]

        class Manager:
            @staticmethod
            def save(_project, make_current=True):
                return True

        regenerated_topics = [
            CourseTopic(topic_id="io", title="Input and Output"),
            CourseTopic(topic_id="cpu", title="Processor"),
        ]
        pipeline = Mock()
        pipeline.build.return_value = SimpleNamespace(
            topics=regenerated_topics,
            summary_markdown="# Updated",
            summary_source="local",
            summary_warning="",
            generation_profile={},
            generation_profile_source="local",
            generation_profile_warning="",
        )
        initializer = CourseInitializer(manager=Manager(), build_pipeline=pipeline)
        initializer.parser = Parser()

        updated = initializer.regenerate_summary(project, make_current=False)

        self.assertEqual("selected", updated.exam_scope_mode)
        self.assertEqual(["io"], updated.exam_scope_topic_ids)
        self.assertEqual(["io"], [topic.topic_id for topic in updated.exam_topics()])


class CourseExamScopeConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_prediction_prefill_policy_lives_with_prediction_domain(self):
        self.assertTrue(
            hasattr(past_exam_prediction, "prediction_prefill_status")
        )

    def test_generation_context_exposes_only_topics_in_exam_scope(self):
        project = _project()
        project.set_exam_scope("selected", ["io"])
        window = SimpleNamespace(
            course_manager=SimpleNamespace(current=lambda: project),
            lang_manager=SimpleNamespace(get_text=lambda zh, _en: zh),
        )

        content, topics, returned_project = MainWindow._load_generation_context(window)

        self.assertEqual("# Systems", content)
        self.assertIs(project, returned_project)
        self.assertEqual(["io"], [topic.topic_id for topic in topics])

    def test_generation_context_does_not_replace_empty_selected_scope_with_general(self):
        project = _project(
            exam_scope_mode="selected",
            exam_scope_topic_ids=["removed-topic"],
        )
        window = SimpleNamespace(
            course_manager=SimpleNamespace(current=lambda: project),
            lang_manager=SimpleNamespace(get_text=lambda zh, _en: zh),
        )

        _content, topics, _project_value = MainWindow._load_generation_context(window)

        self.assertEqual([], topics)

    def test_ai_generation_stops_with_actionable_message_for_empty_selected_scope(self):
        project = _project(
            exam_scope_mode="selected",
            exam_scope_topic_ids=["removed-topic"],
        )
        window = SimpleNamespace(
            lang_manager=SimpleNamespace(get_text=lambda zh, _en: zh),
            settings_screen=SimpleNamespace(settings_snapshot=lambda: {}),
            _load_generation_context=lambda: ("# Systems", [], project),
        )

        with patch.object(QMessageBox, "warning") as warning:
            MainWindow._on_ai_generate(window)

        warning.assert_called_once()
        self.assertEqual("考试范围为空", warning.call_args.args[1])

    def test_prediction_excludes_known_topic_evidence_outside_exam_scope(self):
        project = _project()
        project.set_exam_scope("selected", ["io"])
        record = SimpleNamespace(
            exam_id="exam-a",
            course_id=project.course_id,
            analysis_status="complete",
        )
        analysis = PastExamAnalysis(
            source_sha256="hash-a",
            analyzed_at="2026-07-14T00:00:00+00:00",
            detected_question_count=10,
            question_types=(
                PastExamQuestionTypeProfile("multiple_choice", 10, 0.9, ("section",)),
            ),
            topic_profile=(
                PastExamTopicProfile("io", "I/O", 60, 0.9, ("interrupt",)),
                PastExamTopicProfile("memory", "Memory", 40, 0.9, ("cache",)),
            ),
        )
        manager = SimpleNamespace(
            load_all=lambda: [record],
            get_analysis=lambda _exam_id: analysis,
        )

        prediction = PastExamPredictionPlanner(manager).build(project)

        self.assertEqual(("io",), prediction.plan.selected_topics)
        self.assertEqual({"io": 100}, dict(prediction.plan.topic_weights))
        self.assertTrue(any("outside the current exam scope" in warning for warning in prediction.warnings))

    def test_prediction_status_distinguishes_scope_filter_from_unsupported_types(self):
        prediction = SimpleNamespace(
            source_count=2,
            warnings=(
                "Historical topic evidence outside the current exam scope was excluded: memory",
            ),
        )

        text = past_exam_prediction.prediction_prefill_status(
            prediction,
            lambda zh, _en: zh,
        )

        self.assertIn("考试范围外", text)
        self.assertNotIn("不支持的历史题型", text)

    def test_home_plan_uses_only_questions_in_selected_exam_scope(self):
        class QuestionBank:
            @staticmethod
            def question_ids(course_id=None):
                return ["q-io", "q-memory"]

            @staticmethod
            def topic_index(course_id=None):
                return {
                    "q-io": ("io", "I/O"),
                    "q-memory": ("memory", "Memory"),
                }

            @staticmethod
            def count(course_id=None):
                return 2

        class ProgressManager:
            @staticmethod
            def get_aggregated_stats(question_ids=None):
                return {
                    "total_sessions": 0,
                    "total_questions": 0,
                    "overall_accuracy": 0.0,
                }

            @staticmethod
            def get_incorrect_question_ids():
                return ["q-memory", "q-io"]

            @staticmethod
            def load_all():
                return []

        home = HomeScreen(ProgressManager(), QuestionBank())

        home.set_current_course("course-systems", "Systems", {"io"})

        self.assertEqual(LearningPlanAction.REVIEW_INCORRECT, home._today_plan.action)
        self.assertEqual(1, home._today_plan.review_question_count)
        self.assertEqual({"q-io"}, home._visible_question_ids())


if __name__ == "__main__":
    unittest.main()
