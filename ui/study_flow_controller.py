"""Orchestrate the vertical study flow without owning window chrome."""

from __future__ import annotations

from collections.abc import Callable

from ai.exam_plan import ExamGenerationPlan
from core.study_intent import StudyAction, StudyIntent
from core.topic_display import topic_display_name


class StudyFlowController:
    """Carry one typed intent from recommendation through quiz completion."""

    def __init__(
        self,
        *,
        question_bank,
        set_manager,
        course_manager,
        topic_screen,
        quiz_screen,
        lang_manager,
        navigate: Callable[[int], object],
        setup_screen_index: int,
        quiz_screen_index: int,
        courses_screen_index: int,
        current_course_id: Callable[[], str],
        course_changed: Callable[[], object],
        resume_session: Callable[[], object],
        review_questions: Callable[[StudyIntent], object],
        generate_questions: Callable[..., object],
        show_timer: Callable[[], bool],
    ):
        self.question_bank = question_bank
        self.set_manager = set_manager
        self.course_manager = course_manager
        self.topic_screen = topic_screen
        self.quiz_screen = quiz_screen
        self.lang_manager = lang_manager
        self._navigate = navigate
        self._setup_screen_index = setup_screen_index
        self._quiz_screen_index = quiz_screen_index
        self._courses_screen_index = courses_screen_index
        self._current_course_id = current_course_id
        self._course_changed = course_changed
        self._resume_session = resume_session
        self._review_questions = review_questions
        self._generate_questions = generate_questions
        self._show_timer = show_timer
        self.pending_intent: StudyIntent | None = None
        self.active_intent: StudyIntent | None = None
        self.active_questions: dict = {}

    def handle_intent(self, intent: StudyIntent) -> None:
        if not isinstance(intent, StudyIntent):
            return
        self._activate_course(intent.course_id)
        if intent.action is StudyAction.RESUME_SESSION:
            self.active_intent = intent
            self._resume_session()
            return
        if intent.action is StudyAction.DAILY_QUEUE:
            self.start_prefilled(intent, list(intent.question_ids))
            return
        if intent.action is StudyAction.REVIEW_QUESTIONS:
            self.active_intent = intent
            self._review_questions(intent)
            return
        if intent.action in {
            StudyAction.PRACTICE_TOPIC,
            StudyAction.CUSTOM_PRACTICE,
        }:
            self.pending_intent = intent
            if self._navigate(self._setup_screen_index) is not False:
                self.topic_screen.apply_study_intent(intent)
            return
        if intent.action is StudyAction.GENERATE_MISSING:
            self._generate_questions(
                initial_plan=self._generation_plan(intent),
            )
            return
        if intent.action is StudyAction.IMPORT_COURSE:
            self._navigate(self._courses_screen_index)

    def start_prefilled(
        self,
        intent: StudyIntent,
        question_ids: list[str],
    ) -> dict:
        if not isinstance(intent, StudyIntent):
            return {}
        questions = self.question_bank.get_many(
            question_ids,
            course_id=intent.course_id,
        )
        if not questions:
            return {}
        if intent.topic_ids:
            course = self.course_manager.get(intent.course_id)
            label = topic_display_name(
                questions[0].topic,
                course,
                self.lang_manager.current,
                questions[0].topic_title(),
            )
        else:
            label = self.lang_manager.get_text(
                "今日练习",
                "Today's Practice",
            )
        return self.start_questions(intent, questions, label=label)

    def start_questions(
        self,
        intent: StudyIntent,
        questions,
        *,
        label: str = "",
        question_set=None,
    ) -> dict:
        """Start one session and make this controller its sole state owner."""
        if not isinstance(intent, StudyIntent):
            return {}
        questions = [
            question
            for question in (questions or ())
            if getattr(question, "question_id", "")
        ]
        if not questions:
            return {}
        self._activate_course(intent.course_id)
        self.pending_intent = None
        self.active_intent = intent
        self.active_questions = {
            question.question_id: question for question in questions
        }
        if question_set is None and self.set_manager is not None and intent.set_id:
            question_set = self.set_manager.get(intent.set_id)
        if question_set is not None:
            self.quiz_screen.start_quiz(
                question_set,
                questions,
                show_timer=self._show_timer(),
                submission_mode=intent.submission_mode,
            )
        else:
            self.quiz_screen.start_quiz_custom(
                questions,
                label,
                show_timer=self._show_timer(),
                submission_mode=intent.submission_mode,
            )
        self.quiz_screen.set_study_intent(intent)
        self._navigate(self._quiz_screen_index)
        return self.active_questions

    def generate_missing(
        self,
        intent: StudyIntent,
        missing_count: int,
    ) -> None:
        if not isinstance(intent, StudyIntent) or missing_count <= 0:
            return
        self.handle_intent(StudyIntent(
            course_id=intent.course_id,
            action=StudyAction.GENERATE_MISSING,
            topic_ids=intent.topic_ids,
            question_count=missing_count,
            submission_mode=intent.submission_mode,
            source=intent.source,
        ))

    def clear_setup(self) -> None:
        self.pending_intent = None
        self.topic_screen.clear_study_intent()

    def clear_active(self) -> None:
        self.active_intent = None
        self.active_questions = {}

    def restore_active_intent(
        self,
        intent: StudyIntent,
        questions,
    ) -> None:
        """Restore workflow context after the quiz UI restores a draft."""
        if not isinstance(intent, StudyIntent):
            return
        self._activate_course(intent.course_id)
        self.pending_intent = None
        self.active_intent = intent
        self.active_questions = {
            question.question_id: question
            for question in (questions or ())
            if getattr(question, "question_id", "")
        }
        self.quiz_screen.set_study_intent(intent)

    def take_active_intent(self) -> StudyIntent | None:
        intent = self.active_intent
        self.active_intent = None
        return intent

    def _activate_course(self, course_id: str) -> None:
        if not course_id or course_id == self._current_course_id():
            return
        if (
            self.course_manager.get(course_id) is not None
            and self.course_manager.set_current(course_id)
        ):
            self._course_changed()

    @staticmethod
    def _generation_plan(intent: StudyIntent) -> ExamGenerationPlan:
        topic_weights = {}
        if intent.topic_ids:
            weight = max(1, 100 // len(intent.topic_ids))
            topic_weights = {
                topic_id: weight for topic_id in intent.topic_ids
            }
            topic_weights[intent.topic_ids[-1]] += (
                100 - sum(topic_weights.values())
            )
        return ExamGenerationPlan(
            question_count=max(1, intent.question_count),
            selected_topics=intent.topic_ids,
            topic_weights=topic_weights,
        )
