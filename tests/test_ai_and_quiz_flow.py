import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ai.llm_client import LLMClient
from models.progress import AnswerRecord, ProgressRecord, SessionSummary
from models.question import Question
from models.question import QuestionBank
from models.question_set import QuestionSet
from core.quiz_engine import QuizSession
from core.progress_tracker import ProgressManager
from ui.screens.home_screen import HomeScreen
from ui.widgets.answer_area import MatchingWidget
from utils.constants import Difficulty, QuestionType


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
    def test_matching_widget_populates_left_items(self):
        widget = MatchingWidget()
        widget.set_options({"left": ["CPU", "GPU"], "right": ["Processor", "Graphics"]})

        self.assertEqual(widget.left_list.count(), 2)
        self.assertEqual(widget.left_list.item(0).text(), "CPU")
        self.assertEqual(len(widget.get_answer()), 2)

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


if __name__ == "__main__":
    unittest.main()
