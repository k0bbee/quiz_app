import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from models.progress import (
    AnswerRecord,
    ProgressRecord,
    QuestionReviewSnapshot,
    SessionSummary,
)
from models.question import Question
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.question_set import SetManager
from core.mastery_overrides import MasteryOverrideStore
from core.language_manager import LanguageManager
from core.study_intent import StudyAction, StudyIntent
from ai.exam_plan import ExamGenerationPlan
from ui.screens.progress_dashboard import ProgressDashboard
from ui.screens.results_screen import ResultsScreen
from ui.result_flow_controller import ResultFlowController
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


def _course_context(course_id: str = "", **overrides):
    values = {"current_course_id": lambda: course_id}
    values.update(overrides)
    return types.SimpleNamespace(**values)


class _StudyFlowSpy:
    """Capture MainWindow-to-controller calls without duplicating quiz startup."""

    def __init__(self, started):
        self.started = started
        self.active_questions = {}

    def start_questions(
        self,
        intent,
        questions,
        *,
        label="",
        question_set=None,
    ):
        questions = list(questions)
        self.started["intent"] = intent
        self.started["questions"] = questions
        self.started["label"] = label
        self.started["question_set"] = question_set
        self.started["submission_mode"] = intent.submission_mode
        self.started["screen"] = 2
        self.active_questions = {
            question.question_id: question for question in questions
        }
        return self.active_questions

    def restore_active_intent(self, intent, questions):
        self.started["restored_intent"] = intent
        self.active_questions = {
            question.question_id: question for question in questions
        }

