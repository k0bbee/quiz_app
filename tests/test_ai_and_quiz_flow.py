import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from ai.llm_client import LLMClient
from models.progress import AnswerRecord, ProgressRecord, SessionSummary
from models.question import Question
from models.question import QuestionBank
from models.question_set import QuestionSet, SetManager
from core.quiz_engine import QuizSession
from core.mastery_overrides import MasteryOverrideStore
from core.progress_tracker import ProgressManager
from core.language_manager import LanguageManager
from ui.screens.home_screen import HomeScreen
from ui.screens.progress_dashboard import ProgressDashboard
from ui.screens.quiz_screen import QuizScreen
from ui.screens.results_screen import ResultsScreen
from ui.widgets.answer_area import AnswerArea, MatchingWidget
from utils.constants import Difficulty, QuestionType, QuizState


_APP = QApplication.instance() or QApplication([])


class LocalAgentTests(unittest.TestCase):
    def test_local_agent_provider_does_not_require_api_key(self):
        from ui.main_window import _provider_requires_api_key

        self.assertFalse(_provider_requires_api_key({"ai_provider": "local_agent"}))
        self.assertFalse(_provider_requires_api_key({"ai_base_url": "local-agent://auto"}))
        self.assertFalse(_provider_requires_api_key({"ai_provider": "custom", "ai_base_url": "local-agent://codex"}))
        self.assertTrue(_provider_requires_api_key({"ai_provider": "custom"}))

    def test_ai_generation_preflight_reports_missing_remote_key(self):
        from ui.main_window import _ai_generation_settings_error

        message = _ai_generation_settings_error(
            {"ai_provider": "openai", "ai_base_url": "https://api.openai.com/v1", "ai_model": "gpt-4.1-mini"},
            api_key="",
            detected_agents=[],
        )

        self.assertIn("API key", message)

    def test_ai_generation_preflight_accepts_detected_local_agent(self):
        from ui.main_window import _ai_generation_settings_error

        message = _ai_generation_settings_error(
            {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
            api_key="",
            detected_agents=["codex"],
        )

        self.assertEqual("", message)

    def test_local_agent_accepts_course_prompt_characters_without_shell_rejection(self):
        client = LLMClient(api_key="", base_url="local-agent://auto", model="codex")
        result = types.SimpleNamespace(returncode=0, stdout='{"questions":[]}', stderr="")
        messages = [{"role": "user", "content": "Cache set = block # modulo sets; tag -> compare [A/B]."}]

        with patch("ai.llm_client.shutil.which", return_value="codex"), \
             patch("ai.llm_client.subprocess.run", return_value=result) as run:
            text = client.generate(messages)

        self.assertEqual(text, '{"questions":[]}')
        self.assertTrue(run.called)


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

    def test_answer_record_persists_confidence_marker(self):
        record = AnswerRecord(
            question_id="q1",
            index_in_session=0,
            user_answer="A",
            is_correct=True,
            confidence="unsure",
        )

        loaded = AnswerRecord.from_dict(record.to_dict())

        self.assertEqual("unsure", loaded.confidence)

    def test_quiz_session_can_restore_order_answers_index_and_elapsed_time(self):
        qset = QuestionSet.create_new(
            title={"zh": "测试", "en": "Test"},
            description={"zh": "", "en": ""},
            topics=["cache"],
            question_ids=[],
        )
        q1 = self._make_question("q1")
        q2 = self._make_question("q2")
        q3 = self._make_question("q3")
        answer = AnswerRecord(
            question_id="q1",
            index_in_session=0,
            user_answer="A",
            is_correct=True,
            confidence="sure",
        )
        session = QuizSession()

        session.restore(
            question_set=qset,
            questions=[q1, q2, q3],
            current_index=1,
            answers=[answer],
            language="zh",
            progress_id="progress-restored",
            elapsed_seconds=42.0,
        )

        self.assertEqual(["q1", "q2", "q3"], [question.question_id for question in session.questions])
        self.assertEqual(1, session.current_index)
        self.assertEqual("q2", session.current_question.question_id)
        self.assertEqual("progress-restored", session.progress_id)
        self.assertEqual(1, session.answered_count)
        self.assertGreaterEqual(session.elapsed_seconds, 42.0)

    def test_quiz_session_updates_submitted_answer_confidence(self):
        qset = QuestionSet.create_new(
            title={"zh": "测试", "en": "Test"},
            description={"zh": "", "en": ""},
            topics=["cache"],
            question_ids=[],
        )
        q1 = self._make_question("q1")
        session = QuizSession()
        session.start_fixed_order(qset, [q1], language="zh")
        session.submit_answer("A", confidence="sure")

        changed = session.set_answer_confidence("q1", "unsure")

        self.assertTrue(changed)
        self.assertEqual("unsure", session.answers[0].confidence)

    def test_quiz_session_can_jump_between_unfinished_questions(self):
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
            qtype=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {"stem": "问题 2", "options": ["正确", "错误"], "explanation": "解释说明"},
                "en": {"stem": "Question 2", "options": ["True", "False"], "explanation": "Explanation text"},
            },
            correct_answer="true",
            topic="test",
        )
        third = Question.create_new(
            qtype=QuestionType.FILL_IN_BLANK,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {"stem": "问题 3", "options": [], "explanation": "解释说明"},
                "en": {"stem": "Question 3", "options": [], "explanation": "Explanation text"},
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
        session = QuizSession()
        session.start(qset, [first, second, third], "zh")

        self.assertTrue(session.jump_to(2))
        self.assertEqual(2, session.current_index)
        self.assertEqual(QuizState.IN_PROGRESS, session.state)

        session.submit_answer("answer")
        self.assertEqual(QuizState.SHOWING_FEEDBACK, session.state)

        self.assertTrue(session.jump_to(0))
        self.assertEqual(0, session.current_index)
        self.assertEqual(QuizState.IN_PROGRESS, session.state)

        self.assertTrue(session.jump_to(2))
        self.assertEqual(2, session.current_index)
        self.assertEqual(QuizState.SHOWING_FEEDBACK, session.state)

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

            screen.unsure_btn.click()
            screen.answer_area.choice_widget.buttons[0].setChecked(True)
            screen._submit_answer()

            self.assertEqual("unsure", screen.session.answers[0].confidence)

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

        screen = ResultsScreen()
        screen.set_results(record, {}, "zh")

        self.assertIn("答对但不确定: 1", screen.stats_label.text())

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

        screen = ResultsScreen()
        emitted = []
        screen.retry_unsure.connect(lambda: emitted.append(True))
        screen.set_results(record, {}, "zh")

        self.assertTrue(screen.retry_unsure_btn.isEnabled())
        screen.retry_unsure_btn.click()

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

        screen = ResultsScreen()
        screen.set_results(record, {}, "zh")

        self.assertIn("下一步建议", screen.next_action_label.text())
        self.assertIn("先重做错题", screen.next_action_label.text())

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
            self.assertTrue(screen.submit_btn.isEnabled())

            screen._toggle_language()

            self.assertEqual("B", screen.answer_area.get_answer())
            self.assertTrue(screen.submit_btn.isEnabled())
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
            self.assertTrue(screen.submit_btn.isEnabled())

            screen._toggle_language()

            self.assertEqual("central processing unit", screen.answer_area.get_answer())
            self.assertTrue(screen.submit_btn.isEnabled())

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
            self.assertEqual("标记复查", screen.mark_review_btn.text())

            screen.mark_review_btn.click()

            self.assertEqual({marked_question_id}, screen._marked_question_ids)
            self.assertEqual("取消标记", screen.mark_review_btn.text())

            screen.answer_area.choice_widget.buttons[0].setChecked(True)
            screen._submit_answer()
            screen._next_question()

            self.assertEqual({marked_question_id}, screen._marked_question_ids)
            self.assertEqual("标记复查", screen.mark_review_btn.text())

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

    def test_home_screen_can_show_and_clear_resume_draft_action(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            screen = HomeScreen(
                ProgressManager(str(Path(tmpdir) / "progress")),
                QuestionBank(str(Path(tmpdir) / "questions")),
            )

            self.assertTrue(screen.resume_btn.isHidden())

            screen.set_resume_draft("系统结构练习", 3)

            self.assertFalse(screen.resume_btn.isHidden())
            self.assertIn("继续草稿", screen.resume_btn.text())
            self.assertIn("3", screen.resume_btn.text())

            screen.clear_resume_draft()

            self.assertTrue(screen.resume_btn.isHidden())

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

            screen = ProgressDashboard(progress_manager, question_bank)
            screen.set_current_course("course-a")
            screen.refresh()

            self.assertIn("Questions: 1", screen.overall_label.text())
            self.assertIn("Correct: 1 / 1", screen.detail_label.text())
            self.assertEqual(1, screen.topic_table.rowCount())
            self.assertEqual("100%", screen.topic_table.item(0, 2).text())
            self.assertEqual("75%", screen.topic_table.item(0, 3).text())
            self.assertEqual("1/1", screen.topic_table.item(0, 4).text())
            self.assertEqual("", screen.recommendation_label.text())

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

            screen = ProgressDashboard(progress_manager, question_bank)
            screen.set_current_course("course-a")
            screen.refresh()

            self.assertIn("建议复习", screen.recommendation_label.text())
            self.assertIn("cache", screen.recommendation_label.text())
            self.assertNotIn("process", screen.recommendation_label.text())
            self.assertNotIn("virtual memory", screen.recommendation_label.text())

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

            screen = ProgressDashboard(progress_manager, question_bank, mastery_overrides=mastery_overrides)
            screen.set_current_course("course-a")
            screen.refresh()

            self.assertIn("cache", screen.recommendation_label.text())

            cache_row = 0
            screen.topic_table.selectRow(cache_row)
            screen.mark_mastered_btn.click()

            self.assertTrue(mastery_overrides.is_topic_mastered("course-a", "cache"))
            self.assertEqual("已掌握", screen.topic_table.item(cache_row, 3).text())
            self.assertNotIn("cache", screen.recommendation_label.text())
            self.assertIn("process", screen.recommendation_label.text())

            screen.mark_mastered_btn.click()

            self.assertFalse(mastery_overrides.is_topic_mastered("course-a", "cache"))
            self.assertIn("cache", screen.recommendation_label.text())

    def test_progress_reset_clears_mastered_topic_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            progress_manager = ProgressManager(str(root / "progress"))
            question_bank = QuestionBank(str(root / "questions"))
            mastery_overrides = MasteryOverrideStore(root / "mastery_overrides.json")
            mastery_overrides.mark_topic_mastered("course-a", "cache")

            screen = ProgressDashboard(progress_manager, question_bank, mastery_overrides=mastery_overrides)
            screen.set_current_course("course-a")

            with patch("ui.screens.progress_dashboard.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                screen._reset_progress()

            self.assertFalse(mastery_overrides.is_topic_mastered("course-a", "cache"))

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


if __name__ == "__main__":
    unittest.main()
