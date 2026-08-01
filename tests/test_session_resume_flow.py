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

class SessionResumeFlowTests(unittest.TestCase):
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

    def test_resume_abandoned_practice_starts_only_remaining_questions_and_removes_draft(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                set_manager = SetManager(str(root / "sets"))
                progress_manager = ProgressManager(str(root / "progress"))
                answered = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Answered", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Answered", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                remaining = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Remaining", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Remaining", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                for question in (answered, remaining):
                    question.metadata["course_id"] = "course-a"
                question_bank.save_many([answered, remaining])
                qset = QuestionSet.create_new(
                    title={"zh": "系统结构练习", "en": "Architecture Practice"},
                    description={"zh": "", "en": ""},
                    topics=["cache"],
                    question_ids=[answered.question_id, remaining.question_id],
                )
                set_manager.save(qset)
                draft = ProgressRecord.create_new(qset.set_id)
                draft.progress_id = "draft"
                draft.status = "abandoned"
                draft.answers = [
                    AnswerRecord(question_id=answered.question_id, index_in_session=0, user_answer="A", is_correct=True),
                ]
                draft.summary = SessionSummary.compute(draft.answers, total_questions=2, total_time=10)
                progress_manager.save(draft)
                started = {}

                class FakeQuizScreen:
                    def start_quiz_custom(self, questions, label, show_timer=False):
                        started["questions"] = questions
                        started["label"] = label
                        started["show_timer"] = show_timer

                shell = types.SimpleNamespace(
                    progress_manager=progress_manager,
                    set_manager=set_manager,
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                MainWindow._on_resume_abandoned(shell)

                self.assertEqual([remaining.question_id], [q.question_id for q in started["questions"]])
                self.assertIn("系统结构练习", started["label"])
                self.assertIsNone(progress_manager.get("draft"))

    def test_resume_practice_prefers_snapshot_and_restores_full_session(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                set_manager = SetManager(str(root / "sets"))
                progress_manager = ProgressManager(str(root / "progress"))
                snapshot_manager = QuizSnapshotManager(str(root / "snapshots"))
                answered = self._make_question("q-answered")
                remaining = self._make_question("q-remaining")
                for question in (answered, remaining):
                    question.metadata["course_id"] = "course-a"
                question_bank.save_many([answered, remaining])
                qset = QuestionSet.create_new(
                    title={"zh": "系统结构练习", "en": "Architecture Practice"},
                    description={"zh": "", "en": ""},
                    topics=["cache"],
                    question_ids=[answered.question_id, remaining.question_id],
                )
                set_manager.save(qset)
                snapshot = QuizSessionSnapshot.create_new(
                    set_id=qset.set_id,
                    title="系统结构练习",
                    question_order=[answered.question_id, remaining.question_id],
                    language="zh",
                )
                snapshot.current_index = 1
                snapshot.submitted_answers = [
                    AnswerRecord(
                        question_id=answered.question_id,
                        index_in_session=0,
                        user_answer="A",
                        is_correct=True,
                    )
                ]
                snapshot.draft_answers = {remaining.question_id: "B"}
                snapshot_manager.save(snapshot)
                old_draft = ProgressRecord.create_new(qset.set_id)
                old_draft.progress_id = "old-draft"
                old_draft.status = "abandoned"
                old_draft.answers = [
                    AnswerRecord(question_id=answered.question_id, index_in_session=0, user_answer="A", is_correct=True),
                ]
                old_draft.summary = SessionSummary.compute(old_draft.answers, total_questions=2, total_time=10)
                progress_manager.save(old_draft)
                started = {}

                class FakeQuizScreen:
                    def restore_snapshot(self, snapshot_arg, questions, question_set, show_timer=False):
                        started["snapshot"] = snapshot_arg
                        started["questions"] = questions
                        started["question_set"] = question_set
                        started["show_timer"] = show_timer

                    def start_quiz_custom(self, questions, label, show_timer=False):
                        started["legacy_questions"] = questions

                shell = types.SimpleNamespace(
                    progress_manager=progress_manager,
                    snapshot_manager=snapshot_manager,
                    set_manager=set_manager,
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                MainWindow._on_resume_abandoned(shell)

                self.assertEqual(snapshot.snapshot_id, started["snapshot"].snapshot_id)
                self.assertEqual(
                    [answered.question_id, remaining.question_id],
                    [question.question_id for question in started["questions"]],
                )
                self.assertEqual(qset.set_id, started["question_set"].set_id)
                self.assertNotIn("legacy_questions", started)
                self.assertIsNotNone(snapshot_manager.get(snapshot.snapshot_id))

    def test_home_resume_draft_prefers_snapshot_position_text(self):
            from ui.main_window import MainWindow

            qset = QuestionSet.create_new(
                title={"zh": "系统结构练习", "en": "Architecture Practice"},
                description={"zh": "", "en": ""},
                topics=["cache"],
                question_ids=["q1", "q2"],
            )
            snapshot = QuizSessionSnapshot.create_new(
                set_id=qset.set_id,
                title="系统结构练习",
                question_order=["q1", "q2"],
                language="zh",
            )
            snapshot.current_index = 1
            shown = {}

            class FakeSnapshotManager:
                def load_latest(self):
                    return snapshot

            class FakeSetManager:
                def get(self, set_id):
                    return qset if set_id == qset.set_id else None

            class FakeQuestionBank:
                def get_many(self, question_ids, course_id=None):
                    return [self_outer._make_question(qid) for qid in question_ids]

            self_outer = self

            class FakeHomeScreen:
                def set_resume_draft(self, title, remaining_count, current_index=None, total_count=None, mode=None):
                    shown["title"] = title
                    shown["remaining_count"] = remaining_count
                    shown["current_index"] = current_index
                    shown["total_count"] = total_count
                    shown["mode"] = mode

                def clear_resume_draft(self):
                    shown["cleared"] = True

            shell = types.SimpleNamespace(
                home_screen=FakeHomeScreen(),
                snapshot_manager=FakeSnapshotManager(),
                set_manager=FakeSetManager(),
                question_bank=FakeQuestionBank(),
                lang_manager=LanguageManager.instance(),
                course_context=_course_context(),
            )

            MainWindow._update_home_resume_draft(shell)

            self.assertEqual("系统结构练习", shown["title"])
            self.assertEqual(1, shown["remaining_count"])
            self.assertEqual(1, shown["current_index"])
            self.assertEqual(2, shown["total_count"])

    def test_resume_daily_snapshot_rebuilds_temporary_set_and_plan_context(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                set_manager = SetManager(str(root / "sets"))
                snapshot_manager = QuizSnapshotManager(str(root / "snapshots"))
                question = self._make_question("q-daily", "cache")
                question.metadata["course_id"] = "course-a"
                question_bank.save(question)
                temporary_set = QuestionSet.create_new(
                    title={"zh": "今日学习", "en": "Today's Study"},
                    description={"zh": "", "en": ""},
                    topics=[],
                    question_ids=[question.question_id],
                    source="daily_queue",
                )
                snapshot = QuizSessionSnapshot.create_new(
                    set_id=temporary_set.set_id,
                    title="今日学习",
                    question_order=[question.question_id],
                )
                snapshot.question_set_data = temporary_set.to_dict()
                intent = StudyIntent(
                    course_id="course-a",
                    action=StudyAction.DAILY_QUEUE,
                    question_ids=(question.question_id,),
                    remaining_question_ids=("q-next",),
                    question_count=1,
                    source="today_plan",
                    plan_id="2026-07-28:course-a",
                )
                snapshot.study_intent_data = intent.to_dict()
                snapshot_manager.save(snapshot)
                shown = {}
                study_flow = types.SimpleNamespace(
                    restore_active_intent=Mock(),
                )

                class FakeQuizScreen:
                    def restore_snapshot(
                        self,
                        snapshot_arg,
                        questions,
                        question_set,
                        show_timer=False,
                    ):
                        shown["snapshot"] = snapshot_arg
                        shown["questions"] = questions
                        shown["question_set"] = question_set

                shell = types.SimpleNamespace(
                    progress_manager=ProgressManager(str(root / "progress")),
                    snapshot_manager=snapshot_manager,
                    set_manager=set_manager,
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=study_flow,
                    home_screen=types.SimpleNamespace(clear_resume_draft=Mock()),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: shown.setdefault("screen", screen),
                )

                MainWindow._on_resume_abandoned(shell)

                self.assertEqual(temporary_set.set_id, shown["question_set"].set_id)
                self.assertEqual([question], shown["questions"])
                restored_intent = study_flow.restore_active_intent.call_args.args[0]
                self.assertEqual(intent, restored_intent)
                self.assertIsNotNone(snapshot_manager.get(snapshot.snapshot_id))

    def test_home_resume_draft_passes_snapshot_mode_to_resume_action(self):
            from ui.main_window import MainWindow

            qset = QuestionSet.create_new(
                title={"zh": "系统结构练习", "en": "Architecture Practice"},
                description={"zh": "", "en": ""},
                topics=["cache"],
                question_ids=["q1"],
            )
            snapshot = QuizSessionSnapshot.create_new(
                set_id=qset.set_id,
                title="系统结构练习",
                question_order=["q1"],
                language="zh",
                mode="exam",
            )
            shown = {}

            class FakeSnapshotManager:
                def load_latest(self):
                    return snapshot

            class FakeSetManager:
                def get(self, set_id):
                    return qset if set_id == qset.set_id else None

            class FakeQuestionBank:
                def get_many(self, question_ids, course_id=None):
                    return [self_outer._make_question(qid) for qid in question_ids]

            self_outer = self

            class FakeHomeScreen:
                def set_resume_draft(self, title, remaining_count, current_index=None, total_count=None, mode=None):
                    shown["mode"] = mode

                def clear_resume_draft(self):
                    shown["cleared"] = True

            shell = types.SimpleNamespace(
                home_screen=FakeHomeScreen(),
                snapshot_manager=FakeSnapshotManager(),
                set_manager=FakeSetManager(),
                question_bank=FakeQuestionBank(),
                lang_manager=LanguageManager.instance(),
                course_context=_course_context(),
            )

            MainWindow._update_home_resume_draft(shell)

            self.assertEqual("exam", shown["mode"])

    def test_main_window_opens_persisted_history_without_original_assets(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                progress_dir = Path(tmpdir) / "progress"
                writer = ProgressManager(str(progress_dir))
                record = ProgressRecord.create_new("set-deleted")
                record.status = "completed"
                record.set_title_snapshot = "I/O 专项"
                record.answers = [
                    AnswerRecord(
                        question_id="q-deleted",
                        index_in_session=0,
                        user_answer="A",
                        is_correct=False,
                    )
                ]
                record.summary = SessionSummary.compute(record.answers, 1, 10)
                writer.save(record)

                shown = {}

                class FakeResultsScreen:
                    def set_results(
                        self,
                        progress_record,
                        questions,
                        lang,
                        *,
                        study_intent=None,
                    ):
                        shown["record"] = progress_record
                        shown["questions"] = questions
                        shown["lang"] = lang

                shell = types.SimpleNamespace(
                    progress_manager=ProgressManager(str(progress_dir)),
                    question_bank=types.SimpleNamespace(get_many=lambda _ids: []),
                    results_screen=FakeResultsScreen(),
                    lang_manager=LanguageManager.instance(),
                    study_flow=types.SimpleNamespace(
                        active_questions={"stale": object()},
                    ),
                    course_context=_course_context(
                        refresh_results_retry_availability=lambda: shown.setdefault(
                            "availability_refreshed",
                            True,
                        ),
                    ),
                    navigate_to=lambda index: shown.setdefault("navigated", index),
                    SCREEN_RESULTS=3,
                )

                ResultFlowController(shell).open_progress_record(
                    record.progress_id
                )

                self.assertEqual(record.progress_id, shown["record"].progress_id)
                self.assertEqual({}, shown["questions"])
                self.assertEqual({"stale"}, set(shell.study_flow.active_questions))
                self.assertTrue(shown["availability_refreshed"])
                self.assertEqual(3, shown["navigated"])

    def test_quiz_finished_deletes_snapshot_for_completed_set(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                progress_manager = ProgressManager(str(root / "progress"))
                snapshot_manager = QuizSnapshotManager(str(root / "snapshots"))
                qset = QuestionSet.create_new(
                    title={"zh": "系统结构练习", "en": "Architecture Practice"},
                    description={"zh": "", "en": ""},
                    topics=["cache"],
                    question_ids=["q1"],
                )
                snapshot = QuizSessionSnapshot.create_new(
                    set_id=qset.set_id,
                    title="系统结构练习",
                    question_order=["q1"],
                )
                snapshot_manager.save(snapshot)
                record = ProgressRecord.create_new(qset.set_id)
                record.status = "completed"
                shown = {}
                study_intent = StudyIntent(
                    course_id="course-a",
                    action=StudyAction.PRACTICE_TOPIC,
                    topic_ids=("cache",),
                    question_count=1,
                    source="today_plan",
                )

                class FakeResultsScreen:
                    def set_results(
                        self,
                        progress_record,
                        questions,
                        lang,
                        *,
                        study_intent=None,
                    ):
                        shown["record"] = progress_record
                        shown["questions"] = questions
                        shown["lang"] = lang
                        shown["study_intent"] = study_intent

                shell = types.SimpleNamespace(
                    progress_manager=progress_manager,
                    snapshot_manager=snapshot_manager,
                    results_screen=FakeResultsScreen(),
                    study_flow=types.SimpleNamespace(
                        active_questions={},
                        take_active_intent=Mock(return_value=study_intent),
                    ),
                    lang_manager=LanguageManager.instance(),
                    SCREEN_RESULTS=3,
                    navigate_to=lambda screen: shown.setdefault("screen", screen),
                    _refresh_first_run=Mock(),
                )

                ResultFlowController(shell).quiz_finished(record)

                self.assertIsNone(snapshot_manager.get(snapshot.snapshot_id))
                self.assertEqual(record.progress_id, shown["record"].progress_id)
                self.assertIs(study_intent, shown["study_intent"])
                shell.study_flow.take_active_intent.assert_called_once_with()
                shell._refresh_first_run.assert_called_once_with()

    def test_quiz_finished_reconciles_daily_plan_before_showing_results(self):
            from core.daily_study_plan_store import DailyStudyPlanStore
            from core.study_queue import build_daily_study_queue
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                store = DailyStudyPlanStore(root / "daily-plans.json")
                plan = store.get_or_create(
                    plan_id="2026-07-28:course-a",
                    plan_date="2026-07-28",
                    course_id="course-a",
                    queue=build_daily_study_queue({"q-1"}, []),
                    valid_question_ids={"q-1"},
                )
                intent = StudyIntent(
                    course_id="course-a",
                    action=StudyAction.DAILY_QUEUE,
                    set_id="daily-set",
                    question_ids=("q-1",),
                    question_count=1,
                    submission_mode="exam",
                    source="today_plan",
                    plan_id=plan.plan_id,
                )
                record = ProgressRecord.create_new("daily")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(
                        question_id="q-1",
                        index_in_session=0,
                        user_answer="B",
                        is_correct=False,
                    )
                ]
                record.summary = SessionSummary.compute(record.answers, 1, 10)
                shown = {}

                class FakeResultsScreen:
                    def set_results(
                        self,
                        progress_record,
                        questions,
                        lang,
                        *,
                        study_intent=None,
                    ):
                        shown["intent"] = study_intent

                shell = types.SimpleNamespace(
                    progress_manager=ProgressManager(str(root / "progress")),
                    snapshot_manager=None,
                    daily_plan_store=store,
                    results_screen=FakeResultsScreen(),
                    study_flow=types.SimpleNamespace(
                        active_questions={},
                        take_active_intent=Mock(return_value=intent),
                    ),
                    lang_manager=LanguageManager.instance(),
                    SCREEN_RESULTS=3,
                    navigate_to=lambda screen: shown.setdefault("screen", screen),
                    _refresh_first_run=Mock(),
                )

                ResultFlowController(shell).quiz_finished(record)

                self.assertEqual(("q-1",), shown["intent"].remaining_question_ids)
                self.assertEqual("daily-set", shown["intent"].set_id)
                self.assertEqual("exam", shown["intent"].submission_mode)
                self.assertFalse(store.get(plan.plan_id).is_complete)

    def test_home_resume_draft_deletes_snapshot_when_questions_are_missing(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                set_manager = SetManager(str(root / "sets"))
                snapshot_manager = QuizSnapshotManager(str(root / "snapshots"))
                existing = self._make_question("q1")
                question_bank.save(existing)
                qset = QuestionSet.create_new(
                    title={"zh": "系统结构练习", "en": "Architecture Practice"},
                    description={"zh": "", "en": ""},
                    topics=["cache"],
                    question_ids=["q1", "q-missing"],
                )
                set_manager.save(qset)
                snapshot = QuizSessionSnapshot.create_new(
                    set_id=qset.set_id,
                    title="系统结构练习",
                    question_order=["q1", "q-missing"],
                )
                snapshot_manager.save(snapshot)
                shown = {}

                class FakeHomeScreen:
                    def set_resume_draft(self, *args, **kwargs):
                        shown["shown"] = True

                    def clear_resume_draft(self):
                        shown["cleared"] = True

                shell = types.SimpleNamespace(
                    home_screen=FakeHomeScreen(),
                    snapshot_manager=snapshot_manager,
                    set_manager=set_manager,
                    question_bank=question_bank,
                    progress_manager=ProgressManager(str(root / "progress")),
                    lang_manager=LanguageManager.instance(),
                    course_context=_course_context(),
                )

                MainWindow._update_home_resume_draft(shell)

                self.assertTrue(shown.get("cleared"))
                self.assertNotIn("shown", shown)
                self.assertIsNone(snapshot_manager.get(snapshot.snapshot_id))

    def test_resume_snapshot_missing_set_shows_warning_and_deletes_snapshot(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                snapshot_manager = QuizSnapshotManager(str(root / "snapshots"))
                snapshot = QuizSessionSnapshot.create_new(
                    set_id="missing-set",
                    title="损坏草稿",
                    question_order=["q1"],
                )
                snapshot_manager.save(snapshot)

                class FakeSetManager:
                    def get(self, set_id):
                        return None

                shell = types.SimpleNamespace(
                    progress_manager=ProgressManager(str(root / "progress")),
                    snapshot_manager=snapshot_manager,
                    set_manager=FakeSetManager(),
                    question_bank=QuestionBank(str(root / "questions")),
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=types.SimpleNamespace(),
                    SCREEN_QUIZ=2,
                    course_context=_course_context(),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: None,
                )

                with patch("ui.main_window.QMessageBox.warning") as warning:
                    MainWindow._on_resume_abandoned(shell)

                self.assertTrue(warning.called)
                message = warning.call_args.args[2]
                self.assertIn("草稿", message)
                self.assertIn("题目集", message)
                self.assertIsNone(snapshot_manager.get(snapshot.snapshot_id))
