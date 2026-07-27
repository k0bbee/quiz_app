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
from ui.screens.home_screen import HomeScreen
from ui.screens.progress_dashboard import ProgressDashboard
from ui.screens.quiz_screen import QuizScreen
from ui.screens.results_screen import ResultsScreen
from ui.widgets.answer_area import AnswerArea, MatchingWidget, MultipleChoiceWidget
from utils.constants import Difficulty, QuestionType, QuizState, topic_value


_APP = QApplication.instance() or QApplication([])


class QuizWidgetAndSessionTests(unittest.TestCase):
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

    def test_main_window_quiz_start_defaults_to_practice_mode(self):
        from ui.main_window import MainWindow

        question = self._make_question("q1")
        qset = QuestionSet.create_new(
            title={"zh": "题集", "en": "Set"},
            description={"zh": "", "en": ""},
            topics=["test"],
            question_ids=[question.question_id],
        )
        started = {}
        study_flow = types.SimpleNamespace(clear_active=Mock())
        shell = types.SimpleNamespace(
            lang_manager=LanguageManager.instance(),
            set_manager=types.SimpleNamespace(get=lambda set_id: qset),
            question_bank=types.SimpleNamespace(get_many=lambda question_ids: [question]),
            quiz_screen=types.SimpleNamespace(
                start_quiz=lambda question_set, questions, **kwargs: started.update(kwargs)
            ),
            study_flow=study_flow,
            _active_questions={},
            _show_timer_setting=lambda: False,
            SCREEN_QUIZ="quiz",
            navigate_to=lambda screen_name: started.update({"screen": screen_name}),
        )

        MainWindow._on_quiz_start(shell, qset.set_id, [question.question_id])

        self.assertEqual("practice", started["submission_mode"])
        self.assertEqual("quiz", started["screen"])
        study_flow.clear_active.assert_called_once_with()

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

            screen.exam_mode_btn.click()

            self.assertEqual("exam", screen.submission_mode)
            self.assertFalse(screen.practice_mode_btn.isChecked())
            self.assertTrue(screen.exam_mode_btn.isChecked())
            self.assertEqual("完成", screen.next_question_btn.text())

            screen.practice_mode_btn.click()

            self.assertEqual("practice", screen.submission_mode)
            self.assertTrue(screen.practice_mode_btn.isChecked())
            self.assertFalse(screen.exam_mode_btn.isChecked())

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
            _current_course_id=lambda: "course-a",
        )

        with patch("ui.main_window.QMessageBox.warning") as warning:
            MainWindow._on_retry_incorrect(shell)

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

    def test_results_screen_preserves_study_intent_and_emits_repeat(self):
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
            action=StudyAction.PRACTICE_TOPIC,
            topic_ids=("cache",),
            question_count=1,
            source="today_plan",
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
        self.assertIn("再练", screen.repeat_study_btn.text())
        screen.repeat_study_btn.click()
        self.assertEqual([intent], requests)

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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
                _show_timer_setting=lambda: False,
                navigate_to=lambda screen: started.setdefault("screen", screen),
            )

            MainWindow._on_retry_unsure(shell)

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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
                _show_timer_setting=lambda: False,
                navigate_to=lambda screen: started.setdefault("screen", screen),
            )

            MainWindow._on_retry_review(shell)

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
                _active_questions={},
                SCREEN_QUIZ=2,
                _show_timer_setting=lambda: False,
                navigate_to=lambda screen: started.setdefault("screen", screen),
            )

            MainWindow._on_retry_all(shell)

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

            with patch("ui.main_window.QMessageBox.warning") as warning:
                MainWindow._on_retry_all(shell)

            warning.assert_called_once()
            self.assertIn("已被删除", warning.call_args.args[2])

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

            self.assertIn("累计 1 题", screen.stats_label.text())
            self.assertIn("历史错题 1 题", screen.stats_label.text())
            self.assertIn("题库总量 1 题", screen.stats_label.text())

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

            with patch.object(question_bank, "search", side_effect=AssertionError("home refresh should not load full search results")), \
                 patch.object(question_bank, "get_many", side_effect=AssertionError("home refresh should not load full question objects")):
                screen.refresh()

            self.assertIn("累计 1 题", screen.stats_label.text())
            self.assertIn("历史错题 1 题", screen.stats_label.text())
            self.assertIn("题库总量 1 题", screen.stats_label.text())

    def test_home_today_plan_emits_course_topic_and_count_intent(self):
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
            self.assertIs(StudyAction.PRACTICE_TOPIC, intent.action)
            self.assertEqual("course-a", intent.course_id)
            self.assertEqual(("cache",), intent.topic_ids)
            self.assertEqual(1, intent.question_count)
            self.assertEqual("today_plan", intent.source)

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

            self.assertIn("错题", screen.start_btn.text())
            self.assertIn("1", screen.today_plan_detail.text())
            screen.start_btn.click()

            self.assertEqual(1, len(review_requests))
            self.assertIs(StudyAction.REVIEW_QUESTIONS, review_requests[0].action)
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

            self.assertIn("Matched questions: 1", screen.overall_label.text())
            self.assertIn("Partial: 1", screen.overall_label.text())
            self.assertIn("Correct: 1 / 1", screen.detail_label.text())
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

            source_text = screen.source_refs_label.text()
            self.assertFalse(screen.source_refs_label.isHidden())
            self.assertIn("相关来源", source_text)
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
        host = types.SimpleNamespace(_on_ai_generate=lambda **kwargs: calls.append(kwargs))

        MainWindow._on_generate_progress_topic(host, "cache")

        plan = calls[0]["initial_plan"]
        self.assertEqual(10, plan.question_count)
        self.assertEqual(("cache",), plan.selected_topics)
        self.assertEqual({"cache": 100}, dict(plan.topic_weights))

    def test_progress_reset_clears_mastered_topic_overrides(self):
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
            screen.set_current_course("course-a")

            # Two-step: first click arms, second click executes
            screen._reset_progress()
            screen._reset_progress()

            self.assertFalse(mastery_overrides.is_topic_mastered("course-a", "cache"))

    def test_progress_reset_button_requires_two_clicks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            progress_manager = ProgressManager(str(root / "progress"))
            question_bank = QuestionBank(str(root / "questions"))

            screen = self._make_progress_dashboard(
                root, progress_manager, question_bank
            )
            original_text = screen.reset_btn.text()

            # First click — arms the button, does NOT reset
            screen._reset_progress()
            armed_text = screen.reset_btn.text()
            self.assertNotEqual(original_text, armed_text)

            # Second click — executes reset and restores original text
            screen._reset_progress()
            self.assertEqual(original_text, screen.reset_btn.text())

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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
                _show_timer_setting=lambda: False,
                navigate_to=lambda screen: started.setdefault("screen", screen),
            )

            MainWindow._on_practice_incorrect(shell)

            self.assertEqual({course_a.question_id}, set(shell._active_questions))
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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
                _show_timer_setting=lambda: False,
                navigate_to=lambda screen: started.setdefault("screen", screen),
            )

            MainWindow._on_practice_incorrect(shell)

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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
                _show_timer_setting=lambda: False,
                navigate_to=lambda screen: started.setdefault("screen", screen),
            )

            MainWindow._on_practice_incorrect(shell)

            self.assertEqual([active.question_id], [q.question_id for q in started["questions"]])

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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "course-a",
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
            _current_course_id=lambda: "",
        )

        MainWindow._update_home_resume_draft(shell)

        self.assertEqual("系统结构练习", shown["title"])
        self.assertEqual(1, shown["remaining_count"])
        self.assertEqual(1, shown["current_index"])
        self.assertEqual(2, shown["total_count"])

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
            _current_course_id=lambda: "",
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
                _active_questions={"stale": object()},
                _refresh_results_retry_availability=lambda: shown.setdefault(
                    "availability_refreshed",
                    True,
                ),
                navigate_to=lambda index: shown.setdefault("navigated", index),
                SCREEN_RESULTS=3,
            )

            MainWindow._on_open_progress_record(shell, record.progress_id)

            self.assertEqual(record.progress_id, shown["record"].progress_id)
            self.assertEqual({}, shown["questions"])
            self.assertEqual({}, shell._active_questions)
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
                _active_questions={},
                study_flow=types.SimpleNamespace(
                    take_active_intent=Mock(return_value=study_intent),
                ),
                lang_manager=LanguageManager.instance(),
                SCREEN_RESULTS=3,
                navigate_to=lambda screen: shown.setdefault("screen", screen),
            )

            MainWindow._on_quiz_finished(shell, record)

            self.assertIsNone(snapshot_manager.get(snapshot.snapshot_id))
            self.assertEqual(record.progress_id, shown["record"].progress_id)
            self.assertIs(study_intent, shown["study_intent"])
            shell.study_flow.take_active_intent.assert_called_once_with()

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
                _current_course_id=lambda: "",
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
                _active_questions={},
                SCREEN_QUIZ=2,
                _current_course_id=lambda: "",
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


if __name__ == "__main__":
    unittest.main()
