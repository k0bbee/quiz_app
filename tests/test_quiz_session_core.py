import builtins
import importlib
import sys
import unittest
from unittest.mock import patch

from core.quiz_engine import QuizSession
from models.progress import AnswerRecord, ProgressRecord, QuestionReviewSnapshot
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType, QuizState


class QuizSessionCoreTests(unittest.TestCase):
    def test_quiz_session_imports_and_emits_without_pyqt(self):
        module_name = "core.quiz_engine"
        loaded_module = sys.modules.pop(module_name)
        real_import = builtins.__import__

        def import_without_pyqt(name, *args, **kwargs):
            if name == "PyQt6" or name.startswith("PyQt6."):
                raise ModuleNotFoundError("PyQt6 intentionally unavailable")
            return real_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=import_without_pyqt):
                module = importlib.import_module(module_name)
            errors = []
            session = module.QuizSession()
            session.error_occurred.connect(errors.append)
            session.start_with_questions([])
            self.assertEqual(["No questions available."], errors)
        finally:
            sys.modules[module_name] = loaded_module

    def _make_question(self, question_id: str, topic: str = "cache") -> Question:
        return Question(
            question_id=question_id,
            type=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": f"{question_id}?",
                    "options": ["A. 对", "B. 错"],
                    "explanation": "解释说明",
                },
                "en": {
                    "stem": f"{question_id}?",
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

    def test_answer_record_persists_manual_self_assessment_method(self):
        record = AnswerRecord(
            question_id="short-1",
            index_in_session=0,
            user_answer="我的回答",
            is_correct=True,
            grading_method="manual_self_assessment",
        )

        loaded = AnswerRecord.from_dict(record.to_dict())

        self.assertEqual("manual_self_assessment", loaded.grading_method)

    def test_quiz_session_requires_and_records_short_answer_self_assessment(self):
        question = Question.create_new(
            qtype=QuestionType.SHORT_ANSWER,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": "解释 DMA",
                    "options": [],
                    "explanation": "DMA 的解释说明。",
                },
                "en": {
                    "stem": "Explain DMA",
                    "options": [],
                    "explanation": "DMA explanation.",
                },
            },
            correct_answer="设备可绕过 CPU 直接传输数据。",
            topic="io",
        )
        question_set = QuestionSet.create_new(
            title={"zh": "简答", "en": "Short Answer"},
            description={"zh": "", "en": ""},
            topics=["io"],
            question_ids=[question.question_id],
        )
        session = QuizSession()
        session.start_fixed_order(question_set, [question], language="zh")

        with self.assertRaisesRegex(ValueError, "manual self-assessment"):
            session.submit_answer("我的回答")

        is_correct, _answer = session.submit_answer(
            "我的回答",
            manual_is_correct=True,
        )

        self.assertTrue(is_correct)
        self.assertEqual("manual_self_assessment", session.answers[0].grading_method)

    def test_exam_drafts_require_short_answer_self_assessment_mapping(self):
        question = Question.create_new(
            qtype=QuestionType.SHORT_ANSWER,
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {
                    "stem": "解释中断",
                    "options": [],
                    "explanation": "中断的解释说明。",
                },
                "en": {
                    "stem": "Explain interrupts",
                    "options": [],
                    "explanation": "Interrupt explanation.",
                },
            },
            correct_answer="设备通过中断通知 CPU。",
            topic="io",
        )
        question_set = QuestionSet.create_new(
            title={"zh": "模拟", "en": "Exam"},
            description={"zh": "", "en": ""},
            topics=["io"],
            question_ids=[question.question_id],
        )
        session = QuizSession()
        session.start_fixed_order(question_set, [question], language="zh")

        with self.assertRaisesRegex(ValueError, "manual self-assessment"):
            session.complete_with_drafts({question.question_id: "我的回答"})

        record = session.complete_with_drafts(
            {question.question_id: "我的回答"},
            manual_grades={question.question_id: False},
        )

        self.assertFalse(record.answers[0].is_correct)
        self.assertEqual("manual_self_assessment", record.answers[0].grading_method)

    def test_progress_record_persists_marked_review_questions(self):
        record = ProgressRecord.create_new("set-1")
        record.marked_review_question_ids = ["q1", "q3"]

        loaded = ProgressRecord.from_dict(record.to_dict())

        self.assertEqual(["q1", "q3"], loaded.marked_review_question_ids)

    def test_progress_record_round_trips_review_snapshots(self):
        record = ProgressRecord.create_new("set-io", language="zh")
        record.set_title_snapshot = "I/O 专项"
        record.course_id_snapshot = "course-os"
        record.course_title_snapshot = "操作系统"
        record.question_snapshots = [
            QuestionReviewSnapshot(
                question_id="q-io-1",
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
                        "excerpt": "设备完成后发出中断。",
                    }
                ],
            )
        ]

        loaded = ProgressRecord.from_dict(record.to_dict())

        self.assertEqual("I/O 专项", loaded.set_title_snapshot)
        self.assertEqual("course-os", loaded.course_id_snapshot)
        self.assertEqual("操作系统", loaded.course_title_snapshot)
        self.assertEqual(1, len(loaded.question_snapshots))
        snapshot = loaded.question_snapshots[0]
        self.assertEqual("q-io-1", snapshot.question_id)
        self.assertEqual(["A. 轮询", "B. 中断"], snapshot.options)
        self.assertEqual("B", snapshot.correct_answer)
        self.assertEqual("lecture.pdf", snapshot.source_refs[0]["source_file"])

    def test_progress_record_loads_legacy_data_without_review_snapshots(self):
        loaded = ProgressRecord.from_dict(
            {
                "progress_id": "progress-legacy",
                "set_id": "set-legacy",
                "language": "zh",
                "started_at": "2026-07-01T00:00:00+00:00",
            }
        )

        self.assertEqual("", loaded.set_title_snapshot)
        self.assertEqual("", loaded.course_id_snapshot)
        self.assertEqual("", loaded.course_title_snapshot)
        self.assertEqual([], loaded.question_snapshots)

    def test_quiz_session_can_restore_order_answers_index_and_elapsed_time(self):
        question_set = QuestionSet.create_new(
            title={"zh": "测试", "en": "Test"},
            description={"zh": "", "en": ""},
            topics=["cache"],
            question_ids=[],
        )
        questions = [
            self._make_question("q1"),
            self._make_question("q2"),
            self._make_question("q3"),
        ]
        answer = AnswerRecord(
            question_id="q1",
            index_in_session=0,
            user_answer="A",
            is_correct=True,
            confidence="sure",
        )
        session = QuizSession()

        session.restore(
            question_set=question_set,
            questions=questions,
            current_index=1,
            answers=[answer],
            language="zh",
            progress_id="progress-restored",
            elapsed_seconds=42.0,
        )

        self.assertEqual(
            ["q1", "q2", "q3"],
            [question.question_id for question in session.questions],
        )
        self.assertEqual(1, session.current_index)
        self.assertEqual("q2", session.current_question.question_id)
        self.assertEqual("progress-restored", session.progress_id)
        self.assertEqual(1, session.answered_count)
        self.assertGreaterEqual(session.elapsed_seconds, 42.0)

    def test_quiz_session_updates_submitted_answer_confidence(self):
        question_set = QuestionSet.create_new(
            title={"zh": "测试", "en": "Test"},
            description={"zh": "", "en": ""},
            topics=["cache"],
            question_ids=[],
        )
        question = self._make_question("q1")
        session = QuizSession()
        session.start_fixed_order(question_set, [question], language="zh")
        session.submit_answer("A", confidence="sure")

        changed = session.set_answer_confidence("q1", "unsure")

        self.assertTrue(changed)
        self.assertEqual("unsure", session.answers[0].confidence)

    def test_quiz_session_releases_submit_guard_when_grading_raises(self):
        question_set = QuestionSet.create_new(
            title={"zh": "测试", "en": "Test"},
            description={"zh": "", "en": ""},
            topics=["cache"],
            question_ids=[],
        )
        question = self._make_question("q1")
        session = QuizSession()
        session.start_fixed_order(question_set, [question], language="zh")

        with patch(
            "core.quiz_engine.Grader.grade",
            side_effect=ValueError("bad answer shape"),
        ):
            with self.assertRaises(ValueError):
                session.submit_answer({"unexpected": object()})

        self.assertFalse(session._in_submit)
        self.assertEqual(QuizState.IN_PROGRESS, session.state)

    def test_quiz_session_can_jump_between_unfinished_questions(self):
        first = Question.create_new(
            qtype=QuestionType.MULTIPLE_CHOICE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "问题 1",
                    "options": ["A. 对", "B. 错"],
                    "explanation": "解释说明",
                },
                "en": {
                    "stem": "Question 1",
                    "options": ["A. Right", "B. Wrong"],
                    "explanation": "Explanation text",
                },
            },
            correct_answer="A",
            topic="test",
        )
        second = Question.create_new(
            qtype=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "问题 2",
                    "options": ["正确", "错误"],
                    "explanation": "解释说明",
                },
                "en": {
                    "stem": "Question 2",
                    "options": ["True", "False"],
                    "explanation": "Explanation text",
                },
            },
            correct_answer="true",
            topic="test",
        )
        third = Question.create_new(
            qtype=QuestionType.FILL_IN_BLANK,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": "问题 3",
                    "options": [],
                    "explanation": "解释说明",
                },
                "en": {
                    "stem": "Question 3",
                    "options": [],
                    "explanation": "Explanation text",
                },
            },
            correct_answer="answer",
            topic="test",
        )
        question_set = QuestionSet.create_new(
            title={"zh": "测试", "en": "Test"},
            description={"zh": "", "en": ""},
            topics=["test"],
            question_ids=[
                first.question_id,
                second.question_id,
                third.question_id,
            ],
        )
        session = QuizSession()
        session.start(question_set, [first, second, third], "zh")

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

    def test_quiz_session_falls_back_to_zh_for_invalid_language(self):
        question_set = QuestionSet.create_new(
            title={"zh": "测试", "en": "Test"},
            description={"zh": "", "en": ""},
            topics=["test"],
            question_ids=[],
        )
        question = self._make_question("q1")

        session = QuizSession()
        session.start(question_set, [question], "fr")
        self.assertEqual("zh", session._language)

        second_session = QuizSession()
        second_session.start(question_set, [question], "en")
        self.assertEqual("en", second_session._language)


if __name__ == "__main__":
    unittest.main()
