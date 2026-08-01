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

class ProgressDashboardFlowTests(unittest.TestCase):
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

    def test_progress_stats_can_filter_by_question_ids(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id="q1", index_in_session=0, user_answer="A", is_correct=True),
                    AnswerRecord(question_id="q2", index_in_session=1, user_answer="B", is_correct=False),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)
                progress_manager.save(record)

                stats = progress_manager.get_aggregated_stats({"q1"})

                self.assertEqual(1, stats["total_sessions"])
                self.assertEqual(1, stats["total_questions"])
                self.assertEqual(1, stats["total_correct"])
                self.assertEqual(100.0, stats["overall_accuracy"])
                self.assertEqual(1, stats["partial_sessions"])
                self.assertEqual(1, stats["recent_sessions"][0]["matched_total"])
                self.assertEqual(2, stats["recent_sessions"][0]["session_total"])
                self.assertTrue(stats["recent_sessions"][0]["is_partial"])

    def test_progress_dashboard_filters_stats_and_topics_by_current_course(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("en")
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
                    topic="process_scheduling",
                )
                course_b.metadata["course_id"] = "course-b"
                question_bank.save_many([course_a, course_b])
                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=course_a.question_id, index_in_session=0, user_answer="A", is_correct=True),
                    AnswerRecord(question_id=course_b.question_id, index_in_session=1, user_answer="B", is_correct=False),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)
                progress_manager.save(record)

                screen = self._make_progress_dashboard(
                    tmpdir, progress_manager, question_bank
                )
                screen.set_current_course("course-a")
                screen.refresh()

                self.assertEqual("Learning Analysis", screen.title.text())
                self.assertIn("This week: 1 day", screen.overall_label.text())
                self.assertIn("1 answered", screen.detail_label.text())
                self.assertIn("100.0% accuracy", screen.detail_label.text())
                self.assertEqual(1, screen.topic_table.rowCount())
                self.assertEqual("100%", screen.topic_table.item(0, 2).text())
                self.assertEqual("75%", screen.topic_table.item(0, 3).text())
                self.assertEqual("1/1", screen.topic_table.item(0, 4).text())
                self.assertEqual("", screen.recommendation_label.text())
                self.assertTrue(screen.recommendation_label.isHidden())

    def test_progress_dashboard_reuses_course_search_results_for_topic_table(self):
            class SearchOnlyQuestionBank:
                def __init__(self, questions):
                    self.questions = list(questions)
                    self.search_calls = 0
                    self.load_all_calls = 0

                def search(self, **kwargs):
                    self.search_calls += 1
                    self.last_search_kwargs = kwargs
                    return list(self.questions), len(self.questions)

                def load_all(self):
                    self.load_all_calls += 1
                    raise AssertionError("course-scoped progress dashboard should not load all questions")

                def get_many(self, question_ids, course_id=None):
                    wanted = set(question_ids)
                    return [question for question in self.questions if question.question_id in wanted]

            with tempfile.TemporaryDirectory() as tmpdir:
                question = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                question.metadata["course_id"] = "course-a"
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=question.question_id, index_in_session=0, user_answer="A", is_correct=True),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=1, total_time=10)
                progress_manager.save(record)
                question_bank = SearchOnlyQuestionBank([question])

                screen = self._make_progress_dashboard(
                    tmpdir, progress_manager, question_bank
                )
                screen.set_current_course("course-a")
                screen.refresh()

                self.assertEqual(1, question_bank.search_calls)
                self.assertEqual(0, question_bank.load_all_calls)
                self.assertEqual(1, screen.topic_table.rowCount())

    def test_progress_dashboard_collapses_long_recent_history_until_requested(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                progress_manager = ProgressManager(str(root / "progress"))
                question_bank = QuestionBank(str(root / "questions"))
                for index in range(6):
                    record = ProgressRecord.create_new(f"set-{index}")
                    record.status = "completed"
                    record.summary = SessionSummary.compute([], total_questions=1, total_time=10)
                    progress_manager.save(record)

                screen = self._make_progress_dashboard(
                    tmpdir, progress_manager, question_bank
                )
                screen.refresh()

                self.assertEqual(6, screen.recent_list.count())
                self.assertTrue(screen.recent_toggle_btn.isVisibleTo(screen))
                self.assertFalse(screen.recent_list.isVisibleTo(screen))
                self.assertIn("6", screen.recent_toggle_btn.text())
                self.assertIn("展开", screen.recent_toggle_btn.text())

                screen.recent_toggle_btn.click()

                self.assertTrue(screen.recent_list.isVisibleTo(screen))
                self.assertIn("收起", screen.recent_toggle_btn.text())

                screen.refresh()

                self.assertTrue(screen.recent_list.isVisibleTo(screen))
                self.assertIn("收起", screen.recent_toggle_btn.text())

    def test_progress_dashboard_opens_archived_session_by_snapshot_title(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                progress_manager = ProgressManager(str(root / "progress"))
                question_bank = QuestionBank(str(root / "questions"))
                record = ProgressRecord.create_new("set-internal-deleted")
                record.status = "completed"
                record.set_title_snapshot = "I/O 专项"
                record.course_title_snapshot = "操作系统"
                record.summary = SessionSummary.compute([], total_questions=1, total_time=10)
                progress_manager.save(record)
                screen = self._make_progress_dashboard(
                    tmpdir,
                    progress_manager,
                    question_bank,
                )
                requested = []
                screen.history_requested.connect(requested.append)

                screen.refresh()
                item = screen.recent_list.item(0)
                screen.recent_list.itemActivated.emit(item)

                self.assertIn("操作系统", item.text())
                self.assertIn("I/O 专项", item.text())
                self.assertNotIn("set-internal-deleted", item.text())
                self.assertEqual(record.progress_id, item.data(Qt.ItemDataRole.UserRole))
                self.assertEqual([record.progress_id], requested)

    def test_progress_dashboard_distinguishes_incomplete_and_legacy_history(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                progress_manager = ProgressManager(str(root / "progress"))
                question_bank = QuestionBank(str(root / "questions"))
                records = []
                for status, started_at in (
                    ("complete", "2026-07-28T03:00:00+00:00"),
                    ("incomplete", "2026-07-28T02:00:00+00:00"),
                    ("legacy", "2026-07-28T01:00:00+00:00"),
                ):
                    record = ProgressRecord.create_new(f"set-{status}")
                    record.progress_id = f"progress-{status}"
                    record.started_at = started_at
                    record.status = "completed"
                    record.archive_status = status
                    record.archive_missing_fields = (
                        ["question:q-lost"] if status == "incomplete" else []
                    )
                    record.summary = SessionSummary.compute(
                        [],
                        total_questions=1,
                        total_time=10,
                    )
                    progress_manager.save(record)
                    records.append(record)
                screen = self._make_progress_dashboard(
                    tmpdir,
                    progress_manager,
                    question_bank,
                )

                screen.refresh()

                items = {
                    str(screen.recent_list.item(index).data(Qt.ItemDataRole.UserRole)):
                    screen.recent_list.item(index)
                    for index in range(screen.recent_list.count())
                }
                self.assertIn("残缺", items["progress-incomplete"].text())
                self.assertIn("只能复盘已保存部分", items["progress-incomplete"].toolTip())
                self.assertIn("待保护", items["progress-legacy"].text())
                self.assertIn("尚未完成历史保护", items["progress-legacy"].toolTip())
                self.assertNotIn("残缺", items["progress-complete"].text())
                self.assertNotIn("待保护", items["progress-complete"].text())

    def test_progress_dashboard_keeps_short_recent_history_visible(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                progress_manager = ProgressManager(str(root / "progress"))
                question_bank = QuestionBank(str(root / "questions"))
                for index in range(5):
                    record = ProgressRecord.create_new(f"set-{index}")
                    record.status = "completed"
                    record.summary = SessionSummary.compute([], total_questions=1, total_time=10)
                    progress_manager.save(record)

                screen = self._make_progress_dashboard(
                    tmpdir, progress_manager, question_bank
                )
                screen.refresh()

                self.assertTrue(screen.recent_list.isVisibleTo(screen))
                self.assertFalse(screen.recent_toggle_btn.isVisibleTo(screen))

    def test_progress_dashboard_recommends_low_mastery_topics_for_current_course(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                cache = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                cache.metadata["course_id"] = "course-a"
                process = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="process",
                )
                process.metadata["course_id"] = "course-a"
                other_course = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Other", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Other", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="virtual memory",
                )
                other_course.metadata["course_id"] = "course-b"
                question_bank.save_many([cache, process, other_course])

                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=cache.question_id, index_in_session=0, user_answer="B", is_correct=False),
                    AnswerRecord(question_id=process.question_id, index_in_session=1, user_answer="A", is_correct=True),
                    AnswerRecord(question_id=other_course.question_id, index_in_session=2, user_answer="B", is_correct=False),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=3, total_time=30)
                progress_manager.save(record)

                screen = self._make_progress_dashboard(
                    tmpdir, progress_manager, question_bank
                )
                screen.set_current_course("course-a")
                screen.refresh()

                self.assertIn("建议复习", screen.recommendation_label.text())
                self.assertIn("Cache", screen.recommendation_label.text())
                self.assertNotIn("Process", screen.recommendation_label.text())
                self.assertNotIn("Virtual Memory", screen.recommendation_label.text())
                self.assertFalse(screen.recommendation_label.isHidden())
                self.assertFalse(screen.focus_action_buttons[0].isHidden())
                self.assertEqual("", screen.source_refs_label.text())
                self.assertTrue(screen.source_refs_label.isHidden())

    def test_progress_dashboard_uses_course_topic_title_instead_of_internal_id(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                course_manager = CourseProjectManager(str(root / "courses"))
                course_manager.save(CourseProject(
                    course_id="course-a",
                    title="Computer Systems",
                    source_folder=str(root),
                    summary_markdown="",
                    summary_path=str(root / "summary.md"),
                    topics=[CourseTopic(
                        topic_id="input_output_improvements",
                        title="Input Output Improvements",
                    )],
                    documents=[],
                    created_at="2026-07-12T00:00:00+00:00",
                    updated_at="2026-07-12T00:00:00+00:00",
                ))
                question_bank = QuestionBank(str(root / "questions"))
                progress_manager = ProgressManager(str(root / "progress"))
                question = self._make_question("q-io")
                question.topic = "input_output_improvements"
                question.metadata["course_id"] = "course-a"
                question_bank.save(question)
                record = ProgressRecord.create_new("set-io")
                record.status = "completed"
                record.answers = [AnswerRecord("q-io", 0, "B", False)]
                record.summary = SessionSummary.compute(record.answers, 1, 10)
                progress_manager.save(record)

                screen = self._make_progress_dashboard(
                    tmpdir,
                    progress_manager,
                    question_bank,
                    course_manager=course_manager,
                )
                screen.set_current_course("course-a")
                screen.refresh()

                self.assertEqual("Input Output Improvements", screen.topic_table.item(0, 0).text())
                self.assertIn("Input Output Improvements", screen.recommendation_label.text())
                self.assertNotIn("input_output_improvements", screen.recommendation_label.text())

    def test_topic_display_name_humanizes_unknown_stable_id(self):
            from core.topic_display import topic_display_name

            self.assertEqual(
                "Virtual Memory Address Translation",
                topic_display_name("virtual_memory_address_translation", language="en"),
            )

    def test_progress_dashboard_shows_source_refs_for_recommended_topics(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                cache = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                cache.metadata["course_id"] = "course-a"
                cache.metadata["source_refs"] = [
                    {
                        "chunk_id": "cache-chunk-8",
                        "source_file": "Cache.pdf",
                        "page_or_slide": 8,
                        "heading": "Cache Address Breakdown",
                    }
                ]
                process = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="process",
                )
                process.metadata["course_id"] = "course-a"
                process.metadata["source_refs"] = [
                    {
                        "chunk_id": "process-chunk-1",
                        "source_file": "Process.pdf",
                        "page_or_slide": 1,
                        "heading": "Process States",
                    }
                ]
                question_bank.save_many([cache, process])

                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=cache.question_id, index_in_session=0, user_answer="B", is_correct=False),
                    AnswerRecord(question_id=process.question_id, index_in_session=1, user_answer="A", is_correct=True),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)
                progress_manager.save(record)

                screen = self._make_progress_dashboard(
                    tmpdir, progress_manager, question_bank
                )
                screen.set_current_course("course-a")
                screen.refresh()

                self.assertTrue(screen.source_refs_label.isHidden())

                screen.topic_table.selectRow(0)
                screen.view_topic_source_action.trigger()

                source_text = screen.source_refs_label.text()
                self.assertFalse(screen.source_refs_label.isHidden())
                self.assertIn("主题来源", source_text)
                self.assertIn("Cache.pdf", source_text)
                self.assertIn("页码/幻灯片 8", source_text)
                self.assertIn("cache-chunk-8", source_text)
                self.assertNotIn("Process.pdf", source_text)

    def test_progress_dashboard_skips_topics_marked_fully_mastered(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                progress_manager = ProgressManager(str(root / "progress"))
                mastery_overrides = MasteryOverrideStore(root / "mastery_overrides.json")
                cache = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                cache.metadata["course_id"] = "course-a"
                process = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="process",
                )
                process.metadata["course_id"] = "course-a"
                question_bank.save_many([cache, process])

                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=cache.question_id, index_in_session=0, user_answer="B", is_correct=False),
                    AnswerRecord(question_id=process.question_id, index_in_session=1, user_answer="B", is_correct=False),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=2, total_time=20)
                progress_manager.save(record)

                screen = self._make_progress_dashboard(
                    tmpdir,
                    progress_manager,
                    question_bank,
                    mastery_overrides=mastery_overrides,
                )
                screen.set_current_course("course-a")
                screen.refresh()

                self.assertIn("Cache", screen.recommendation_label.text())

                cache_row = 0
                screen.topic_table.selectRow(cache_row)
                screen.mark_mastered_action.trigger()

                self.assertTrue(mastery_overrides.is_topic_mastered("course-a", "cache"))
                self.assertEqual("已掌握", screen.topic_table.item(cache_row, 3).text())
                self.assertNotIn("Cache", screen.recommendation_label.text())
                self.assertIn("Process", screen.recommendation_label.text())

                screen.mark_mastered_action.trigger()

                self.assertFalse(mastery_overrides.is_topic_mastered("course-a", "cache"))
                self.assertIn("Cache", screen.recommendation_label.text())

    def test_progress_dashboard_topic_action_buttons_emit_selected_topic(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                question = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                question.metadata["course_id"] = "course-a"
                question.metadata["source_refs"] = [{
                    "source_file": "Cache.pdf",
                    "page_or_slide": 8,
                    "heading": "Cache Address Breakdown",
                }]
                question_bank.save(question)
                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=question.question_id, index_in_session=0, user_answer="B", is_correct=False),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=1, total_time=10)
                progress_manager.save(record)
                screen = self._make_progress_dashboard(
                    tmpdir, progress_manager, question_bank
                )
                screen.set_current_course("course-a")
                screen.refresh()

                emitted: list[tuple[str, str]] = []
                screen.practice_topic_requested.connect(lambda topic: emitted.append(("practice", topic)))
                screen.review_topic_requested.connect(lambda topic: emitted.append(("review", topic)))
                screen.generate_topic_requested.connect(lambda topic: emitted.append(("generate", topic)))

                screen.topic_table.selectRow(0)
                self.assertTrue(screen.practice_topic_btn.isEnabled())
                self.assertTrue(screen.review_topic_btn.isEnabled())
                self.assertTrue(screen.generate_topic_action.isEnabled())

                screen.practice_topic_btn.click()
                screen.review_topic_btn.click()
                screen.generate_topic_action.trigger()
                screen.view_topic_source_action.trigger()

                self.assertEqual(
                    [("practice", "cache"), ("review", "cache"), ("generate", "cache")],
                    emitted,
                )
                self.assertFalse(screen.source_refs_panel.isHidden())
                self.assertIn("Cache.pdf", screen.source_refs_panel.text())
                self.assertIn("主题来源", screen.source_refs_panel.text())

    def test_progress_topic_actions_use_three_text_only_top_level_entries(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")
            with tempfile.TemporaryDirectory() as tmpdir:
                screen = self._make_progress_dashboard(
                    tmpdir,
                    ProgressManager(str(Path(tmpdir) / "progress")),
                    QuestionBank(str(Path(tmpdir) / "questions")),
                )

                top_level_widgets = [
                    screen.topic_action_layout.itemAt(index).widget()
                    for index in range(screen.topic_action_layout.count())
                    if screen.topic_action_layout.itemAt(index).widget() is not None
                ]

                self.assertEqual(
                    [screen.topic_action_hint, screen.practice_topic_btn, screen.review_topic_btn, screen.more_topic_actions_btn],
                    top_level_widgets,
                )
                self.assertTrue(screen.more_topic_actions_btn.icon().isNull())
                self.assertEqual(
                    ["生成新题", "查看来源", "标记已掌握"],
                    [action.text() for action in screen.more_topic_actions_menu.actions()],
                )

    def test_progress_topic_generation_builds_single_topic_reviewable_plan(self):
            from ui.main_window import MainWindow

            calls = []
            host = types.SimpleNamespace(
                generation_flow=types.SimpleNamespace(
                    open=lambda **kwargs: calls.append(kwargs)
                )
            )

            MainWindow._on_generate_progress_topic(host, "cache")

            plan = calls[0]["initial_plan"]
            self.assertEqual(10, plan.question_count)
            self.assertEqual(("cache",), plan.selected_topics)
            self.assertEqual({"cache": 100}, dict(plan.topic_weights))

    def test_learning_analysis_leaves_destructive_reset_in_settings(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                progress_manager = ProgressManager(str(root / "progress"))
                question_bank = QuestionBank(str(root / "questions"))
                mastery_overrides = MasteryOverrideStore(root / "mastery_overrides.json")
                mastery_overrides.mark_topic_mastered("course-a", "cache")

                screen = self._make_progress_dashboard(
                    root,
                    progress_manager,
                    question_bank,
                    mastery_overrides=mastery_overrides,
                )

                self.assertFalse(hasattr(screen, "reset_btn"))
                self.assertFalse(hasattr(screen, "_reset_progress"))
                self.assertTrue(
                    mastery_overrides.is_topic_mastered("course-a", "cache")
                )

    def test_incorrect_review_uses_current_course_filter(self):
            from ui.main_window import MainWindow

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

                started = {}

                class FakeQuizScreen:
                    def start_quiz_custom(self, questions, label, show_timer=False):
                        started["questions"] = questions
                        started["label"] = label
                        started["show_timer"] = show_timer

                shell = types.SimpleNamespace(
                    progress_manager=progress_manager,
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                ResultFlowController(shell).practice_incorrect()

                self.assertEqual(
                    {course_a.question_id},
                    set(shell.study_flow.active_questions),
                )
                self.assertEqual([course_a.question_id], [q.question_id for q in started["questions"]])

    def test_incorrect_review_uses_mastery_priority_order(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                lower_priority = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "旧错题", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Old mistake", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                lower_priority.metadata["course_id"] = "course-a"
                higher_priority = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "反复错题", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Repeated mistake", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                higher_priority.metadata["course_id"] = "course-a"
                question_bank.save_many([lower_priority, higher_priority])

                class FakeProgressManager:
                    def get_incorrect_question_ids(self):
                        raise AssertionError("historical review should use mastery-prioritized IDs")

                    def get_prioritized_review_question_ids(self):
                        return [higher_priority.question_id, lower_priority.question_id]

                started = {}

                class FakeQuizScreen:
                    def start_quiz_custom(self, questions, label, show_timer=False):
                        started["questions"] = questions
                        started["label"] = label
                        started["show_timer"] = show_timer

                shell = types.SimpleNamespace(
                    progress_manager=FakeProgressManager(),
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                ResultFlowController(shell).practice_incorrect()

                self.assertEqual(
                    [higher_priority.question_id, lower_priority.question_id],
                    [q.question_id for q in started["questions"]],
                )

    def test_progress_topic_practice_starts_first_ten_questions_for_topic(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                cache_questions = []
                for index in range(12):
                    question = Question.create_new(
                        qtype=QuestionType.MULTIPLE_CHOICE,
                        difficulty=Difficulty.MEDIUM,
                        bilingual={
                            "zh": {"stem": f"Cache {index}", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                            "en": {"stem": f"Cache {index}", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        },
                        correct_answer="A",
                        topic="cache",
                    )
                    question.metadata["course_id"] = "course-a"
                    cache_questions.append(question)
                process = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="process",
                )
                process.metadata["course_id"] = "course-a"
                question_bank.save_many([*cache_questions, process])

                started = {}

                class FakeQuizScreen:
                    def start_quiz_custom(self, questions, label, show_timer=False, submission_mode="practice"):
                        started["questions"] = questions
                        started["label"] = label
                        started["submission_mode"] = submission_mode

                shell = types.SimpleNamespace(
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                MainWindow._on_practice_progress_topic(shell, "cache")

                self.assertEqual(10, len(started["questions"]))
                self.assertEqual({"cache"}, {topic_value(question.topic) for question in started["questions"]})
                self.assertEqual("practice", started["submission_mode"])
                self.assertEqual(2, started["screen"])

    def test_progress_topic_review_starts_only_incorrect_questions_for_topic(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                cache_wrong = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Cache wrong", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Cache wrong", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                cache_right = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Cache right", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Cache right", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                process_wrong = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Process wrong", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Process wrong", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="process",
                )
                for question in (cache_wrong, cache_right, process_wrong):
                    question.metadata["course_id"] = "course-a"
                question_bank.save_many([cache_wrong, cache_right, process_wrong])
                record = ProgressRecord.create_new("set-any")
                record.status = "completed"
                record.answers = [
                    AnswerRecord(question_id=cache_wrong.question_id, index_in_session=0, user_answer="B", is_correct=False),
                    AnswerRecord(question_id=cache_right.question_id, index_in_session=1, user_answer="A", is_correct=True),
                    AnswerRecord(question_id=process_wrong.question_id, index_in_session=2, user_answer="B", is_correct=False),
                ]
                record.summary = SessionSummary.compute(record.answers, total_questions=3, total_time=20)
                progress_manager.save(record)

                started = {}

                class FakeQuizScreen:
                    def start_quiz_custom(self, questions, label, show_timer=False, submission_mode="practice"):
                        started["questions"] = questions
                        started["label"] = label
                        started["submission_mode"] = submission_mode

                shell = types.SimpleNamespace(
                    progress_manager=progress_manager,
                    question_bank=question_bank,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                MainWindow._on_review_progress_topic(shell, "cache")

                self.assertEqual([cache_wrong.question_id], [question.question_id for question in started["questions"]])
                self.assertEqual("practice", started["submission_mode"])
                self.assertEqual(2, started["screen"])

    def test_incorrect_review_skips_fully_mastered_topics(self):
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                mastered = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Cache", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="cache",
                )
                mastered.metadata["course_id"] = "course-a"
                active = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                        "en": {"stem": "Process", "options": ["A. one", "B. two"], "explanation": "A valid explanation text."},
                    },
                    correct_answer="A",
                    topic="process",
                )
                active.metadata["course_id"] = "course-a"
                question_bank.save_many([mastered, active])

                class FakeProgressManager:
                    def get_prioritized_review_question_ids(self):
                        return [mastered.question_id, active.question_id]

                mastery_overrides = MasteryOverrideStore(root / "mastery_overrides.json")
                mastery_overrides.mark_topic_mastered("course-a", "cache")
                started = {}

                class FakeQuizScreen:
                    def start_quiz_custom(self, questions, label, show_timer=False):
                        started["questions"] = questions

                shell = types.SimpleNamespace(
                    progress_manager=FakeProgressManager(),
                    question_bank=question_bank,
                    mastery_overrides=mastery_overrides,
                    lang_manager=LanguageManager.instance(),
                    quiz_screen=FakeQuizScreen(),
                    study_flow=_StudyFlowSpy(started),
                    SCREEN_QUIZ=2,
                    course_context=_course_context("course-a"),
                    _show_timer_setting=lambda: False,
                    navigate_to=lambda screen: started.setdefault("screen", screen),
                )

                ResultFlowController(shell).practice_incorrect()

                self.assertEqual([active.question_id], [q.question_id for q in started["questions"]])
