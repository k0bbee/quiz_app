import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QMessageBox, QRadioButton

from models.progress import (
    AnswerRecord,
    ProgressRecord,
    QuestionReviewSnapshot,
    SessionSummary,
)
from models.question import Question
from models.question import QuestionBank
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from models.quiz_snapshot import QuizSessionSnapshot
from models.question_set import QuestionSet, SetManager
from core.quiz_engine import QuizSession
from core.mastery_overrides import MasteryOverrideStore
from core.progress_tracker import ProgressManager
from core.quiz_snapshot_manager import QuizSnapshotManager
from core.language_manager import LanguageManager
from core.study_intent import StudyAction, StudyIntent
from core.today_learning_plan import LearningPlanAction
from ui.screens.home_screen import HomeScreen
from ui.screens.progress_dashboard import ProgressDashboard
from ui.screens.quiz_screen import QuizScreen
from ui.screens.results_screen import ResultsScreen
from ui.course_context_controller import CourseContextController
from ui.result_flow_controller import ResultFlowController
from ui.widgets.answer_area import AnswerArea, MatchingWidget, MultipleChoiceWidget
from utils.constants import Difficulty, QuestionType, QuizState, topic_value


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

            self.assertIn("答对但不确定: 1", screen.stats_label.text())

    def test_results_can_generate_a_bounded_course_reinforcement_plan(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = CourseProjectManager(str(Path(tmpdir) / "courses"))
                course = self._make_course("course-a", "课程 A")
                course.topics = [
                    CourseTopic("cache", "高速缓存", source_files=["cache.pdf"]),
                    CourseTopic("io", "输入输出", source_files=["io.pdf"]),
                ]
                self.assertTrue(manager.save(course))
                screen = ResultsScreen(course_manager=manager)
                cache = self._make_question("q-cache", "cache")
                io = self._make_question("q-io", "io")
                for question in (cache, io):
                    question.metadata["course_id"] = course.course_id
                record = ProgressRecord.create_new("set-a")
                record.status = "completed"
                record.answers = [
                    AnswerRecord("q-cache", 0, "B", False),
                    AnswerRecord(
                        "q-io",
                        1,
                        "A",
                        True,
                        confidence="unsure",
                    ),
                ]
                record.summary = SessionSummary.compute(record.answers, 2, 20)
                requests = []
                screen.generate_reinforcement_requested.connect(requests.append)

                screen.set_results(
                    record,
                    {"q-cache": cache, "q-io": io},
                    "zh",
                )
                screen.reinforce_btn.click()

                self.assertEqual([{
                    "course_id": "course-a",
                    "topic_ids": ["cache", "io"],
                    "question_count": 6,
                    "max_questions": 6,
                    "destination": "practice_now",
                    "signals": [
                        {
                            "topic_id": "cache",
                            "question_ids": ["q-cache"],
                            "observed_wrong_answers": ["B"],
                            "unsure_question_ids": [],
                            "source_refs": [],
                            "observed_question_stems": ["q-cache?"],
                        },
                        {
                            "topic_id": "io",
                            "question_ids": ["q-io"],
                            "observed_wrong_answers": [],
                            "unsure_question_ids": ["q-io"],
                            "source_refs": [],
                            "observed_question_stems": ["q-io?"],
                        },
                    ],
                }], requests)

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
            self.assertIn("错误: 1", screen.stats_label.text())
            self.assertIn("未答: 1", screen.stats_label.text())
            self.assertIn("重做错题（1 题）", screen.next_action_label.text())

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
            self.assertTrue(screen.retry_all_action.isEnabled())

            screen.set_retry_availability([], can_retry_all=False)

            self.assertFalse(screen.retry_incorrect_btn.isEnabled())
            self.assertFalse(screen.retry_unsure_action.isEnabled())
            self.assertFalse(screen.retry_review_action.isEnabled())
            self.assertFalse(screen.retry_all_action.isEnabled())
            self.assertFalse(screen.more_practice_btn.isEnabled())
            self.assertIn("原题已不可用", screen.next_action_label.text())

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
            screen.set_retry_availability([], can_retry_all=False)

            card = screen.review_layout.itemAt(0).widget()
            self.assertEqual("哪种方式由设备主动通知 CPU？", card.stem_label.text())
            self.assertIn("A. 轮询", card.answer_info.text())
            self.assertIn("B. 中断", card.answer_info.text())
            self.assertIn("中断由设备在完成后通知 CPU。", card.explanation_label.text())
            self.assertIn("lecture.pdf", card.source_label.text())
            self.assertIn("输入输出: 0/1", screen.topic_stats_label.text())
            self.assertEqual("操作系统 · I/O 专项", screen.context_label.text())
            self.assertFalse(screen.retry_incorrect_btn.isEnabled())
            self.assertIn("仍可复盘", screen.next_action_label.text())

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
            self.assertTrue(screen.retry_all_action.isEnabled())

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
            screen.set_retry_availability([], can_retry_all=False)

            card = screen.review_layout.itemAt(0).widget()
            self.assertIn("题目 q-missing", card.stem_label.text())
            self.assertNotIn("现在的题干", card.stem_label.text())
            self.assertTrue(screen.archive_notice_label.isVisibleTo(screen))
            self.assertIn("残缺历史", screen.archive_notice_label.text())
            self.assertIn("0/1", screen.archive_notice_label.text())
            self.assertIn("题目复盘内容", screen.archive_notice_label.text())
            self.assertIn("只能查看已保存的部分", screen.next_action_label.text())
            self.assertNotIn("仍可复盘", screen.next_action_label.text())

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
            from ui.main_window import MainWindow

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

    def test_results_screen_enables_retry_unsure_action_when_needed(self):
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
                    is_correct=True,
                ),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)

            screen = self._make_results_screen()
            emitted = []
            screen.retry_unsure.connect(lambda: emitted.append(True))
            questions = {
                question_id: self._make_question(question_id)
                for question_id in ("q1", "q2")
            }
            screen.set_results(record, questions, "zh")

            self.assertTrue(screen.retry_unsure_action.isEnabled())
            screen.retry_unsure_action.trigger()

            self.assertEqual([True], emitted)

    def test_results_screen_uses_one_primary_retry_and_compact_more_menu(self):
            screen = self._make_results_screen()

            self.assertEqual("primaryButton", screen.retry_incorrect_btn.objectName())
            self.assertEqual("secondaryButton", screen.more_practice_btn.objectName())
            self.assertIs(screen.more_practice_menu, screen.more_practice_btn.menu())
            self.assertFalse(hasattr(screen, "retry_unsure_btn"))
            self.assertFalse(hasattr(screen, "retry_review_btn"))
            self.assertFalse(hasattr(screen, "retry_all_btn"))

    def test_results_screen_shows_and_retries_marked_review_questions(self):
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(question_id="q1", index_in_session=0, user_answer="A", is_correct=True),
                AnswerRecord(question_id="q2", index_in_session=1, user_answer="B", is_correct=False),
            ]
            record.marked_review_question_ids = ["q2"]
            record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)

            screen = self._make_results_screen()
            emitted = []
            screen.retry_review.connect(lambda: emitted.append(True))
            questions = {
                question_id: self._make_question(question_id)
                for question_id in ("q1", "q2")
            }
            screen.set_results(record, questions, "zh")

            self.assertIn("复查: 1", screen.stats_label.text())
            self.assertTrue(screen.retry_review_action.isEnabled())
            screen.retry_review_action.trigger()
            self.assertEqual([True], emitted)

    def test_results_screen_shows_next_action_recommendation(self):
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(
                    question_id="q1",
                    index_in_session=0,
                    user_answer="B",
                    is_correct=False,
                ),
                AnswerRecord(
                    question_id="q2",
                    index_in_session=1,
                    user_answer="A",
                    is_correct=True,
                    confidence="unsure",
                ),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)

            screen = self._make_results_screen()
            screen.set_results(record, {}, "zh")

            self.assertIn("下一步建议", screen.next_action_label.text())
            self.assertIn("先重做错题", screen.next_action_label.text())

    def test_results_screen_continues_to_remaining_daily_queue_questions(self):
            question = self._make_question("q-cache", "cache")
            record = ProgressRecord.create_new("today-cache")
            record.status = "completed"
            record.answers = [
                AnswerRecord(
                    question_id=question.question_id,
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                )
            ]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            intent = StudyIntent(
                course_id="course-a",
                action=StudyAction.DAILY_QUEUE,
                question_ids=(question.question_id,),
                remaining_question_ids=("q-next-1", "q-next-2"),
                question_count=1,
                source="today_plan",
                plan_id="2026-07-28:course-a",
            )
            screen = self._make_results_screen()
            requests = []
            signal = getattr(screen, "study_requested", None)
            self.assertIsNotNone(signal)
            signal.connect(requests.append)
            try:
                screen.set_results(
                    record,
                    {question.question_id: question},
                    "zh",
                    study_intent=intent,
                )
            except TypeError as exc:
                self.fail(f"results screen cannot preserve study intent: {exc}")

            self.assertIs(intent, screen.current_study_intent)
            self.assertFalse(screen.repeat_study_btn.isHidden())
            self.assertIn("继续今日学习", screen.repeat_study_btn.text())
            self.assertIn("2", screen.repeat_study_btn.text())
            self.assertEqual("primaryButton", screen.repeat_study_btn.objectName())
            self.assertEqual("secondaryButton", screen.retry_incorrect_btn.objectName())
            screen.repeat_study_btn.click()
            self.assertEqual(1, len(requests))
            continued = requests[0]
            self.assertIs(StudyAction.DAILY_QUEUE, continued.action)
            self.assertEqual(("q-next-1", "q-next-2"), continued.question_ids)
            self.assertEqual((), continued.remaining_question_ids)
            self.assertEqual(intent.plan_id, continued.plan_id)

    def test_results_screen_marks_daily_queue_complete_without_repeat(self):
            question = self._make_question("q-cache", "cache")
            record = ProgressRecord.create_new("today-cache")
            record.status = "completed"
            record.answers = [
                AnswerRecord(
                    question_id=question.question_id,
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                )
            ]
            record.summary = SessionSummary.compute(record.answers, 1, 10)
            intent = StudyIntent(
                course_id="course-a",
                action=StudyAction.DAILY_QUEUE,
                question_ids=(question.question_id,),
                question_count=1,
                source="today_plan",
                plan_id="2026-07-28:course-a",
            )
            screen = self._make_results_screen()

            screen.set_results(
                record,
                {question.question_id: question},
                "zh",
                study_intent=intent,
            )

            self.assertTrue(screen.repeat_study_btn.isHidden())
            self.assertEqual("primaryButton", screen.retry_incorrect_btn.objectName())
            self.assertIn("今日任务完成", screen.next_action_label.text())

    def test_results_screen_recommends_action_for_topic_with_most_incorrect_answers(self):
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(question_id="q-io-1", index_in_session=0, user_answer="B", is_correct=False),
                AnswerRecord(question_id="q-cache", index_in_session=1, user_answer="B", is_correct=False),
                AnswerRecord(question_id="q-io-2", index_in_session=2, user_answer="B", is_correct=False),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=3, total_time=30)
            questions = {
                "q-io-1": self._make_question("q-io-1", "io"),
                "q-cache": self._make_question("q-cache", "cache"),
                "q-io-2": self._make_question("q-io-2", "io"),
            }
            screen = self._make_results_screen()
            emitted = []
            screen.review_topic_requested.connect(emitted.append)

            screen.set_results(record, questions, "zh")

            self.assertFalse(screen.next_action_btn.isHidden())
            self.assertIn("io", screen.next_action_btn.text().lower())
            screen.next_action_btn.click()
            self.assertEqual(["io"], emitted)

    def test_results_screen_recommends_topic_practice_for_unsure_answers_without_errors(self):
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(
                    question_id="q-cache",
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                    confidence="unsure",
                ),
                AnswerRecord(
                    question_id="q-io",
                    index_in_session=1,
                    user_answer="A",
                    is_correct=True,
                ),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)
            questions = {
                "q-cache": self._make_question("q-cache", "cache"),
                "q-io": self._make_question("q-io", "io"),
            }
            screen = self._make_results_screen()
            emitted = []
            screen.practice_topic_requested.connect(emitted.append)

            screen.set_results(record, questions, "zh")

            self.assertFalse(screen.next_action_btn.isHidden())
            self.assertIn("cache", screen.next_action_btn.text().lower())
            screen.next_action_btn.click()
            self.assertEqual(["cache"], emitted)

    def test_main_window_routes_results_topic_actions_through_existing_progress_handlers(self):
            source = Path("ui/main_window.py").read_text(encoding="utf-8")

            self.assertIn(
                "self.results_screen.practice_topic_requested.connect(self._on_practice_progress_topic)",
                source,
            )
            self.assertIn(
                "self.results_screen.review_topic_requested.connect(self._on_review_progress_topic)",
                source,
            )

    def test_results_screen_clears_stale_topic_action_when_results_are_unavailable(self):
            question = self._make_question("q-cache", "cache")
            record = ProgressRecord.create_new("set-1")
            record.status = "completed"
            record.answers = [
                AnswerRecord(question_id=question.question_id, index_in_session=0, user_answer="B", is_correct=False),
            ]
            record.summary = SessionSummary.compute(record.answers, total_questions=1, total_time=10)
            screen = self._make_results_screen()
            screen.set_results(record, {question.question_id: question}, "zh")
            self.assertFalse(screen.next_action_btn.isHidden())

            screen.set_results(None, {}, "zh")

            self.assertTrue(screen.next_action_btn.isHidden())

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

            self.assertTrue(screen.score_label.text().startswith("🔎 "))
            self.assertNotIn("💪", screen.score_label.text())
            self.assertIn("先重做错题", screen.next_action_label.text())

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

    def test_retry_unsure_starts_only_unsure_questions_for_current_course(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                unsure_current = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.EASY,
                    bilingual={
                        "zh": {"stem": "当前课程不确定", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                        "en": {"stem": "Current unsure", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                unsure_current.metadata["course_id"] = "course-a"
                unsure_other_course = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.EASY,
                    bilingual={
                        "zh": {"stem": "其他课程不确定", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                        "en": {"stem": "Other unsure", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                unsure_other_course.metadata["course_id"] = "course-b"
                sure_current = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.EASY,
                    bilingual={
                        "zh": {"stem": "当前课程确定", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                        "en": {"stem": "Current sure", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                    },
                    correct_answer="A",
                    topic="process",
                )
                sure_current.metadata["course_id"] = "course-a"
                question_bank.save_many([unsure_current, unsure_other_course, sure_current])

                record = ProgressRecord.create_new("set-1")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(
                        question_id=unsure_current.question_id,
                        index_in_session=0,
                        user_answer="A",
                        is_correct=True,
                        confidence="unsure",
                    ),
                    AnswerRecord(
                        question_id=unsure_other_course.question_id,
                        index_in_session=1,
                        user_answer="A",
                        is_correct=True,
                        confidence="unsure",
                    ),
                    AnswerRecord(
                        question_id=sure_current.question_id,
                        index_in_session=2,
                        user_answer="A",
                        is_correct=True,
                    ),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=3, total_time=30)

                started = {}

                class FakeQuizScreen:
                    def start_quiz_custom(self, questions, label, show_timer=False):
                        started["questions"] = questions
                        started["label"] = label
                        started["show_timer"] = show_timer

                shell = types.SimpleNamespace(
                    results_screen=types.SimpleNamespace(current_record=record),
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                ResultFlowController(shell).retry_unsure()

                self.assertEqual([unsure_current.question_id], [q.question_id for q in started["questions"]])
                self.assertIn("不确定", started["label"])

    def test_retry_review_starts_only_marked_review_questions_for_current_course(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                marked_current = self._make_question("review-current")
                marked_current.metadata["course_id"] = "course-a"
                marked_other_course = self._make_question("review-other")
                marked_other_course.metadata["course_id"] = "course-b"
                unmarked_current = self._make_question("review-unmarked")
                unmarked_current.metadata["course_id"] = "course-a"
                question_bank.save_many([marked_current, marked_other_course, unmarked_current])

                record = ProgressRecord.create_new("set-1")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=marked_current.question_id, index_in_session=0, user_answer="A", is_correct=True),
                    AnswerRecord(question_id=marked_other_course.question_id, index_in_session=1, user_answer="A", is_correct=True),
                    AnswerRecord(question_id=unmarked_current.question_id, index_in_session=2, user_answer="A", is_correct=True),
                ]
                record.marked_review_question_ids = [
                    marked_current.question_id,
                    marked_other_course.question_id,
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=3, total_time=30)

                started = {}

                class FakeQuizScreen:
                    def start_quiz_custom(self, questions, label, show_timer=False):
                        started["questions"] = questions
                        started["label"] = label
                        started["show_timer"] = show_timer

                shell = types.SimpleNamespace(
                    results_screen=types.SimpleNamespace(current_record=record),
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                ResultFlowController(shell).retry_review()

                self.assertEqual([marked_current.question_id], [q.question_id for q in started["questions"]])
                self.assertIn("复查", started["label"])

    def test_retry_all_starts_entire_set_in_practice_mode(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                set_manager = SetManager(str(Path(tmpdir) / "sets"))
                q1 = self._make_question("retry-all-1")
                q2 = self._make_question("retry-all-2")
                question_bank.save_many([q1, q2])
                qset = QuestionSet.create_new(
                    title={"zh": "整套", "en": "Full Set"},
                    description={"zh": "", "en": ""},
                    topics=["cache"],
                    question_ids=[q1.question_id, q2.question_id],
                )
                set_manager.save(qset)
                record = ProgressRecord.create_new(qset.set_id)
                record.status = "completed"
                record.summary = SessionSummary.compute([], total_questions=2, total_time=20)
                started = {}

                class FakeQuizScreen:
                    def start_quiz(self, question_set, questions, **kwargs):
                        started["question_set"] = question_set
                        started["questions"] = questions
                        started.update(kwargs)

                shell = types.SimpleNamespace(
                    results_screen=types.SimpleNamespace(current_record=record),
                    set_manager=set_manager,
                    question_bank=question_bank,
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                ResultFlowController(shell).retry_all()

                self.assertEqual(qset.set_id, started["question_set"].set_id)
                self.assertEqual([q1.question_id, q2.question_id], [q.question_id for q in started["questions"]])
                self.assertEqual("practice", started["submission_mode"])

    def test_retry_all_explains_when_original_question_set_was_deleted(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                record = ProgressRecord.create_new("set-deleted")
                record.status = "completed"
                record.answers = [
                    AnswerRecord("q-deleted", 0, "B", False),
                ]
                shell = types.SimpleNamespace(
                    results_screen=types.SimpleNamespace(current_record=record),
                    set_manager=SetManager(str(Path(tmpdir) / "sets")),
                    question_bank=QuestionBank(str(Path(tmpdir) / "questions")),
                    lang_manager=LanguageManager.instance(),
                )

                with patch(
                    "ui.result_flow_controller.QMessageBox.warning"
                ) as warning:
                    ResultFlowController(shell).retry_all()

                warning.assert_called_once()
                self.assertIn("已被删除", warning.call_args.args[2])
