import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.study_intent import StudyAction, StudyIntent


class StudyFlowControllerTests(unittest.TestCase):
    @staticmethod
    def _controller(**overrides):
        from ui.study_flow_controller import StudyFlowController

        dependencies = {
            "question_bank": Mock(),
            "set_manager": None,
            "course_manager": SimpleNamespace(get=lambda _course_id: None),
            "topic_screen": SimpleNamespace(
                apply_study_intent=Mock(),
                clear_study_intent=Mock(),
            ),
            "quiz_screen": SimpleNamespace(
                start_quiz=Mock(),
                start_quiz_custom=Mock(),
                set_study_intent=Mock(),
            ),
            "lang_manager": SimpleNamespace(
                current="zh",
                get_text=lambda zh, _en: zh,
            ),
            "navigate": Mock(return_value=True),
            "setup_screen_index": 4,
            "quiz_screen_index": 2,
            "courses_screen_index": 5,
            "current_course_id": lambda: "course-a",
            "course_changed": Mock(),
            "resume_session": Mock(),
            "review_questions": Mock(),
            "generate_questions": Mock(),
            "show_timer": lambda: False,
        }
        dependencies.update(overrides)
        return StudyFlowController(**dependencies)

    def test_topic_intent_is_preserved_and_applied_to_setup(self):
        topic_screen = SimpleNamespace(apply_study_intent=Mock())
        navigate = Mock(return_value=True)
        controller = self._controller(
            topic_screen=topic_screen,
            navigate=navigate,
        )
        intent = StudyIntent(
            course_id="course-a",
            action=StudyAction.PRACTICE_TOPIC,
            topic_ids=("cache",),
            question_count=6,
            source="today_plan",
        )

        controller.handle_intent(intent)

        self.assertIs(intent, controller.pending_intent)
        navigate.assert_called_once_with(4)
        topic_screen.apply_study_intent.assert_called_once_with(intent)

    def test_prefilled_study_starts_quiz_and_becomes_active(self):
        question = SimpleNamespace(
            question_id="q1",
            topic="cache",
            topic_title=lambda: "Cache",
        )
        question_bank = Mock()
        question_bank.get_many.return_value = [question]
        quiz_screen = SimpleNamespace(
            start_quiz=Mock(),
            start_quiz_custom=Mock(),
            set_study_intent=Mock(),
        )
        navigate = Mock(return_value=True)
        controller = self._controller(
            question_bank=question_bank,
            quiz_screen=quiz_screen,
            navigate=navigate,
        )
        intent = StudyIntent(
            course_id="course-a",
            action=StudyAction.PRACTICE_TOPIC,
            topic_ids=("cache",),
            question_count=1,
        )

        active_questions = controller.start_prefilled(intent, ["q1"])

        self.assertEqual({"q1": question}, active_questions)
        self.assertIs(intent, controller.active_intent)
        question_bank.get_many.assert_called_once_with(
            ["q1"],
            course_id="course-a",
        )
        quiz_screen.start_quiz_custom.assert_called_once_with(
            [question],
            "Cache",
            show_timer=False,
            submission_mode="practice",
        )
        quiz_screen.set_study_intent.assert_called_once_with(intent)
        navigate.assert_called_once_with(2)

    def test_start_questions_owns_session_state_and_attaches_intent(self):
        question = SimpleNamespace(
            question_id="q1",
            topic="cache",
            topic_title=lambda: "Cache",
        )
        quiz_screen = SimpleNamespace(
            start_quiz=Mock(),
            start_quiz_custom=Mock(),
            set_study_intent=Mock(),
        )
        controller = self._controller(quiz_screen=quiz_screen)
        intent = StudyIntent(
            course_id="course-a",
            action=StudyAction.CUSTOM_PRACTICE,
            question_ids=("q1",),
            question_count=1,
            submission_mode="exam",
            source="retry",
        )

        active_questions = controller.start_questions(
            intent,
            [question],
            label="重试",
        )

        self.assertEqual({"q1": question}, active_questions)
        self.assertIs(intent, controller.active_intent)
        self.assertIsNone(controller.pending_intent)
        quiz_screen.start_quiz_custom.assert_called_once_with(
            [question],
            "重试",
            show_timer=False,
            submission_mode="exam",
        )
        quiz_screen.set_study_intent.assert_called_once_with(intent)

    def test_saved_set_intent_starts_real_set_in_requested_mode(self):
        question = SimpleNamespace(
            question_id="q1",
            topic="cache",
            topic_title=lambda: "Cache",
        )
        question_set = SimpleNamespace(set_id="set-1")
        question_bank = Mock()
        question_bank.get_many.return_value = [question]
        set_manager = SimpleNamespace(get=Mock(return_value=question_set))
        quiz_screen = SimpleNamespace(
            start_quiz=Mock(),
            start_quiz_custom=Mock(),
            set_study_intent=Mock(),
        )
        controller = self._controller(
            question_bank=question_bank,
            set_manager=set_manager,
            quiz_screen=quiz_screen,
        )
        intent = StudyIntent(
            course_id="course-a",
            action=StudyAction.CUSTOM_PRACTICE,
            set_id="set-1",
            question_ids=("q1",),
            question_count=1,
            submission_mode="exam",
        )

        controller.start_prefilled(intent, ["q1"])

        set_manager.get.assert_called_once_with("set-1")
        quiz_screen.start_quiz.assert_called_once_with(
            question_set,
            [question],
            show_timer=False,
            submission_mode="exam",
        )
        quiz_screen.start_quiz_custom.assert_not_called()

    def test_daily_queue_intent_starts_prefilled_quiz_without_setup_screen(self):
        question = SimpleNamespace(
            question_id="q-daily",
            topic="cache",
            topic_title=lambda: "Cache",
        )
        question_bank = Mock()
        question_bank.get_many.return_value = [question]
        quiz_screen = SimpleNamespace(
            start_quiz=Mock(),
            start_quiz_custom=Mock(),
            set_study_intent=Mock(),
        )
        navigate = Mock(return_value=True)
        topic_screen = SimpleNamespace(apply_study_intent=Mock())
        controller = self._controller(
            question_bank=question_bank,
            quiz_screen=quiz_screen,
            topic_screen=topic_screen,
            navigate=navigate,
        )
        intent = StudyIntent(
            course_id="course-a",
            action=StudyAction.DAILY_QUEUE,
            question_ids=("q-daily",),
            remaining_question_ids=("q-next",),
            question_count=1,
            source="today_plan",
            plan_id="2026-07-28:course-a",
        )

        controller.handle_intent(intent)

        self.assertIs(intent, controller.active_intent)
        self.assertIsNone(controller.pending_intent)
        topic_screen.apply_study_intent.assert_not_called()
        quiz_screen.start_quiz_custom.assert_called_once()
        navigate.assert_called_once_with(2)

    def test_restored_session_rebinds_intent_and_questions_to_quiz(self):
        question = SimpleNamespace(question_id="q-restored")
        quiz_screen = SimpleNamespace(
            start_quiz=Mock(),
            start_quiz_custom=Mock(),
            set_study_intent=Mock(),
        )
        controller = self._controller(quiz_screen=quiz_screen)
        intent = StudyIntent(
            course_id="course-a",
            action=StudyAction.CUSTOM_PRACTICE,
            question_ids=("q-restored",),
            question_count=1,
            submission_mode="exam",
            source="snapshot_resume",
        )

        controller.restore_active_intent(intent, [question])

        self.assertIs(intent, controller.active_intent)
        self.assertEqual({"q-restored": question}, controller.active_questions)
        quiz_screen.set_study_intent.assert_called_once_with(intent)

    def test_generate_missing_preserves_topic_scope_and_missing_count(self):
        generate_questions = Mock()
        controller = self._controller(generate_questions=generate_questions)
        intent = StudyIntent(
            course_id="course-a",
            action=StudyAction.PRACTICE_TOPIC,
            topic_ids=("cache", "io"),
            question_count=10,
            source="today_plan",
        )

        controller.generate_missing(intent, 3)

        plan = generate_questions.call_args.kwargs["initial_plan"]
        self.assertEqual(3, plan.question_count)
        self.assertEqual(("cache", "io"), plan.selected_topics)
        self.assertEqual({"cache": 50, "io": 50}, dict(plan.topic_weights))


if __name__ == "__main__":
    unittest.main()
