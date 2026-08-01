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

class HomeLearningFlowTests(unittest.TestCase):
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

    def test_home_screen_counts_incorrect_questions_for_current_course(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                course_a = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "A", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "A", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                course_a.metadata["course_id"] = "course-a"
                course_b = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "B", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "B", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                course_b.metadata["course_id"] = "course-b"
                question_bank.save_many([course_a, course_b])
                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=course_a.question_id, index_in_session=0, user_answer="B", is_correct=False),
                    AnswerRecord(question_id=course_b.question_id, index_in_session=1, user_answer="B", is_correct=False),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)
                progress_manager.save(record)

                screen = HomeScreen(progress_manager, question_bank)
                screen.set_current_course("course-a")
                screen.refresh()

                self.assertIn("本周学习 1 天", screen.stats_label.text())
                self.assertIn("完成 1 题", screen.stats_label.text())

    def test_home_screen_refresh_uses_lightweight_question_counts(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                course_question = self._make_question("course-a-q")
                course_question.metadata["course_id"] = "course-a"
                other_question = self._make_question("course-b-q")
                other_question.metadata["course_id"] = "course-b"
                question_bank.save_many([course_question, other_question])
                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=course_question.question_id, index_in_session=0, user_answer="B", is_correct=False),
                    AnswerRecord(question_id=other_question.question_id, index_in_session=1, user_answer="B", is_correct=False),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)
                progress_manager.save(record)

                screen = HomeScreen(progress_manager, question_bank)
                screen.set_current_course("course-a")

                with patch.object(progress_manager, "load_all", wraps=progress_manager.load_all) as load_all, \
                     patch.object(question_bank, "search", side_effect=AssertionError("home refresh should not load full search results")), \
                     patch.object(question_bank, "get_many", side_effect=AssertionError("home refresh should not load full question objects")):
                    screen.refresh()

                load_all.assert_called_once_with()
                self.assertIn("本周学习 1 天", screen.stats_label.text())
                self.assertIn("完成 1 题", screen.stats_label.text())

    def test_home_today_queue_emits_direct_course_scoped_intent(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                question = self._make_question("course-a-cache", "cache")
                question.metadata["course_id"] = "course-a"
                question_bank.save(question)
                screen = HomeScreen(
                    ProgressManager(str(Path(tmpdir) / "progress")),
                    question_bank,
                )
                screen.set_current_course("course-a", "Systems")
                requests = []
                signal = getattr(screen, "study_requested", None)
                self.assertIsNotNone(signal)
                signal.connect(requests.append)

                screen.start_btn.click()

                self.assertEqual(1, len(requests))
                intent = requests[0]
                self.assertIs(StudyAction.DAILY_QUEUE, intent.action)
                self.assertEqual("course-a", intent.course_id)
                self.assertEqual((), intent.topic_ids)
                self.assertEqual((question.question_id,), intent.question_ids)
                self.assertEqual((), intent.remaining_question_ids)
                self.assertEqual(1, intent.question_count)
                self.assertEqual("today_plan", intent.source)
                self.assertIn("course-a", intent.plan_id)

    def test_home_today_queue_distinguishes_current_group_from_today_total(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                questions = [
                    self._make_question(f"course-a-q-{index}", "cache")
                    for index in range(12)
                ]
                for question in questions:
                    question.metadata["course_id"] = "course-a"
                question_bank.save_many(questions)
                screen = HomeScreen(
                    ProgressManager(str(Path(tmpdir) / "progress")),
                    question_bank,
                )
                screen.set_current_course("course-a", "Systems")
                requests = []
                screen.study_requested.connect(requests.append)

                self.assertEqual("今日计划", screen.today_plan_title.text())
                self.assertIn("今日进度 0 / 12 题", screen.today_plan_detail.text())
                self.assertIn("第一组 10 题", screen.today_plan_detail.text())
                self.assertIn("完成后还有 2 题", screen.today_plan_detail.text())
                self.assertIn("开始第一组", screen.start_btn.text())
                screen.start_btn.click()

                intent = requests[0]
                self.assertEqual(10, len(intent.question_ids))
                self.assertEqual(2, len(intent.remaining_question_ids))

    def test_home_daily_plan_separates_today_count_from_total_backlog(self):
            from core.daily_study_plan_store import DailyStudyPlanStore

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                questions = [
                    self._make_question(f"course-a-q-{index:03d}", "cache")
                    for index in range(100)
                ]
                for question in questions:
                    question.metadata["course_id"] = "course-a"
                question_bank.save_many(questions)
                screen = HomeScreen(
                    ProgressManager(str(root / "progress")),
                    question_bank,
                    daily_plan_store=DailyStudyPlanStore(root / "daily-plans.json"),
                )

                screen.set_current_course("course-a", "Systems")

                self.assertIn("今日进度 0 / 15 题", screen.today_plan_detail.text())
                self.assertIn("第一组 10 题", screen.today_plan_detail.text())
                self.assertIn("完成后还有 5 题", screen.today_plan_detail.text())
                self.assertIn("明日预计 15 题", screen.next_step_label.text())

    def test_home_daily_plan_uses_balanced_topic_and_difficulty_metadata(self):
            from core.daily_study_plan_store import DailyStudyPlanStore

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                difficulties = (
                    Difficulty.EASY,
                    Difficulty.MEDIUM,
                    Difficulty.HARD,
                )
                questions = []
                for topic, count in (("memory", 9), ("process", 6)):
                    for index in range(count):
                        question = self._make_question(
                            f"course-a-{topic}-{index:02d}",
                            topic,
                        )
                        question.difficulty = difficulties[index % len(difficulties)]
                        question.metadata["course_id"] = "course-a"
                        questions.append(question)
                question_bank.save_many(questions)
                screen = HomeScreen(
                    ProgressManager(str(root / "progress")),
                    question_bank,
                    daily_plan_store=DailyStudyPlanStore(root / "daily-plans.json"),
                )

                screen.set_current_course(
                    "course-a",
                    "Systems",
                    exam_scope_weights={"memory": 60, "process": 40},
                )

                intent = screen._today_study_intent()
                topic_index = question_bank.topic_index(course_id="course-a")
                selected_topics = [
                    topic_index[question_id][0]
                    for question_id in (
                        intent.question_ids + intent.remaining_question_ids
                    )
                ]
                self.assertEqual({"memory", "process"}, set(selected_topics))
                self.assertIn("主题轮换", screen.today_plan_detail.toolTip())
                self.assertIn("难度", screen.today_plan_detail.toolTip())

    def test_main_syncs_course_topic_weights_to_home_scheduler(self):
            from ui.main_window import MainWindow

            course = CourseProject(
                course_id="course-a",
                title="Systems",
                source_folder="",
                summary_markdown="",
                summary_path="",
                topics=[
                    CourseTopic("memory", "Memory"),
                    CourseTopic("process", "Process"),
                ],
                documents=[],
                created_at="2026-07-01T00:00:00+00:00",
                updated_at="2026-07-01T00:00:00+00:00",
                generation_profile={
                    "topic_weights": {
                        "memory": 70,
                        "process": 30,
                        "outside": 100,
                    }
                },
                exam_scope_mode="selected",
                exam_scope_topic_ids=["memory", "process"],
            )
            captured = {}

            class FakeHomeScreen:
                def set_current_course(self, *args, **kwargs):
                    captured["args"] = args
                    captured["kwargs"] = kwargs

            shell = types.SimpleNamespace(
                course_manager=types.SimpleNamespace(current=lambda: course),
                home_screen=FakeHomeScreen(),
                _update_home_resume_draft=lambda: None,
            )

            CourseContextController(shell).sync_home()

            self.assertEqual({"memory", "process"}, captured["args"][2])
            self.assertEqual(
                {"memory": 70, "process": 30},
                captured["kwargs"]["exam_scope_weights"],
            )

    def test_home_keeps_completed_daily_plan_complete_after_repeat_failure(self):
            from core.daily_study_plan_store import DailyStudyPlanStore

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                question = self._make_question("course-a-q-1", "cache")
                question.metadata["course_id"] = "course-a"
                question_bank.save(question)
                progress_manager = ProgressManager(str(root / "progress"))
                store = DailyStudyPlanStore(root / "daily-plans.json")
                screen = HomeScreen(
                    progress_manager,
                    question_bank,
                    daily_plan_store=store,
                )
                screen.set_current_course("course-a", "Systems")
                intent = screen._today_study_intent()
                wrong = AnswerRecord(
                    question_id=question.question_id,
                    index_in_session=0,
                    user_answer="B",
                    is_correct=False,
                )

                plan = store.record_completion(
                    intent.plan_id,
                    current_question_ids=intent.question_ids,
                    answers=[wrong],
                )
                self.assertEqual((question.question_id,), plan.pending_ids)

                plan = store.record_completion(
                    intent.plan_id,
                    current_question_ids=plan.pending_ids,
                    answers=[wrong],
                )
                self.assertTrue(plan.is_complete)

                failed_record = ProgressRecord.create_new("daily")
                failed_record.status = "completed"
                failed_record.answers = [wrong]
                failed_record.summary = SessionSummary.compute([wrong], 1, 10)
                progress_manager.save(failed_record)
                restarted = HomeScreen(
                    ProgressManager(str(root / "progress")),
                    QuestionBank(str(root / "questions")),
                    daily_plan_store=DailyStudyPlanStore(root / "daily-plans.json"),
                )
                restarted.set_current_course("course-a", "Systems")

                self.assertIs(
                    LearningPlanAction.DAILY_COMPLETE,
                    restarted._today_plan.action,
                )
                self.assertIn("今日任务完成", restarted.today_plan_title.text())

    def test_home_today_queue_excludes_topics_marked_fully_mastered(self):
            from core.mastery_overrides import MasteryOverrideStore

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                mastered = self._make_question("q-mastered", "cache")
                visible = self._make_question("q-visible", "io")
                for question in (mastered, visible):
                    question.metadata["course_id"] = "course-a"
                question_bank.save_many([mastered, visible])
                overrides = MasteryOverrideStore(root / "mastery.json")
                overrides.mark_topic_mastered("course-a", "cache")
                screen = HomeScreen(
                    ProgressManager(str(root / "progress")),
                    question_bank,
                    mastery_overrides=overrides,
                )

                screen.set_current_course("course-a", "Systems")

                self.assertEqual((visible.question_id,), screen._today_plan.question_ids)
                self.assertEqual({visible.question_id}, screen._visible_question_ids())

    def test_home_screen_can_show_and_clear_resume_draft_action(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                screen = HomeScreen(
                    ProgressManager(str(Path(tmpdir) / "progress")),
                    QuestionBank(str(Path(tmpdir) / "questions")),
                )

                self.assertTrue(screen.resume_btn.isHidden())

                screen.set_resume_draft("系统结构练习", 3)

                self.assertTrue(screen.resume_btn.isHidden())
                self.assertIn("继续练习", screen.start_btn.text())
                self.assertIn("系统结构练习", screen.today_plan_detail.text())
                self.assertIn("3", screen.today_plan_detail.text())

                screen.set_resume_draft("系统结构练习", 13, current_index=6, total_count=20)

                self.assertIn("13", screen.today_plan_detail.text())

                screen.set_resume_draft("系统结构练习", 13, current_index=6, total_count=20, mode="exam")

                self.assertIn("继续模拟卷", screen.start_btn.text())

                screen.set_resume_draft("系统结构练习", 13, current_index=6, total_count=20, mode="practice")

                self.assertIn("继续练习", screen.start_btn.text())
                resumed = []
                screen.study_requested.connect(resumed.append)
                screen.start_btn.click()
                self.assertEqual(1, len(resumed))
                self.assertIs(StudyAction.RESUME_SESSION, resumed[0].action)
                self.assertEqual(13, resumed[0].question_count)

                screen.clear_resume_draft()

                self.assertTrue(screen.resume_btn.isHidden())
                self.assertNotIn("继续练习", screen.start_btn.text())

    def test_home_primary_action_routes_to_course_scoped_incorrect_review(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                question = self._make_question("course-a-q")
                question.metadata["course_id"] = "course-a"
                question_bank.save(question)
                record = ProgressRecord.create_new("set-a")
                record.status = "completed"
                record.answers = [AnswerRecord(
                    question_id=question.question_id,
                    index_in_session=0,
                    user_answer="B",
                    is_correct=False,
                )]
                record.summary = SessionSummary.compute(record.answers, 1, 10)
                progress_manager.save(record)
                screen = HomeScreen(progress_manager, question_bank)
                screen.set_current_course("course-a", "Systems")
                review_requests = []
                screen.study_requested.connect(review_requests.append)

                self.assertIn("开始第一组", screen.start_btn.text())
                self.assertIn("今日进度 0 / 1 题", screen.today_plan_detail.text())
                screen.start_btn.click()

                self.assertEqual(1, len(review_requests))
                self.assertIs(StudyAction.DAILY_QUEUE, review_requests[0].action)
                self.assertEqual("course-a", review_requests[0].course_id)
                self.assertEqual((question.question_id,), review_requests[0].question_ids)

    def test_home_primary_action_routes_new_users_to_course_import(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                screen = HomeScreen(
                    ProgressManager(str(Path(tmpdir) / "progress")),
                    QuestionBank(str(Path(tmpdir) / "questions")),
                )
                import_requests = []
                screen.study_requested.connect(import_requests.append)
                screen.refresh()

                self.assertIn("导入", screen.start_btn.text())
                screen.start_btn.click()

                self.assertEqual(1, len(import_requests))
                self.assertIs(StudyAction.IMPORT_COURSE, import_requests[0].action)
