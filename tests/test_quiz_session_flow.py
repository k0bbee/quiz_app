import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QMessageBox, QRadioButton

from models.progress import (
    AnswerRecord,
    ProgressRecord,
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
from ui.screens.progress_dashboard import ProgressDashboard
from ui.screens.quiz_screen import QuizScreen
from ui.screens.results_screen import ResultsScreen
from ui.widgets.answer_area import AnswerArea, MatchingWidget, MultipleChoiceWidget
from utils.constants import Difficulty, QuestionType, QuizState


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

class QuizSessionFlowTests(unittest.TestCase):
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

    def test_quiz_screen_supports_question_preview_filter_and_free_navigation(self):
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")

            first = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "选择题题干", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                    "en": {"stem": "Choice stem", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                },
                correct_answer="A",
                topic="test",
            )
            second = Question.create_new(
                qtype=QuestionType.TRUE_FALSE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "判断题题干", "options": ["正确", "错误"], "explanation": "解释说明"},
                    "en": {"stem": "True false stem", "options": ["True", "False"], "explanation": "Explanation text"},
                },
                correct_answer="true",
                topic="test",
            )
            third = Question.create_new(
                qtype=QuestionType.FILL_IN_BLANK,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "填空题题干", "options": [], "explanation": "解释说明"},
                    "en": {"stem": "Blank stem", "options": [], "explanation": "Explanation text"},
                },
                correct_answer="answer",
                topic="test",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[first.question_id, second.question_id, third.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [first, second, third], show_timer=False)

                self.assertEqual(3, screen.question_nav_list.count())
                self.assertEqual("全部题型", screen.question_filter_combo.itemText(0))
                self.assertFalse(screen.prev_question_btn.isEnabled())
                self.assertTrue(screen.next_question_btn.isEnabled())

                screen.question_filter_combo.setCurrentText("判断题")

                self.assertEqual(1, screen.question_nav_list.count())
                self.assertIn("判断题", screen.question_nav_list.item(0).text())

                screen.question_filter_combo.setCurrentIndex(0)
                true_false_row = next(
                    row
                    for row in range(screen.question_nav_list.count())
                    if "判断题" in screen.question_nav_list.item(row).text()
                )
                true_false_index = screen.question_nav_list.item(true_false_row).data(
                    Qt.ItemDataRole.UserRole
                )
                screen._toggle_review_panel()
                screen.question_nav_list.setCurrentRow(true_false_row)
                self.assertEqual(true_false_index, screen.session.current_index)
                self.assertIn("判断题题干", screen.question_card.stem_label.text())

                if true_false_index > 0:
                    screen.prev_question_btn.click()
                    self.assertEqual(true_false_index - 1, screen.session.current_index)

                    screen.next_question_btn.click()
                    self.assertEqual(true_false_index, screen.session.current_index)
                else:
                    screen.next_question_btn.click()
                    self.assertEqual(1, screen.session.current_index)

                    screen.prev_question_btn.click()
                    self.assertEqual(0, screen.session.current_index)

    def test_matching_widget_populates_left_items(self):
            widget = MatchingWidget()
            widget.set_options({"left": ["CPU", "GPU"], "right": ["Processor", "Graphics"]})

            self.assertEqual(widget.left_list.count(), 2)
            self.assertEqual(widget.left_list.item(0).text(), "CPU")
            self.assertEqual(len(widget.get_answer()), 2)

    def test_matching_answer_requires_every_pair_selected(self):
            area = AnswerArea()
            area.set_question_type(
                QuestionType.MATCHING,
                {"left": ["CPU", "GPU"], "right": ["Processor", "Graphics"]},
            )

            self.assertFalse(area.has_answer())

            area.matching_widget.combos[0].setCurrentIndex(1)
            self.assertFalse(area.has_answer())

            area.matching_widget.combos[1].setCurrentIndex(1)
            self.assertTrue(area.has_answer())

    def test_matching_widget_clear_preserves_only_label_and_stretch(self):
            widget = MatchingWidget()
            widget.set_options({"left": ["CPU", "GPU"], "right": ["Processor", "Graphics"]})

            widget.clear()

            self.assertEqual(2, widget._right_layout.count())
            self.assertIs(widget._right_label, widget._right_layout.itemAt(0).widget())
            self.assertIsNotNone(widget._right_layout.itemAt(1).spacerItem())
            self.assertEqual([], widget.combos)
            self.assertEqual([], widget.left_item_labels)

    def test_multiple_choice_ignores_stale_button_signals_after_options_reset(self):
            widget = MultipleChoiceWidget()
            emitted = []
            widget.answer_ready.connect(emitted.append)

            widget.set_options(["A. old", "B. old"])
            stale_button = widget.buttons[0]

            widget.set_options(["A. new", "B. new"])
            widget.buttons[1].setChecked(True)
            emitted.clear()

            stale_button.setChecked(True)

            self.assertEqual([], emitted)

    def test_multiple_choice_removes_old_buttons_from_widget_tree_immediately(self):
            widget = MultipleChoiceWidget()
            widget.set_options(["A", "B", "C", "D"])

            widget.set_options(["E", "F", "G", "H"])

            self.assertEqual(4, len(widget.findChildren(QRadioButton)))

    def test_matching_removes_old_dynamic_rows_from_widget_tree_immediately(self):
            widget = MatchingWidget()
            widget.set_options({"left": ["CPU", "GPU"], "right": ["处理器", "图形"]})

            widget.set_options({"left": ["RAM"], "right": ["内存"]})

            self.assertEqual(1, len(widget.findChildren(QComboBox)))

    def test_ordering_widget_tracks_whether_user_reordered_default_order(self):
            area = AnswerArea()
            area.set_question_type(
                QuestionType.ORDERING,
                [
                    {"id": "item_1", "text": "取指"},
                    {"id": "item_2", "text": "译码"},
                    {"id": "item_3", "text": "执行"},
                ],
            )

            self.assertFalse(area.ordering_widget.has_user_reordered())

            area.ordering_widget.list_widget.setCurrentRow(1)
            area.ordering_widget._move_up()

            self.assertTrue(area.ordering_widget.has_user_reordered())

    def test_ordering_widget_reports_stale_draft_restore_failure(self):
            area = AnswerArea()
            area.set_question_type(
                QuestionType.ORDERING,
                [
                    {"id": "item_1", "text": "取指"},
                    {"id": "item_2", "text": "译码"},
                ],
            )

            restored = area.set_answer(["item_1", "removed_item"])

            self.assertIs(False, restored)
            self.assertEqual(["item_1", "item_2"], area.get_answer())
            self.assertFalse(area.ordering_widget.has_user_reordered())

    def test_quiz_screen_warns_and_removes_stale_ordering_draft(self):
            question = Question.create_new(
                qtype=QuestionType.ORDERING,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "按执行顺序排序",
                        "options": [
                            {"id": "item_1", "text": "取指"},
                            {"id": "item_2", "text": "译码"},
                        ],
                        "explanation": "解释说明",
                    },
                    "en": {
                        "stem": "Order the stages",
                        "options": [
                            {"id": "item_1", "text": "Fetch"},
                            {"id": "item_2", "text": "Decode"},
                        ],
                        "explanation": "Explanation text",
                    },
                },
                correct_answer=["item_1", "item_2"],
                topic="pipeline",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["pipeline"],
                question_ids=[question.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False)
                screen._draft_answers_by_question_id[question.question_id] = [
                    "item_1",
                    "removed_item",
                ]

                with patch("ui.screens.quiz_screen.QMessageBox.warning") as warning:
                    screen._display_current_question()

                warning.assert_called_once()
                self.assertNotIn(question.question_id, screen._draft_answers_by_question_id)
                self.assertFalse(screen.answer_area.ordering_widget.has_user_reordered())

    def test_ordering_question_confirms_when_submitting_default_order(self):
            question = Question.create_new(
                qtype=QuestionType.ORDERING,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "按执行顺序排序",
                        "options": ["取指", "译码", "执行"],
                        "explanation": "解释说明",
                    },
                    "en": {
                        "stem": "Order the execution stages",
                        "options": ["Fetch", "Decode", "Execute"],
                        "explanation": "Explanation text",
                    },
                },
                correct_answer=["取指", "译码", "执行"],
                topic="pipeline",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["pipeline"],
                question_ids=[question.question_id],
            )
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False)

                with patch(
                    "ui.screens.quiz_screen.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ) as confirm:
                    screen._submit_answer()

                self.assertTrue(confirm.called)
                self.assertEqual(QuizState.IN_PROGRESS, screen.session.state)
                self.assertEqual(0, screen.session.answered_count)

                with patch(
                    "ui.screens.quiz_screen.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ) as confirm:
                    screen._submit_answer()

                self.assertTrue(confirm.called)
                self.assertEqual(QuizState.SHOWING_FEEDBACK, screen.session.state)
                self.assertEqual(1, screen.session.answered_count)

    def test_quiz_screen_records_unsure_confidence_for_current_answer(self):
            question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "问题", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                    "en": {"stem": "Question", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                },
                correct_answer="A",
                topic="test",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[question.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False)

                screen.uncertain_checkbox.click()
                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._submit_answer()

                self.assertEqual("unsure", screen.session.answers[0].confidence)

    def test_exam_mode_next_only_switches_and_finish_submits_all_drafts(self):
            q1 = self._make_question("q1")
            q2 = self._make_question("q2")
            qset = QuestionSet.create_new(
                title={"zh": "模拟", "en": "Exam"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1", "q2"],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [q1, q2], show_timer=False, submission_mode="exam")
                first_id = screen.session.questions[0].question_id
                second_id = screen.session.questions[1].question_id
                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._update_submit_enabled()

                screen._advance_without_submitting()

                self.assertEqual(1, screen.session.current_index)
                self.assertEqual(0, screen.session.answered_count)
                self.assertEqual("完成", screen.next_question_btn.text())

                screen.answer_area.choice_widget.buttons[1].setChecked(True)
                screen._update_submit_enabled()
                screen._advance_without_submitting()

                self.assertEqual(QuizState.COMPLETED, screen.session.state)
                self.assertEqual(2, screen.session.answered_count)
                answers_by_id = {answer.question_id: answer.user_answer for answer in screen.session.answers}
                self.assertEqual({first_id: "A", second_id: "B"}, answers_by_id)

    def test_exam_mode_finish_requires_confirmation_when_questions_are_unanswered(self):
            q1 = self._make_question("q1")
            q2 = self._make_question("q2")
            qset = QuestionSet.create_new(
                title={"zh": "模拟", "en": "Exam"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1", "q2"],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [q1, q2], show_timer=False, submission_mode="exam")
                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._advance_without_submitting()

                with patch(
                    "ui.screens.quiz_screen.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ) as question:
                    screen._advance_without_submitting()

                self.assertTrue(question.called)
                self.assertEqual(1, screen.session.current_index)
                self.assertEqual(QuizState.IN_PROGRESS, screen.session.state)
                self.assertEqual(0, screen.session.answered_count)

    def test_exam_mode_finish_submits_after_unanswered_confirmation(self):
            q1 = self._make_question("q1")
            q2 = self._make_question("q2")
            qset = QuestionSet.create_new(
                title={"zh": "模拟", "en": "Exam"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1", "q2"],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [q1, q2], show_timer=False, submission_mode="exam")
                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._advance_without_submitting()

                with patch(
                    "ui.screens.quiz_screen.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ) as question:
                    screen._advance_without_submitting()

                self.assertTrue(question.called)
                self.assertEqual(QuizState.COMPLETED, screen.session.state)
                self.assertEqual(2, screen.session.answered_count)
                self.assertFalse(screen.session.answers[0].skipped)
                self.assertTrue(screen.session.answers[1].skipped)

    def test_exam_mode_untouched_ordering_question_is_skipped_on_finish(self):
            question = Question.create_new(
                qtype=QuestionType.ORDERING,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {
                        "stem": "按执行顺序排序",
                        "options": [
                            {"id": "item_1", "text": "取指"},
                            {"id": "item_2", "text": "译码"},
                            {"id": "item_3", "text": "执行"},
                        ],
                        "explanation": "解释说明",
                    },
                    "en": {
                        "stem": "Order the execution stages",
                        "options": [
                            {"id": "item_1", "text": "Fetch"},
                            {"id": "item_2", "text": "Decode"},
                            {"id": "item_3", "text": "Execute"},
                        ],
                        "explanation": "Explanation text",
                    },
                },
                correct_answer=["item_1", "item_2", "item_3"],
                topic="pipeline",
            )
            qset = QuestionSet.create_new(
                title={"zh": "模拟", "en": "Exam"},
                description={"zh": "", "en": ""},
                topics=["pipeline"],
                question_ids=[question.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False, submission_mode="exam")

                with patch(
                    "ui.screens.quiz_screen.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ) as confirm:
                    screen._advance_without_submitting()

                self.assertTrue(confirm.called)
                self.assertEqual(QuizState.COMPLETED, screen.session.state)
                self.assertEqual(1, screen.session.answered_count)
                self.assertTrue(screen.session.answers[0].skipped)
                self.assertEqual("", screen.session.answers[0].user_answer)

    def test_practice_mode_primary_action_submits_current_question_then_advances(self):
            q1 = self._make_question("q1")
            q2 = self._make_question("q2")
            qset = QuestionSet.create_new(
                title={"zh": "例题", "en": "Practice"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1", "q2"],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [q1, q2], show_timer=False, submission_mode="practice")
                self.assertEqual("提交本题", screen.next_question_btn.text())
                self.assertFalse(screen.next_question_btn.isEnabled())

                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._update_submit_enabled()
                self.assertTrue(screen.next_question_btn.isEnabled())

                screen.next_question_btn.click()

                self.assertEqual(QuizState.SHOWING_FEEDBACK, screen.session.state)
                self.assertEqual(1, screen.session.answered_count)
                self.assertEqual("下一题", screen.next_question_btn.text())

                screen.next_question_btn.click()

                self.assertEqual(1, screen.session.current_index)
                self.assertEqual(QuizState.IN_PROGRESS, screen.session.state)
                self.assertEqual("提交本题", screen.next_question_btn.text())

    def test_practice_mode_enter_submits_current_question_without_advancing(self):
            q1 = self._make_question("q1")
            q2 = self._make_question("q2")
            qset = QuestionSet.create_new(
                title={"zh": "例题", "en": "Practice"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1", "q2"],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [q1, q2], show_timer=False, submission_mode="practice")
                screen.answer_area.choice_widget.buttons[0].setChecked(True)

                screen._submit_or_next()

                self.assertEqual(0, screen.session.current_index)
                self.assertEqual(QuizState.SHOWING_FEEDBACK, screen.session.state)
                self.assertEqual(1, screen.session.answered_count)
                self.assertEqual("下一题", screen.next_question_btn.text())

    def test_quiz_mode_uses_inline_toggle_before_answering(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                question = self._make_question("q-mode-switch")
                qset = QuestionSet.create_new(
                    title={"zh": "题集", "en": "Set"},
                    description={"zh": "", "en": ""},
                    topics=["test"],
                    question_ids=[question.question_id],
                )

                screen.start_quiz(qset, [question], show_timer=False, submission_mode="practice")
                screen.answer_area.set_answer(question.correct_answer)

                self.assertTrue(screen.practice_mode_btn.isChecked())
                self.assertFalse(screen.exam_mode_btn.isChecked())
                self.assertTrue(screen.practice_mode_btn.isEnabled())
                self.assertTrue(screen.exam_mode_btn.isEnabled())
                self.assertEqual("逐题练习", screen.practice_mode_btn.text())
                self.assertEqual("模拟考试", screen.exam_mode_btn.text())
                self.assertTrue(screen.review_toggle_btn.isHidden())
                self.assertTrue(screen.review_checkbox.isHidden())

                screen.exam_mode_btn.click()

                self.assertEqual("exam", screen.submission_mode)
                self.assertFalse(screen.practice_mode_btn.isChecked())
                self.assertTrue(screen.exam_mode_btn.isChecked())
                self.assertEqual("完成", screen.next_question_btn.text())
                self.assertFalse(screen.review_toggle_btn.isHidden())
                self.assertFalse(screen.review_checkbox.isHidden())

                screen.practice_mode_btn.click()

                self.assertEqual("practice", screen.submission_mode)
                self.assertTrue(screen.practice_mode_btn.isChecked())
                self.assertFalse(screen.exam_mode_btn.isChecked())
                self.assertTrue(screen.review_toggle_btn.isHidden())
                self.assertTrue(screen.review_checkbox.isHidden())

    def test_quiz_mode_toggle_locks_after_leaving_the_untouched_start_state(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                question = self._make_question("q-mode-lock")
                qset = QuestionSet.create_new(
                    title={"zh": "题集", "en": "Set"},
                    description={"zh": "", "en": ""},
                    topics=["test"],
                    question_ids=[question.question_id],
                )
                screen.start_quiz(
                    qset,
                    [question],
                    show_timer=False,
                    submission_mode="practice",
                )
                screen.answer_area.set_answer(question.correct_answer)
                screen._save_current_draft_answer()
                screen._refresh_navigation_button_state()

                self.assertFalse(screen.practice_mode_btn.isEnabled())
                self.assertFalse(screen.exam_mode_btn.isEnabled())

                screen.exam_mode_btn.click()

                self.assertEqual("practice", screen.submission_mode)
                self.assertFalse(screen.mode_status_label.isHidden())
                self.assertTrue(screen.practice_mode_btn.isHidden())
                self.assertTrue(screen.exam_mode_btn.isHidden())

    def test_quiz_mode_switch_locks_after_practice_feedback_is_shown(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                question = self._make_question("q-mode-lock")
                qset = QuestionSet.create_new(
                    title={"zh": "题集", "en": "Set"},
                    description={"zh": "", "en": ""},
                    topics=["test"],
                    question_ids=[question.question_id],
                )
                screen.start_quiz(qset, [question], show_timer=False, submission_mode="practice")
                screen.answer_area.set_answer(question.correct_answer)

                screen._submit_answer()

                self.assertEqual(1, screen.session.answered_count)
                self.assertFalse(screen.practice_mode_btn.isEnabled())
                self.assertFalse(screen.exam_mode_btn.isEnabled())
                self.assertFalse(screen.mode_status_label.isHidden())
                self.assertTrue(screen.practice_mode_btn.isHidden())
                self.assertTrue(screen.exam_mode_btn.isHidden())

    def test_quiz_screen_captures_snapshot_with_current_state(self):
            qset = QuestionSet.create_new(
                title={"zh": "测试题集", "en": "Test Set"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1", "q2"],
            )
            q1 = self._make_question("q1")
            q2 = self._make_question("q2")

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [q1, q2], show_timer=False)
                screen._jump_to_question(1)
                current_id = screen.session.current_question.question_id
                screen.answer_area.choice_widget.buttons[1].setChecked(True)
                screen.uncertain_checkbox.click()
                screen.review_checkbox.click()

                snapshot = screen.capture_snapshot()

                self.assertEqual(qset.set_id, snapshot.set_id)
                self.assertEqual("测试题集", snapshot.title)
                self.assertEqual(
                    [question.question_id for question in screen.session.questions],
                    snapshot.question_order,
                )
                self.assertEqual(1, snapshot.current_index)
                self.assertEqual({"B"}, set(snapshot.draft_answers.values()))
                self.assertEqual([current_id], snapshot.unsure_question_ids)
                self.assertEqual([current_id], snapshot.marked_review_question_ids)

    def test_quiz_screen_captures_snapshot_with_submission_mode(self):
            question = self._make_question("q1")
            qset = QuestionSet.create_new(
                title={"zh": "模拟", "en": "Exam"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[question.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False, submission_mode="exam")

                snapshot = screen.capture_snapshot()

                self.assertEqual("exam", snapshot.mode)

    def test_quiz_screen_snapshot_captures_daily_intent_and_temporary_set(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                question_bank = QuestionBank(str(Path(tmpdir) / "questions"))
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                question = self._make_question("q-daily", "cache")
                question_bank.save(question)
                screen = QuizScreen(question_bank, progress_manager)
                self.addCleanup(screen.close)
                intent = StudyIntent(
                    course_id="course-a",
                    action=StudyAction.DAILY_QUEUE,
                    question_ids=(question.question_id,),
                    remaining_question_ids=("q-next",),
                    question_count=1,
                    source="today_plan",
                    plan_id="2026-07-28:course-a",
                )
                screen.start_quiz_custom([question], "今日学习")
                screen.set_study_intent(intent)

                snapshot = screen.capture_snapshot()

                self.assertEqual(
                    screen._question_set.set_id,
                    snapshot.question_set_data["set_id"],
                )
                self.assertEqual("daily_queue", snapshot.study_intent_data["action"])
                self.assertEqual(["q-next"], snapshot.study_intent_data["remaining_question_ids"])

    def test_quiz_screen_restores_snapshot_state_and_draft_answer(self):
            qset = QuestionSet.create_new(
                title={"zh": "测试题集", "en": "Test Set"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1", "q2"],
            )
            q1 = self._make_question("q1")
            q2 = self._make_question("q2")
            snapshot = QuizSessionSnapshot.create_new(
                set_id=qset.set_id,
                title="测试题集",
                question_order=["q1", "q2"],
                language="zh",
            )
            snapshot.current_index = 1
            snapshot.submitted_answers = [
                AnswerRecord(
                    question_id="q1",
                    index_in_session=0,
                    user_answer="A",
                    is_correct=True,
                    confidence="sure",
                )
            ]
            snapshot.draft_answers = {"q2": "B"}
            snapshot.unsure_question_ids = ["q2"]
            snapshot.marked_review_question_ids = ["q2"]
            snapshot.elapsed_seconds = 12.0

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )

                screen.restore_snapshot(snapshot, [q1, q2], qset, show_timer=False)

                self.assertEqual("q2", screen.session.current_question.question_id)
                self.assertEqual(["q1", "q2"], [q.question_id for q in screen.session.questions])
                self.assertEqual(1, screen.session.answered_count)
                self.assertEqual("B", screen.answer_area.get_answer())
                self.assertEqual({"q2"}, screen._unsure_question_ids)
                self.assertEqual({"q2"}, screen._marked_question_ids)
                self.assertTrue(screen.uncertain_checkbox.isChecked())
                self.assertTrue(screen.review_checkbox.isChecked())

    def test_quiz_screen_restores_snapshot_submission_mode(self):
            qset = QuestionSet.create_new(
                title={"zh": "模拟", "en": "Exam"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1"],
            )
            question = self._make_question("q1")
            snapshot = QuizSessionSnapshot.create_new(
                set_id=qset.set_id,
                title="模拟",
                question_order=["q1"],
                language="zh",
                mode="exam",
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.submission_mode = "practice"

                screen.restore_snapshot(snapshot, [question], qset, show_timer=False)

                self.assertEqual("exam", screen.submission_mode)
                self.assertEqual("完成", screen.next_question_btn.text())

    def test_quiz_screen_updates_submitted_confidence_when_unsure_toggles(self):
            question = self._make_question("q1")
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[question.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False)
                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._submit_answer()

                screen.uncertain_checkbox.click()

                self.assertEqual({"q1"}, screen._unsure_question_ids)
                self.assertEqual(set(), screen._marked_question_ids)
                self.assertEqual("unsure", screen.session.answers[0].confidence)

                screen.uncertain_checkbox.click()

                self.assertEqual(set(), screen._unsure_question_ids)
                self.assertEqual(set(), screen._marked_question_ids)
                self.assertEqual("sure", screen.session.answers[0].confidence)

    def test_quiz_screen_confirm_exit_saves_snapshot_without_abandoned_progress(self):
            qset = QuestionSet.create_new(
                title={"zh": "测试题集", "en": "Test Set"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1", "q2"],
            )
            q1 = self._make_question("q1")
            q2 = self._make_question("q2")

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                progress_manager = ProgressManager(str(root / "progress"))
                snapshot_manager = QuizSnapshotManager(str(root / "snapshots"))
                screen = QuizScreen(
                    QuestionBank(str(root / "questions")),
                    progress_manager,
                    snapshot_manager=snapshot_manager,
                )
                screen.start_quiz(qset, [q1, q2], show_timer=False)
                screen._jump_to_question(1)
                current_id = screen.session.current_question.question_id
                screen.answer_area.choice_widget.buttons[1].setChecked(True)

                with patch(
                    "ui.screens.quiz_screen.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ):
                    confirmed = screen.confirm_exit()

                snapshot = snapshot_manager.load_latest()

                self.assertTrue(confirmed)
                self.assertIsNotNone(snapshot)
                self.assertEqual(qset.set_id, snapshot.set_id)
                self.assertEqual(1, snapshot.current_index)
                self.assertEqual("B", snapshot.draft_answers[current_id])
                self.assertIsNone(progress_manager.get_latest_abandoned_record())

    def test_quiz_screen_confirm_exit_stops_timer_after_abandon(self):
            qset = QuestionSet.create_new(
                title={"zh": "测试题集", "en": "Test Set"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=["q1"],
            )
            question = self._make_question("q1")

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                self.addCleanup(screen.session_timer.stop)
                screen.start_quiz(qset, [question], show_timer=True)

                with patch(
                    "ui.screens.quiz_screen.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ):
                    confirmed = screen.confirm_exit()

                self.assertTrue(confirmed)
                self.assertFalse(screen.session_timer.isActive())

    def test_quiz_screen_completed_record_includes_marked_review_questions(self):
            question = self._make_question("q1")
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[question.question_id],
            )
            finished = []

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.quiz_finished.connect(finished.append)
                screen.start_quiz(qset, [question], show_timer=False)
                screen.review_checkbox.click()
                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._finish_from_drafts()

                self.assertEqual([question.question_id], finished[0].marked_review_question_ids)

    def test_quiz_feedback_shows_source_refs_after_answer_submission(self):
            question = self._make_question("q-source")
            question.metadata["source_refs"] = [
                {
                    "chunk_id": "source-0007",
                    "source_file": "第21讲 Cache.pdf",
                    "page_or_slide": 8,
                    "heading": "Cache Address Breakdown",
                }
            ]
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["cache"],
                question_ids=[question.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False, submission_mode="practice")
                screen.answer_area.choice_widget.buttons[1].setChecked(True)
                screen._submit_answer()

                feedback = screen.explanation_label.text()
                self.assertIn("第21讲 Cache.pdf", feedback)
                self.assertIn("页码/幻灯片 8", feedback)
                self.assertIn("source-0007", feedback)
                self.assertIn("Cache Address Breakdown", feedback)

    def test_quiz_feedback_escapes_generated_html_content(self):
            question = self._make_question("q-html")
            question.bilingual["zh"]["options"] = ["A. <b>正确</b>", "B. <img src=x onerror=alert(1)>"]
            question.bilingual["zh"]["explanation"] = "解释 <script>alert(1)</script>"
            question.metadata["source_refs"] = [
                {
                    "chunk_id": "source-<7>",
                    "source_file": "<img src=x onerror=alert(1)>",
                    "heading": "DMA <b>unsafe</b>",
                    "excerpt": "<script>alert(1)</script>",
                }
            ]
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["cache"],
                question_ids=[question.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False, submission_mode="practice")
                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._submit_answer()

                feedback = screen.explanation_label.text()
                self.assertIn("&lt;b&gt;正确&lt;/b&gt;", feedback)
                self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", feedback)
                self.assertIn("&lt;img", feedback)
                self.assertNotIn("<script>", feedback)
                self.assertNotIn("<img", feedback)

    def test_quiz_feedback_formats_matching_ids_as_readable_labels(self):
            question = Question.create_new(
                qtype=QuestionType.MATCHING,
                difficulty=Difficulty.MEDIUM,
                bilingual={
                    "zh": {
                        "stem": "配对 I/O 术语。",
                        "options": {
                            "left": [{"id": "left_dma", "text": "DMA"}],
                            "right": [{"id": "right_direct", "text": "直接内存访问"}],
                        },
                        "explanation": "DMA 与直接内存访问配对。",
                    },
                    "en": {
                        "stem": "Match I/O terms.",
                        "options": {
                            "left": [{"id": "left_dma", "text": "DMA"}],
                            "right": [{"id": "right_direct", "text": "Direct memory access"}],
                        },
                        "explanation": "DMA matches direct memory access.",
                    },
                },
                correct_answer=[["left_dma", "right_direct"]],
                topic="io",
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.session.set_language("en")

                formatted = screen._format_answer([["left_dma", "right_direct"]], question)

            self.assertIn("DMA", formatted)
            self.assertIn("Direct memory access", formatted)
            self.assertNotIn("left_dma", formatted)
            self.assertNotIn("right_direct", formatted)

    def test_quiz_screen_timer_visibility_follows_setting(self):
            question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "问题", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                    "en": {"stem": "Question", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                },
                correct_answer="A",
                topic="test",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[question.question_id],
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                hidden_timer_screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                hidden_timer_screen.start_quiz(qset, [question], show_timer=False)
                self.assertTrue(hidden_timer_screen.timer_label.isHidden())

                visible_timer_screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                visible_timer_screen.start_quiz(qset, [question], show_timer=True)
                self.assertFalse(visible_timer_screen.timer_label.isHidden())
                visible_timer_screen.session_timer.stop()

    def test_quiz_language_switch_preserves_selected_choice(self):
            question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "问题", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                    "en": {"stem": "Question", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                },
                correct_answer="A",
                topic="test",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[question.question_id],
            )
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False)

                screen.answer_area.choice_widget.buttons[1].setChecked(True)
                self.assertEqual("B", screen.answer_area.get_answer())
                self.assertTrue(screen.next_question_btn.isEnabled())

                screen._toggle_language()

                self.assertEqual("B", screen.answer_area.get_answer())
                self.assertTrue(screen.next_question_btn.isEnabled())
                self.assertEqual("B. Wrong", screen.answer_area.choice_widget.buttons[1].text())

    def test_quiz_language_switch_preserves_typed_answer(self):
            question = Question.create_new(
                qtype=QuestionType.FILL_IN_BLANK,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "CPU 的全称是 ____", "options": [], "explanation": "解释说明"},
                    "en": {"stem": "CPU stands for ____", "options": [], "explanation": "Explanation text"},
                },
                correct_answer="central processing unit",
                topic="test",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[question.question_id],
            )
            language_manager = LanguageManager.instance()
            previous_language = language_manager.current
            self.addCleanup(language_manager.set_language, previous_language)
            language_manager.set_language("zh")

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [question], show_timer=False)

                screen.answer_area.fill_widget.input.setText("central processing unit")
                self.assertEqual("central processing unit", screen.answer_area.get_answer())
                self.assertTrue(screen.next_question_btn.isEnabled())

                screen._toggle_language()

                self.assertEqual("central processing unit", screen.answer_area.get_answer())
                self.assertTrue(screen.next_question_btn.isEnabled())

    def test_quiz_screen_marks_current_question_for_review(self):
            first = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "问题 1", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                    "en": {"stem": "Question 1", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                },
                correct_answer="A",
                topic="test",
            )
            second = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "问题 2", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                    "en": {"stem": "Question 2", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                },
                correct_answer="A",
                topic="test",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[first.question_id, second.question_id],
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                screen = QuizScreen(
                    QuestionBank(str(Path(tmpdir) / "questions")),
                    ProgressManager(str(Path(tmpdir) / "progress")),
                )
                screen.start_quiz(qset, [first, second], show_timer=False)
                marked_question_id = screen.session.current_question.question_id

                self.assertEqual(set(), screen._marked_question_ids)
                self.assertFalse(screen.review_checkbox.isChecked())
                self.assertFalse(screen.uncertain_checkbox.isChecked())

                screen.review_checkbox.click()

                self.assertEqual({marked_question_id}, screen._marked_question_ids)
                self.assertTrue(screen.review_checkbox.isChecked())
                self.assertFalse(screen.uncertain_checkbox.isChecked())

                screen.answer_area.choice_widget.buttons[0].setChecked(True)
                screen._advance_without_submitting()

                self.assertEqual({marked_question_id}, screen._marked_question_ids)
                self.assertFalse(screen.review_checkbox.isChecked())
                self.assertFalse(screen.uncertain_checkbox.isChecked())

    def test_quiz_session_abandon_returns_abandoned_record(self):
            question = Question.create_new(
                qtype=QuestionType.MULTIPLE_CHOICE,
                difficulty=Difficulty.EASY,
                bilingual={
                    "zh": {"stem": "问题", "options": ["A. 对", "B. 错"], "explanation": "解释说明"},
                    "en": {"stem": "Question", "options": ["A. Right", "B. Wrong"], "explanation": "Explanation text"},
                },
                correct_answer="A",
                topic="test",
            )
            qset = QuestionSet.create_new(
                title={"zh": "测试", "en": "Test"},
                description={"zh": "", "en": ""},
                topics=["test"],
                question_ids=[question.question_id],
            )
            session = QuizSession()
            session.start(qset, [question], "zh")

            record = session.abandon()

            self.assertIsInstance(record, ProgressRecord)
            self.assertEqual(record.status, "abandoned")
            self.assertEqual(record.set_id, qset.set_id)

    def test_progress_manager_returns_latest_abandoned_record(self):
            with tempfile.TemporaryDirectory() as tmpdir:
                progress_manager = ProgressManager(str(Path(tmpdir) / "progress"))
                old = ProgressRecord.create_new("set-old")
                old.progress_id = "old"
                old.status = "abandoned"
                old.started_at = "2026-06-01T00:00:00+00:00"
                progress_manager.save(old)
                completed = ProgressRecord.create_new("set-completed")
                completed.progress_id = "completed"
                completed.status = "completed"
                completed.started_at = "2026-06-20T00:00:00+00:00"
                progress_manager.save(completed)
                latest = ProgressRecord.create_new("set-latest")
                latest.progress_id = "latest"
                latest.status = "abandoned"
                latest.started_at = "2026-06-15T00:00:00+00:00"
                progress_manager.save(latest)

                draft = progress_manager.get_latest_abandoned_record()

                self.assertIsNotNone(draft)
                self.assertEqual("latest", draft.progress_id)