class ResultsFlowTests(unittest.TestCase):
    def _make_question(self, qid: str, topic: str = "cache") -> Question:
            return Question(
                question_id=qid,
                type=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": f"{qid}?",
                        "options": ["A. 对", "B. 错"],
                        "explanation": "解释说明",
                    },
                    "en": {
                        "stem": f"{qid}?",
                        "options": ["A. Right", "B. Wrong"],
                        "explanation": "Explanation text",
                    },
                },
                correct_answer="A",
                topic=topic,
            )

    def _make_progress_dashboard(
            self,
            root,
            progress_manager,
            question_bank,
            **kwargs,
        ) -> ProgressDashboard:
            root = Path(root)
            kwargs.setdefault(
                "mastery_overrides",
                MasteryOverrideStore(root / "mastery_overrides.json"),
            )
            kwargs.setdefault(
                "course_manager",
                CourseProjectManager(str(root / "courses")),
            )
            return ProgressDashboard(
                progress_manager,
                question_bank,
                set_manager=SetManager(str(root / "sets")),
                **kwargs,
            )

    def _make_results_screen(self) -> ResultsScreen:
            temp_dir = tempfile.TemporaryDirectory(prefix="quiz-results-test-")
            self.addCleanup(temp_dir.cleanup)
            return ResultsScreen(
                course_manager=CourseProjectManager(
                    str(Path(temp_dir.name) / "courses")
                )
            )

    @staticmethod
    def _make_course(course_id: str, title: str) -> CourseProject:
            return CourseProject(
                course_id=course_id,
                title=title,
                source_folder="",
                summary_markdown=f"# {title}",
                summary_path="",
                topics=[CourseTopic(f"{course_id}-topic", title)],
                documents=[],
                created_at="2026-07-01T00:00:00+00:00",
                updated_at="2026-07-01T00:00:00+00:00",
            )

    def test_results_screen_shows_correct_but_unsure_count(self):
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(
                    question_id="q1",
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                    confidence="unsure",
                ),
                AnswerRecord(
                    question_id="q2",
                    index_in_session=1,
                    user_answer="B",
                    is_correct=False,
                ),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)

            screen = self._make_results_screen()
            screen.set_results(record, {}, "zh")

            self.assertIn("正确 1/2", screen.stats_label.text())

    def test_results_screen_recomputes_course_context_for_displayed_questions(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
                course_a = self._make_course("course-a", "课程 A")
                course_b = self._make_course("course-b", "课程 B")
                self.assertTrue(manager.save(course_a, make_current=True))
                self.assertTrue(manager.save(course_b, make_current=False))
                screen = ResultsScreen(course_manager=manager)
                question = self._make_question("q-b")
                question.metadata["course_id"] = course_b.course_id
                record = ProgressRecord.create_new("set-b")
                record.status = "completed"
                record.course_id_snapshot = course_b.course_id
                record.answers = [AnswerRecord("q-b", 0, "A", True)]
                record.summary = SessionSummary.compute(record.answers, 1, 10)

                screen.set_results(record, {"q-b": question}, "zh")

                self.assertEqual(course_b.course_id, screen._course_project.course_id)

    def test_results_screen_does_not_borrow_current_course_for_deleted_history(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
                current = self._make_course("course-current", "当前课程")
                self.assertTrue(manager.save(current, make_current=True))
                screen = ResultsScreen(course_manager=manager)
                record = ProgressRecord.create_new("set-deleted")
                record.status = "completed"
                record.course_id_snapshot = "course-deleted"
                record.course_title_snapshot = "已删除课程"
                record.answers = []
                record.summary = SessionSummary.compute([], 0, 0)

                screen.set_results(record, {}, "zh")

                self.assertIsNone(screen._course_project)

    def test_results_screen_leaves_cross_course_custom_practice_unbound(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
                course_a = self._make_course("course-a", "课程 A")
                course_b = self._make_course("course-b", "课程 B")
                self.assertTrue(manager.save(course_a, make_current=True))
                self.assertTrue(manager.save(course_b, make_current=False))
                screen = ResultsScreen(course_manager=manager)
                question_a = self._make_question("q-a")
                question_a.metadata["course_id"] = course_a.course_id
                question_b = self._make_question("q-b")
                question_b.metadata["course_id"] = course_b.course_id
                record = ProgressRecord.create_new("set-custom")
                record.status = "completed"
                record.course_id_snapshot = course_a.course_id
                record.answers = [
                    AnswerRecord("q-a", 0, "A", True),
                    AnswerRecord("q-b", 1, "A", True),
                ]
                record.summary = SessionSummary.compute(record.answers, 2, 20)

                screen.set_results(
                    record,
                    {"q-a": question_a, "q-b": question_b},
                    "zh",
                )

                self.assertIsNone(screen._course_project)

    def test_results_screen_uses_study_intent_when_record_has_no_course_identity(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
                course = self._make_course("course-intent", "意图课程")
                self.assertTrue(manager.save(course, make_current=False))
                screen = ResultsScreen(course_manager=manager)
                record = ProgressRecord.create_new("set-custom")
                record.status = "completed"
                record.summary = SessionSummary.compute([], 0, 0)
                intent = StudyIntent(
                    course_id=course.course_id,
                    action=StudyAction.CUSTOM_PRACTICE,
                )

                screen.set_results(record, {}, "zh", study_intent=intent)

                self.assertEqual(course.course_id, screen._course_project.course_id)

    def test_results_screen_distinguishes_skipped_from_incorrect(self):
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord("q-right", 0, "A", True),
                AnswerRecord("q-wrong", 1, "B", False),
                AnswerRecord("q-skip", 2, None, False, skipped=True),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=3, total_time=30)

            screen = self._make_results_screen()
            screen.set_results(record, {}, "zh")

            self.assertEqual((1, 1, 1), (
                screen.summary_bar._correct,
                screen.summary_bar._incorrect,
                screen.summary_bar._unanswered,
            ))
            self.assertIn("错误 1", screen.stats_label.text())
            self.assertIn("未答 1", screen.stats_label.text())

    def test_results_screen_disables_retry_actions_when_questions_are_deleted(self):
            question = self._make_question("q-deleted")
            record = ProgressRecord.create_new("set-deleted")
            record.status = "completed"
            record.answers = [
                AnswerRecord(
                    question_id=question.question_id,
                    index_in_session=0,
                    user_answer="B",
                    is_correct=False,
                )
            ]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            screen = self._make_results_screen()
            screen.set_results(record, {question.question_id: question}, "zh")
            self.assertTrue(screen.retry_incorrect_btn.isEnabled())

            screen.set_retry_availability([])

            self.assertFalse(screen.retry_incorrect_btn.isEnabled())
            self.assertIn("原题已不可用", screen.retry_incorrect_btn.toolTip())

    def test_results_screen_reviews_snapshot_when_original_question_is_deleted(self):
            record = ProgressRecord.create_new("set-deleted")
            record.status = "completed"
            record.set_title_snapshot = "I/O 专项"
            record.course_title_snapshot = "操作系统"
            record.answers = [
                AnswerRecord(
                    question_id="q-deleted",
                    index_in_session=0,
                    user_answer="A",
                    is_correct=False,
                )
            ]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            record.question_snapshots = [
                QuestionReviewSnapshot(
                    question_id="q-deleted",
                    question_type="multiple_choice",
                    topic_id="input-output",
                    topic_title="输入输出",
                    stem="哪种方式由设备主动通知 CPU？",
                    options=["A. 轮询", "B. 中断"],
                    correct_answer="B",
                    explanation="中断由设备在完成后通知 CPU。",
                    source_refs=[
                        {
                            "source_file": "lecture.pdf",
                            "page_or_slide": 8,
                        }
                    ],
                )
            ]
            screen = self._make_results_screen()

            screen.set_results(record, {}, "zh")
            screen.set_retry_availability([])

            card = screen.review_layout.itemAt(0).widget()
            self.assertEqual("哪种方式由设备主动通知 CPU？", card.stem_label.text())
            self.assertIn("A. 轮询", card.answer_info.text())
            self.assertIn("B. 中断", card.answer_info.text())
            self.assertIn("中断由设备在完成后通知 CPU。", card.explanation_label.text())
            self.assertIn("lecture.pdf", card.source_label.text())
            self.assertIn("输入输出: 0/1", screen.topic_stats_label.text())
            self.assertEqual("操作系统 · I/O 专项", screen.context_label.text())
            self.assertFalse(screen.retry_incorrect_btn.isEnabled())

    def test_results_screen_prefers_historical_snapshot_after_live_question_edit(self):
            live_question = self._make_question("q-edited")
            live_question.bilingual["zh"] = {
                "stem": "编辑后的题干",
                "options": ["A. 新答案", "B. 旧答案"],
                "explanation": "编辑后的解析",
            }
            live_question.correct_answer = "A"
            record = ProgressRecord.create_new("set-history")
            record.status = "completed"
            record.archive_schema_version = 1
            record.archive_status = "complete"
            record.answers = [AnswerRecord("q-edited", 0, "B", True)]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            record.question_snapshots = [
                QuestionReviewSnapshot(
                    question_id="q-edited",
                    question_type="multiple_choice",
                    topic_id="history-topic",
                    topic_title="历史主题",
                    stem="作答时的题干",
                    options=["A. 新答案", "B. 旧答案"],
                    correct_answer="B",
                    explanation="作答时的解析",
                )
            ]
            screen = self._make_results_screen()

            screen.set_results(record, {"q-edited": live_question}, "zh")

            card = screen.review_layout.itemAt(0).widget()
            self.assertEqual("作答时的题干", card.stem_label.text())
            self.assertIn("正确答案: B. 旧答案", card.answer_info.text())
            self.assertIn("作答时的解析", card.explanation_label.text())
            self.assertNotIn("编辑后的", card.stem_label.text() + card.explanation_label.text())

    def test_results_screen_keeps_historical_course_context_after_live_reassignment(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
                historical_course = self._make_course("course-a", "历史课程 A")
                live_course = self._make_course("course-b", "当前课程 B")
                self.assertTrue(manager.save(historical_course, make_current=True))
                self.assertTrue(manager.save(live_course, make_current=False))
                live_question = self._make_question("q-moved")
                live_question.metadata["course_id"] = live_course.course_id
                record = ProgressRecord.create_new("set-history")
                record.status = "completed"
                record.archive_schema_version = 1
                record.archive_status = "complete"
                record.course_id_snapshot = historical_course.course_id
                record.course_title_snapshot = historical_course.title
                record.answers = [AnswerRecord("q-moved", 0, "A", True)]
                record.summary = SessionSummary.compute(record.answers, 1, 10)
                record.question_snapshots = [
                    QuestionReviewSnapshot(
                        question_id="q-moved",
                        question_type="multiple_choice",
                        topic_id="historical-topic",
                        topic_title="历史主题",
                        stem="历史题干",
                        options=["A. 正确", "B. 错误"],
                        correct_answer="A",
                        explanation="历史解析",
                        source_refs=[{"source_file": "historical.pdf", "page_or_slide": 3}],
                    )
                ]
                screen = ResultsScreen(course_manager=manager)

                screen.set_results(record, {"q-moved": live_question}, "zh")

                card = screen.review_layout.itemAt(0).widget()
                self.assertEqual(historical_course.course_id, screen._course_project.course_id)
                self.assertEqual(historical_course.course_id, card._course_project.course_id)
                self.assertEqual("历史课程 A", screen.context_label.text())

    def test_results_screen_does_not_use_live_question_for_incomplete_history(self):
            live_question = self._make_question("q-missing")
            live_question.bilingual["zh"]["stem"] = "现在的题干不代表历史"
            record = ProgressRecord.create_new("set-incomplete")
            record.status = "completed"
            record.archive_schema_version = 1
            record.archive_status = "incomplete"
            record.archive_missing_fields = ["question_snapshots:q-missing"]
            record.answers = [AnswerRecord("q-missing", 0, "B", False)]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            screen = self._make_results_screen()

            screen.set_results(record, {"q-missing": live_question}, "zh")
            screen.set_retry_availability([])

            card = screen.review_layout.itemAt(0).widget()
            self.assertIn("题目 q-missing", card.stem_label.text())
            self.assertNotIn("现在的题干", card.stem_label.text())
            self.assertTrue(screen.archive_notice_label.isVisibleTo(screen))
            self.assertIn("残缺历史", screen.archive_notice_label.text())
            self.assertIn("0/1", screen.archive_notice_label.text())
            self.assertIn("题目复盘内容", screen.archive_notice_label.text())

    def test_results_screen_marks_legacy_history_as_awaiting_protection(self):
            record = ProgressRecord.create_new("set-legacy")
            record.status = "completed"
            record.archive_status = "legacy"
            record.answers = [AnswerRecord("q-legacy", 0, "A", True)]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            screen = self._make_results_screen()

            screen.set_results(record, {}, "zh")

            self.assertTrue(screen.archive_notice_label.isVisibleTo(screen))
            self.assertIn("尚未完成保护", screen.archive_notice_label.text())

    def test_results_screen_hides_archive_notice_for_complete_history(self):
            question = self._make_question("q-complete")
            record = ProgressRecord.create_new("set-complete")
            record.status = "completed"
            record.archive_schema_version = 1
            record.archive_status = "complete"
            record.answers = [AnswerRecord("q-complete", 0, "A", True)]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            record.question_snapshots = [
                QuestionReviewSnapshot(
                    question_id=question.question_id,
                    question_type=question.type.value,
                    topic_id=question.topic_id(),
                    topic_title=question.topic_title(),
                    stem=question.get_stem("zh"),
                    options=question.get_options("zh"),
                    correct_answer=question.correct_answer,
                    explanation=question.get_explanation("zh"),
                )
            ]
            screen = self._make_results_screen()

            screen.set_results(record, {question.question_id: question}, "zh")

            self.assertTrue(screen.archive_notice_label.isHidden())

    def test_results_screen_does_not_render_malformed_historical_snapshot(self):
            record = ProgressRecord.create_new("set-incomplete")
            record.status = "completed"
            record.archive_schema_version = 1
            record.archive_status = "incomplete"
            record.answers = [AnswerRecord("q-malformed", 0, "B", False)]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            record.question_snapshots = [
                QuestionReviewSnapshot(
                    question_id="q-malformed",
                    question_type="multiple_choice",
                    topic_id="history-topic",
                    topic_title="历史主题",
                    stem="",
                    options=[],
                    correct_answer=None,
                    explanation="",
                )
            ]
            screen = self._make_results_screen()

            screen.set_results(record, {}, "zh")

            card = screen.review_layout.itemAt(0).widget()
            self.assertIn("题目 q-malformed", card.stem_label.text())
            self.assertNotIn("正确答案", card.answer_info.text())

    def test_retry_incorrect_excludes_skipped_answers(self):

            record = ProgressRecord.create_new("set-1")
            record.answers = [
                AnswerRecord("q-skip", 0, None, False, skipped=True),
                AnswerRecord("q-wrong", 1, "B", False),
            ]
            requested = []
            question_bank = types.SimpleNamespace(
                get_many=lambda ids, course_id="": requested.extend(ids) or []
            )
            shell = types.SimpleNamespace(
                results_screen=types.SimpleNamespace(current_record=record),
                lang_manager=LanguageManager.instance(),
                question_bank=question_bank,
                course_context=_course_context("course-a"),
            )

            with patch("ui.result_flow_controller.QMessageBox.warning") as warning:
                ResultFlowController(shell).retry_incorrect()

            self.assertEqual(["q-wrong"], requested)
            self.assertIn("题目不可用", warning.call_args.args[1])


    def test_results_screen_has_only_retry_incorrect_and_return_home_actions(self):
            screen = self._make_results_screen()
            emitted = []
            screen.return_home_requested.connect(lambda: emitted.append(True))

            self.assertEqual("primaryButton", screen.retry_incorrect_btn.objectName())
            self.assertEqual("secondaryButton", screen.return_home_btn.objectName())
            self.assertEqual("secondaryButton", screen.reinforce_btn.objectName())
            self.assertTrue(screen.reinforce_btn.isHidden())

            screen.return_home_btn.click()
            self.assertEqual([True], emitted)

    def test_results_screen_exposes_reinforcement_topics_only_after_mistakes(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
                course = self._make_course("course-a", "课程 A")
                course.topics = [CourseTopic("topic-a", "主题 A")]
                self.assertTrue(manager.save(course, make_current=True))
                question = self._make_question("q-wrong", "topic-a")
                question.metadata["course_id"] = course.course_id
                record = ProgressRecord.create_new("set-reinforce")
                record.status = "completed"
                record.course_id_snapshot = course.course_id
                record.answers = [AnswerRecord("q-wrong", 0, "B", False)]
                record.summary = SessionSummary.compute(record.answers, 1, 10)

                screen = ResultsScreen(course_manager=manager)
                screen.set_results(record, {question.question_id: question}, "zh")

                self.assertEqual(("topic-a",), screen.reinforcement_topic_ids())
                self.assertTrue(screen.reinforce_btn.isVisibleTo(screen))

                correct_record = ProgressRecord.create_new("set-correct")
                correct_record.status = "completed"
                correct_record.course_id_snapshot = course.course_id
                correct_record.answers = [AnswerRecord("q-right", 0, "A", True)]
                correct_record.summary = SessionSummary.compute(correct_record.answers, 1, 10)
                screen.set_results(
                    correct_record,
                    {"q-right": self._make_question("q-right")},
                    "zh",
                )

                self.assertEqual((), screen.reinforcement_topic_ids())
                self.assertTrue(screen.reinforce_btn.isHidden())

    def test_results_screen_does_not_keep_legacy_question_injection_wrappers(self):
            screen = self._make_results_screen()

            self.assertFalse(hasattr(screen, "set_questions"))
            self.assertFalse(hasattr(screen, "retryable_questions"))

    def test_result_flow_opens_existing_generation_workspace_for_weak_topics(self):
            record = ProgressRecord.create_new("set-reinforce")
            record.status = "completed"
            record.course_id_snapshot = "course-a"
            record.answers = [AnswerRecord("q-wrong", 0, "B", False)]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            course = self._make_course("course-a", "课程 A")
            course.topics = [CourseTopic("topic-a", "主题 A")]
            opened = {}
            host = types.SimpleNamespace(
                results_screen=types.SimpleNamespace(
                    current_record=record,
                    reinforcement_topic_ids=lambda: ("topic-a",),
                ),
                course_context=_course_context("course-a"),
                course_manager=types.SimpleNamespace(get=lambda course_id: course if course_id == "course-a" else None),
                generation_flow=types.SimpleNamespace(
                    open=lambda **kwargs: opened.update(kwargs) or True,
                ),
                lang_manager=LanguageManager.instance(),
            )

            ResultFlowController(host).generate_reinforcement()

            self.assertIs(course, opened["course_override"])
            self.assertEqual("result_reinforcement", opened["draft_source"])
            self.assertEqual("薄弱主题强化练习", opened["question_set_title"])
            plan = opened["initial_plan"]
            self.assertIsInstance(plan, ExamGenerationPlan)
            self.assertEqual(5, plan.question_count)
            self.assertEqual(("topic-a",), plan.selected_topics)
            self.assertEqual({"topic-a": 100}, dict(plan.topic_weights))

    def test_results_screen_only_shows_items_needing_review(self):
            record = ProgressRecord.create_new("set-review-filter")
            record.status = "completed"
            record.answers = [
                AnswerRecord("q-right", 0, "A", True),
                AnswerRecord("q-unsure", 1, "A", True, confidence="unsure"),
                AnswerRecord("q-wrong", 2, "B", False),
            ]
            record.summary = SessionSummary.compute(record.answers, 3, 20)
            questions = {
                question_id: self._make_question(question_id)
                for question_id in ("q-right", "q-unsure", "q-wrong")
            }

            screen = self._make_results_screen()
            screen.set_results(record, questions, "zh")

            cards = [
                screen.review_layout.itemAt(index).widget()
                for index in range(screen.review_layout.count() - 1)
            ]
            self.assertEqual(3, len(cards))
            self.assertTrue(cards[0].isHidden())
            self.assertFalse(cards[1].isHidden())
            self.assertFalse(cards[2].isHidden())
            self.assertEqual("错题回顾:", screen.review_label.text())

    def test_results_screen_limits_topic_summary_to_two_weakest_topics(self):
            record = ProgressRecord.create_new("set-topics")
            record.status = "completed"
            record.answers = [
                AnswerRecord("q-a-1", 0, "B", False),
                AnswerRecord("q-a-2", 1, "B", False),
                AnswerRecord("q-b", 2, "A", True),
                AnswerRecord("q-c", 3, "A", True),
            ]
            record.summary = SessionSummary.compute(record.answers, 4, 20)
            questions = {
                "q-a-1": self._make_question("q-a-1", "topic-a"),
                "q-a-2": self._make_question("q-a-2", "topic-a"),
                "q-b": self._make_question("q-b", "topic-b"),
                "q-c": self._make_question("q-c", "topic-c"),
            }
            screen = self._make_results_screen()

            screen.set_results(record, questions, "zh")

            summary = screen.topic_stats_label.text()
            self.assertTrue(summary.startswith("最薄弱主题:"))
            self.assertEqual(1, summary.count("|"))
            self.assertIn("Topic A", summary)

    def test_results_screen_low_score_uses_review_oriented_badge(self):
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(question_id="q1", index_in_session=0, user_answer="B", is_correct=False),
                AnswerRecord(question_id="q2", index_in_session=1, user_answer="B", is_correct=False),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)

            screen = self._make_results_screen()
            screen.set_results(record, {}, "zh")

            self.assertEqual("得分 0%", screen.score_label.text())

    def test_results_screen_review_card_shows_source_refs(self):
            question = self._make_question("q-source")
            question.metadata["source_refs"] = [
                {
                    "chunk_id": "source-0007",
                    "source_file": "第21讲 Cache.pdf",
                    "page_or_slide": 8,
                    "heading": "Cache Address Breakdown",
                }
            ]
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(
                    question_id=question.question_id,
                    index_in_session=0,
                    user_answer="B",
                    is_correct=False,
                ),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=1, total_time=10)

            screen = self._make_results_screen()
            screen.set_results(record, {question.question_id: question}, "zh")

            card = screen.review_layout.itemAt(0).widget()
            source_text = card.source_label.text()
            self.assertIn("第21讲 Cache.pdf", source_text)
            self.assertIn("页码/幻灯片 8", source_text)
            self.assertIn("source-0007", source_text)
            self.assertIn("Cache Address Breakdown", source_text)

    def test_clear_reviews_removes_all_widgets_and_keeps_only_stretch(self):
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(question_id="q1", index_in_session=0, user_answer="A", is_correct=True),
                AnswerRecord(question_id="q2", index_in_session=1, user_answer="B", is_correct=False),
                AnswerRecord(question_id="q3", index_in_session=2, user_answer="C", is_correct=True),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=3, total_time=30)
            questions = {
                "q1": self._make_question("q1"),
                "q2": self._make_question("q2"),
                "q3": self._make_question("q3"),
            }

            screen = self._make_results_screen()
            screen.set_results(record, questions, "zh")
            self.assertGreater(screen.review_layout.count(), 1)

            screen._clear_reviews()

            self.assertEqual(screen.review_layout.count(), 1)
